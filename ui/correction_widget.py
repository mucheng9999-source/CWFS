"""
校正力求解界面组件 (在UI层动态计算初始PV和RMS)
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                             QPushButton, QGroupBox, QGridLayout, QTableWidget,
                             QTableWidgetItem, QTextEdit, QSpinBox, QDoubleSpinBox,
                             QProgressBar, QSplitter, QHeaderView, QTabWidget,
                             QMessageBox, QComboBox)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QColor, QFont, QBrush
import pyqtgraph as pg
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# 设置字体支持中文
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

# --- Zernike 频谱图组件 ---
class ZernikeSpectrumWidget(QWidget):
    """Zernike系数频谱图显示组件 (柱状图)"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(6, 5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
    
    def plot_spectrum(self, coeffs, start_index=1, title="Zernike 系数频谱"):
        """绘制系数柱状图"""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        
        # [安全检查]
        if coeffs is None or len(coeffs) == 0:
            self.canvas.draw()
            return

        # 1. 数据准备
        indices = np.arange(start_index, start_index + len(coeffs))
        
        # 单位转换: 米 -> 纳米 (x 1e9)
        values = np.array(coeffs) * 1e9 
        
        # 2. 绘制柱状图
        bars = ax.bar(indices, values, color='teal', alpha=0.7, edgecolor='black')
        
        # 3. 添加数值标签
        for bar in bars:
            height = bar.get_height()
            y_offset = 20 if height >= 0 else -20 
            va = 'bottom' if height >= 0 else 'top'
            ax.text(bar.get_x() + bar.get_width()/2., height,
                    f'{height:.1f}',  
                    ha='center', va=va, 
                    fontsize=9, color='black', rotation=0) 

        # 4. 设置坐标轴和标题
        ax.set_xlabel("Zernike Index (Noll)")
        ax.set_ylabel("Coefficient Value (nm)") 
        ax.set_title(title)
        
        ax.grid(True, linestyle='--', alpha=0.5, axis='y')
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        
        y_max = np.max(np.abs(values)) if len(values) > 0 else 1.0
        if y_max == 0: y_max = 1.0
        ax.set_ylim(-y_max * 1.2, y_max * 1.2)
        
        self.figure.tight_layout()
        self.canvas.draw()


