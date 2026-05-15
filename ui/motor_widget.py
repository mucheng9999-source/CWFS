"""
单个电机控件 - 优化布局版本
"""
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QCheckBox,
                             QLabel, QLineEdit, QGroupBox, QGridLayout, QSizePolicy)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

class MotorWidget(QWidget):
    """单个电机控件"""
    
    # 信号定义
    control_requested = pyqtSignal(int, str, dict)  # 电机ID, 命令类型, 参数
    data_updated = pyqtSignal(int, str, float)      # 电机ID, 数据类型, 值
    
    def __init__(self, motor_id):
        super().__init__()
        self.motor_id = motor_id
        
        self.init_ui()

        # [新增] 初始化力传感器数值缓存 (用于计算差值)
        self.current_force1 = 0.0
        self.current_force2 = 0.0
        
        # 根据电机类型设置不同样式
        if motor_id < 27:
            self.set_force_motor_style()
        else:
            self.set_displacement_motor_style()
        
        # 设置尺寸策略
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.MinimumExpanding)
        self.setMinimumSize(200, 300)
        self.setMaximumSize(250, 350)
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # 标题和选择框
        title_layout = QHBoxLayout()
        self.checkbox = QCheckBox(f"M{self.motor_id:02d}")
        self.checkbox.setChecked(False)
        title_layout.addWidget(self.checkbox)
        title_layout.addStretch()
        layout.addLayout(title_layout)
        
        # 步进控制
        steps_group = QGroupBox("步进控制")
        steps_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        steps_layout = QVBoxLayout()
        self.steps_edit = QLineEdit()
        self.steps_edit.setText("0")
        self.steps_edit.setFixedHeight(25)
        steps_layout.addWidget(self.steps_edit)
        steps_group.setLayout(steps_layout)
        layout.addWidget(steps_group)
        
        # 当前位置显示
        pos_group = QGroupBox("当前位置")
        pos_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        pos_layout = QVBoxLayout()
        self.position_label = QLabel("0.000")
        self.position_label.setAlignment(Qt.AlignCenter)
        self.position_label.setFixedHeight(25)
        self.position_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 3px;
                font-weight: bold;
                font-size: 10pt;
            }
        """)
        pos_layout.addWidget(self.position_label)
        pos_group.setLayout(pos_layout)
        layout.addWidget(pos_group)
        
        # 目标位置/力
        group_name = "目标力:" if self.motor_id < 27 else "目标位置:"
        target_group = QGroupBox(group_name)
        target_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        target_layout = QVBoxLayout()
        self.target_edit = QLineEdit()
        self.target_edit.setText("0" if self.motor_id < 27 else "0.0")
        self.target_edit.setFixedHeight(25)
        target_layout.addWidget(self.target_edit)
        target_group.setLayout(target_layout)
        layout.addWidget(target_group)
        
        # 对于位移促动器，添加力传感器显示
        if self.motor_id >= 27:
            force_group = self.create_force_sensor_group()
            force_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            layout.addWidget(force_group)
        
        layout.addStretch()
    
    def create_force_sensor_group(self):
        """创建力传感器组（仅位移促动器）"""
        force_group = QGroupBox("力传感器")
        force_layout = QGridLayout()
        force_layout.setHorizontalSpacing(5)
        force_layout.setVerticalSpacing(5)
        
        # 力传感器1
        force1_label = QLabel(f"力{self.motor_id-26}1:")
        force1_label.setFixedWidth(40)
        self.force1_label = QLabel("0.000")
        self.force1_label.setAlignment(Qt.AlignCenter)
        self.force1_label.setFixedHeight(20)
        self.force1_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 2px;
            }
        """)
        
        # 力传感器2
        force2_label = QLabel(f"力{self.motor_id-26}2:")
        force2_label.setFixedWidth(40)
        self.force2_label = QLabel("0.000")
        self.force2_label.setAlignment(Qt.AlignCenter)
        self.force2_label.setFixedHeight(20)
        self.force2_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 2px;
            }
        """)

        # [新增] 差值显示
        diff_title_label = QLabel("差值:")
        diff_title_label.setFixedWidth(40)
        self.diff_label = QLabel("0.000")
        self.diff_label.setAlignment(Qt.AlignCenter)
        self.diff_label.setFixedHeight(20)
        # 使用不同颜色(如蓝色)区分差值
        self.diff_label.setStyleSheet("""
            QLabel {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 3px;
                padding: 2px;
                color: blue;
                font-weight: bold;
            }
        """)


        
        force_layout.addWidget(force1_label, 0, 0)
        force_layout.addWidget(self.force1_label, 0, 1)
        force_layout.addWidget(force2_label, 1, 0)
        force_layout.addWidget(self.force2_label, 1, 1)
        
        force_layout.addWidget(diff_title_label, 2, 0)
        force_layout.addWidget(self.diff_label, 2, 1)


        force_group.setLayout(force_layout)
        return force_group
    
    def set_force_motor_style(self):
        """设置力促动器样式"""
        self.setStyleSheet("""
            QGroupBox {
                border: 2px solid #2196F3;
                border-radius: 5px;
                margin-top: 5px;
                font-weight: bold;
                font-size: 9pt;
                background-color: #f0f8ff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
                font-size: 9pt;
            }
        """)
    
    def set_displacement_motor_style(self):
        """设置位移促动器样式"""
        self.setStyleSheet("""
            QGroupBox {
                border: 2px solid #4CAF50;
                border-radius: 5px;
                margin-top: 5px;
                font-weight: bold;
                font-size: 9pt;
                background-color: #f0fff0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
                font-size: 9pt;
            }
        """)
    
    def is_checked(self):
        """是否被选中"""
        return self.checkbox.isChecked()
    
    def set_checked(self, checked):
        """设置选中状态"""
        self.checkbox.setChecked(checked)
    
    def get_steps_text(self):
        """获取步数文本"""
        return self.steps_edit.text()
    
    def get_target_pos_text(self):
        """获取目标位置/力文本"""
        return self.target_edit.text()
    
    def update_position_display(self, value):
        """更新当前位置显示"""
        if self.motor_id < 27:
            self.position_label.setText(f"{value:.3f}")
        else:
            self.position_label.setText(f"{value:.3f}")
    
    def update_force1_display(self, value):
        """更新力传感器1显示"""
        self.force1_label.setText(f"{value:.3f}")
        self.current_force1 = value
        self.update_diff_display()
    
    def update_force2_display(self, value):
        """更新力传感器2显示"""
        self.force2_label.setText(f"{value:.3f}")
        self.current_force2 = value
        self.update_diff_display()
    
    def update_diff_display(self):
        """[新增] 计算并更新差值显示"""
        if hasattr(self, 'diff_label'):
            diff = self.current_force1 - self.current_force2
            self.diff_label.setText(f"{diff:.3f}")


    def reset_position_display(self):
        """重置位置显示"""
        self.position_label.setText("..")
    
    def reset_steps_color(self):
        """重置步数文本颜色"""
        self.steps_edit.setStyleSheet("")
    
    def reset_target_pos_color(self):
        """重置目标位置文本颜色"""
        self.target_edit.setStyleSheet("")
    
    def set_querying_display(self):
        """设置正在查询显示"""
        self.position_label.setText("......")
    
    def set_checkbox_color(self, color):
        """设置选择框颜色"""
        self.checkbox.setStyleSheet(f"QCheckBox {{ background-color: {color.name()}; }}")
    
    def reset_checkbox_color(self):
        """重置选择框颜色"""
        self.checkbox.setStyleSheet("")
    
    def set_target_pos_color(self, color):
        """设置目标位置文本颜色"""
        self.target_edit.setStyleSheet(f"QLineEdit {{ color: {color.name()}; }}")
    
    def set_steps_color(self, color):
        """设置步数文本颜色"""
        self.steps_edit.setStyleSheet(f"QLineEdit {{ color: {color.name()}; }}")