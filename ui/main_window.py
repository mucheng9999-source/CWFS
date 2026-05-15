"""
主窗口 - 包含所有UI组件和主要逻辑
"""
import json
import os
import threading
import time
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QCheckBox,
                             QGroupBox, QGridLayout, QScrollArea, QMessageBox,
                             QStatusBar, QMenuBar, QMenu, QAction, QTabWidget,
                             QSplitter, QSizePolicy, QFrame,
                             QTableWidgetItem, QFileDialog) # [修改] 新增 QFileDialog
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QFont, QCloseEvent
from .motor_widget import MotorWidget
from .log_widget import LogWidget
from core.network_manager import NetworkManager
from core.protocol_parser import ProtocolParser
from utils.data_converter import DataConverter
from .mini_motor_widget import MiniMotorWidget
from core.correction_calculator import CorrectionForceCalculator
from .correction_widget import CorrectionWidget
from .cwfs_window import CWFSWindow
from .mirror_view_widget import MirrorViewWidget
from PyQt5.QtWidgets import QDialog


class MainWindow(QMainWindow):
    """主窗口类"""
    
    # 信号定义 - 新增数据传输相关信号
    connection_status_changed = pyqtSignal(bool)
    data_received = pyqtSignal(bytes)
    motor_data_updated = pyqtSignal(int, str, float)  # 电机ID, 数据类型, 值
    
    # 新增日志相关信号
    data_received_signal = pyqtSignal(int, str, float)  # 电机ID, 数据类型, 值 - 用于日志
    network_event_signal = pyqtSignal(str, str)  # 网络事件类型, 详情
    control_command_signal = pyqtSignal(str, dict)  # 控制命令, 参数
    system_event_signal = pyqtSignal(str, str)  # 系统事件, 级别
    
    # 新增校正相关信号
    update_correction_status_signal = pyqtSignal(int, float, str)

    # [新增] 线程安全信号：用于从子线程请求主线程启动监控定时器
    start_monitoring_signal = pyqtSignal()

    update_motor_view_signal = pyqtSignal(int, bool)

    def __init__(self,user_role="GUEST", username="访客"):
        super().__init__()
        self.user_role = user_role 
        self.username = username

        # 加载配置
        self.config = self.load_config()
        
        # 初始化变量
        self.net_connected = False
        self.stop_flag = 0x00
        self.steps_ctrl_flag = 0x00
        self.sequential_query_flag = False
        self.query_lvdt_flag = 0x00
        self.close_loop_ctrl_flag = 0x00

        self.closed_loop_targets = {}     # 存储每个电机的目标力值: {motor_id: target_force}
        self.closed_loop_adjusting = {}   # 存储每个电机的调整状态: {motor_id: True/False} (True=正在跟随, False=已停止)
        self.is_supervisor_running = False # 监控线程运行标志
        
        # CAN命令模板
        self.can_cmd_template = bytearray([0x08, 0x00, 0x00, 0x00, 0x01, 0x52, 0x54, 0x00, 
                                          0x00, 0x00, 0x00, 0x00, 0xAA])
        
        # 选中的电机列表
        self.active_motors = []
        
        # Socket对象
        self.sock_listen_can = None
        self.client_socket = None
        
        # 接收线程
        self.receive_thread = None
        self.receive_thread_running = False

        # 文档管理相关属性初始化 
        self.pdf_document_path = None
        self.install_dir = None
        
        # 校正控制状态
        self.correction_active = False
        self.correction_target_forces = [0.0] * 27
        self.correction_current_forces = [0.0] * 27
        self.correction_motor_status = ["待执行"] * 27
        self.correction_motor_completed = [False] * 27
        self.correction_monitor_timer = None
        self.current_positions = [0.0] * 30
        
        # 校正力求解相关变量 - 初始化为None，稍后初始化
        self.correction_calculator = None
        self.correction_widget = None
        
        # 波前传感窗口实例
        self.cwfs_window = None

        # 初始化UI
        self.init_ui()
        self.setup_menu_bar()

        # 初始化网络管理器
        self.network_manager = NetworkManager()
        
        # 初始化协议解析器
        self.protocol_parser = ProtocolParser()
        
        # 初始化数据转换器
        self.data_converter = DataConverter()
        
        # 连接信号
        self.connect_signals()
        
        # 设置窗口属性
        self.setWindowTitle("主动支撑控制系统")
        self.resize(1600, 800)
        
        # 设置数据传输日志（现在可以正确过滤）
        self.setup_data_logging()

        # 添加初始日志
        self.add_log("信息", "系统启动完成")
        self.add_log("信息", f"加载配置: 电机总数={self.config['motors']['total_count']}")

        # 初始化校正力求解组件
        self.init_correction_widget()
        self.apply_permissions()
        
    def load_config(self):
        """加载配置文件"""
        config_path = "config/config.json"
        default_config = {
            "network": {
                "default_ip": "192.168.0.201",
                "default_port": 20001,
                "timeout": 5,
                "buffer_size": 80
            },
            "motors": {
                "total_count": 30,
                "force_motors": 27,
                "displacement_motors": 3
            },
            "ui": {
                "window_width": 1600,
                "window_height": 800,
                 "view_motors_per_row": 10,  
                "control_motors_per_row": 7,  
                "view_motor_width": 130,  
                "view_motor_height": 80,
                "theme": "light"
            }
        }
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return default_config
        return default_config
    
    def init_correction_widget(self):
        """初始化校正力求解组件 - [修复] 在此处统一连接信号"""
        # 指定数据目录路径
        data_dir = r"F:\DeskTop\弯月镜主动支撑仿真\VSProject\弯月镜支撑控制\data"

        # 初始化校正计算器
        if self.correction_calculator is None:
            self.correction_calculator = CorrectionForceCalculator()
            
            # 1. 连接开始信号
            self.correction_calculator.calculation_started.connect(
                lambda: self.correction_widget.log_message("正在加载数据并开始计算...") if self.correction_widget else None
            )
            # 2. 连接进度信号
            self.correction_calculator.progress_updated.connect(
                lambda val: self.correction_widget.update_progress(val) if self.correction_widget else None
            )
            # 3. 连接完成信号
            self.correction_calculator.calculation_finished.connect(
                self.on_correction_calculation_finished
            )
            # 4. 连接错误信号
            self.correction_calculator.calculation_error.connect(
                self.on_correction_calculation_error
            )
        
        # 初始化校正界面
        if self.correction_widget is None:
            self.correction_widget = CorrectionWidget()
            
            # 连接位移执行按钮
            self.correction_widget.btn_exec_disp.clicked.connect(self.execute_displacement_correction_from_ui)

            # 连接界面内部按钮信号
            self.correction_widget.apply_correction_requested.connect(self.apply_correction_forces)
            self.correction_widget.send_to_motors_requested.connect(self.send_correction_to_motors)
            self.correction_widget.calculation_requested.connect(self.start_correction_calculation)
            
            self.correction_widget.stop_correction_requested.connect(self.stop_correction_control)

            # 连接更新校正状态的信号
            self.update_correction_status_signal.connect(self.update_correction_status)
    
    def init_ui(self):
        """初始化UI"""
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)
        
        # 网络连接区域
        network_group = self.create_network_group()
        main_layout.addWidget(network_group)
        
        # 控制按钮区域
        control_group = self.create_control_group()
        main_layout.addWidget(control_group)
        
        # 创建分割器，上半部分显示电机，下半部分显示日志
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        
        # 电机控制区域（使用选项卡）
        self.motor_tabs = QTabWidget()
        self.motor_tabs.setTabPosition(QTabWidget.North)

        # 连接 Tab 切换信号，用于检测何时进入校正界面
        self.motor_tabs.currentChanged.connect(self.on_tab_changed)
        
        # 创建所有电机查看界面
        all_motors_view_widget = self.create_all_motors_view_widget()
        self.motor_tabs.addTab(all_motors_view_widget, "所有电机")

        # 创建力促动器选项卡
        force_motors_widget = self.create_motors_widget(0, 26, "力促动器")
        self.motor_tabs.addTab(force_motors_widget, "力促动器 (0-26)")
        
        # 创建位移促动器选项卡
        displacement_motors_widget = self.create_motors_widget(27, 29, "位移促动器")
        self.motor_tabs.addTab(displacement_motors_widget, "位移促动器 (27-29)")
        
        # 添加校正力求解选项卡（如果已初始化）
        if self.correction_widget:
            self.motor_tabs.addTab(self.correction_widget, "校正力求解")

        # 创建日志组件
        self.log_widget = LogWidget()
        self.log_widget.setMinimumHeight(200)
        self.log_widget.setMaximumHeight(300)
        
        # 添加到分割器
        splitter.addWidget(self.motor_tabs)
        splitter.addWidget(self.log_widget)
        splitter.setSizes([550, 200])  # 设置初始大小比例
        
        main_layout.addWidget(splitter, 1)  # 1表示拉伸因子
        
        # 创建状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
        # 创建菜单栏
        self.create_menu_bar()
    
    def create_network_group(self):
        """创建网络连接组"""
        group = QGroupBox("网络连接")
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        
        # IP地址
        ip_label = QLabel("IP地址:")
        self.ip_edit = QLineEdit()
        self.ip_edit.setText(self.config["network"]["default_ip"])
        self.ip_edit.setMinimumWidth(120)
        layout.addWidget(ip_label)
        layout.addWidget(self.ip_edit)
        layout.addSpacing(10)
        
        # 端口
        port_label = QLabel("端口:")
        self.port_edit = QLineEdit()
        self.port_edit.setText(str(self.config["network"]["default_port"]))
        self.port_edit.setMaximumWidth(80)
        layout.addWidget(port_label)
        layout.addWidget(self.port_edit)
        layout.addSpacing(20)
        
        # 连接按钮
        self.connect_btn = QPushButton("连接")
        self.connect_btn.setMinimumWidth(80)
        self.connect_btn.clicked.connect(self.connect_to_server)
        layout.addWidget(self.connect_btn)
        layout.addSpacing(10)
        
        # 断开按钮
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.setMinimumWidth(80)
        self.disconnect_btn.clicked.connect(self.disconnect_from_server)
        self.disconnect_btn.setEnabled(False)
        layout.addWidget(self.disconnect_btn)
        layout.addSpacing(20)
        
        # 连接状态
        self.connection_status_label = QLabel("未连接")
        self.connection_status_label.setStyleSheet("""
            QLabel {
                color: red; 
                font-weight: bold;
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.connection_status_label)
        
        layout.addStretch()
        group.setLayout(layout)
        return group
    
    def create_control_group(self):
        """创建控制按钮组"""
        group = QGroupBox("控制")
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        
        # 全选按钮
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.setMinimumWidth(80)
        self.select_all_btn.clicked.connect(self.select_all_motors)
        layout.addWidget(self.select_all_btn)
        layout.addSpacing(10)
        
        # 停止电机按钮
        self.stop_motor_btn = QPushButton("停止电机")
        self.stop_motor_btn.setMinimumWidth(80)
        self.stop_motor_btn.clicked.connect(self.stop_selected_motors)
        layout.addWidget(self.stop_motor_btn)
        layout.addSpacing(10)
        
        # 步进控制按钮
        self.steps_ctrl_btn = QPushButton("步进控制")
        self.steps_ctrl_btn.setMinimumWidth(80)
        self.steps_ctrl_btn.clicked.connect(self.steps_control)
        layout.addWidget(self.steps_ctrl_btn)
        layout.addSpacing(10)
        
        # 位置查询按钮
        self.query_pos_btn = QPushButton("位置查询")
        self.query_pos_btn.setMinimumWidth(80)
        self.query_pos_btn.clicked.connect(self.query_position)
        layout.addWidget(self.query_pos_btn)
        layout.addSpacing(10)
        
        # 闭环控制按钮
        self.close_loop_btn = QPushButton("闭环控制")
        self.close_loop_btn.setMinimumWidth(80)
        self.close_loop_btn.clicked.connect(self.close_loop_control)
        layout.addWidget(self.close_loop_btn)
        layout.addSpacing(10)

        # 清空目标力按钮
        self.clear_target_btn = QPushButton("目标力归零")
        self.clear_target_btn.setMinimumWidth(80)
        self.clear_target_btn.clicked.connect(self.clear_target_force)
        self.clear_target_btn.setToolTip("将选中力促动器的目标力设置为0")
        layout.addWidget(self.clear_target_btn)
        layout.addSpacing(10)

        # ================= [新增] 导入数值按钮 =================
        self.import_btn = QPushButton("导入数值")
        self.import_btn.setMinimumWidth(80)
        self.import_btn.clicked.connect(self.import_target_values)
        self.import_btn.setToolTip("从 Excel 或 CSV 文件批量导入电机目标值")
        layout.addWidget(self.import_btn)
        layout.addSpacing(10)
        # =======================================================

        # 校正力求解按钮（新增）
        self.correction_btn = QPushButton("校正力求解")
        self.correction_btn.setMinimumWidth(80)
        self.correction_btn.clicked.connect(self.show_correction_widget)
        self.correction_btn.setStyleSheet("""
                QPushButton {
                    background-color: #9C27B0;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #7B1FA2;
                }
            """)
        layout.addWidget(self.correction_btn)
        layout.addSpacing(10)

        #  波前传感按钮 ===
        self.cwfs_btn = QPushButton("波前传感")
        self.cwfs_btn.setMinimumWidth(80)
        self.cwfs_btn.clicked.connect(self.show_cwfs_window) # 连接到槽函数
        self.cwfs_btn.setStyleSheet("""
                QPushButton {
                    background-color: #009688; 
                    color: white; 
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #00796B;
                }
            """)
        self.cwfs_btn.setToolTip("打开曲率波前传感(CWFS)分析窗口")
        layout.addWidget(self.cwfs_btn)
        layout.addSpacing(10)

        
        layout.addStretch()
        group.setLayout(layout)
        return group
    
    # ================= [新增] 导入数值方法 =================
    def import_target_values(self):
        """从Excel或CSV导入促动器目标数值"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择促动器数值文件", "", 
            "Excel/CSV Files (*.xlsx *.xls *.csv);;All Files (*)"
        )
        
        if not file_path:
            return
            
        try:
            import pandas as pd
        except ImportError:
            QMessageBox.critical(self, "缺少依赖", "无法导入：系统缺少 pandas 库。\n请在终端运行：pip install pandas openpyxl")
            return
            
        try:
            self.add_log("系统", f"正在导入文件: {os.path.basename(file_path)}")
            
            # 使用 header=None 防止第一行真实数据被当作表头吃掉
            if file_path.endswith('.csv'):
                df = pd.read_csv(file_path, header=None)
            else:
                df = pd.read_excel(file_path, header=None)
            
            success_count = 0
            for index, row in df.iterrows():
                # 至少需要两列数据
                if len(row) < 2: continue
                
                motor_id_raw = str(row.iloc[0]).strip()
                val_raw = row.iloc[1]
                
                # 跳过空值
                if pd.isna(val_raw): continue
                
                # 提取电机ID（支持 'M0' 或纯数字 '0'）
                motor_id = -1
                if motor_id_raw.upper().startswith('M'):
                    try:
                        motor_id = int(motor_id_raw[1:])
                    except ValueError:
                        continue
                elif motor_id_raw.isdigit():
                    motor_id = int(motor_id_raw)
                    
                # 检查ID有效性并在UI填入数据
                if 0 <= motor_id < len(self.motor_widgets):
                    try:
                        target_val = float(val_raw)
                        motor_widget = self.motor_widgets[motor_id]
                        
                        # 自动填入输入框
                        if hasattr(motor_widget, 'target_edit'):
                            motor_widget.target_edit.setText(f"{target_val:.3f}")
                            # 自动帮用户勾选该电机
                            motor_widget.set_checked(True)
                            
                            success_count += 1
                    except ValueError:
                        continue
                        
            if success_count > 0:
                self.add_log("控制", f"成功导入 {success_count} 个电机的目标值")
                QMessageBox.information(self, "导入成功", 
                    f"成功导入了 {success_count} 个电机的目标数值！\n已自动为您勾选这些电机，可检查后直接点击【闭环控制】。")
            else:
                self.add_log("警告", "文件中未找到有效的促动器数据")
                QMessageBox.warning(self, "导入失败", 
                    "未读取到有效数据，请检查文件格式。\n(标准格式要求：第一列为M0~M29或纯数字，第二列为目标数值)")
                
        except Exception as e:
            err_msg = f"导入文件失败: {str(e)}"
            self.add_log("错误", err_msg)
            QMessageBox.critical(self, "导入错误", err_msg)
    # =======================================================
    
    def setup_menu_bar(self):
        """在软件顶部生成账户菜单栏"""
        if hasattr(self, "menuBar"):
            menubar = self.menuBar() # 如果是 QMainWindow
        else:
            menubar = QMenuBar(self) # 如果是 QWidget
            self.layout().setMenuBar(menubar) 

        # 创建账户菜单
        account_menu = menubar.addMenu("账户管理")

        self.login_action = QAction("登录提权 (Login)", self)
        self.login_action.triggered.connect(self.show_login_dialog)
        account_menu.addAction(self.login_action)

        self.logout_action = QAction("退出登录 (Logout)", self)
        self.logout_action.triggered.connect(self.logout)
        account_menu.addAction(self.logout_action)

    def show_login_dialog(self):
        """点击菜单栏的登录时触发"""
        from ui.login_dialog import LoginDialog
        dialog = LoginDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.user_role = dialog.user_role
            self.username = dialog.username
            self.apply_permissions() # 重新刷新界面权限
            self.add_log("系统", f"用户 [{self.username}] 登录成功，当前权限：{self.user_role}")

    def logout(self):
        """点击菜单栏的退出登录时触发"""
        from PyQt5.QtWidgets import QMessageBox
        reply = QMessageBox.question(self, "注销", "确定要退出当前账号并返回【访客模式】吗？", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.user_role = "GUEST"
            self.username = "访客"
            self.apply_permissions() # 重新刷新界面权限
            self.add_log("系统", "已注销，系统恢复为访客只读模式")

    def apply_permissions(self):
        """动态刷新权限：先全部解锁，再根据角色重新禁用"""
        self.setWindowTitle(f"主动支撑控制系统 - [当前用户: {self.username} | 级别: {self.user_role}]")

        # ================= 第一步：重置(解开)所有权限 =================
        if hasattr(self, 'motor_tabs'):
            self.motor_tabs.setTabEnabled(2, True)
            self.motor_tabs.setTabToolTip(2, "")

        if hasattr(self, 'correction_widget') and self.correction_widget:
            if hasattr(self.correction_widget, 'btn_exec_disp'):
                self.correction_widget.btn_exec_disp.setEnabled(True)
                self.correction_widget.btn_exec_disp.setToolTip("")
            self.correction_widget.apply_btn.setEnabled(True)
            self.correction_widget.send_btn.setEnabled(True)

        if hasattr(self, 'motor_widgets') and self.motor_widgets:
            for mid in [27, 28, 29]:
                if mid < len(self.motor_widgets):
                    self.motor_widgets[mid].setEnabled(True)
                    self.motor_widgets[mid].setToolTip("")

        control_btns = [
            getattr(self, 'stop_motor_btn', None),
            getattr(self, 'steps_ctrl_btn', None),
            getattr(self, 'close_loop_btn', None),
            getattr(self, 'clear_target_btn', None),
            getattr(self, 'correction_btn', None),
            getattr(self, 'cwfs_btn', None),
            getattr(self, 'import_btn', None)  # [修改] 纳入权限管辖
        ]
        for btn in control_btns:
            if btn:
                btn.setEnabled(True)
                btn.setToolTip("")

        # ================= 第二步：根据角色重新上锁 =================
        if self.user_role == "ADMIN":
            self.login_action.setEnabled(False) # 隐藏登录
            self.logout_action.setEnabled(True) # 显示注销
            return

        if self.user_role == "USER":
            self.login_action.setEnabled(False)
            self.logout_action.setEnabled(True)

            if hasattr(self, 'motor_tabs'):
                self.motor_tabs.setTabEnabled(2, False)
                self.motor_tabs.setTabToolTip(2, "权限不足：当前等级不可控制位移促动器")

            if hasattr(self, 'correction_widget') and hasattr(self.correction_widget, 'btn_exec_disp'):
                self.correction_widget.btn_exec_disp.setEnabled(False)
                self.correction_widget.btn_exec_disp.setToolTip("权限不足")

            if hasattr(self, 'motor_widgets') and self.motor_widgets:
                for mid in [27, 28, 29]:
                    if mid < len(self.motor_widgets):
                        self.motor_widgets[mid].setEnabled(False)
                        self.motor_widgets[mid].setToolTip("当前权限不可控制此电机")
            return

        if self.user_role == "GUEST":
            self.login_action.setEnabled(True)  # 显示登录
            self.logout_action.setEnabled(False)# 隐藏注销

            for btn in control_btns:
                if btn:
                    btn.setEnabled(False)
                    btn.setToolTip("访客权限：禁止下发控制指令")

            if hasattr(self, 'motor_tabs'):
                self.motor_tabs.setTabEnabled(2, False)

            if hasattr(self, 'correction_widget') and self.correction_widget:
                self.correction_widget.apply_btn.setEnabled(False)
                self.correction_widget.send_btn.setEnabled(False)
                if hasattr(self.correction_widget, 'btn_exec_disp'):
                    self.correction_widget.btn_exec_disp.setEnabled(False)
            return


    def create_all_motors_widget(self):
        """创建所有电机控件 - 完全修复版本"""
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # 创建容器部件
        container = QWidget()
        scroll_area.setWidget(container)
        
        # 创建网格布局
        grid_layout = QGridLayout(container)
        grid_layout.setContentsMargins(10, 10, 10, 10)
        grid_layout.setSpacing(10)
        grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        # 创建30个电机控件
        self.motor_widgets = []
        total_motors = self.config["motors"]["total_count"]
        motors_per_row = 7  # 每行显示6个
        
        for i in range(total_motors):
            row = i // motors_per_row
            col = i % motors_per_row
            
            motor_widget = MotorWidget(i)
            self.motor_widgets.append(motor_widget)
            
            # 添加到网格布局
            grid_layout.addWidget(motor_widget, row, col, 1, 1)
        
        # 设置列宽比，使每列均匀分布
        for col in range(motors_per_row):
            grid_layout.setColumnStretch(col, 1)
        
        # 添加拉伸行，确保内容靠上显示
        grid_layout.setRowStretch(row + 1, 1)
        
        return scroll_area
    

    def create_all_motors_view_widget(self):
        """创建所有电机查看界面 - 左右分栏布局 + 顶部图例"""
        # 主容器
        main_container = QWidget()
        main_layout = QHBoxLayout(main_container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === 左侧：电机网格 (保持不变) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        grid_container = QWidget()
        scroll_area.setWidget(grid_container)
        
        grid_layout = QGridLayout(grid_container)
        grid_layout.setContentsMargins(5, 5, 5, 5)
        grid_layout.setVerticalSpacing(2)
        grid_layout.setHorizontalSpacing(2)
        grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        self.mini_motor_widgets = []
        total_motors = self.config["motors"]["total_count"]
        motors_per_row = 7 
        
        for i in range(total_motors):
            row = i // motors_per_row
            col = i % motors_per_row
            mini_motor_widget = MiniMotorWidget(i)
            self.mini_motor_widgets.append(mini_motor_widget)
            grid_layout.addWidget(mini_motor_widget, row, col, 1, 1)
        
        for col in range(motors_per_row):
            grid_layout.setColumnStretch(col, 1)
        rows_needed = (total_motors + motors_per_row - 1) // motors_per_row
        grid_layout.setRowStretch(rows_needed, 1)
        
        main_layout.addWidget(scroll_area, 7) # 左侧占比 6

        # === 右侧：可视化区域 (图例 + 镜面) ===
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(5)

        # 1. [新增] 自定义图例栏 (放在右上角)
        legend_layout = QHBoxLayout()
        legend_layout.addStretch()
        
        # 图例项: 静止 (红)
        lbl_static_icon = QLabel()
        lbl_static_icon.setFixedSize(14, 14)
        lbl_static_icon.setStyleSheet("background-color: #FF5252; border-radius: 7px; border: 1px solid #999;")
        lbl_static_text = QLabel("静止/到位")
        lbl_static_text.setStyleSheet("font-size: 12px; color: #333;")
        
        # 图例项: 运动 (绿)
        lbl_moving_icon = QLabel()
        lbl_moving_icon.setFixedSize(14, 14)
        lbl_moving_icon.setStyleSheet("background-color: #4CAF50; border-radius: 7px; border: 1px solid #999;")
        lbl_moving_text = QLabel("调整中/运动")
        lbl_moving_text.setStyleSheet("font-size: 12px; color: #333;")
        
        legend_layout.addWidget(lbl_static_icon)
        legend_layout.addWidget(lbl_static_text)
        legend_layout.addSpacing(15)
        legend_layout.addWidget(lbl_moving_icon)
        legend_layout.addWidget(lbl_moving_text)
        
        right_layout.addLayout(legend_layout)

        # 2. 镜面组件
        self.mirror_view = MirrorViewWidget()
        # [新增] 连接信号：当收到更新信号时，调用 update_motor_status
        self.update_motor_view_signal.connect(self.mirror_view.update_motor_status)
        
        right_layout.addWidget(self.mirror_view)
        
        # 将右侧容器加入主布局
        main_layout.addWidget(right_container, 3) # 右侧占比 4

        return main_container
    
    def create_motors_widget(self, start_id, end_id, title):
        """创建指定范围电机控件 (修改版：位移促动器页增加带图例的镜面视图)"""
        # 1. 创建原有的滚动区域和电机网格 (保持不变)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        container = QWidget()
        scroll_area.setWidget(container)
        
        layout = QGridLayout(container)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setVerticalSpacing(1)  
        layout.setHorizontalSpacing(12)
        layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        if not hasattr(self, 'motor_widgets') or self.motor_widgets is None:
            self.motor_widgets = []
            for i in range(self.config["motors"]["total_count"]):
                self.motor_widgets.append(MotorWidget(i))
        
        motors_per_row = 7
        
        for i in range(start_id, end_id + 1):
            row = (i - start_id) // motors_per_row
            col = (i - start_id) % motors_per_row
            if i < len(self.motor_widgets):
                motor_widget = self.motor_widgets[i]
                layout.addWidget(motor_widget, row, col)
        
        for col in range(motors_per_row):
            layout.setColumnStretch(col, 1)
        
        total = end_id - start_id + 1
        rows = (total + motors_per_row - 1) // motors_per_row
        layout.setRowStretch(rows, 1)
        
        # ================= [关键修改] =================
        # 如果是位移促动器 (ID 27-29)，则在右侧添加“图例 + 镜面视图”
        if start_id == 27: 
            # 1. 创建总容器 (水平布局)
            wrapper_widget = QWidget()
            wrapper_layout = QHBoxLayout(wrapper_widget)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(0)
            
            # 2. 左侧：原有的电机列表 (占比 7)
            wrapper_layout.addWidget(scroll_area, 7)
            
            # 3. 右侧：可视化区域容器 (垂直布局)
            right_container = QWidget()
            right_layout = QVBoxLayout(right_container)
            right_layout.setContentsMargins(10, 10, 10, 10)
            right_layout.setSpacing(5)
            
            # --- 3a. 添加图例 (复制自 create_all_motors_view_widget) ---
            legend_layout = QHBoxLayout()
            legend_layout.addStretch() # 弹簧，把图例顶到最右边
            
            # 图例项: 静止 (红)
            lbl_static_icon = QLabel()
            lbl_static_icon.setFixedSize(14, 14)
            lbl_static_icon.setStyleSheet("background-color: #FF5252; border-radius: 7px; border: 1px solid #999;")
            lbl_static_text = QLabel("静止/到位")
            lbl_static_text.setStyleSheet("font-size: 12px; color: #333;")
            
            # 图例项: 运动 (绿)
            lbl_moving_icon = QLabel()
            lbl_moving_icon.setFixedSize(14, 14)
            lbl_moving_icon.setStyleSheet("background-color: #4CAF50; border-radius: 7px; border: 1px solid #999;")
            lbl_moving_text = QLabel("调整中/运动")
            lbl_moving_text.setStyleSheet("font-size: 12px; color: #333;")
            
            legend_layout.addWidget(lbl_static_icon)
            legend_layout.addWidget(lbl_static_text)
            legend_layout.addSpacing(15)
            legend_layout.addWidget(lbl_moving_icon)
            legend_layout.addWidget(lbl_moving_text)
            
            right_layout.addLayout(legend_layout)
            
            # --- 3b. 添加镜面组件 ---
            # 注意：这是该界面的独立实例，命名为 self.disp_mirror_view 以示区分
            self.disp_mirror_view = MirrorViewWidget()
            
            # 【重要】连接信号，确保它也能随状态变色
            self.update_motor_view_signal.connect(self.disp_mirror_view.update_motor_status)
            
            right_layout.addWidget(self.disp_mirror_view)
            
            # 将右侧容器加入总布局 (占比 3)
            wrapper_layout.addWidget(right_container, 3)
            
            return wrapper_widget
        else:
            # 其他界面（如力促动器）保持原样，只返回滚动区域
            return scroll_area
    
    def show_correction_widget(self):
        """显示校正力求解界面"""
        # 确保校正组件已初始化
        self.init_correction_widget()
        
        # 查找电机选项卡控件
        central_widget = self.centralWidget()
        if central_widget:
            # 查找分割器
            for child in central_widget.findChildren(QSplitter):
                # 在分割器中查找选项卡
                for sub_child in child.findChildren(QTabWidget):
                    # 切换到校正力求解选项卡
                    for i in range(sub_child.count()):
                        if sub_child.widget(i) == self.correction_widget:
                            sub_child.setCurrentIndex(i)
                            return
        
        # 如果没有找到选项卡，作为独立窗口显示
        if self.correction_widget and not self.correction_widget.parent():
            self.correction_widget.setWindowTitle("校正力求解")
            self.correction_widget.resize(1000, 700)
            self.correction_widget.show()
            self.auto_start_force_query()
    
    def on_tab_changed(self, index):
        """Tab切换事件处理"""
        # 检查当前显示的页面是否为校正组件
        current_widget = self.motor_tabs.widget(index)
        if current_widget == self.correction_widget:
            self.auto_start_force_query()

    def auto_start_force_query(self):
        """自动启动力促动器(0-26)的实时查询"""
        if not self.net_connected:
            # 如果没连接网络，静默返回或记录日志
            return

        # 目标：确保 0-26 号电机都在 active_motors 中
        force_motors = list(range(27))
        
        # 情况1：当前未开启查询 -> 开启查询
        if not self.sequential_query_flag:
            self.add_log("系统", "进入校正界面，自动启动力促动器实时查询...")
            
            # 更新内部列表
            self.active_motors = force_motors
            
            # 同步更新UI上的复选框（视觉反馈）
            for i in force_motors:
                if i < len(self.motor_widgets):
                    self.motor_widgets[i].set_checked(True)
            
            # 启动查询线程
            self.sequential_query_flag = True
            self.query_pos_btn.setText("停止查询")
            threading.Thread(target=self.query_lvdt_thread, daemon=True).start()
            
        # 情况2：当前已开启查询 -> 确保力促动器在查询列表中
        else:
            # 检查是否所有力电机都在列表中，如果不在，添加进去
            missing_motors = [m for m in force_motors if m not in self.active_motors]
            if missing_motors:
                self.add_log("系统", "进入校正界面，自动追加力促动器到查询列表...")
                self.active_motors.extend(missing_motors)
                # 排序并去重（虽然逻辑上不会重复，但保险起见）
                self.active_motors = sorted(list(set(self.active_motors)))
                
                # 同步更新UI复选框
                for i in missing_motors:
                    if i < len(self.motor_widgets):
                        self.motor_widgets[i].set_checked(True)

    def start_correction_calculation(self, zernike_order, scale, damping):
        """开始校正力计算 (手动模式)"""
        # 确保校正计算器已初始化
        if self.correction_calculator is None:
            self.init_correction_widget()
        
        self.correction_widget.log_message(f"开始手动计算: Zernike阶数={zernike_order}, 缩放={scale}, 阻尼={damping}")
        
 
        # 启动计算线程
        self.correction_calculator.start_calculation_thread(zernike_order, scale, damping) 



    def show_cwfs_window(self):
        """显示波前传感窗口"""
        try:
            # 如果窗口尚未创建，则创建实例
            if self.cwfs_window is None:
                self.cwfs_window = CWFSWindow()
                
                # === [关键修改] 连接信号 ===
                # 1. 将 CWFS 窗口的日志转发到主窗口日志组件
                self.cwfs_window.log_forward_signal.connect(self.handle_cwfs_log)
                
                # 2. 将 CWFS 的一键校正请求连接到处理函数
                self.cwfs_window.request_correction_signal.connect(self.handle_cwfs_correction)
            
            # 显示窗口
            self.cwfs_window.show()
            self.cwfs_window.raise_()
            self.cwfs_window.activateWindow()
            
            self.add_log("系统", "已打开波前传感分析窗口")
            
        except Exception as e:
            error_msg = f"无法打开波前传感窗口: {str(e)}"
            QMessageBox.critical(self, "错误", error_msg)
            self.add_log("错误", error_msg)
            
    def handle_cwfs_log(self, level, message):
        """处理来自 CWFS 窗口的日志"""
        # 直接添加到主界面的日志区域
        self.add_log(level, message)

    def handle_cwfs_correction(self, data_packet):
        """处理来自 CWFS 的一键校正请求"""
        # [新增] 兼容性处理：判断接收到的是字典还是列表
        if isinstance(data_packet, dict):
            zernike_coeffs = data_packet.get("coeffs", [])
            obs_ratio = data_packet.get("obs", 0.0)
        else:
            # 兼容旧代码直接发送列表的情况
            zernike_coeffs = data_packet
            obs_ratio = 0.0

        self.add_log("校正", f"接收到 CWFS Zernike 数据，共 {len(zernike_coeffs)} 项 (遮拦比 e={obs_ratio:.2f})")
        
        # 1. 确保校正界面和计算器已初始化
        if self.correction_widget is None or self.correction_calculator is None:
            self.init_correction_widget()
            
        # 2. 显示校正界面
        self.show_correction_widget()

        # 3. 更新界面显示的系数日志
        # [关键修复] 这里必须只传递系数列表，不能传字典
        if hasattr(self.correction_widget, 'update_zernike_coeffs'):
            self.correction_widget.update_zernike_coeffs(zernike_coeffs)

        # 4. [关键] 执行位移解算并更新界面
        try:
            if len(zernike_coeffs) > 0:
                # 调用我们在 correction_calculator 中修改过的安全计算方法
                disp_deltas = self.correction_calculator.calculate_displacement_correction(zernike_coeffs)
                
                # 将结果推送到 correction_widget 显示
                if self.correction_widget:
                    self.correction_widget.update_displacement_info(zernike_coeffs, disp_deltas)
                    
                    if disp_deltas:
                        log_str = ", ".join([f"M{k}:{v:.3f}um" for k,v in disp_deltas.items()])
                        self.add_log("校正", f"位移解算结果: {log_str}")
                    else:
                        self.add_log("警告", "位移解算结果为空(可能系数全为0)")
        except Exception as e:
            self.add_log("错误", f"位移计算过程出错: {str(e)}")

        # 4. 启动计算
        try:
            self.correction_widget.log_message(f"正在启动校正力解算器 (Source: CWFS, e={obs_ratio:.2f})...")
            
            # 获取当前界面设置的阻尼值
            current_damping = self.correction_widget.damping_spin.value() if hasattr(self.correction_widget, 'damping_spin') else 0
            
            # 启动线程
            # [关键修复] 传递 obs 参数 (前提是您已经按上一步修改了 correction_calculator.py)
            # 如果 correction_calculator.py 还没改好，暂时删掉 obs=obs_ratio
            if hasattr(self.correction_calculator, 'start_calculation_from_coeffs_thread'):
                 self.correction_calculator.start_calculation_from_coeffs_thread(
                     zernike_coeffs, 
                     obs=obs_ratio, 
                     damping=current_damping
                 )
            
        except Exception as e:
            err = f"启动校正计算失败: {str(e)}"
            self.add_log("错误", err)
            QMessageBox.critical(self, "错误", err)      



    def on_correction_calculation_finished(self, force_distribution, pv_value, rms_value, residuals, coordinates, zernike_values):
        """校正计算完成处理"""
        # [修改] 调用 update_results 时传入 zernike_values
        self.correction_widget.update_results(force_distribution, pv_value, rms_value, residuals, coordinates, zernike_values)
        
        # 记录到系统日志
        self.add_log("校正", f"校正力计算完成，PV={pv_value* 1e6:.2f} nm, RMS={rms_value* 1e6:.2f} nm")
        
        # 显示成功消息
        if self.correction_widget and self.correction_widget.isVisible():
            QMessageBox.information(self.correction_widget, "计算完成", 
                               f"校正力计算完成！\nPV值: {pv_value * 1e6:.2f} nm\nRMS值: {rms_value * 1e6:.2f} nm")  
        else:
            QMessageBox.information(self, "计算完成", 
                               f"校正力计算完成！\nPV值: {pv_value * 1e6:.2f} nm\nRMS值: {rms_value * 1e6:.2f} nm")  

    def on_correction_calculation_error(self, error_message):
        """校正计算错误处理"""
        self.correction_widget.show_error(error_message)
        self.add_log("错误", f"校正计算失败: {error_message}")
    
    def apply_correction_forces(self, force_distribution):
        """应用校正力到界面 - 叠加模式 (目标 = 当前 + 校正)"""
        
        # 计算叠加后的目标力
        new_targets = []
        for i, correction_val in enumerate(force_distribution):
            current_val = 0.0
            # 获取当前力 (如果已连接并接收到数据，self.correction_current_forces 会存储最新的力传感器值)
            if i < len(self.correction_current_forces):
                current_val = self.correction_current_forces[i]
            
            # 叠加: 目标力 = 当前力 + 校正力
            target = current_val + correction_val
            new_targets.append(target)
            
            # 更新电机控件的目标力显示
            if i < len(self.motor_widgets):
                motor_widget = self.motor_widgets[i]
                motor_widget.target_edit.setText(f"{target:.3f}")
        
        # 保存计算出的目标力，以备后用
        self.correction_target_forces = new_targets
        
        self.correction_widget.log_message("叠加后的校正力(当前+校正)已应用到界面")
        self.add_log("校正", "叠加后的校正力已应用到界面")
        
        QMessageBox.information(self, "应用成功", "叠加后的校正力已成功应用到电机控件！\n(目标力 = 当前力 + 校正力)")
    
    def send_correction_to_motors(self, force_distribution):
        """发送校正力到电机 - 改用闭环监控模式 (更稳健)"""
        if not self.net_connected:
            QMessageBox.warning(self, "警告", "网络未连接，无法发送校正力到电机！")
            return
        
        # 1. [快照逻辑] 获取当前瞬间的所有力值作为基准
        base_forces = list(self.correction_current_forces[:27]) # 复制一份，防止引用变化
        
        # 将基准力更新到表格显示
        if self.correction_widget:
            self.correction_widget.set_base_forces(base_forces)
        
        # 2. 计算固定的目标力
        self.correction_target_forces = []
        target_dict = {}
        
        for i, correction_val in enumerate(force_distribution):
            if i >= 27: break
            
            # 目标 = 基准(快照) + 校正
            base_val = base_forces[i]
            target = base_val + correction_val
            
            # =================  限位保护 (+-150N) =================
            if target > 150.0:
                self.add_log("警告", f"M{i:02d} 目标力 {target:.3f}N 超过上限，已限制为 150.0N")
                target = 150.0
            elif target < -150.0:
                self.add_log("警告", f"M{i:02d} 目标力 {target:.3f}N 超过下限，已限制为 -150.0N")
                target = -150.0
            # ==========================================================


            self.correction_target_forces.append(target)
            target_dict[i] = target
            
            # 更新表格中的目标力显示 (列3)
            if self.correction_widget:
                 self.correction_widget.result_table.setItem(i, 3, QTableWidgetItem(f"{target:.3f}"))
            
            # 同步更新主界面电机控件
            if i < len(self.motor_widgets):
                self.motor_widgets[i].target_edit.setText(f"{target:.3f}")
                self.motor_widgets[i].set_target_pos_color(QColor(0, 255, 0)) 
                self.motor_widgets[i].set_checked(True)

        self.add_log("校正", "已生成目标力快照，准备顺序启动校正...")
        
        # 3. 启动闭环监控线程 (如果尚未运行)
        # 注意：此时 closed_loop_targets 还是空的，由下面的顺序线程逐个添加
        if not self.is_supervisor_running:
            self.is_supervisor_running = True
            threading.Thread(target=self.closed_loop_supervisor, daemon=True).start()
            self.add_log("系统", "闭环监控线程已启动")

        # 4. [顺序发送逻辑] 启动一个线程来逐个激活电机
        self.correction_active = True
        threading.Thread(target=self.sequential_activation_thread, 
                         args=(target_dict,), daemon=True).start()
        
        self.start_monitoring_signal.emit()
    
    def sequential_activation_thread(self, target_dict):
        """顺序激活电机线程 - 避免同时发送导致拥堵"""
        self.add_log("校正", "开始顺序激活电机 (间隔 0.5s)...")
        
        for motor_id, target in target_dict.items():
            if not self.correction_active:
                break
                
            # 将该电机加入闭环监控列表
            self.closed_loop_targets[motor_id] = target
            self.closed_loop_adjusting[motor_id] = True # 标记为“需要调整”
            
            # 更新状态
            self.update_correction_status_signal.emit(motor_id, self.correction_current_forces[motor_id], "启动中")
            
            # [关键] 延时，确保一个个发
            time.sleep(0.5) 
            
        self.add_log("校正", "所有电机已激活，正在进行闭环调整...")

    def correction_control_thread(self):
        """校正控制线程"""
        try:
            if self.correction_widget:
                self.correction_widget.log_message("开始执行校正控制...")
            
            # 步骤1：发送校正力到所有电机
            for motor_id in range(27):
                if motor_id >= len(self.correction_target_forces):
                    break
                
                # 检查是否请求停止
                if not self.correction_active:
                    break
                    
                target_force = self.correction_target_forces[motor_id]
                
                # 更新状态为执行中
                self.update_correction_status_signal.emit(motor_id, 0.0, "执行中")
                
                # 发送闭环控制命令
                if self.send_correction_force_to_motor(motor_id, target_force):
                    if self.correction_widget:
                        self.correction_widget.log_message(f"电机 {motor_id} 目标力 {target_force:.3f}N 已发送")
                else:
                    self.update_correction_status_signal.emit(motor_id, 0.0, "发送失败")
                    if self.correction_widget:
                        self.correction_widget.log_message(f"电机 {motor_id} 发送失败")
                
                # 短暂延迟
                time.sleep(0.05)
            
            # 步骤2：启动位置查询以监控执行情况
            # [修改] 使用信号通知主线程启动定时器，而不是直接调用
            self.start_monitoring_signal.emit()
            
            if self.correction_widget:
                self.correction_widget.log_message("校正力发送完成，开始监控执行状态...")
            
        except Exception as e:
            error_msg = f"校正控制线程错误: {str(e)}"
            if self.correction_widget:
                self.correction_widget.log_message(error_msg)
            # 使用LogWidget的安全信号方式添加日志
            if hasattr(self, 'log_widget'):
                self.log_widget.add_log("ERROR", error_msg, "SYSTEM")
            
            # 更新所有电机状态为错误
            for i in range(27):
                self.update_correction_status_signal.emit(i, 0.0, "错误") 
   
    def send_correction_force_to_motor(self, motor_id, force):
        """发送校正力到单个电机"""
        try:
            if not self.net_connected:
                self.correction_widget.log_message(f"网络未连接，无法发送到电机 {motor_id}")
                return False
            
            # 使用数据转换器将力值转换为命令值
            cmd_value = self.data_converter.convert_force_target_to_cmd(force)
            sh = (cmd_value >> 8) & 0xFF
            sl = cmd_value & 0xFF
            
            # 发送闭环控制命令 (0xA1)
            self.send_can_cmd(motor_id, 0xA1, sh, sl, 0, 0)
            
            # 发送确认命令
            # time.sleep(0.1)
            # self.send_can_cmd(motor_id, 0xA1, 0xAA, 0x00, 0x00, 0x00)
            
            return True
            
        except Exception as e:
            error_msg = f"发送校正力到电机 {motor_id} 失败: {str(e)}"
            self.correction_widget.log_message(error_msg)
            return False
    
    def start_correction_monitoring(self):
        """开始校正监控"""
        # 设置定时器检查校正完成状态
        if self.correction_monitor_timer:
            self.correction_monitor_timer.stop()
        
        self.correction_monitor_timer = QTimer()
        self.correction_monitor_timer.timeout.connect(self.check_correction_completion)
        self.correction_monitor_timer.start(100)  # 每秒检查一次
        
        self.correction_widget.log_message("开始监控校正执行状态...")
    
    def check_correction_completion(self):
        """检查校正完成状态 (只更新UI，控制逻辑由Supervisor处理)"""
        if not self.correction_active:
            if self.correction_monitor_timer:
                self.correction_monitor_timer.stop()
            return
        
        all_completed = True
        
        for motor_id in range(27):
            if motor_id >= len(self.correction_target_forces):
                continue
            
            # 获取实时数据
            target_force = self.correction_target_forces[motor_id]
            current_force = self.correction_current_forces[motor_id]
            
            # 判断是否完成
            # 注意：Supervisor 的死区是 0.05，我们这里用 0.1 作为显示完成的阈值，稍微宽一点避免闪烁
            if abs(current_force - target_force) < 0.1:
                if not self.correction_motor_completed[motor_id]:
                    self.correction_motor_completed[motor_id] = True
                    self.correction_motor_status[motor_id] = "完成"
                    self.update_correction_status_signal.emit(motor_id, current_force, "完成")
            else:
                # 如果误差又变大了，状态回退到执行中
                if self.correction_motor_completed[motor_id]:
                    self.correction_motor_completed[motor_id] = False
                    self.correction_motor_status[motor_id] = "执行中"
                    self.update_correction_status_signal.emit(motor_id, current_force, "执行中")
                all_completed = False
        
        # 如果全部完成
        if all_completed:
            # 1. 停止定时器，防止重复检测和弹窗
            if self.correction_monitor_timer:
                self.correction_monitor_timer.stop()
            
            # 2. 弹出提示框 (阻塞直到用户点击OK)
            if self.correction_widget and self.correction_widget.isVisible(): 

                QMessageBox.information(self.correction_widget, "校正完成", "所有电机已达到目标力！\n点击确认将自动停止校正并释放电机。")
            else:
                QMessageBox.information(self, "校正完成", "所有电机已达到目标力！\n点击确认将自动停止校正并释放电机。")
            # 3. 执行停止逻辑 (用户点击OK后才会执行到这里)
            self.stop_correction_control()
            
            # 4. [新增] 强制复位校正窗口的按钮状态
            if self.correction_widget:
                # 禁用"停止"按钮，启用"发送"按钮
                self.correction_widget.stop_btn.setEnabled(False)
                self.correction_widget.send_btn.setEnabled(True)
                # 更新状态标签
                self.correction_widget.update_status("校正完成 (已停止)") 
  
  
    def stop_correction_control(self):
        """停止校正控制"""
        self.correction_active = False
        
        if self.correction_monitor_timer:
            self.correction_monitor_timer.stop()
        
        # 从闭环监控中移除这些电机并发送停止指令
        for i in range(27):
            # 1. 移除监控目标
            if i in self.closed_loop_targets:
                del self.closed_loop_targets[i]
            if i in self.closed_loop_adjusting:
                del self.closed_loop_adjusting[i]
            
            # 2. 发送停止指令 (0xA0)
            self.send_can_cmd(i, 0xA0, 0x00, 0x00, 0x00, 0x00)
            
            # 3. 更新状态
            self.update_correction_status_signal.emit(i, self.correction_current_forces[i], "已停止")
            
            # 4. 取消主界面的绿色标记
            if i < len(self.motor_widgets):
                self.motor_widgets[i].reset_target_pos_color()
        
        self.correction_widget.log_message("校正过程已停止，电机已释放")
        self.add_log("校正", "校正过程已停止")
    
    def update_correction_status(self, motor_id, current_force, status):
        """更新校正状态（线程安全）"""
        if 0 <= motor_id < 27:
            self.correction_current_forces[motor_id] = current_force
            self.correction_motor_status[motor_id] = status
            
            if self.correction_widget:
                self.correction_widget.update_motor_status(motor_id, current_force, status)
    
    def create_menu_bar(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        # 校正菜单
        correction_menu = menubar.addMenu("校正")
        
        correction_action = QAction("校正力求解", self)
        correction_action.triggered.connect(self.show_correction_widget)
        correction_menu.addAction(correction_action)

        # 添加打开说明文档菜单项
        manual_action = QAction("打开使用说明", self)
        manual_action.setShortcut("Ctrl+H")  # 设置快捷键 Ctrl+H
        manual_action.triggered.connect(self.open_user_manual)
        file_menu.addAction(manual_action)
        
        file_menu.addSeparator()  # 添加分隔线
        
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def init_document_manager(self):
        """初始化文档管理器"""
        import os
        import sys
        
        # 获取软件安装路径
        if getattr(sys, 'frozen', False):
            # 打包后的exe程序路径
            self.install_dir = os.path.dirname(sys.executable)
        else:
            # 开发时的脚本路径
            self.install_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.add_log("信息", f"软件安装目录: {self.install_dir}")
    
    def open_user_manual(self):
        """打开用户手册PDF文件"""
        import os
        import subprocess
        import platform
        
        # 确保文档管理器已初始化
        if not hasattr(self, 'install_dir') or not self.install_dir:
            self.init_document_manager()
        
        # 记录操作
        self.add_log("信息", "正在打开使用说明文档...")
        
        # 主要文件名
        primary_filename = "弯月镜支撑控制系统使用说明.pdf"
        
        # 备选路径列表（按优先级）
        pdf_paths = []
        
        # 1. 安装目录下
        pdf_paths.append(os.path.join(self.install_dir, primary_filename))
        
        # 2. docs文件夹中
        docs_dir = os.path.join(self.install_dir, "docs")
        pdf_paths.append(os.path.join(docs_dir, primary_filename))
        
        # 3. Documentation文件夹中
        doc_dir = os.path.join(self.install_dir, "Documentation")
        pdf_paths.append(os.path.join(doc_dir, primary_filename))
        
        # 4. 其他常见文件名
        other_filenames = [
            "电机控制系统使用说明.pdf",
            "用户手册.pdf",
            "使用说明.pdf",
            "UserManual.pdf",
            "Manual.pdf"
        ]
        
        for filename in other_filenames:
            # 安装目录下
            pdf_paths.append(os.path.join(self.install_dir, filename))
            # docs文件夹中
            pdf_paths.append(os.path.join(docs_dir, filename))
            # Documentation文件夹中
            pdf_paths.append(os.path.join(doc_dir, filename))
        
        # 查找第一个存在的路径
        pdf_path = None
        for path in pdf_paths:
            if path and os.path.exists(path):
                pdf_path = path
                break
        
        if pdf_path and os.path.exists(pdf_path):
            try:
                # 获取系统类型
                system = platform.system()
                
                # 记录要打开的文件
                file_name = os.path.basename(pdf_path)
                self.add_log("信息", f"找到PDF文档: {file_name}")
                
                # 使用系统默认程序打开PDF
                if system == "Windows":
                    # Windows系统
                    os.startfile(pdf_path)
                    self.add_log("信息", "已使用默认程序打开PDF")
                    
                elif system == "Darwin":
                    # macOS系统
                    subprocess.call(["open", pdf_path])
                    self.add_log("信息", "已在macOS中打开PDF")
                    
                elif system == "Linux":
                    # Linux系统
                    subprocess.call(["xdg-open", pdf_path])
                    self.add_log("信息", "已在Linux中打开PDF")
                    
                else:
                    # 其他系统
                    self.add_log("警告", f"未知操作系统: {system}")
                    self.open_with_generic_method(pdf_path)
                
                # 保存PDF路径到属性
                self.pdf_document_path = pdf_path
                
                # 更新状态栏
                self.status_bar.showMessage(f"已打开使用说明: {file_name}", 5000)
                
            except Exception as e:
                error_msg = f"无法打开PDF文件: {str(e)}"
                self.add_log("错误", error_msg)
                
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.critical(self, "打开失败", error_msg)
        else:
            # 如果PDF文件不存在，提示用户
            self.show_document_not_found_message()
    
    def open_with_generic_method(self, pdf_path):
        """通用方法打开PDF"""
        import subprocess
        try:
            subprocess.Popen([pdf_path], shell=True)
        except Exception as e:
            self.add_log("错误", f"无法用通用方法打开PDF: {str(e)}")
    
    def show_document_not_found_message(self):
        """显示文档未找到的消息"""
        from PyQt5.QtWidgets import QMessageBox
        
        primary_filename = "弯月镜支撑控制系统使用说明.pdf"
        
        QMessageBox.information(
            self, "文档未找到",
            f"找不到使用说明文档。\n\n"
            f"请将 '{primary_filename}' 文件放在以下位置之一：\n"
            f"1.软件安装目录: {self.install_dir}\n"
            f"2.{self.install_dir}/docs/\n"
            f"3.{self.install_dir}/Documentation/\n\n"
            f"然后重新尝试打开。"
        )
        
        # 同时记录到日志
        self.add_log("警告", f"未找到PDF文档，请将'{primary_filename}'放在软件安装目录下")
    
    def connect_signals(self):
        """连接信号"""
        # 电机数据更新信号
        self.motor_data_updated.connect(self.update_motor_display)
        
        # 网络管理器信号
        self.network_manager.log_message.connect(self.add_log)
        self.network_manager.data_received.connect(self.handle_received_data)
        self.network_manager.connection_status_changed.connect(self.handle_connection_status_changed)
        
        # 添加校正相关信号连接
        self.update_correction_status_signal.connect(self.update_correction_status)

        # [新增] 连接监控启动信号到主线程槽函数
        self.start_monitoring_signal.connect(self.start_correction_monitoring)  

        # 将motor_data_updated信号转发到data_received_signal用于日志
        self.motor_data_updated.connect(self.data_received_signal.emit)
    
    def add_log(self, level, message):
        """添加日志"""
        if hasattr(self, 'log_widget'):
            self.log_widget.add_log(level, message)
    
    def connect_to_server(self):
        """连接到服务器"""
        try:
            ip = self.ip_edit.text().strip()
            port = int(self.port_edit.text())
            
            # 记录网络事件
            self.network_event_signal.emit("正在连接", f"服务器 {ip}:{port}")
            
            self.add_log("网络", f"正在连接服务器 {ip}:{port}...")
            
            # 创建服务器
            success = self.network_manager.create_server(ip, port)
            
            if success:
                # 记录系统事件
                self.system_event_signal.emit("连接成功", "INFO")
                
                # 更新UI状态
                self.net_connected = True
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                self.connection_status_label.setText("监听中")
                self.connection_status_label.setStyleSheet("""
                    QLabel {
                        color: blue; 
                        font-weight: bold;
                        padding: 5px;
                        border: 1px solid #ccc;
                        border-radius: 3px;
                    }
                """)
                self.status_bar.showMessage(f"监听中 - {ip}:{port}")
                
                self.add_log("网络", f"服务器监听在 {ip}:{port}")
                
                QMessageBox.information(self, "连接成功", 
                    f"服务器已启动，监听端口 {port}\n等待客户端连接...")
            else:
                # 记录错误事件
                self.system_event_signal.emit("连接失败", "ERROR")
                QMessageBox.critical(self, "连接错误", "创建服务器失败")
            
        except ValueError:
            error_msg = "端口号必须是数字"
            self.add_log("错误", error_msg)
            self.system_event_signal.emit("端口格式错误", "ERROR")
            QMessageBox.critical(self, "连接错误", error_msg)
        except Exception as e:
            error_msg = f"连接失败: {str(e)}"
            self.add_log("错误", error_msg)
            self.system_event_signal.emit(f"连接异常: {str(e)}", "ERROR")
            QMessageBox.critical(self, "连接错误", error_msg)
    
    def handle_connection_status_changed(self, connected):
        """处理连接状态变化"""
        if connected:
            # 记录网络事件
            self.network_event_signal.emit("客户端连接", "已连接")
            
            self.connection_status_label.setText("已连接")
            self.connection_status_label.setStyleSheet("""
                QLabel {
                    color: green; 
                    font-weight: bold;
                    padding: 5px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                }
            """)
            self.add_log("网络", "客户端已连接")
            QTimer.singleShot(0, lambda: self.status_bar.showMessage("已连接到客户端"))
        else:
            # 记录网络事件
            self.network_event_signal.emit("客户端断开", "连接断开")
            
            self.connection_status_label.setText("监听中")
            self.connection_status_label.setStyleSheet("""
                QLabel {
                    color: blue; 
                    font-weight: bold;
                    padding: 5px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                }
            """)
            self.add_log("网络", "客户端断开连接")
            self.status_bar.showMessage("监听中")
    
    def setup_data_logging(self):
        """设置数据传输日志"""
        # 当接收到数据时，这样记录日志
        def log_data_receive(motor_id, data_type, value):
            return
        
        # 网络连接日志
        def log_network_event(event, details=""):
            self.log_widget.add_log("INFO", 
                                   f"网络事件: {event} {details}", 
                                   "NETWORK")
        
        # 控制命令日志
        def log_control_command(command, params):
            self.log_widget.add_log("INFO", 
                                   f"控制命令: {command}, 参数: {params}", 
                                   "CONTROL")
        
        # 系统事件日志
        def log_system_event(event, level="INFO"):
            self.log_widget.add_log(level, 
                                   f"系统事件: {event}", 
                                   "SYSTEM")
        
        # 将日志函数绑定到相应的事件
        # 现在data_received_signal已经定义
        # self.data_received_signal.connect(log_data_receive)
        self.network_event_signal.connect(log_network_event)
        self.system_event_signal.connect(log_system_event)
        
        # 控制命令日志暂时不使用信号，直接记录
        # self.control_command_signal.connect(log_control_command)
        
        # 添加一些示例日志
        self.add_sample_logs()
    
    def add_sample_logs(self):
        """添加示例日志"""
        # 测试不同级别的日志
        self.system_event_signal.emit("系统启动完成", "INFO")
        self.network_event_signal.emit("初始化网络", "系统就绪")
        
        # 添加一些调试日志
        for i in range(2):
            self.system_event_signal.emit(f"初始化步骤 {i+1}", "DEBUG")
    
    def disconnect_from_server(self):
        """断开服务器连接"""
        reply = QMessageBox.question(self, "确认", 
            "确定要断开连接并关闭服务器吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            # 记录系统事件
            self.system_event_signal.emit("正在关闭服务器", "INFO")
            
            # 停止监控线程
            self.is_supervisor_running = False
            self.closed_loop_targets.clear()
            self.closed_loop_adjusting.clear()

            self.add_log("网络", "正在关闭服务器...")
            self.network_manager.close_server()
            
            # 更新UI状态
            self.net_connected = False
            self.connect_btn.setEnabled(True)
            self.disconnect_btn.setEnabled(False)
            self.connection_status_label.setText("未连接")
            self.connection_status_label.setStyleSheet("""
                QLabel {
                    color: red; 
                    font-weight: bold;
                    padding: 5px;
                    border: 1px solid #ccc;
                    border-radius: 3px;
                }
            """)
            self.status_bar.showMessage("连接已断开")
            
            # 记录系统事件
            self.system_event_signal.emit("服务器已关闭", "INFO")
            self.add_log("网络", "服务器已关闭")
    
    def select_all_motors(self):
        """选择或取消当前选项卡内的电机"""
        # 确保能访问到 tabs 组件
        if not hasattr(self, 'motor_tabs'):
            return

        # 获取当前选中的选项卡索引
        current_tab_index = self.motor_tabs.currentIndex()
        
        # 根据选项卡索引确定要操作的电机ID范围
        # Tab 0: 所有电机 (0-29)
        # Tab 1: 力促动器 (0-26)
        # Tab 2: 位移促动器 (27-29)
        target_indices = []
        tab_name = ""
        
        if current_tab_index == 0:
            target_indices = range(30)
            tab_name = "所有电机"
        elif current_tab_index == 1:
            target_indices = range(27) # 0 到 26
            tab_name = "力促动器"
        elif current_tab_index == 2:
            target_indices = range(27, 30) # 27 到 29
            tab_name = "位移促动器"
        else:
            # 如果是其他页面（如校正页面），则不执行全选操作
            return

        # 获取当前按钮文本，判断是全选还是全不选
        current_text = self.select_all_btn.text()
        should_check = (current_text == "全选")
        
        # 执行操作
        count = 0
        for i in target_indices:
            if i < len(self.motor_widgets):
                self.motor_widgets[i].set_checked(should_check)
                count += 1
            
        # 更新按钮文本
        if should_check:
            self.select_all_btn.setText("全不选")
            log_msg = f"全选 {tab_name} (共{count}个)"
        else:
            self.select_all_btn.setText("全选")
            log_msg = f"取消全选 {tab_name}"
            
        # 记录日志
        if hasattr(self, 'log_widget'):
            self.log_widget.add_log("INFO", log_msg, "CONTROL")

    def stop_selected_motors(self):
        """停止选中的电机 (修复版：立即更新状态)"""
        # 收集选中的电机
        self.active_motors = []
        for i, motor_widget in enumerate(self.motor_widgets):
            if motor_widget.is_checked():
                self.active_motors.append(i)
                motor_widget.reset_checkbox_color()
        
        self.stop_flag = 0x00
        
        if not self.active_motors:
            QMessageBox.warning(self, "警告", "请先选择要停止的电机！")
            return
        
        if not self.net_connected:
            QMessageBox.warning(self, "警告", "网络未连接，无法执行操作！")
            return
        
        # [关键修复] 从闭环监控中移除，并立即通知界面变红
        for motor_id in self.active_motors:
            # 1. 从监控列表删除，防止Supervisor再次接管
            if motor_id in self.closed_loop_targets:
                del self.closed_loop_targets[motor_id]
            if motor_id in self.closed_loop_adjusting:
                del self.closed_loop_adjusting[motor_id]
                
            # 2. 【核心】强制发送“静止”信号，让圆点立即变红
            self.update_motor_view_signal.emit(motor_id, False)
                
        # 记录日志
        self.control_command_signal.emit("停止电机", {"motors": self.active_motors})
        self.add_log("控制", f"停止选中电机: {self.active_motors}")
        
        # 启动线程发送硬件停止指令 (0xA0)
        threading.Thread(target=self.stop_thread, daemon=True).start()
    
    def stop_thread(self):
        """停止控制线程"""
        for motor_id in self.active_motors:
            self.send_can_cmd(motor_id, 0xA0, 0x00, 0x00, 0x00, 0x00)
            
            # 等待响应（简化处理）
            time.sleep(0.05)
        
        # 记录系统事件
        self.system_event_signal.emit("停止命令发送完成", "INFO")
        self.add_log("控制", "停止命令发送完成")
    
    def steps_control(self):
        """步进控制"""
        # 收集选中的电机
        self.active_motors = []
        for i, motor_widget in enumerate(self.motor_widgets):
            motor_widget.reset_steps_color()
            if motor_widget.is_checked():
                motor_widget.reset_checkbox_color()
                self.active_motors.append(i)
        
        if not self.active_motors:
            QMessageBox.warning(self, "警告", "请先选择要控制的电机！")
            return
        
        # [新增] 检查网络连接
        if not self.net_connected:
            QMessageBox.warning(self, "警告", "网络未连接，无法执行操作！")
            return

        self.steps_ctrl_flag = 0x00
        
        # 记录控制命令
        self.control_command_signal.emit("步进控制", {"motors": self.active_motors})
        self.add_log("控制", f"开始步进控制: {self.active_motors}")
        
        # 在新线程中发送步进控制命令
        threading.Thread(target=self.steps_ctrl_thread, daemon=True).start()
    
    def steps_ctrl_thread(self):
        """步进控制线程"""
        for motor_id in self.active_motors:
            try:
                motor_widget = self.motor_widgets[motor_id]
                steps_text = motor_widget.get_steps_text()
                
                if steps_text:
                    steps = int(steps_text)
                    self.add_log("控制", f"电机 {motor_id} 步数: {steps}")
                    
                    if 0 <= motor_id <= 26:
                        # 力促动器
                        abs_steps = abs(steps)
                        sh = (abs_steps >> 16) & 0xFF
                        sm = (abs_steps >> 8) & 0xFF
                        sl = abs_steps & 0xFF
                        direction = 1 if steps > 0 else 0
                        
                        self.send_can_cmd(motor_id, 0xA2, sh, sm, sl, direction)
                    
                    elif 27 <= motor_id <= 29:
                        # 位移促动器
                        self.send_can_cmd(motor_id, 0xA2, 
                                         (steps >> 16) & 0xFF,
                                         (steps >> 8) & 0xFF,
                                         steps & 0xFF, 0x00)
                
                # 等待响应（简化处理）
                time.sleep(0.05)
                
            except ValueError:
                error_msg = f"电机 {motor_id} 的步数格式错误: {steps_text}"
                self.add_log("错误", error_msg)
                self.system_event_signal.emit(error_msg, "ERROR")
                QMessageBox.warning(self, "输入错误", error_msg)
    
    def query_position(self):
        """位置查询"""
        # 收集选中的电机
        self.active_motors = []
        for i, motor_widget in enumerate(self.motor_widgets):
            motor_widget.reset_position_display()
            if motor_widget.is_checked():
                self.active_motors.append(i)
        
        if not self.active_motors:
            QMessageBox.warning(self, "警告", "请先选择要查询的电机！")
            return
        
        # [修复逻辑] 先检查连接，再切换状态
        if not self.sequential_query_flag:
            # 准备开始查询
            if not self.net_connected:
                QMessageBox.warning(self, "警告", "网络未连接，无法开始查询！")
                return
                
            self.sequential_query_flag = True
            self.query_pos_btn.setText("停止查询")
            
            # 记录控制命令
            self.control_command_signal.emit("位置查询", {"motors": self.active_motors})
            self.add_log("控制", f"开始位置查询: {self.active_motors}")
            
            # 在新线程中发送查询命令
            threading.Thread(target=self.query_lvdt_thread, daemon=True).start()
            
        else:
            # 停止查询
            self.sequential_query_flag = False
            self.query_pos_btn.setText("位置查询")
            
            # 记录控制命令
            self.control_command_signal.emit("停止位置查询", {})
            self.add_log("控制", "停止位置查询")
    
    def query_lvdt_thread(self):
        """位置查询线程"""
        while self.sequential_query_flag and self.net_connected:
            for motor_id in self.active_motors:
                # 设置正在查询显示
                self.motor_widgets[motor_id].set_querying_display()
                
                # 发送查询命令
                self.send_can_cmd(motor_id, 0xA5, 0xFF, 0x00, 0x00, 0x00, log_cmd=False)
                time.sleep(0.05)
                
                # 查位移促动器上的力传感数据
                if 27 <= motor_id <= 29:
                    self.send_can_cmd(27, 0xA7, 0xFF, 0x00, 0x00, 0x00)
                    time.sleep(0.05)
                    self.send_can_cmd(27, 0xA7, 0xAF, 0x00, 0x00, 0x00)
                    time.sleep(0.05)
            
            time.sleep(0.5)  # 稍微延迟一下
    
    def closed_loop_supervisor(self):
        """闭环控制监控线程 - 实现±0.05N死区逻辑"""
        while self.is_supervisor_running and self.net_connected:
            try:
                # 获取当前需要监控的电机列表 (转换为list避免字典在遍历时变化)
                monitor_list = list(self.closed_loop_targets.keys())
                
                if not monitor_list:
                    time.sleep(0.1)
                    continue
                
                for motor_id in monitor_list:

                    if motor_id < 27:
                        # === 力电机逻辑 (保持不变) ===
                        self.send_can_cmd(motor_id, 0xA5, 0xFF, 0x00, 0x00, 0x00, log_cmd=False)
                        current_val = self.correction_current_forces[motor_id]
                        deadband = 0.05 # 力死区 0.05N
                        hysteresis = 0.1
                    else:
                        # === [新增] 位移电机逻辑 ===
                        # 1. 查询位移 (0xA7)
                        # 注意：位移电机27-29共用一个物理ID(27)，但这里我们逻辑上分开
                        # 发送 0xA7 查询 LVDT (对应 send_can_cmd 中的逻辑)
                        # 由于 send_can_cmd 内部对 27-29 做了映射，直接调用即可
                        # 但为了效率，最好不要对27/28/29分别发三次查询，因为一条指令回三个数据
                        # 这里简单处理：每次都发，下位机多回几次也无妨
                        self.send_can_cmd(motor_id, 0xA7, 0xFF, 0x00, 0x00, 0x00, log_cmd=False)
                        
                        current_val = self.current_positions[motor_id]
                        deadband = 2.0  # [假设] 位移死区 2个单位 (例如um)
                        hysteresis = 5.0

                    target_val = self.closed_loop_targets.get(motor_id)
                    if target_val is None: continue

                    diff = abs(current_val - target_val)
                    is_adjusting = self.closed_loop_adjusting.get(motor_id, True)
                    
                    # 通用死区逻辑
                    if is_adjusting:
                        if diff <= deadband:
                            # 到位停止 (0xA0)
                            self.send_can_cmd(motor_id, 0xA0, 0x00, 0x00, 0x00, 0x00, log_cmd=False)
                            self.closed_loop_adjusting[motor_id] = False
                            self.update_motor_view_signal.emit(motor_id, False)


                            # 更新状态显示（如果是力电机，有专门的信号；位移电机暂时没有专门的校正状态列）
                            if motor_id < 27:
                                self.update_correction_status_signal.emit(motor_id, current_val, "到位")
                            self.add_log("闭环", f"M{motor_id} 达到目标 {target_val} (当前{current_val:.1f})")
                        else:
                            # 维持调整 (发送 0xA1)
                            if motor_id < 27:
                                cmd_value = self.data_converter.convert_force_target_to_cmd(target_val)
                                sh, sl = (cmd_value >> 8) & 0xFF, cmd_value & 0xFF
                                self.send_can_cmd(motor_id, 0xA1, sh, sl, 0, 0, log_cmd=False)
                                self.update_correction_status_signal.emit(motor_id, current_val, "调整中")
                            else:
                                # 位移电机指令 (p3, p4)
                                cmd_value = self.data_converter.convert_pos_target_to_cmd(target_val)
                                sh, sl = (cmd_value >> 8) & 0xFF, cmd_value & 0xFF
                                self.send_can_cmd(motor_id, 0xA1, 0, 0, sh, sl, log_cmd=False)
                            self.update_motor_view_signal.emit(motor_id, True)

                    else:
                        if diff > hysteresis:
                            self.closed_loop_adjusting[motor_id] = True
                            self.add_log("闭环", f"M{motor_id} 偏离目标，重新激活")
                            self.update_motor_view_signal.emit(motor_id, True)

                    time.sleep(0.05)
                    
            except Exception as e:
                print(f"监控线程异常: {e}")
                
            time.sleep(0.1) # 轮询周期

    def close_loop_control(self):
        """闭环控制 - 启动带死区的监控"""
        # 收集选中的电机
        self.active_motors = []
        for i, motor_widget in enumerate(self.motor_widgets):
            motor_widget.reset_target_pos_color()
            if motor_widget.is_checked():
                motor_widget.reset_checkbox_color()
                self.active_motors.append(i)
        
        if not self.active_motors:
            QMessageBox.warning(self, "警告", "请先选择要控制的电机！")
            return
            
        if not self.net_connected:
            QMessageBox.warning(self, "警告", "网络未连接，无法执行操作！")
            return
        
        self.close_loop_ctrl_flag = 0x00

        # ================= [新增] 面型保持逻辑 =================
        # 如果当前操作包含位移促动器 (ID >= 27)，则自动锁定所有力促动器
        has_displacement_control = any(mid >= 27 for mid in self.active_motors)
        
        if has_displacement_control:
            locked_count = 0
            for mid in range(27): # 遍历所有力促动器 (0-26)
                # 如果该力促动器 1.没被用户选中 且 2.不在当前的闭环监控列表中
                if mid not in self.active_motors and mid not in self.closed_loop_targets:
                    # 获取当前实时力值作为保持目标
                    # 注意：correction_current_forces 存储了最近一次查询到的力值
                    current_force = self.correction_current_forces[mid]
                    
                    # 添加到闭环监控目标
                    self.closed_loop_targets[mid] = current_force
                    self.closed_loop_adjusting[mid] = True
                    
                    # 发送闭环指令 (0xA1)
                    cmd_value = self.data_converter.convert_force_target_to_cmd(current_force)
                    sh, sl = (cmd_value >> 8) & 0xFF, cmd_value & 0xFF
                    self.send_can_cmd(mid, 0xA1, sh, sl, 0, 0, log_cmd=False)
                    
                    # 更新UI状态 (绿色文字 + 更新目标值输入框)
                    if mid < len(self.motor_widgets):
                        self.update_motor_pos_text_color(mid, QColor(0, 255, 0))
                        self.motor_widgets[mid].target_edit.setText(f"{current_force:.3f}")
                    
                    locked_count += 1
            
            if locked_count > 0:
                self.add_log("系统", f"检测到位移调整，已自动锁定 {locked_count} 个力促动器以保持当前面型")
        # ========================================================
        
        # 1. 更新用户选中电机的目标值 (原有逻辑)
        for motor_id in self.active_motors:
            try:
                motor_widget = self.motor_widgets[motor_id]
                target_text = motor_widget.get_target_pos_text()
                if target_text:
                    target_val = float(target_text)
                    
                    # ================= 限位保护 (+-150N) =================
                    # 仅针对力促动器 (0-26)
                    if motor_id < 27:
                        if target_val > 150.0:
                            self.add_log("警告", f"M{motor_id:02d} 手动目标力 > 150N，已限制")
                            target_val = 150.0
                            motor_widget.target_edit.setText("150.000")
                        elif target_val < -150.0:
                            self.add_log("警告", f"M{motor_id:02d} 手动目标力 < -150N，已限制")
                            target_val = -150.0
                            motor_widget.target_edit.setText("-150.000")

                    else:
                        if target_val < 2000: 
                            self.add_log("警告", f"M{motor_id:02d} 位移目标 < 2000，已限制为 2000")
                            target_val = 2000.0
                            motor_widget.target_edit.setText("2000")
                            
                        elif target_val > 3000.0: 
                            self.add_log("警告", f"M{motor_id:02d} 位移目标 > 3000，已限制为 3000")
                            target_val = 3000.0
                            motor_widget.target_edit.setText("3000")
                    # ==========================================================

                    # 记录到字典中，供Supervisor使用
                    self.closed_loop_targets[motor_id] = target_val
                    self.closed_loop_adjusting[motor_id] = True 
                    
                    self.update_motor_pos_text_color(motor_id, QColor(0, 255, 0)) # 标记为绿色
                    if motor_id < 27:
                        cmd_value = self.data_converter.convert_force_target_to_cmd(target_val)
                        sh = (cmd_value >> 8) & 0xFF, cmd_value & 0xFF
                        # 注意：原来的代码这里有一个小bug，sh=(...) & 0xFF 后面多了一个逗号变成元组了？
                        # 修正为：
                        sh = (cmd_value >> 8) & 0xFF
                        sl = cmd_value & 0xFF
                        self.send_can_cmd(motor_id, 0xA1, sh, sl, 0, 0)
                    else:
                        # 位移电机
                        cmd_value = self.data_converter.convert_pos_target_to_cmd(target_val)
                        sh = (cmd_value >> 8) & 0xFF
                        sl = cmd_value & 0xFF
                        self.send_can_cmd(motor_id, 0xA1, 0, 0, sh, sl)

            except ValueError:
                self.add_log("错误", f"电机 {motor_id} 目标值无效")

        # 记录日志
        self.control_command_signal.emit("闭环控制", {"motors": self.active_motors})
        self.add_log("控制", f"开始闭环监控: {self.active_motors}")
        
        # 2. 启动监控线程 (如果尚未运行)
        if not self.is_supervisor_running:
            self.is_supervisor_running = True
            threading.Thread(target=self.closed_loop_supervisor, daemon=True).start()  


    def clear_target_force(self):
        """清空选中力促动器的目标力 (置为0)"""
        count = 0
        has_selection = False
        
        for i, motor_widget in enumerate(self.motor_widgets):
            if motor_widget.is_checked():
                has_selection = True
                # 仅针对力促动器 (0-26)
                if i < 27:
                    # 直接设置目标值输入框的文本为 0.000
                    if hasattr(motor_widget, 'target_edit'):
                        motor_widget.target_edit.setText("0.000")
                        # 如果之前有红色警告等状态，也可以顺便重置颜色
                        motor_widget.reset_target_pos_color()
                        count += 1
        
        if not has_selection:
            QMessageBox.warning(self, "警告", "请先选择要操作的电机！")
            return
            
        if count > 0:
            self.add_log("控制", f"已将 {count} 个选中的力促动器目标力置为 0")
        else:
            self.add_log("提示", "未选中力促动器 (可能仅选中了位移促动器)")

    def close_loop_ctrl_thread(self):
        """闭环控制线程"""
        for motor_id in self.active_motors:
            try:
                motor_widget = self.motor_widgets[motor_id]
                target_text = motor_widget.get_target_pos_text()
                
                if target_text:
                    self.add_log("控制", f"电机 {motor_id} 目标值: {target_text}")
                    
                    if motor_id < 27:
                        # 力促动器
                        target = float(target_text)
                        cmd_value = self.data_converter.convert_force_target_to_cmd(target)
                        sh = (cmd_value >> 8) & 0xFF
                        sl = cmd_value & 0xFF
                        self.send_can_cmd(motor_id, 0xA1, sh, sl, 0, 0)
                    else:
                        # 位移促动器
                        target = float(target_text)
                        cmd_value = self.data_converter.convert_pos_target_to_cmd(target)
                        sh = (cmd_value >> 8) & 0xFF
                        sl = cmd_value & 0xFF
                        self.send_can_cmd(motor_id, 0xA1, 0, 0, sh, sl)
                
                # 等待响应（简化处理）
                time.sleep(0.05)
                
            except ValueError:
                error_msg = f"电机 {motor_id} 的目标值格式错误: {target_text}"
                self.add_log("错误", error_msg)
                self.system_event_signal.emit(error_msg, "ERROR")
                QMessageBox.warning(self, "输入错误", error_msg)
    
    def send_can_cmd(self, motor_id, cmd_type, p1, p2, p3, p4,log_cmd=True):
        """发送CAN命令"""
        if not self.net_connected:
            self.add_log("错误", f"发送失败: 网络未连接 (电机 {motor_id})")
            return
        
        try:
            cmd = bytearray(self.can_cmd_template)
            cmd[4] = motor_id  # ID
            
            if 0 <= motor_id <= 26:
                # 力促动器
                cmd[5] = 0x52
                cmd[6] = 0x54
                cmd[7] = cmd_type
                cmd[8] = p1
                cmd[9] = p2
                cmd[10] = p3
                cmd[11] = p4
            
            elif 27 <= motor_id <= 29:
                # 位移促动器
                cmd[4] = 27  # 27-29共用一个ID
                cmd[5] = 0x52
                cmd[6] = cmd_type
                cmd[7] = 0x80 + (motor_id - 27)
                cmd[8] = p1
                cmd[9] = p2
                cmd[10] = p3
                cmd[11] = p4
            
            # 发送命令
            success = self.network_manager.send_data(cmd)
            if success:
                if log_cmd:
                    hex_str = ' '.join(f'{b:02X}' for b in cmd)
                    self.add_log("控制", f"发送命令到电机 {motor_id}: {hex_str}")
                time.sleep(0.1)
                
                # 发送确认
                cmd[7] = 0xAA
                self.network_manager.send_data(cmd)
            else:
                error_msg = f"发送命令到电机 {motor_id} 失败"
                self.add_log("错误", error_msg)
                self.system_event_signal.emit(error_msg, "ERROR")
        
        except Exception as e:
            error_msg = f"发送命令失败: {e}"
            self.add_log("错误", error_msg)
            self.system_event_signal.emit(error_msg, "ERROR")
    
    def process_received_data(self, data):
        """处理接收到的数据"""
        # 查找特定模式
        for i in range(5, len(data) - 1):
            # 位移促动器上的LVDT和力传感数据
            if data[i - 1] == 27 and data[i] == 0xA7:
                self.process_displacement_actuator_data(data, i)
            

            if i + 3 >= len(data):
                continue

            # 是否收到停止指令
            if data[i] == 0xA0 and data[i + 3] == 0xAA:
                motor_id = data[i - 1]
                if 0 <= motor_id <= 26:
                    self.update_motor_checkbox_color(motor_id, QColor(255, 0, 0))
                    self.stop_flag |= (1 << motor_id)
            
            # 是否收到闭环指令
            if data[i] == 0xA1 and data[i + 3] == 0x11:
                motor_id = data[i - 1]
                if 0 <= motor_id <= 29:
                    self.update_motor_pos_text_color(motor_id, QColor(0, 255, 0))
                    self.close_loop_ctrl_flag |= (1 << motor_id)
            
            # 是否收到开环指令
            if data[i] == 0xA2 and data[i + 3] == 0x22:
                motor_id = data[i - 1]
                if 0 <= motor_id <= 29:
                    self.update_motor_steps_text_color(motor_id, QColor(0, 255, 0))
                    self.steps_ctrl_flag |= (1 << motor_id)
            
            # 是否收到力促动器的力传感数据
            if data[i] == 0xA5 and data[i + 3] == 0x55:
                motor_id = data[i - 1]
                
                if motor_id < 27:
                    fx = data[i + 1] * 256 + data[i + 2]
                    force = self.data_converter.convert_ad_to_force(fx)
                    display_text = f"{force:.3f}"
                else:
                    fx = data[i + 1] * 256 + data[i + 2]
                    force = 5000.0 * (fx / 65535.0)
                    display_text = f"{force:.3f}"
                
                if 0 <= motor_id <= 29:
                    self.motor_data_updated.emit(motor_id, "position", float(display_text))
                    self.query_lvdt_flag |= (1 << motor_id)
                    
                    # 记录接收到的数据
                    # self.add_log("数据", f"电机 {motor_id} 位置: {display_text}")
                 # 新增：发送力数据到校正力求解窗口
                   
                    if motor_id < 27:  # 只处理力促动器
                        self.send_force_to_correction_widget(motor_id, force)               
                

    def execute_displacement_correction_from_ui(self):
        """执行位移校正"""
        if not self.correction_widget or not hasattr(self.correction_widget, 'current_disp_deltas'):
            return
        
        deltas = self.correction_widget.current_disp_deltas
        if not deltas: return
        
        # 弹窗确认
        reply = QMessageBox.question(self.correction_widget, "确认执行",
            f"确定要执行位移校正吗？\n\n"
            f"M27: {deltas[27]:+.1f} um\n"
            f"M28: {deltas[28]:+.1f} um\n"
            f"M29: {deltas[29]:+.1f} um\n\n"
            "注意：将自动锁定其他力促动器以保持面型。",
            QMessageBox.Yes | QMessageBox.No)
            
        if reply == QMessageBox.Yes:
            self.apply_displacement_correction(deltas)


    def apply_displacement_correction(self, disp_deltas):
        if not self.net_connected: return
        
        # 锁定当前力分布
        self.close_loop_control() 
        
        for mid, delta in disp_deltas.items():
            # 获取当前位置 (注意：需要确保 self.current_positions 已有数据)
            # 如果没数据，默认为 2500 或报错
            curr = self.current_positions[mid] if mid < len(self.current_positions) else 2500
            target = curr + delta
            
            # 限位
            target = max(2000, min(3000, target))
            
            # 设置闭环目标
            self.closed_loop_targets[mid] = target
            self.closed_loop_adjusting[mid] = True
            
            # 发送指令
            cmd = self.data_converter.convert_pos_target_to_cmd(target)
            self.send_can_cmd(mid, 0xA1, 0, 0, (cmd>>8)&0xFF, cmd&0xFF)
            
            # 更新UI
            if mid < len(self.motor_widgets):
                self.motor_widgets[mid].target_edit.setText(f"{target:.0f}")
                self.motor_widgets[mid].set_target_pos_color(QColor(0,255,0))
        
        # 确保监控运行
        if not self.is_supervisor_running:
            self.is_supervisor_running = True
            threading.Thread(target=self.closed_loop_supervisor, daemon=True).start()
            
        self.add_log("校正", "位移校正指令已发送")



    
    def process_displacement_actuator_data(self, data, i):
        """处理位移促动器数据"""
        # 查3个LVDT数据
        if data[i + 1] == 0xAA:
            for j in range(3):
                fx = (data[i + 2 + j * 2] << 8) + data[i + 3 + j * 2]
                position = fx * 5000 / 65535
                motor_id = 27 + j

                if motor_id < len(self.current_positions):
                    self.current_positions[motor_id] = position

                display_text = f"{position:.0f}"
                self.motor_data_updated.emit(motor_id, "position", float(display_text))
                # self.add_log("数据", f"位移促动器 {motor_id-26} LVDT: {display_text}")
        
        # 查位移促动器力传感器数据
        elif 0xF1 <= data[i + 1] <= 0xF6:
            force_index = data[i + 1] - 0xF1
            # 原始数据拼接
            fx = (data[i + 2] << 24) + (data[i + 3] << 16) + (data[i + 4] << 8) + data[i + 5]
            
            # [修复] 增加符号位处理：如果最高位为1（大于 0x7FFFFFFF），则是负数，需要减去 2^32
            if fx > 0x7FFFFFFF:
                fx -= 0x100000000
                
            force = fx / 1000.0
            display_text = f"{force:.3f}"
            
            # 更新对应的力传感器显示
            motor_id = 27 + (force_index // 2)
            sensor_type = "force1" if force_index % 2 == 0 else "force2"
            
            # 使用 LogWidget 的安全信号或直接忽略日志，避免在主线程中频繁调用导致卡顿
            # self.add_log("数据", f"位移促动器 {motor_id-26} 力传感器{force_index%2+1}: {display_text}")
            
            self.motor_data_updated.emit(motor_id, sensor_type, force)

    def send_force_to_correction_widget(self, motor_id, force):
        """发送力数据到校正力求解窗口"""
        try:
            if hasattr(self, 'correction_widget') and self.correction_widget:
                # 使用线程安全的信号发射方式
                from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                
                # 定义更新函数
                def update_correction_force():
                    if 0 <= motor_id < 27:
                        # 更新校正力求解窗口的当前力显示
                        self.correction_widget.update_motor_status(motor_id, force, "正常")
                        
                        # 同时更新校正监控中的当前力
                        if hasattr(self, 'correction_current_forces'):
                            self.correction_current_forces[motor_id] = force
                
                # 确保在主线程中执行
                from PyQt5.QtCore import QThread
                if QThread.currentThread() != self.thread():
                    QMetaObject.invokeMethod(self, "update_correction_force_slot", 
                                            Qt.QueuedConnection,
                                            Q_ARG(int, motor_id),
                                            Q_ARG(float, force))
                else:
                    update_correction_force()
                    
        except Exception as e:
            print(f"发送力数据到校正窗口失败: {e}")

    def update_correction_force_slot(self, motor_id, force):
        """线程安全地更新校正力显示"""
        try:
            if hasattr(self, 'correction_widget') and self.correction_widget:
                if 0 <= motor_id < 27:
                    # 获取当前状态
                    status = "正常"
                    if hasattr(self, 'correction_motor_status'):
                        status = self.correction_motor_status[motor_id]
                    
                    # 更新校正力求解窗口
                    self.correction_widget.update_motor_status(motor_id, force, status)
                    
                    # 更新校正监控中的当前力
                    if hasattr(self, 'correction_current_forces'):
                        self.correction_current_forces[motor_id] = force
                        
        except Exception as e:
            print(f"更新校正力显示失败: {e}")

    def update_motor_display(self, motor_id, data_type, value):
        """更新电机显示"""
        if 0 <= motor_id < len(self.motor_widgets):
            motor_widget = self.motor_widgets[motor_id]
            
            if data_type == "position":
                motor_widget.update_position_display(value)
            elif data_type == "force1":
                motor_widget.update_force1_display(value)
            elif data_type == "force2":
                motor_widget.update_force2_display(value)
    
        # 2. 更新简洁版电机控件  
        if hasattr(self, 'mini_motor_widgets') and 0 <= motor_id < len(self.mini_motor_widgets):
            mini_motor_widget = self.mini_motor_widgets[motor_id]
            
            should_update = False
            
            if motor_id < 27:
                # 力促动器：只显示主数据 (position在这里代表力值)
                if data_type == "position":
                    should_update = True
            else:
                # 位移促动器：[关键修复] 仅允许 "position" (位移) 数据更新界面
                # 忽略 "force1" 和 "force2" 数据，防止覆盖位移显示
                if data_type == "position":
                    should_update = True
            
            if should_update:
                mini_motor_widget.update_value(value, "position")   
  
  
    def update_motor_checkbox_color(self, motor_id, color):
        """更新电机选择框颜色"""
        if 0 <= motor_id < len(self.motor_widgets):
            self.motor_widgets[motor_id].set_checkbox_color(color)
    
    def update_motor_pos_text_color(self, motor_id, color):
        """更新电机目标位置文本颜色"""
        if 0 <= motor_id < len(self.motor_widgets):
            self.motor_widgets[motor_id].set_target_pos_color(color)
    
    def update_motor_steps_text_color(self, motor_id, color):
        """更新电机步数文本颜色"""
        if 0 <= motor_id < len(self.motor_widgets):
            self.motor_widgets[motor_id].set_steps_color(color)
    
    def handle_received_data(self, data):
        """处理接收到的数据（通过信号）"""
        self.process_received_data(data)
    
    def show_about(self):
        """显示关于对话框"""
        about_text = """
        <h2>主动支撑控制系统</h2>
        <p>版本: 2.0.0</p>
        <p>基于弯月镜支撑控制开发的电机控制系统</p>
        <p>支持主动支撑的促动器的实时监控和控制</p>
        <p>技术支持：yongbohe2025@niaot.ac.cn</p>
        <p>© 2025 版权所有 中国科学院南京天文光学技术研究所</p>
        """
        QMessageBox.about(self, "关于", about_text)
    
    def closeEvent(self, event: QCloseEvent):
        """关闭事件 - 同时关闭所有子窗口"""
        reply = QMessageBox.question(
            self, '确认退出',
            '确定要退出程序吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 1. 关闭波前传感窗口 (如果是独立窗口)
            if self.cwfs_window is not None:
                self.cwfs_window.close()
            
            # 2. 关闭校正力求解窗口 (如果是独立浮动窗口)
            # 如果它是嵌入在 Tab 里的，会随主窗口自动销毁；如果是浮动的，需要手动关闭
            if self.correction_widget is not None:
                self.correction_widget.close()

            # 3. 清理网络资源
            self.disconnect_from_server()
            
            # 4. 记录日志并退出
            self.add_log("信息", "系统关闭")
            self.system_event_signal.emit("系统关闭", "INFO")
            event.accept()
        else:
            event.ignore()