class ZernikePlotWidget(QWidget):
    """Zernike多项式显示组件"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(5, 5)) 
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
    
    def plot_zernike(self, x, y, values, title="Zernike 多项式"):
        self.figure.clear()
        
        if isinstance(x, list): x = np.array(x)
        if isinstance(y, list): y = np.array(y)
        if isinstance(values, list): values = np.array(values)
        
        min_len = min(len(x), len(y), len(values))
        x = x[:min_len]
        y = y[:min_len]
        values = values[:min_len]
        
        ax = self.figure.add_subplot(111)
        
        scatter = ax.scatter(x, y, c=values * 1e6, cmap='jet', 
                        edgecolors='none', s=20)
        
        ax.set_aspect('equal')
        cbar = self.figure.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label('变形量 (nm)')
        
        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_title(title)
        
        self.figure.tight_layout()
        self.canvas.draw()


class ResidualPlotWidget(QWidget):
    """残差图显示组件"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        self.figure = Figure(figsize=(5, 5))
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
    
    def plot_residuals(self, x, y, residuals, title="残差分布"):
        self.figure.clear()
        
        if isinstance(x, list): x = np.array(x)
        if isinstance(y, list): y = np.array(y)
        if isinstance(residuals, list): residuals = np.array(residuals)
        
        min_len = min(len(x), len(y), len(residuals))
        x = x[:min_len]
        y = y[:min_len]
        residuals = residuals[:min_len]
        
        ax = self.figure.add_subplot(111)
        
        scatter = ax.scatter(x, y, c=residuals * 1e6, cmap='jet', 
                        edgecolors='none', s=20)
        
        ax.set_aspect('equal')
        
        cbar = self.figure.colorbar(scatter, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label('残差 (nm)')
        
        ax.set_xlabel('X (mm)')
        ax.set_ylabel('Y (mm)')
        ax.set_title(title)
        
        self.figure.tight_layout()
        self.canvas.draw()


class ForceDistributionWidget(QWidget):
    """力分布显示组件"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')
        self.plot_widget.setLabel('left', '校正力 (N)')
        self.plot_widget.setLabel('bottom', '电机序号')
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)
        layout.addWidget(self.plot_widget)
    
    def plot_forces(self, forces, title="校正力分布"):
        self.plot_widget.clear()
        x = list(range(len(forces)))
        y = forces
        
        bg = pg.BarGraphItem(x=x, height=y, width=0.6, brush='#2196F3')
        self.plot_widget.addItem(bg)
        
        zero_line = pg.InfiniteLine(pos=0, angle=0, 
                                   pen=pg.mkPen('r', width=1, style=Qt.DashLine))
        self.plot_widget.addItem(zero_line)
        
        if len(x) > 0:
            self.plot_widget.setXRange(-1, len(x))
            if len(y) > 0:
                max_abs = max(abs(min(y)), abs(max(y)))
            else:
                max_abs = 0
            
            padding = max_abs * 0.2 if max_abs > 0 else 1.0
            self.plot_widget.setYRange(-max_abs - padding, max_abs + padding)
        
        self.plot_widget.setTitle(title, size="12pt")


class CorrectionWidget(QWidget):
    """校正力求解结果显示组件"""
    
    # 信号定义
    apply_correction_requested = pyqtSignal(list)
    send_to_motors_requested = pyqtSignal(list)
    calculation_requested = pyqtSignal(int, float, float)
    stop_correction_requested = pyqtSignal()

    # 【回退】恢复使用 6 个参数的安全信号，防止底层崩溃
    _safe_update_signal = pyqtSignal(list, float, float, list, list, list)
    _safe_progress_signal = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.force_distribution = []
        self.pv_value = 0.0
        self.rms_value = 0.0
        self.residuals = []
        self.coordinates = []
        
        self.current_disp_deltas = {} 
        self.current_zernike_coeffs = []
        self.is_cwfs_mode = False

        self._safe_update_signal.connect(self.update_results, Qt.QueuedConnection)
        self._safe_progress_signal.connect(self.update_progress, Qt.QueuedConnection)

        self.init_ui()
        self.setup_styles()
        self.update_status("就绪")
    
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # 参数设置区域
        param_group = QGroupBox("校正参数设置")
        param_layout = QGridLayout()
        
        param_layout.addWidget(QLabel("Zernike阶数:"), 0, 0)
        self.zernike_combo = QComboBox()
        
        zernike_names = {
            0: "平移 (Piston/Bias)", 1: "X轴倾斜 (Tilt X)", 2: "Y轴倾斜 (Tilt Y)", 3: "离焦 (Power)",
            4: "0度像散 (Astig X)", 5: "45度像散 (Astig Y)", 6: "X轴慧差 (Coma X)", 7: "Y轴慧差 (Coma Y)",
            8: "球差 (Primary Spherical)", 9: "X轴三叶草 (Trefoil X)", 10: "Y轴三叶草 (Trefoil Y)",
            11: "X轴二级像散 (Secondary Astigmatism X)", 12: "Y轴二级像散 (Secondary Astigmatism Y)",
            13: "X轴二级慧差 (Secondary Coma X)", 14: "Y轴二级慧差 (Secondary Coma Y)",
            15: "二级球差 (Secondary Spherical)", 16: "X轴四叶草 (Tetrafoil X)", 17: "Y轴四叶草 (Tetrafoil Y)",
            18: "X轴二级三叶草 (Secondary Trefoil X)", 19: "Y轴二级三叶草 (Secondary Trefoil Y)",
            20: "X轴三级像散 (Tertiary Astigmatism X)", 21: "Y轴三级像散 (Tertiary Astigmatism Y)",
            22: "X轴三级慧差 (Tertiary Coma X)", 23: "Y轴三级慧差 (Tertiary Coma Y)",
            24: "三级球差 (Tertiary Spherical)", 25: "X轴五叶草 (Pentafoil X)", 26: "Y轴五叶草 (Pentafoil Y)",
            27: "X轴二级四叶草 (Secondary Tetrafoil X)", 28: "Y轴二级四叶草 (Secondary Tetrafoil Y)",
            29: "X轴三级三叶草 (Tertiary Trefoil X)", 30: "Y轴三级三叶草 (Tertiary Trefoil Y)",
            31: "X轴四级像散 (Quaternary Astigmatism X)", 32: "Y轴四级像散 (Quaternary Astigmatism Y)",
            33: "X轴四级慧差 (Quaternary Coma X)", 34: "Y轴四级慧差 (Quaternary Coma Y)",
            35: "四级球差 (Quaternary Spherical)", 36: "五级球差 (Quinary Spherical)"  
        }
        
        for i in range(37):
            name = zernike_names.get(i, f"项 {i}")
            self.zernike_combo.addItem(f"{i} - {name}")
            
        self.zernike_combo.setCurrentIndex(4) 
        self.zernike_combo.setMinimumWidth(200)
        
        param_layout.addWidget(self.zernike_combo, 0, 1)
        
        param_layout.addWidget(QLabel("缩放因子:"), 0, 2)
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.001, 1.0)
        self.scale_spin.setValue(0.01)
        self.scale_spin.setSingleStep(0.001)
        self.scale_spin.setDecimals(3)
        param_layout.addWidget(self.scale_spin, 0, 3)
        
        param_layout.addWidget(QLabel("阻尼因子:"), 1, 0)
        self.damping_spin = QDoubleSpinBox()
        self.damping_spin.setRange(0,1)
        self.damping_spin.setValue(0.001)
        self.damping_spin.setSingleStep(0.0001)
        self.damping_spin.setDecimals(5)
        param_layout.addWidget(self.damping_spin, 1, 1)
        
        self.calculate_btn = QPushButton("开始计算 (理论)")
        self.calculate_btn.clicked.connect(self.start_calculation)
        param_layout.addWidget(self.calculate_btn, 1, 2, 1, 2)
        
        param_group.setLayout(param_layout)
        main_layout.addWidget(param_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)
        
        # 创建选项卡
        self.tab_widget = QTabWidget()
        
        # 选项卡1: 力分布结果
        result_tab = QWidget()
        result_layout = QVBoxLayout(result_tab)
        result_splitter = QSplitter(Qt.Vertical)
        
        table_group = QGroupBox("校正力分布结果 (27个力电机)")
        table_layout = QVBoxLayout()
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(["电机ID", "校正力(N)", "状态", "目标力(N)", "基准力(N)", "实时力(N)"])
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_table.setAlternatingRowColors(True)
        table_layout.addWidget(self.result_table)

        stats_layout = QHBoxLayout()
        self.pv_label = QLabel("PV: --")
        self.rms_label = QLabel("RMS: --")
        self.status_label = QLabel("就绪")
        stats_layout.addWidget(self.pv_label)
        stats_layout.addWidget(self.rms_label)
        stats_layout.addStretch()
        stats_layout.addWidget(self.status_label)
        table_layout.addLayout(stats_layout)
        
        table_group.setLayout(table_layout)
        result_splitter.addWidget(table_group)
        
        self.force_plot_widget = ForceDistributionWidget()
        result_splitter.addWidget(self.force_plot_widget)
        result_splitter.setSizes([300, 200])
        result_layout.addWidget(result_splitter)
        self.tab_widget.addTab(result_tab, "力分布")
        
        # 选项卡: 位移校正
        disp_tab = QWidget()
        disp_tab_layout = QVBoxLayout(disp_tab)
        
        z_group = QGroupBox("输入 Zernike 系数 (前3项)")
        z_layout = QGridLayout()
        
        z_layout.addWidget(QLabel("Z1 (Piston/平移):"), 0, 0)
        self.lbl_z_piston = QLabel("-- nm")
        z_layout.addWidget(self.lbl_z_piston, 0, 1)
        
        z_layout.addWidget(QLabel("Z2 (Tip/X倾斜):"), 1, 0)
        self.lbl_z1 = QLabel("-- nm")
        z_layout.addWidget(self.lbl_z1, 1, 1)
        
        z_layout.addWidget(QLabel("Z3 (Tilt/Y倾斜):"), 2, 0)
        self.lbl_z2 = QLabel("-- nm")
        z_layout.addWidget(self.lbl_z2, 2, 1)
        
        for lbl in [self.lbl_z_piston, self.lbl_z1, self.lbl_z2]:
            lbl.setStyleSheet("color: #555; font-family: monospace; font-size: 11pt;")
            
        z_group.setLayout(z_layout)
        disp_tab_layout.addWidget(z_group)
        
        d_group = QGroupBox("计算位移增量 (M27-M29)")
        d_layout = QGridLayout()
        
        d_layout.addWidget(QLabel("M27 (右):"), 0, 0)
        self.lbl_d27 = QLabel("-- μm")
        d_layout.addWidget(self.lbl_d27, 0, 1)
        
        d_layout.addWidget(QLabel("M28 (上):"), 1, 0)
        self.lbl_d28 = QLabel("-- μm")
        d_layout.addWidget(self.lbl_d28, 1, 1)
        
        d_layout.addWidget(QLabel("M29 (左):"), 2, 0)
        self.lbl_d29 = QLabel("-- μm")
        d_layout.addWidget(self.lbl_d29, 2, 1)
        
        for lbl in [self.lbl_d27, self.lbl_d28, self.lbl_d29]:
            lbl.setStyleSheet("color: #1976D2; font-weight: bold; font-family: monospace; font-size: 12pt;")
            
        d_group.setLayout(d_layout)
        disp_tab_layout.addWidget(d_group)
        
        action_layout = QHBoxLayout()
        action_layout.addStretch()
        
        self.btn_exec_disp = QPushButton("执行位移校正")
        self.btn_exec_disp.setMinimumHeight(50)
        self.btn_exec_disp.setMinimumWidth(150)
        self.btn_exec_disp.setStyleSheet("""
            QPushButton { 
                background-color: #673AB7; color: white; 
                font-weight: bold; font-size: 11pt; border-radius: 5px; 
            }
            QPushButton:hover { background-color: #5E35B1; }
            QPushButton:disabled { background-color: #BDBDBD; }
        """)
        self.btn_exec_disp.setEnabled(False)
        self.btn_exec_disp.setToolTip("调整 M27, M28, M29 的位置，并自动锁定其他力促动器")
        
        action_layout.addWidget(self.btn_exec_disp)
        action_layout.addStretch()
        
        disp_tab_layout.addLayout(action_layout)
        disp_tab_layout.addStretch()
        
        self.tab_widget.insertTab(1, disp_tab, "位移校正")

        # 选项卡2: 图形分析
        graph_tab = QWidget()
        graph_layout = QHBoxLayout(graph_tab)
        graph_layout.setSpacing(20) 
        
        self.zernike_plot_widget = ZernikePlotWidget()
        graph_layout.addWidget(self.zernike_plot_widget)
        
        self.residual_plot_widget = ResidualPlotWidget()
        graph_layout.addWidget(self.residual_plot_widget)
        
        self.tab_widget.addTab(graph_tab, "图形分析")

        # 选项卡3: Zernike 频谱
        spectrum_tab = QWidget()
        spectrum_layout = QVBoxLayout(spectrum_tab)
        self.spectrum_plot_widget = ZernikeSpectrumWidget()
        spectrum_layout.addWidget(self.spectrum_plot_widget)
        self.tab_widget.addTab(spectrum_tab, "Zernike 频谱")
        
        main_layout.addWidget(self.tab_widget, 1)
        
        control_layout = QHBoxLayout()
        self.apply_btn = QPushButton("应用到界面")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply_correction)
        control_layout.addWidget(self.apply_btn)
        
        self.send_btn = QPushButton("发送到电机")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self.send_to_motors)
        control_layout.addWidget(self.send_btn)
        
        self.stop_btn = QPushButton("停止校正")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_correction)
        control_layout.addWidget(self.stop_btn)
        
        self.clear_btn = QPushButton("清空结果")
        self.clear_btn.clicked.connect(self.clear_results)
        control_layout.addWidget(self.clear_btn)
        
        control_layout.addStretch()
        main_layout.addLayout(control_layout)
        
        log_group = QGroupBox("计算日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group)
        
        self.init_result_table()
    
    def init_result_table(self):
        self.result_table.setRowCount(27)
        for i in range(27):
            id_item = QTableWidgetItem(f"M{i:02d}")
            id_item.setTextAlignment(Qt.AlignCenter)
            id_item.setForeground(QColor("#1971c2"))
            self.result_table.setItem(i, 0, id_item)
            self.result_table.setItem(i, 1, QTableWidgetItem("--"))      
            self.result_table.setItem(i, 2, QTableWidgetItem("未计算"))   
            self.result_table.setItem(i, 3, QTableWidgetItem("0.000"))    
            self.result_table.setItem(i, 4, QTableWidgetItem("0.000"))    
            self.result_table.setItem(i, 5, QTableWidgetItem("0.000"))     
    
    def set_base_forces(self, base_forces):
        for i, force in enumerate(base_forces):
            if i < self.result_table.rowCount():
                self.result_table.setItem(i, 4, QTableWidgetItem(f"{force:.3f}"))

    def setup_styles(self):
        self.apply_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; border-radius: 4px; min-width: 80px; }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.send_btn.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white; font-weight: bold; padding: 8px; border-radius: 4px; min-width: 80px; }
            QPushButton:hover { background-color: #1976D2; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.stop_btn.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white; font-weight: bold; padding: 8px; border-radius: 4px; min-width: 80px; }
            QPushButton:hover { background-color: #d32f2f; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.clear_btn.setStyleSheet("""
            QPushButton { background-color: #ff9800; color: white; font-weight: bold; padding: 8px; border-radius: 4px; min-width: 80px; }
            QPushButton:hover { background-color: #f57c00; }
        """)
        self.pv_label.setStyleSheet("color: #FF5722; font-weight: bold; font-size: 10pt;")
        self.rms_label.setStyleSheet("color: #3F51B5; font-weight: bold; font-size: 10pt;")
    
    def start_calculation(self):
        self.log_message("开始计算校正力 (手动模式)...")
        self.update_status("计算中...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.calculate_btn.setEnabled(False)
        self.is_cwfs_mode = False 
        self.current_zernike_coeffs = [] 
        self.calculation_requested.emit(self.zernike_combo.currentIndex(), self.scale_spin.value(), self.damping_spin.value())
    
    def update_zernike_coeffs(self, coeffs):
        self.current_zernike_coeffs = coeffs
        self.is_cwfs_mode = True
        
        self.log_message(f">>> 收到外部 Zernike 系数输入，共 {len(coeffs)} 项")
        if len(coeffs) > 0:
            try:
                vals = []
                for i in range(min(5, len(coeffs))):
                    val = coeffs[i]
                    if hasattr(val, 'item'): val = val.item()
                    vals.append(f"{val * 1e9:.1f}")
                info_str = "系数预览 (Z1... nm): " + ", ".join(vals)
                self.log_message(info_str)
            except:
                pass
            
        self.spectrum_plot_widget.plot_spectrum(coeffs, start_index=1, title="输入 Zernike 频谱 (CWFS)")
        self.log_message("正在后台进行校正力解算...")

    def update_displacement_info(self, zernike_coeffs, disp_deltas):
        if zernike_coeffs is None or len(zernike_coeffs) < 3:
            return
            
        def fmt_nm(v):
            val = v.item() if hasattr(v, 'item') else v
            return f"{val*1e9:.2f} nm"

        try:
            self.lbl_z_piston.setText(fmt_nm(zernike_coeffs[0]))
            self.lbl_z1.setText(fmt_nm(zernike_coeffs[1]))
            self.lbl_z2.setText(fmt_nm(zernike_coeffs[2]))
        except Exception as e:
            self.log_message(f"Zernike 显示出错: {e}")
        
        if disp_deltas:
            self.lbl_d27.setText(f"{disp_deltas.get(27, 0):+.3f} μm")
            self.lbl_d28.setText(f"{disp_deltas.get(28, 0):+.3f} μm")
            self.lbl_d29.setText(f"{disp_deltas.get(29, 0):+.3f} μm")
            
            self.btn_exec_disp.setEnabled(True)
            self.current_disp_deltas = disp_deltas
            self.tab_widget.setCurrentIndex(1)
            
            d_msg = f"M27:{disp_deltas.get(27,0):.1f}, M28:{disp_deltas.get(28,0):.1f}, M29:{disp_deltas.get(29,0):.1f}"
            self.log_message(f"位移计算成功: {d_msg}")
        else:
            self.lbl_d27.setText("-- μm")
            self.lbl_d28.setText("-- μm")
            self.lbl_d29.setText("-- μm")
            self.btn_exec_disp.setEnabled(False)

    # ================= 【核心修改区】 =================
    def update_results(self, force_distribution, pv_value, rms_value, residuals, coordinates, zernike_values):
        """更新计算结果 (通过解析 zernike_values 在 UI 层计算初始 PV/RMS)"""
        
        # 1. 跨线程分发，注意必须恢复为 6 个参数
        if QThread.currentThread() != self.thread():
            self._safe_update_signal.emit(force_distribution, pv_value, rms_value, residuals, coordinates, zernike_values)
            return

        self.force_distribution = force_distribution
        self.pv_value = pv_value
        self.rms_value = rms_value
        self.residuals = residuals
        self.coordinates = coordinates
        
        # 2. 动态计算校正前的初始 PV 和 RMS
        # 取反操作对极差(PV)和标准差(RMS)完全不影响，直接使用传过来的 target wavefront (zernike_values) 计算即可
        if zernike_values is not None and len(zernike_values) > 0:
            z_arr = np.array(zernike_values)
            initial_pv = np.max(z_arr) - np.min(z_arr)
            initial_rms = np.std(z_arr)
        else:
            initial_pv = 0.0
            initial_rms = 0.0

        # 3. 标签上同步显示前后的对比
        self.pv_label.setText(f"PV: {initial_pv * 1e6:.1f} ➔ {pv_value * 1e6:.1f} nm")
        self.rms_label.setText(f"RMS: {initial_rms * 1e6:.1f} ➔ {rms_value * 1e6:.1f} nm")
        # =================================================

        self.update_result_table()
        self.force_plot_widget.plot_forces(force_distribution, "校正力分布")
        
        if len(coordinates) > 0:
            x_coords = [coord[0] for coord in coordinates]
            y_coords = [coord[1] for coord in coordinates]
            
            if self.is_cwfs_mode and len(self.current_zernike_coeffs) > 0:
                z_title = f"目标面形 (CWFS 重构, {len(self.current_zernike_coeffs)}项)"
            else:
                z_title = f"目标面形 (理论阶数: {self.zernike_combo.currentText()})"
                if not self.is_cwfs_mode:
                     self.spectrum_plot_widget.plot_spectrum([], title="Zernike 频谱 (空)")

            if len(zernike_values) > 0:
                self.zernike_plot_widget.plot_zernike(x_coords, y_coords, zernike_values, z_title)
            
            if len(residuals) > 0:
                self.residual_plot_widget.plot_residuals(x_coords, y_coords, residuals, "残差分布")
        
        self.apply_btn.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.calculate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.update_status("计算完成")
        
        # 4. 日志也输出对比
        self.log_message(f"计算完成 | PV: {initial_pv * 1e6:.1f} ➔ {pv_value * 1e6:.1f} nm | RMS: {initial_rms * 1e6:.1f} ➔ {rms_value * 1e6:.1f} nm")

    def update_result_table(self):
        for i, force in enumerate(self.force_distribution):
            if i >= 27: break
            
            if hasattr(force, 'item'): force = force.item()
            
            force_item = QTableWidgetItem(f"{force:.3f}")
            force_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            
            if abs(force) > 100:
                force_item.setForeground(QColor(255, 0, 0)) 
                force_item.setBackground(QBrush(QColor(255, 240, 240)))
            elif abs(force) > 50:
                force_item.setForeground(QColor(255, 165, 0)) 
                force_item.setBackground(QBrush(QColor(255, 250, 240)))
            else:
                force_item.setForeground(QColor(0, 128, 0)) 
                force_item.setBackground(QBrush(QColor(240, 255, 240)))
            self.result_table.setItem(i, 1, force_item)
            
            status_item = QTableWidgetItem("计算完成")
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(QColor(0, 128, 0))
            self.result_table.setItem(i, 2, status_item)
            
            current_force = 0.0
            current_item = self.result_table.item(i, 4)
            if current_item and current_item.text():
                try: 
                    current_force = float(current_item.text())
                except: 
                    pass
            
            target_val = current_force + force
            target_item = QTableWidgetItem(f"{target_val:.3f}")
            target_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.result_table.setItem(i, 3, target_item)
  
    def update_motor_status(self, motor_id, current_force, status):
        if motor_id < self.result_table.rowCount():
            current_item = QTableWidgetItem(f"{current_force:.3f}")
            current_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.result_table.setItem(motor_id, 5, current_item)
            
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)

            if status == "到位": 
                status_item.setForeground(QColor(0, 150, 0)) 
                status_item.setFont(QFont("Arial", 9, QFont.Bold))
            if status in ["执行中", "准备中"]:
                status_item.setForeground(QColor(255, 165, 0))
            elif status == "完成":
                status_item.setForeground(QColor(0, 128, 0))
            elif status in ["错误", "发送失败"]:
                status_item.setForeground(QColor(255, 0, 0))
            elif status == "正常":
                status_item.setForeground(QColor(0, 0, 255))
            self.result_table.setItem(motor_id, 2, status_item)
    
    def update_progress(self, value):
        if QThread.currentThread() != self.thread():
            self._safe_progress_signal.emit(value)
            return
        self.progress_bar.setValue(value)
    
    def update_status(self, status):
        self.status_label.setText(status)
    
    def apply_correction(self):
        if self.force_distribution is None or len(self.force_distribution) == 0:
            QMessageBox.warning(self, "警告", "请先计算校正力！")
            return
        self.apply_correction_requested.emit(self.force_distribution)
        self.update_status("校正力已应用到界面")
    
    def send_to_motors(self):
        if self.force_distribution is None or len(self.force_distribution) == 0:
            QMessageBox.warning(self, "警告", "请先计算校正力！")
            return
        reply = QMessageBox.question(self, "确认", "确定要发送校正力到27个力电机吗？\n\n注意：目标力将计算为 [基准力 + 校正力] 进行叠加。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            for i in range(27): self.update_motor_status(i, 0.0, "待执行")
            self.send_to_motors_requested.emit(self.force_distribution)
            self.stop_btn.setEnabled(True)
            self.send_btn.setEnabled(False)
            self.update_status("正在发送校正力到电机...")
    
    def stop_correction(self):
        reply = QMessageBox.question(self, "确认", "确定要停止校正过程吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.emit_stop_correction_signal()
            self.stop_btn.setEnabled(False)
            self.send_btn.setEnabled(True)
            self.update_status("校正已停止")
            
    def emit_stop_correction_signal(self):
        self.stop_correction_requested.emit()
    
    def clear_results(self):
        reply = QMessageBox.question(self, "确认", "确定要清空所有计算结果吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.force_distribution = []
            self.init_result_table()
            self.force_plot_widget.plot_widget.clear()
            self.residual_plot_widget.figure.clear()
            self.residual_plot_widget.canvas.draw()
            self.zernike_plot_widget.figure.clear()
            self.zernike_plot_widget.canvas.draw()
            self.spectrum_plot_widget.figure.clear() 
            self.spectrum_plot_widget.canvas.draw()
            self.apply_btn.setEnabled(False)
            self.send_btn.setEnabled(False)
            self.calculate_btn.setEnabled(True)
            self.update_status("就绪")
            self.log_message("已清空所有结果")
    
    def log_message(self, message):
        from datetime import datetime
        log_text = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
        if QThread.currentThread() != self.thread():
            QMetaObject.invokeMethod(self, "_add_log_internal", Qt.QueuedConnection, Q_ARG(str, log_text))
        else:
            self._add_log_internal(log_text)

    def _add_log_internal(self, log_text):
        self.log_text.append(log_text)
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def show_error(self, error_message):
        self.update_status("计算错误")
        self.progress_bar.setVisible(False)
        self.calculate_btn.setEnabled(True)
        self.log_message(f"错误: {error_message}")
        QMessageBox.critical(self, "计算错误", error_message)