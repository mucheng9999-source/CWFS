"""
ui/mirror_view_widget.py
镜面促动器分布可视化组件
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel, QSizePolicy
# [新增] 导入 QTimer 用于防抖
from PyQt5.QtCore import Qt, pyqtSlot, QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

# 配置字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

# ==================== 参数配置区域 ====================
MIRROR_DIAMETER = 700.0
HOLE_DIAMETER = 150.0

DIA_INNER = 253.6
DIA_MID = 440.4
DIA_OUTER = 632.2

COUNT_INNER = 6
COUNT_MID = 9
COUNT_OUTER = 12

ANGLE_START_INNER = 30
ANGLE_START_MID = -50
ANGLE_START_OUTER = 0

ID_MAP = [
    # 内圈 (6个)
    2, 3, 4, 5, 0, 1,
    # 中圈 (9个)
    7, 8, 9, 10, 11, 12, 13, 14, 6,
    # 外圈 (12个)
    18, 19, 20, 21, 22, 23, 24, 25, 26, 15, 16, 17,
]
# =================================================================

class MirrorViewWidget(QWidget):
    """镜面促动器分布显示组件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_front_view = True # 默认正面
        self.motor_status = {}    # 存储电机状态: {id: True(动)/False(静)}
        
        # [新增] 防抖定时器 (关键！避免停止时瞬间卡顿)
        self.plot_timer = QTimer()
        self.plot_timer.setSingleShot(True) # 单次触发
        self.plot_timer.setInterval(50)     # 延迟 50ms 统一刷新
        self.plot_timer.timeout.connect(self.plot)
        
        self.init_data()
        self.init_ui()
        self.plot()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # 1. 标题标签
        self.title_label = QLabel("正面视图 (从镜前看)")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333; margin-top: 5px;")
        layout.addWidget(self.title_label)
        
        # 2. 图表区域
        self.figure = Figure(figsize=(6, 6), dpi=100, facecolor='none') 
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setStyleSheet("background-color:transparent;")
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.canvas)
        
        # 3. 切换按钮
        self.switch_btn = QPushButton("切换视图 (当前: 正面)")
        self.switch_btn.setMinimumHeight(35)
        self.switch_btn.setStyleSheet("""
            QPushButton {
                font-weight: bold; font-size: 12px;
                background-color: #2196F3; color: white;
                border-radius: 4px; margin: 0px 40px 10px 40px;
            }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self.switch_btn.clicked.connect(self.toggle_view)
        layout.addWidget(self.switch_btn)

    def init_data(self):
        self.points = []
        self.points.extend(self.generate_ring_coordinates(DIA_INNER, COUNT_INNER, ANGLE_START_INNER))
        self.points.extend(self.generate_ring_coordinates(DIA_MID, COUNT_MID, ANGLE_START_MID))
        self.points.extend(self.generate_ring_coordinates(DIA_OUTER, COUNT_OUTER, ANGLE_START_OUTER))
        
        self.disp_map = {} 
        mid_radius = DIA_MID / 2.0
        insert_rules = [(7, 8, 27), (10, 11, 28), (13, 14, 29)]
        for id_a, id_b, target_id in insert_rules:
            pos_a = self.get_pos_by_id(id_a)
            pos_b = self.get_pos_by_id(id_b)
            if pos_a and pos_b:
                self.disp_map[target_id] = self.calculate_midpoint_on_circle(pos_a, pos_b, mid_radius)

    def generate_ring_coordinates(self, diameter, count, start_angle_deg):
        radius = diameter / 2.0
        coords = []
        for i in range(count):
            angle_deg = start_angle_deg + i * (360.0 / count)
            angle_rad = np.radians(angle_deg)
            coords.append((radius * np.cos(angle_rad), radius * np.sin(angle_rad)))
        return coords

    def calculate_midpoint_on_circle(self, p1, p2, radius):
        mid_x = (p1[0] + p2[0]) / 2.0
        mid_y = (p1[1] + p2[1]) / 2.0
        current_r = np.sqrt(mid_x**2 + mid_y**2)
        if current_r == 0: return (0, 0)
        scale = radius / current_r
        return (mid_x * scale, mid_y * scale)

    def get_pos_by_id(self, target_id):
        if target_id in ID_MAP:
            idx = ID_MAP.index(target_id)
            if idx < len(self.points):
                return self.points[idx]
        return None

    def toggle_view(self):
        self.is_front_view = not self.is_front_view
        view_name = "正面" if self.is_front_view else "反面"
        desc = "正面视图 (从镜前看)" if self.is_front_view else "背面视图 (从镜后看)"
        self.switch_btn.setText(f"切换视图 (当前: {view_name})")
        self.title_label.setText(desc) 
        self.plot()
    
    @pyqtSlot(int, bool)
    def update_motor_status(self, motor_id, is_moving):
        """[新增] 更新电机状态并刷新视图 (带防抖)"""
        if self.motor_status.get(motor_id) != is_moving:
            self.motor_status[motor_id] = is_moving
            # [关键] 启动定时器，而不是直接绘图
            if not self.plot_timer.isActive():
                self.plot_timer.start()

    def plot(self):
        """绘制逻辑"""
        self.figure.clear()
        
        # 填满画布
        ax = self.figure.add_axes([0.01, 0.01, 0.98, 0.98], facecolor='none')
        flip_factor = -1 if self.is_front_view else 1

        # 1. 绘制背景
        ax.add_patch(patches.Circle((0, 0), MIRROR_DIAMETER/2, fill=True, color='#ffffff', alpha=0.9))
        ax.add_patch(patches.Circle((0, 0), MIRROR_DIAMETER/2, fill=False, color='black', linestyle='-', linewidth=2.0))
        ax.add_patch(patches.Circle((0, 0), HOLE_DIAMETER/2, fill=True, color='white'))
        ax.add_patch(patches.Circle((0, 0), HOLE_DIAMETER/2, fill=False, color='black'))
        
        for dia in [DIA_INNER, DIA_MID, DIA_OUTER]:
            ax.add_patch(patches.Circle((0, 0), dia/2, fill=False, color='blue', linestyle=':', alpha=0.3))
            
        # 颜色定义
        COLOR_MOVING = '#4CAF50' # 绿 (运动)
        COLOR_STATIC = '#FF5252' # 红 (静止)

        # 2. 绘制力促动器
        x_force = [p[0] * flip_factor for p in self.points]
        y_force = [p[1] for p in self.points]
        
        # 计算颜色
        force_colors = []
        for i in range(len(self.points)):
            if i < len(ID_MAP):
                mid = ID_MAP[i]
                # 默认False(静)
                is_moving = self.motor_status.get(mid, False)
                force_colors.append(COLOR_MOVING if is_moving else COLOR_STATIC)
            else:
                force_colors.append(COLOR_STATIC)

        ax.scatter(x_force, y_force, c=force_colors, s=400, edgecolors='white', linewidth=1.0, zorder=10)
        
        for i, (x, y) in enumerate(self.points):
            if i < len(ID_MAP):
                motor_id = ID_MAP[i]
                draw_x = x * flip_factor
                ax.text(draw_x, y, str(motor_id), color='white', fontsize=11, 
                        ha='center', va='center', fontweight='bold', zorder=11)

        # 3. 绘制位移促动器
        if self.disp_map:
            x_disp = [p[0] * flip_factor for p in self.disp_map.values()]
            y_disp = [p[1] for p in self.disp_map.values()]
            
            disp_colors = []
            for uid in self.disp_map.keys():
                is_moving = self.motor_status.get(uid, False)
                disp_colors.append(COLOR_MOVING if is_moving else COLOR_STATIC)

            ax.scatter(x_disp, y_disp, c=disp_colors, s=400, edgecolors='white', linewidth=1.0, marker='s', zorder=10)
            
            for uid, (x, y) in self.disp_map.items():
                draw_x = x * flip_factor
                ax.text(draw_x, y, str(uid), color='white', fontsize=11, 
                        ha='center', va='center', fontweight='bold', zorder=11)

        ax.set_aspect('equal', anchor='N') 
        ax.axis('off') 
        
        limit = MIRROR_DIAMETER / 2 * 1.02
        ax.set_xlim(-limit, limit)
        ax.set_ylim(-limit, limit)
        
        self.canvas.draw()