"""
简洁版电机查看控件 - 通过P点状态指示数据有效性
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QGroupBox
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QBrush, QPen
import time

class MiniMotorWidget(QGroupBox):
    """简洁版电机查看控件"""
    
    # 信号定义
    data_updated = pyqtSignal(int, str, float)  # 电机ID, 数据类型, 值
    
    def __init__(self, motor_id):
        super().__init__()
        self.motor_id = motor_id
        self.last_update_time = 0
        self.is_data_valid = False  # 数据是否有效
        self.p_active = False  # P点是否活跃
        self.data_timeout = 1500  # 数据超时时间（毫秒）
        
        # 设置组框标题为电机ID
        self.setTitle(f"M{motor_id:02d}")
        self.setAlignment(Qt.AlignCenter)
        
        # 初始化UI
        self.init_ui()
        
        # 根据电机类型设置不同样式
        if motor_id < 27:
            self.set_force_motor_style()
        else:
            self.set_displacement_motor_style()
        
        # 设置固定尺寸
        self.setFixedSize(180, 160)
        
        # 设置超时检查定时器
        self.timeout_timer = QTimer(self)
        self.timeout_timer.setInterval(500)  # 每500毫秒检查一次
        self.timeout_timer.timeout.connect(self.check_data_timeout)
        self.timeout_timer.start()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 12, 6, 6)
        layout.setSpacing(3)
        
        # 标题行：电机ID和类型
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        # 电机类型标签
        motor_type = "力" if self.motor_id < 27 else "位移"
        type_label = QLabel(f"{motor_type}")
        type_font = QFont()
        type_font.setBold(True)
        type_font.setPointSize(9)
        type_label.setFont(type_font)
        
        # 根据类型设置颜色
        if self.motor_id < 27:
            type_label.setStyleSheet("color: #1971c2;")
        else:
            type_label.setStyleSheet("color: #2b8a3e;")
        
        title_layout.addWidget(type_label)
        title_layout.addStretch()
        
        # 连接状态指示灯
        self.connection_indicator = QLabel("●")
        self.connection_indicator.setFixedSize(12, 12)
        self.update_connection_status(False)  # 初始为灰色
        
        title_layout.addWidget(self.connection_indicator)
        
        layout.addLayout(title_layout)
        
        # 当前值显示区域
        value_frame = QFrame()
        value_frame.setFrameShape(QFrame.StyledPanel)
        value_frame.setFixedHeight(60)
        value_frame.setStyleSheet("""
            QFrame {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }
        """)
        
        value_layout = QVBoxLayout(value_frame)
        value_layout.setContentsMargins(4, 4, 4, 4)
        value_layout.setSpacing(1)
        
        # 值标签
        self.value_label = QLabel("0.000" if self.motor_id < 27 else "0")
        self.value_label.setAlignment(Qt.AlignCenter)
        
        # 使用等宽字体，确保数字对齐
        value_font = QFont("Courier New", 14, QFont.Bold)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet("color: #0066CC;")
        
        value_layout.addWidget(self.value_label)
        
        # 单位标签
        unit_text = "N" if self.motor_id < 27 else "μm"
        unit_label = QLabel(unit_text)
        unit_label.setAlignment(Qt.AlignCenter)
        unit_label.setStyleSheet("color: #666666; font-size: 9pt; font-weight: bold;")
        value_layout.addWidget(unit_label)
        
        layout.addWidget(value_frame)
        
        # 底部状态栏
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 2, 0, 0)
        
        # P点状态指示器
        self.p_status_widget = PStatusWidget()
        self.p_status_widget.setFixedSize(24, 16)
        self.p_status_widget.update_status(False)  # 初始为灰色
        
        status_layout.addWidget(self.p_status_widget)
        
        # 更新时间
        self.time_label = QLabel("--:--:--")
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setStyleSheet("color: #888888; font-size: 9pt; font-family: 'Arial';")
        status_layout.addWidget(self.time_label)
        
        layout.addLayout(status_layout)
    
    def set_force_motor_style(self):
        """设置力促动器样式"""
        self.setStyleSheet("""
            QGroupBox {
                background-color: #e8f4ff;
                border: 2px solid #4dabf7;
                border-radius: 6px;
                margin-top: 8px;
                font-weight: bold;
                color: #1971c2;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px 0 4px;
                background-color: #e8f4ff;
            }
        """)
    
    def set_displacement_motor_style(self):
        """设置位移促动器样式"""
        self.setStyleSheet("""
            QGroupBox {
                background-color: #ebfbee;
                border: 2px solid #69db7c;
                border-radius: 6px;
                margin-top: 8px;
                font-weight: bold;
                color: #2b8a3e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px 0 4px;
                background-color: #ebfbee;
            }
        """)
    
    def update_value(self, value, data_type="position", timestamp=None):
        """更新显示值"""
        # 记录更新时间
        current_time = time.time() * 1000
        self.last_update_time = current_time
        self.is_data_valid = True
        
        # 更新连接状态为绿色
        self.update_connection_status(True)
        
        # 根据数据类型更新P点状态
        if data_type == "position":
            self.p_active = True
            self.p_status_widget.update_status(True)
        
        # 格式化显示值
        if self.motor_id < 27:
            # 力促动器显示力值
            if data_type == "position":
                formatted_value = f"{value:>6.3f}"
            else:
                formatted_value = f"{value:>6.2f}"
        else:
            # 位移促动器
            if data_type == "position":
                formatted_value = f"{value:>6.0f}"
            else:
                formatted_value = f"{value:>6.2f}"
        
        self.value_label.setText(formatted_value)
        
        # 根据值的大小设置颜色
        abs_value = abs(value)
        if self.motor_id < 27:
            # 力促动器的颜色逻辑
            if abs_value < 0.01:
                value_color = "#868e96"  # 灰色，很小
            elif value > 0:
                value_color = "#2b8a3e"  # 绿色，正力
            else:
                value_color = "#c92a2a"  # 红色，负力
        else:
            # 位移促动器的颜色逻辑
            if abs_value < 0.1:
                value_color = "#868e96"  # 灰色，很小
            elif value > 0:
                value_color = "#1864ab"  # 蓝色，正位移
            else:
                value_color = "#862e9c"  # 紫色，负位移
        
        self.value_label.setStyleSheet(f"color: {value_color}; font-family: 'Courier New'; font-size: 14pt; font-weight: bold;")
        
        # 更新时间戳
        if timestamp:
            import datetime
            time_str = datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
            self.time_label.setText(time_str)
        else:
            # 如果没有提供时间戳，使用当前时间
            import datetime
            time_str = datetime.datetime.now().strftime('%H:%M:%S')
            self.time_label.setText(time_str)
        
        # 发出数据更新信号
        self.data_updated.emit(self.motor_id, data_type, value)
    
    def update_connection_status(self, is_connected):
        """更新连接状态"""
        if is_connected:
            # 连接正常 - 绿色
            self.connection_indicator.setStyleSheet("""
                QLabel {
                    background-color: #40c057;
                    border-radius: 6px;
                    color: transparent;
                }
            """)
        else:
            # 未连接 - 灰色
            self.connection_indicator.setStyleSheet("""
                QLabel {
                    background-color: #868e96;
                    border-radius: 6px;
                    color: transparent;
                }
            """)
    
    def check_data_timeout(self):
        """检查数据是否超时"""
        if self.last_update_time > 0:
            current_time = time.time() * 1000
            time_diff = current_time - self.last_update_time
            
            if time_diff > self.data_timeout:
                # 数据超时，设置为无效
                self.is_data_valid = False
                self.update_connection_status(False)
                self.p_active = False
                self.p_status_widget.update_status(False)
            else:
                # 数据有效
                self.update_connection_status(True)
                # 如果没有P数据，确保P点是灰色
                if not self.p_active:
                    self.p_status_widget.update_status(False)
        else:
            # 从未接收过数据
            self.update_connection_status(False)
            self.p_status_widget.update_status(False)
    
    def reset(self):
        """重置控件状态"""
        self.last_update_time = 0
        self.is_data_valid = False
        self.p_active = False
        
        self.value_label.setText("0.000" if self.motor_id < 27 else "0")
        self.value_label.setStyleSheet("color: #0066CC; font-family: 'Courier New'; font-size: 14pt; font-weight: bold;")
        self.time_label.setText("--:--:--")
        
        self.update_connection_status(False)
        self.p_status_widget.update_status(False)


class PStatusWidget(QWidget):
    """P点状态指示器"""
    
    def __init__(self):
        super().__init__()
        self.status = False  # False: 灰色, True: 绿色
        self.setToolTip("P点状态: 绿色表示正在接收数据，灰色表示无数据")
    
    def update_status(self, is_active):
        """更新状态"""
        self.status = is_active
        self.update()
    
    def paintEvent(self, event):
        """绘制P点状态指示器"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制背景
        if self.status:
            # 绿色 - 活跃状态
            painter.setBrush(QBrush(QColor("#40c057")))
            painter.setPen(QPen(QColor("#2b8a3e"), 1))
        else:
            # 灰色 - 非活跃状态
            painter.setBrush(QBrush(QColor("#868e96")))
            painter.setPen(QPen(QColor("#495057"), 1))
        
        # 绘制圆角矩形背景
        painter.drawRoundedRect(0, 0, self.width(), self.height(), 3, 3)
        
        # 绘制"P"字母
        painter.setPen(QPen(QColor("white"), 1))
        font = QFont("Arial", 8, QFont.Bold)
        painter.setFont(font)
        painter.drawText(0, 0, self.width(), self.height(), Qt.AlignCenter, "P")