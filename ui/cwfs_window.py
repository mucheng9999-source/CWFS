import sys
import os
import numpy as np
import scipy.ndimage as ndimage  # 用于图像旋转
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QFileDialog, QGroupBox, QTextEdit, QComboBox, 
                             QMessageBox, QDoubleSpinBox, QTabWidget, QApplication,
                             QCheckBox, QSpinBox, QScrollArea, QGridLayout, QDialog) 
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from mpl_toolkits.axes_grid1 import make_axes_locatable
import matplotlib.ticker as ticker
from core.camera_interface import ThorCamController
from astropy.io import fits
import datetime


# --- 路径配置 ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir) 
cwfs_lib_path = os.path.join(project_root, "cwfs-master", "python")

print(f"DEBUG: CWFS Lib Path: {cwfs_lib_path}")

if os.path.exists(cwfs_lib_path):
    if cwfs_lib_path not in sys.path:
        sys.path.append(cwfs_lib_path)
        print("DEBUG: 已添加 CWFS 路径到 sys.path")
else:
    print(f"WARNING: 未找到 CWFS 库路径: {cwfs_lib_path}")
    alt_path = r"F:/DeskTop/弯月镜主动支撑仿真/VSProject/弯月镜支撑控制/cwfs-master/python" 
    if os.path.exists(alt_path) and alt_path not in sys.path:
        sys.path.append(alt_path)
        print("DEBUG: 使用备用绝对路径")


# --- 导入 CWFS 模块 ---
cwfs_available = False
try:
    from lsst.cwfs.instrument import Instrument
    from lsst.cwfs.algorithm import Algorithm
    from lsst.cwfs.image import Image, readFile
    from lsst.cwfs.tools import ZernikeAnnularEval
    cwfs_available = True
    print("DEBUG: 成功导入 lsst.cwfs 模块")
except ImportError as e:
    print(f"Critical Error: 无法导入 lsst.cwfs. {e}")
    Instrument = None
    Algorithm = None
    Image = None
    readFile = None


# --- 后台工作线程 ---
class CWFSWorker(QThread):
    finished_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(str)

    def __init__(self, intra_path, extra_path, inst_name, algo_name, field_x, field_y, flips, bin_factor, z_terms):
        super().__init__()
        self.intra_path = intra_path
        self.extra_path = extra_path
        self.inst_name = inst_name
        self.algo_name = algo_name
        self.field_xy = [field_x, field_y]
        self.flips = flips 
        self.bin_factor = bin_factor   # [恢复] 像素合并系数
        self.z_terms = z_terms         # [恢复] 求解阶数

    def run(self):
        self.log_signal.emit(">>> 线程启动: 开始波前解算任务...")
        
        if not cwfs_available or readFile is None:
            self.error_signal.emit("致命错误: 未能加载 lsst.cwfs 算法库。\n请检查 'cwfs-master' 文件夹是否存在于项目目录中。")
            return

        try:
            self.log_signal.emit(f"正在读取图像...")
            image_data_intra = readFile(self.intra_path)
            image_data_extra = readFile(self.extra_path)
            
            # 处理镜像翻转
            if self.flips.get('intra_lr'): image_data_intra = np.fliplr(image_data_intra)
            if self.flips.get('intra_ud'): image_data_intra = np.flipud(image_data_intra)
            if self.flips.get('extra_lr'): image_data_extra = np.fliplr(image_data_extra)
            if self.flips.get('extra_ud'): image_data_extra = np.flipud(image_data_extra)

            # 处理旋转
            intra_rot = self.flips.get('intra_rot', 0.0)
            if intra_rot != 0.0:
                image_data_intra = ndimage.rotate(image_data_intra, intra_rot, reshape=False, order=1)
            extra_rot = self.flips.get('extra_rot', 0.0)
            if extra_rot != 0.0:
                image_data_extra = ndimage.rotate(image_data_extra, extra_rot, reshape=False, order=1)

            # ================= 【恢复：像素合并 (Binning)】 =================
            if self.bin_factor > 1:
                self.log_signal.emit(f"💡 正在执行像素合并：将 {self.bin_factor}x{self.bin_factor} 物理像素融合成 1 个大像素...")
                def perform_binning(img, b):
                    h, w = img.shape
                    new_h, new_w = h // b, w // b
                    img_c = img[:new_h*b, :new_w*b]
                    return img_c.reshape(new_h, b, new_w, b).mean(axis=(1, 3))

                image_data_intra = perform_binning(image_data_intra, self.bin_factor)
                image_data_extra = perform_binning(image_data_extra, self.bin_factor)
            # ================================================================

            img_size = image_data_intra.shape[0]
            self.log_signal.emit(f"图像分辨率: {img_size} x {img_size}")
            
            if image_data_intra.shape != image_data_extra.shape:
                raise ValueError("焦前和焦后图像尺寸不一致！")

            self.log_signal.emit(f"初始化 Instrument: {self.inst_name}")
            inst = Instrument(self.inst_name, img_size)

            # ================= 【恢复：同步放大物理像素尺寸】 =================
            if self.bin_factor > 1:
                inst.pixelSize = inst.pixelSize * self.bin_factor
                
                # 重新评估 Instrument 内与像素尺寸相关的绝对参数
                inst.sensorFactor = inst.sensorSamples / (inst.offset * inst.apertureDiameter / inst.focalLength / inst.pixelSize)
                inst.sensorWidth = (inst.apertureDiameter * inst.offset / inst.focalLength) * inst.sensorFactor
                inst.donutR = inst.pixelSize * (inst.sensorSamples / inst.sensorFactor) / 2
                
                # 重新构建算法底层的归一化掩膜坐标系
                y, x = np.mgrid[
                    -(inst.sensorSamples / 2 - 0.5):(inst.sensorSamples / 2 + 0.5),
                    -(inst.sensorSamples / 2 - 0.5):(inst.sensorSamples / 2 + 0.5)]
                inst.xSensor = x / (inst.sensorSamples / 2 / inst.sensorFactor)
                inst.ySensor = y / (inst.sensorSamples / 2 / inst.sensorFactor)
                
                r2Sensor = inst.xSensor**2 + inst.ySensor**2
                idx = (r2Sensor > 1) | (r2Sensor < inst.obscuration**2)
                inst.xoSensor = inst.xSensor.copy()
                inst.yoSensor = inst.ySensor.copy()
                inst.xoSensor[idx] = np.nan
                inst.yoSensor[idx] = np.nan
                
                self.log_signal.emit(f"🔧 已将底层物理像元尺寸补偿放大 {self.bin_factor} 倍，确保导数步长正确！")
            # =======================================================================
            
            self.log_signal.emit(f"初始化 Algorithm: {self.algo_name}")
            algo = Algorithm(self.algo_name, inst, 1)

            self.log_signal.emit(f"设定视场坐标: {self.field_xy}")
            I1 = Image(image_data_intra, self.field_xy, Image.INTRA)
            I2 = Image(image_data_extra, self.field_xy, Image.EXTRA)

            if abs(self.field_xy[0]) > 1e-5 or abs(self.field_xy[1]) > 1e-5:
                mode = 'offAxis'
                self.log_signal.emit("检测到非零视场，启用【离轴 (offAxis)】模式")
            else:
                mode = 'paraxial'
                self.log_signal.emit("视场为零，启用【近似轴上 (paraxial)】模式")

            self.log_signal.emit("正在运行核心解算，请稍候...")
            algo.runIt(inst, I1, I2, mode)
            self.log_signal.emit("核心解算完成！")

            # [恢复] 提取设定的阶数
            z_coeffs_full = algo.converge[:,-1]
            z_coeffs_final = z_coeffs_full[:self.z_terms] if len(z_coeffs_full) > self.z_terms else z_coeffs_full

            result = {
                "zernikes": z_coeffs_final,
                "converge": z_coeffs_final,
                "image_intra": I1.image,
                "image_extra": I2.image,
                "wavefront": algo.Wconverge,
                "obs": algo.zobsR,
                "x": inst.xoSensor,
                "y": inst.yoSensor,
            }
            
            log_str = f"共计算出 {len(z_coeffs_final)} 项泽尼克系数 (nm):\n"
            for i, val in enumerate(z_coeffs_final):
                log_str += f"  Z{i+1}: {val * 1e9:.3f}\n"
            self.log_signal.emit(log_str)
            
            self.finished_signal.emit(result)
            self.log_signal.emit("✅ 任务完成，绘图完成...")

        except Exception as e:
            import traceback
            err_msg = f"❌ 运行出错:\n{str(e)}\n{traceback.format_exc()}"
            self.log_signal.emit(err_msg)
            self.error_signal.emit(err_msg)


# --- 手动输入 Zernike 的弹窗类 ---
class ManualZernikeDialog(QDialog):
    def __init__(self, current_zernikes=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动输入 Zernike 系数")
        self.resize(650, 500)
        self.spinboxes = []
        
        layout = QVBoxLayout(self)
        
        info_label = QLabel("请输入各项 Zernike 系数 (单位：纳米 nm)。\n生成后可直接点击主界面的【一键校正】发送至主控计算校正力。")
        info_label.setStyleSheet("color: #333; font-weight: bold; margin-bottom: 5px;")
        layout.addWidget(info_label)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(10)
        
        # 预设 36 项输入框
        for i in range(36):
            row = i // 4
            col = (i % 4) * 2
            
            lbl = QLabel(f"Z{i+1}:")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setStyleSheet("font-weight: bold;")
            
            spin = QDoubleSpinBox()
            spin.setRange(-1000000.0, 1000000.0)
            spin.setDecimals(3)
            spin.setSuffix(" nm")
            spin.setMinimumWidth(100)
            
            # 如果已有数据，则回显
            if current_zernikes is not None and i < len(current_zernikes):
                spin.setValue(current_zernikes[i] * 1e9)
            else:
                spin.setValue(0.0)
                
            grid.addWidget(lbl, row, col)
            grid.addWidget(spin, row, col+1)
            self.spinboxes.append(spin)
            
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton("✅ 确认并生成")
        btn_ok.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; height: 35px;")
        btn_ok.clicked.connect(self.accept)
        
        btn_clear = QPushButton("🗑️ 全部清零")
        btn_clear.clicked.connect(self.clear_all)
        
        btn_cancel = QPushButton("❌ 取消")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_clear)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
    def clear_all(self):
        for spin in self.spinboxes:
            spin.setValue(0.0)
            
    def get_coefficients_in_meters(self):
        # 内部系统单位是米，所以需要乘以 1e-9 将 nm 转换回 m
        return np.array([spin.value() * 1e-9 for spin in self.spinboxes])
# ---------------------------------------


# --- 独立窗口 UI ---
class CWFSWindow(QWidget):
    log_forward_signal = pyqtSignal(str, str) 
    request_correction_signal = pyqtSignal(object) 

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CWFS 波前传感分析 (Pro)")
        self.resize(1200, 800)
        
        self.sn_intra = "22972" 
        self.sn_extra = "22556"

        self.ax_zernike = None
        self.zernike_line = None
        self.annot = None
        self.last_zernikes = None 
        self.zernike_checkboxes = []
        
        self.init_ui()
        
        if not cwfs_available:
            self.append_log("❌ 警告: 未能加载 lsst.cwfs 库，解算功能不可用！")
            self.btn_calc.setEnabled(False)

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # === 左侧：控制面板 ===
        control_panel = QGroupBox("参数与控制")
        control_layout = QVBoxLayout()

        exp_layout = QHBoxLayout()
        exp_layout.addWidget(QLabel("📷 相机曝光时间(ms):"))
        self.spin_exp = QDoubleSpinBox()
        self.spin_exp.setRange(0.01, 5000.0)
        self.spin_exp.setDecimals(2)
        self.spin_exp.setValue(10.0)  
        exp_layout.addWidget(self.spin_exp)
        control_layout.addLayout(exp_layout)

        intra_group = QGroupBox("1. 焦前图 (Intra)")
        intra_layout = QVBoxLayout()
        intra_layout.setContentsMargins(5, 5, 5, 5)

        btns_layout_intra = QHBoxLayout()
        btns_layout_intra.setSpacing(5)
        
        self.btn_intra = QPushButton("📂 选择文件")
        self.btn_intra.clicked.connect(lambda: self.select_file("intra"))
        
        self.btn_snap_intra = QPushButton("📸 拍照")
        self.btn_snap_intra.setStyleSheet("color: #009688; font-weight: bold;")
        self.btn_snap_intra.clicked.connect(lambda: self.capture_to_slot("intra"))
        
        btns_layout_intra.addWidget(self.btn_intra)
        btns_layout_intra.addWidget(self.btn_snap_intra)
        
        self.lbl_intra = QLabel("未选择文件")
        self.lbl_intra.setStyleSheet("color: #757575; font-size: 11px;")
        self.lbl_intra.setWordWrap(True)
        
        intra_layout.addLayout(btns_layout_intra)
        intra_layout.addWidget(self.lbl_intra)
        intra_group.setLayout(intra_layout)
        control_layout.addWidget(intra_group)

        extra_group = QGroupBox("2. 焦后图 (Extra)")
        extra_layout = QVBoxLayout()
        extra_layout.setContentsMargins(5, 5, 5, 5)

        btns_layout_extra = QHBoxLayout()
        btns_layout_extra.setSpacing(5)
        
        self.btn_extra = QPushButton("📂 选择文件")
        self.btn_extra.clicked.connect(lambda: self.select_file("extra"))
        
        self.btn_snap_extra = QPushButton("📸 拍照")
        self.btn_snap_extra.setStyleSheet("color: #009688; font-weight: bold;")
        self.btn_snap_extra.clicked.connect(lambda: self.capture_to_slot("extra"))
        
        btns_layout_extra.addWidget(self.btn_extra)
        btns_layout_extra.addWidget(self.btn_snap_extra)
        
        self.lbl_extra = QLabel("未选择文件")
        self.lbl_extra.setStyleSheet("color: #757575; font-size: 11px;")
        self.lbl_extra.setWordWrap(True)
        
        extra_layout.addLayout(btns_layout_extra)
        extra_layout.addWidget(self.lbl_extra)
        extra_group.setLayout(extra_layout)
        control_layout.addWidget(extra_group)
        
        control_layout.addSpacing(10)

        control_layout.addWidget(QLabel("仪器模型 (Instrument):"))
        self.combo_inst = QComboBox()
        self.combo_inst.addItems(["USTC_mirror", "lsst", "lsstfam", "AuxTel", "comcam10", "comcam20"]) 
        self.combo_inst.setEditable(True)
        control_layout.addWidget(self.combo_inst)

        control_layout.addWidget(QLabel("解算算法 (Algorithm):"))
        self.combo_algo = QComboBox()
        self.combo_algo.addItems(["fft", "exp"])
        control_layout.addWidget(self.combo_algo)

        # === [恢复] 极速计算配置 ===
        speed_group = QGroupBox("⚡ 极速计算配置")
        speed_layout = QVBoxLayout()
        
        h_bin = QHBoxLayout()
        h_bin.addWidget(QLabel("像素合并(Binning):"))
        self.combo_binning = QComboBox()
        self.combo_binning.addItems(["1x1 原始", "2x2 合并", "4x4 合并 ", "8x8 合并 "])
        self.combo_binning.setCurrentIndex(2) # 默认 4x4
        h_bin.addWidget(self.combo_binning)
        speed_layout.addLayout(h_bin)

        h_term = QHBoxLayout()
        h_term.addWidget(QLabel("求解阶数:"))
        self.combo_zterms = QComboBox()
        self.combo_zterms.addItems(["11", "15", "22", "36"])
        self.combo_zterms.setCurrentIndex(2) # 默认 22 项
        h_term.addWidget(self.combo_zterms)
        speed_layout.addLayout(h_term)

        speed_group.setLayout(speed_layout)
        control_layout.addWidget(speed_group)
        # =================================

        control_layout.addSpacing(10)

        field_group = QGroupBox("视场坐标 (Field Position)")
        field_layout = QHBoxLayout()
        
        field_layout.addWidget(QLabel("X (deg):"))
        self.spin_fx = QDoubleSpinBox()
        self.spin_fx.setRange(-10, 10)
        self.spin_fx.setSingleStep(0.01)
        self.spin_fx.setDecimals(4)
        self.spin_fx.setValue(0.0)
        field_layout.addWidget(self.spin_fx)

        field_layout.addWidget(QLabel("Y (deg):"))
        self.spin_fy = QDoubleSpinBox()
        self.spin_fy.setRange(-10, 10)
        self.spin_fy.setSingleStep(0.01)
        self.spin_fy.setDecimals(4)
        self.spin_fy.setValue(0.0)
        field_layout.addWidget(self.spin_fy)
        
        field_group.setLayout(field_layout)
        control_layout.addWidget(field_group)
        control_layout.addSpacing(20)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_calc = QPushButton("🚀 开始解算 (Run CWFS)")
        self.btn_calc.setFixedHeight(45)
        self.btn_calc.setStyleSheet("""
            QPushButton {
                background-color: #00796B; 
                color: white; 
                font-weight: bold; 
                font-size: 14px; 
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #004D40; }
            QPushButton:pressed { background-color: #00251A; }
        """)
        self.btn_calc.clicked.connect(self.run_cwfs)
        
        self.btn_clear = QPushButton("🗑️ 清空")
        self.btn_clear.setFixedHeight(45)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #D32F2F; 
                color: white; 
                font-weight: bold; 
                font-size: 14px; 
                border-radius: 5px;
            }
            QPushButton:hover { background-color: #B71C1C; }
            QPushButton:pressed { background-color: #7F0000; }
        """)
        self.btn_clear.clicked.connect(self.clear_all_data)

        # 保持7:3比例并排显示
        btn_layout.addWidget(self.btn_calc, 7)
        btn_layout.addWidget(self.btn_clear, 3)
        control_layout.addLayout(btn_layout)

        self.btn_apply = QPushButton("一键校正 (Apply)")
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0; 
                color: white; 
                font-weight: bold; 
                font-size: 14px; 
                height: 40px;
            }
            QPushButton:hover { background-color: #7B1FA2; }
            QPushButton:disabled { background-color: #BDBDBD; }
        """)
        self.btn_apply.clicked.connect(self.apply_correction)
        self.btn_apply.setEnabled(False) 
        control_layout.addWidget(self.btn_apply)

        control_layout.addWidget(QLabel("运行日志:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        control_layout.addWidget(self.log_text)

        control_panel.setLayout(control_layout)
        control_panel.setMaximumWidth(320)

        # === 右侧：可视化标签页 ===
        self.tabs = QTabWidget()
        
        # ---------------------------------------------------------
        # Tab 1: 泽尼克系数
        # ---------------------------------------------------------
        self.tab_zernike = QWidget()
        tab1_layout = QVBoxLayout()
        
        self.fig_zernike = Figure(figsize=(8, 4), dpi=100) 
        self.canvas_zernike = FigureCanvas(self.fig_zernike)
        self.canvas_zernike.mpl_connect("motion_notify_event", self.on_hover)
        tab1_layout.addWidget(self.canvas_zernike, stretch=7) 
        
        checkbox_container = QWidget()
        checkbox_vlayout = QVBoxLayout()
        checkbox_vlayout.setContentsMargins(0,0,0,0)
        
        btn_chk_layout = QHBoxLayout()
        lbl_chk_title = QLabel("<b>选择要补偿的 Zernike 项:</b> (取消勾选的项将被置为 0 发送)")
        
        # --- 手动输入 Zernike 按钮 ---
        self.btn_manual = QPushButton("✍️ 手动输入 Zernike 系数")
        self.btn_manual.setFixedHeight(30)
        self.btn_manual.setStyleSheet("""
            QPushButton {
                background-color: #F57C00; 
                color: white; 
                font-weight: bold; 
                padding: 0 10px;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #EF6C00; }
            QPushButton:pressed { background-color: #E65100; }
        """)
        self.btn_manual.clicked.connect(self.open_manual_input)
        # ----------------------------------------

        btn_sel_all = QPushButton("全部勾选")
        btn_sel_none = QPushButton("全部取消")
        btn_sel_all.clicked.connect(lambda: self.set_all_checkboxes(True))
        btn_sel_none.clicked.connect(lambda: self.set_all_checkboxes(False))
        
        btn_chk_layout.addWidget(lbl_chk_title)
        btn_chk_layout.addStretch()
        btn_chk_layout.addWidget(self.btn_manual) 
        btn_chk_layout.addWidget(btn_sel_all)
        btn_chk_layout.addWidget(btn_sel_none)
        checkbox_vlayout.addLayout(btn_chk_layout)
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMaximumHeight(120)
        
        self.chk_widget = QWidget()
        self.zernike_grid_layout = QGridLayout()
        self.chk_widget.setLayout(self.zernike_grid_layout)
        self.scroll_area.setWidget(self.chk_widget)
        
        checkbox_vlayout.addWidget(self.scroll_area)
        checkbox_container.setLayout(checkbox_vlayout)
        
        tab1_layout.addWidget(checkbox_container, stretch=3) 
        self.tab_zernike.setLayout(tab1_layout)
        
        # ---------------------------------------------------------
        # Tab 2: 图像显示 
        # ---------------------------------------------------------
        self.tab_images = QWidget()
        tab2_layout = QVBoxLayout()
        
        transform_layout = QHBoxLayout()
        
        # 翻转控件
        self.chk_intra_lr = QCheckBox("前·左右翻转")
        self.chk_intra_ud = QCheckBox("前·上下翻转")
        self.chk_extra_lr = QCheckBox("后·左右翻转")
        self.chk_extra_ud = QCheckBox("后·上下翻转")
        self.chk_intra_lr.stateChanged.connect(self.update_image_preview)
        self.chk_intra_ud.stateChanged.connect(self.update_image_preview)
        self.chk_extra_lr.stateChanged.connect(self.update_image_preview)
        self.chk_extra_ud.stateChanged.connect(self.update_image_preview)

        # 旋转控件
        self.spin_rot_intra = QDoubleSpinBox()
        self.spin_rot_intra.setRange(-360.0, 360.0)
        self.spin_rot_intra.setSingleStep(1.0)
        self.spin_rot_intra.setPrefix("前·旋转(°): ")
        self.spin_rot_intra.valueChanged.connect(self.update_image_preview)
        
        self.spin_rot_extra = QDoubleSpinBox()
        self.spin_rot_extra.setRange(-360.0, 360.0)
        self.spin_rot_extra.setSingleStep(1.0)
        self.spin_rot_extra.setPrefix("后·旋转(°): ")
        self.spin_rot_extra.valueChanged.connect(self.update_image_preview)

        transform_layout.addWidget(self.chk_intra_lr)
        transform_layout.addWidget(self.chk_intra_ud)
        transform_layout.addWidget(self.spin_rot_intra)
        transform_layout.addSpacing(15)
        transform_layout.addWidget(self.chk_extra_lr)
        transform_layout.addWidget(self.chk_extra_ud)
        transform_layout.addWidget(self.spin_rot_extra)
        transform_layout.addStretch() 
        tab2_layout.addLayout(transform_layout)

        self.fig_images = Figure(figsize=(10, 5), dpi=100)
        self.canvas_images = FigureCanvas(self.fig_images)
        tab2_layout.addWidget(self.canvas_images)
        self.tab_images.setLayout(tab2_layout)

        # ---------------------------------------------------------
        # Tab 3: 波前图
        # ---------------------------------------------------------
        self.tab_wavefront = QWidget()
        self.fig_wavefront = Figure(figsize=(8, 6), dpi=100)
        self.canvas_wavefront = FigureCanvas(self.fig_wavefront)
        tab3_layout = QVBoxLayout()
        tab3_layout.addWidget(self.canvas_wavefront)
        self.tab_wavefront.setLayout(tab3_layout)

        self.tabs.addTab(self.tab_zernike, "📊 泽尼克系数 (Zernike)")
        self.tabs.addTab(self.tab_images, "📷 焦前/焦后图像 (Images)")
        self.tabs.addTab(self.tab_wavefront, "🌊 波前图 (Wavefront)")

        main_layout.addWidget(control_panel, stretch=2)
        main_layout.addWidget(self.tabs, stretch=8)
        
        self.intra_file = ""
        self.extra_file = ""

    def enable_scroll_zoom(self, canvas, axes_list):
        """核心滚轮缩放方法：支持动态交互放大/缩小，且自动更新坐标轴"""
        def on_scroll(event):
            if event.inaxes not in axes_list:
                return
            ax = event.inaxes
            base_scale = 1.2
            
            if event.button == 'up': # 滚轮向上，放大 (Zoom In)
                scale_factor = 1 / base_scale
            elif event.button == 'down': # 滚轮向下，缩小 (Zoom Out)
                scale_factor = base_scale
            else:
                return

            xdata = event.xdata
            ydata = event.ydata
            if xdata is None or ydata is None:
                return

            # 获取当前显示的坐标轴范围
            cur_xlim = ax.get_xlim()
            cur_ylim = ax.get_ylim()

            # 计算新的坐标轴范围，保持鼠标当前位置相对静止
            x_left = xdata - (xdata - cur_xlim[0]) * scale_factor
            x_right = xdata + (cur_xlim[1] - xdata) * scale_factor
            y_bottom = ydata - (ydata - cur_ylim[0]) * scale_factor
            y_top = ydata + (cur_ylim[1] - ydata) * scale_factor

            # 设置新范围并重新绘制
            ax.set_xlim([x_left, x_right])
            ax.set_ylim([y_bottom, y_top])
            canvas.draw_idle()

        # 防止事件被重复绑定
        if hasattr(canvas, '_cwfs_scroll_cid'):
            canvas.mpl_disconnect(canvas._cwfs_scroll_cid)
        canvas._cwfs_scroll_cid = canvas.mpl_connect('scroll_event', on_scroll)

    def set_all_checkboxes(self, state):
        for cb in self.zernike_checkboxes:
            cb.setChecked(state)

    def select_file(self, ftype):
        fname, _ = QFileDialog.getOpenFileName(self, "选择图像文件", "", "FITS Files (*.fits);;All Files (*)")
        if fname:
            if ftype == "intra":
                self.intra_file = fname
                self.lbl_intra.setText(os.path.basename(fname))
                self.lbl_intra.setStyleSheet("color: #2E7D32; font-weight: bold;")
            else:
                self.extra_file = fname
                self.lbl_extra.setText(os.path.basename(fname))
                self.lbl_extra.setStyleSheet("color: #2E7D32; font-weight: bold;")
            self.update_image_preview()

    # --- 打开手动输入对话框的方法 ---
    def open_manual_input(self):
        dialog = ManualZernikeDialog(current_zernikes=self.last_zernikes, parent=self)
        if dialog.exec_() == QDialog.Accepted:
            coeffs_in_meters = dialog.get_coefficients_in_meters()
            
            # 构造虚拟的结果字典，直接传递给现有的绘图处理函数，完美兼容
            mock_result = {
                'converge': coeffs_in_meters,
                'zernikes': coeffs_in_meters,
                'obs': 0.0,
                'image_intra': np.zeros((256, 256)),  # 虚拟图像以防报错
                'image_extra': np.zeros((256, 256)),
                'wavefront': np.zeros((256, 256)),
                'x': None,
                'y': None
            }
            
            self.handle_result(mock_result)
            self.append_log(">>> 手动输入模式：已跳过图像解算，直接生成系数图表并激活校正。")
            
            # 自动跳转到Zernike标签页查看数据
            self.tabs.setCurrentIndex(0)

    def run_cwfs(self):
        if not self.intra_file or not self.extra_file:
            QMessageBox.warning(self, "警告", "请先选择焦前和焦后图像！")
            return

        self.btn_calc.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.log_text.clear()
        
        inst_name = self.combo_inst.currentText()
        algo_name = self.combo_algo.currentText()
        fx = self.spin_fx.value()
        fy = self.spin_fy.value()

        # [恢复] 获取合并系数和求解阶数
        bin_idx = self.combo_binning.currentIndex()
        bin_factor = 1 if bin_idx == 0 else (2 if bin_idx == 1 else (4 if bin_idx == 2 else 8))
        z_terms = int(self.combo_zterms.currentText())

        # 收集图像变换参数
        flips = {
            'intra_lr': self.chk_intra_lr.isChecked(),
            'intra_ud': self.chk_intra_ud.isChecked(),
            'extra_lr': self.chk_extra_lr.isChecked(),
            'extra_ud': self.chk_extra_ud.isChecked(),
            'intra_rot': self.spin_rot_intra.value(),
            'extra_rot': self.spin_rot_extra.value()
        }

        # [恢复] 传递参数给 Worker
        self.worker = CWFSWorker(self.intra_file, self.extra_file, inst_name, algo_name, fx, fy, flips, bin_factor, z_terms)
        self.worker.log_signal.connect(self.append_log)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.finished_signal.connect(self.handle_result)
        self.worker.start()

    def append_log(self, text):
        self.log_text.append(text)
        level = "ERROR" if "错误" in text or "Error" in text else "INFO"
        self.log_forward_signal.emit(level, f"[CWFS] {text}")

    def handle_error(self, err_msg):
        QMessageBox.critical(self, "错误", err_msg)
        self.btn_calc.setEnabled(True)

    def handle_result(self, result):
        self.btn_calc.setEnabled(True)
        z_coeffs = result['converge']
        img_intra = result['image_intra']
        img_extra = result['image_extra']
        wavefront = result['wavefront']

        self.last_zernikes = z_coeffs
        self.last_obs = result['obs']
        self.btn_apply.setEnabled(True)

        # 1. 动态生成并刷新复选框
        for i in reversed(range(self.zernike_grid_layout.count())): 
            widget_to_remove = self.zernike_grid_layout.itemAt(i).widget()
            if widget_to_remove is not None:
                widget_to_remove.setParent(None)
                
        self.zernike_checkboxes.clear()
        
        max_cols = 8
        for i, val in enumerate(z_coeffs):
            idx = i + 1
            cb = QCheckBox(f"Z{idx}")
            cb.setChecked(True)
            
            val_nm = val * 1e9
            cb.setToolTip(f"Z{idx} 当前解算值: {val_nm:.3f} nm")
            
            row = i // max_cols
            col = i % max_cols
            self.zernike_grid_layout.addWidget(cb, row, col)
            self.zernike_checkboxes.append(cb)

        # 2. 绘制泽尼克系数折线图
        self.fig_zernike.clear()
        ax1 = self.fig_zernike.add_subplot(111)
        self.ax_zernike = ax1 
        
        z_coeffs_nm = z_coeffs * 1e9
        indices = np.arange(1, 1 + len(z_coeffs_nm))
        
        lines = ax1.plot(indices, z_coeffs_nm, marker='o', color='r', markersize=8, linestyle='-', linewidth=1, picker=5)
        self.zernike_line = lines[0]
        
        for x, y in zip(indices, z_coeffs_nm):
            ax1.text(x, y, f"{y:.1f}", ha='center', va='bottom', fontsize=12, color='green')
            
        ax1.set_title("Zernike Coefficients (nm)")
        ax1.set_xlabel("Zernike Index")
        ax1.set_ylabel("Zernike coefficient (nm)")
        ax1.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax1.grid(True)
        
        self.annot = ax1.annotate("", xy=(0,0), xytext=(10,10), textcoords="offset points",
                                  bbox=dict(boxstyle="round", fc="w", alpha=0.9),
                                  arrowprops=dict(arrowstyle="->"))
        self.annot.set_visible(False)
        self.fig_zernike.subplots_adjust(left=0.1, right=0.95, top=0.9, bottom=0.15) 
        self.canvas_zernike.draw()

        # 3. 绘制图像及波前 (绑定交互缩放事件)
        self.fig_images.clear()
        
        ax2a = self.fig_images.add_subplot(121)
        im1 = ax2a.imshow(img_intra, origin='lower', cmap='gray')
        ax2a.set_title("Calculated Intra-focal")
        divider1 = make_axes_locatable(ax2a)
        cax1 = divider1.append_axes("right", size="5%", pad=0.05)
        self.fig_images.colorbar(im1, cax=cax1)

        ax2b = self.fig_images.add_subplot(122)
        im2 = ax2b.imshow(img_extra, origin='lower', cmap='gray')
        ax2b.set_title("Calculated Extra-focal")
        divider2 = make_axes_locatable(ax2b)
        cax2 = divider2.append_axes("right", size="5%", pad=0.05)
        self.fig_images.colorbar(im2, cax=cax2)

        self.fig_images.subplots_adjust(left=0.05, right=0.95, top=0.9, bottom=0.05, wspace=0.2)
        self.canvas_images.draw()
        # 启用滚轮缩放
        self.enable_scroll_zoom(self.canvas_images, [ax2a, ax2b])

        self.fig_wavefront.clear()
        ax3 = self.fig_wavefront.add_subplot(111)
        im3 = ax3.imshow(wavefront, origin='lower')
        ax3.set_title("Final Wavefront")
        self.fig_wavefront.colorbar(im3, ax=ax3)

        self.fig_wavefront.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.05)
        self.canvas_wavefront.draw()
        # 启用滚轮缩放
        self.enable_scroll_zoom(self.canvas_wavefront, [ax3])

        self.append_log(">>> 数据处理与图表更新完毕。")

    def apply_correction(self):
        if self.last_zernikes is not None:
            self.append_log(">>> 正在应用滤波并发送数据到主控系统...")
            
            filtered_zernikes = np.zeros_like(self.last_zernikes)
            active_terms = []
            
            for i, cb in enumerate(self.zernike_checkboxes):
                if i < len(self.last_zernikes):
                    if cb.isChecked():
                        filtered_zernikes[i] = self.last_zernikes[i]
                        active_terms.append(f"Z{i+1}")
                    else:
                        filtered_zernikes[i] = 0.0 

            data_packet = {
                "coeffs": filtered_zernikes,
                "obs": self.last_obs
            }
            self.request_correction_signal.emit(data_packet)
            
            active_str = ", ".join(active_terms) if active_terms else "无 (所有项均被发送为0)"
            self.append_log(f"✅ 发送完毕! 当前生效补偿的项: [{active_str}]")
            
            QMessageBox.information(self, "发送成功", 
                                    f"选定的 Zernike 系数已发送。\n生效的项: {active_str}\n未选中的项已强制置为 0。")

    def init_camera(self):
        if not hasattr(self, 'camera') or self.camera is None:
            self.append_log(">>> 正在加载相机驱动...")
            try:
                self.camera = ThorCamController()
            except Exception as e:
                self.append_log(f"❌ 驱动加载异常: {e}")
                self.camera = None
                return

        if not self.camera.is_connected:
            self.append_log(">>> 正在连接相机硬件...")
            if self.camera.connect():
                cam_id = "Unknown"
                try:
                    if self.camera.cam and self.camera.cam.list:
                        cam_id = self.camera.cam.list[0]
                except: pass
                self.append_log(f"✅ 相机连接成功 (ID: {cam_id})")
            else:
                self.append_log("❌ 相机连接失败: 请检查USB线")
        
    def capture_to_slot(self, slot_type):
        self.init_camera()

        if not hasattr(self, 'camera') or self.camera is None or not self.camera.is_connected:
            QMessageBox.warning(self, "拍摄失败", "相机未连接！\n请检查USB连接后重试。")
            return

        target_sn = self.sn_intra if slot_type == "intra" else self.sn_extra
        
        self.append_log(f"🔄 正在切换到 {slot_type} 相机 (SN: {target_sn})...")
        
        if not self.camera.select_camera(target_sn):
            available = self.camera.get_camera_list()
            msg = f"未找到编号为 {target_sn} 的相机！\n当前已连接: {available}"
            self.append_log(f"❌ {msg}")
            QMessageBox.warning(self, "相机匹配失败", msg)
            return

        exp_val = self.spin_exp.value()
        self.append_log(f"📸 正在拍摄 {slot_type} 图像 (曝光: {exp_val}ms)...")
        QApplication.processEvents() 

        try:
            img = self.camera.capture_image(exposure_ms=exp_val, roi=(300, 300))
        except Exception as e:
            self.append_log(f"❌ 拍摄指令异常: {e}")
            img = None

        if img is None:
            self.append_log("❌ 拍摄失败: 未获取到图像数据")
            QMessageBox.warning(self, "拍摄失败", "无法获取图像。\n如果多次失败，请尝试重新插拔相机USB线。")
            return

        save_dir = os.path.join(project_root, "data", "captured_images", slot_type)
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{slot_type}_{timestamp}.fits"
        filepath = os.path.join(save_dir, filename)

        try:
            fits.writeto(filepath, img, overwrite=True)
            self.append_log(f"✅ 拍摄并保存成功: {slot_type}/{filename}")

            if slot_type == "intra":
                self.intra_file = filepath
                self.lbl_intra.setText(filename)
                self.lbl_intra.setStyleSheet("color: #2E7D32; font-weight: bold;")
            else:
                self.extra_file = filepath
                self.lbl_extra.setText(filename)
                self.lbl_extra.setStyleSheet("color: #2E7D32; font-weight: bold;")
        
            self.update_image_preview()

        except Exception as e:
            err_msg = f"保存文件失败: {str(e)}"
            self.append_log(f"❌ {err_msg}")
            QMessageBox.critical(self, "保存失败", err_msg)

    def closeEvent(self, event):
        if hasattr(self, 'camera') and self.camera:
            if self.camera.is_connected:
                self.append_log(">>> 正在断开相机...")
                try:
                    self.camera.close()
                except: pass
        event.accept()

    def update_image_preview(self):
        if not self.intra_file or not os.path.exists(self.intra_file):
            return
        if not self.extra_file or not os.path.exists(self.extra_file):
            return
            
        try:
            data_intra = fits.getdata(self.intra_file)
            data_extra = fits.getdata(self.extra_file)
            
            # 处理镜像翻转
            if self.chk_intra_lr.isChecked(): data_intra = np.fliplr(data_intra)
            if self.chk_intra_ud.isChecked(): data_intra = np.flipud(data_intra)
            if self.chk_extra_lr.isChecked(): data_extra = np.fliplr(data_extra)
            if self.chk_extra_ud.isChecked(): data_extra = np.flipud(data_extra)
            
            # 处理任意角度旋转
            intra_rot = self.spin_rot_intra.value()
            if intra_rot != 0.0:
                data_intra = ndimage.rotate(data_intra, intra_rot, reshape=False, order=1)
                
            extra_rot = self.spin_rot_extra.value()
            if extra_rot != 0.0:
                data_extra = ndimage.rotate(data_extra, extra_rot, reshape=False, order=1)

            self.fig_images.clear()
            
            ax1 = self.fig_images.add_subplot(121)
            im1 = ax1.imshow(data_intra, origin='lower', cmap='gray')
            ax1.set_title("Intra-focal (Preview)")
            divider1 = make_axes_locatable(ax1)
            cax1 = divider1.append_axes("right", size="5%", pad=0.05)
            self.fig_images.colorbar(im1, cax=cax1)
            
            ax2 = self.fig_images.add_subplot(122)
            im2 = ax2.imshow(data_extra, origin='lower', cmap='gray')
            ax2.set_title("Extra-focal (Preview)")
            divider2 = make_axes_locatable(ax2)
            cax2 = divider2.append_axes("right", size="5%", pad=0.05)
            self.fig_images.colorbar(im2, cax=cax2)
            
            self.fig_images.subplots_adjust(left=0.05, right=0.95, top=0.9, bottom=0.05, wspace=0.2)
            self.canvas_images.draw()
            
            # 为预览图也启用滚轮交互缩放
            self.enable_scroll_zoom(self.canvas_images, [ax1, ax2])
            
            self.tabs.setCurrentIndex(1)
            self.append_log(">>> 图像预览已更新（支持鼠标滚轮缩放）")
            
        except Exception as e:
            self.append_log(f"⚠️ 图像预览失败: {e}")

    def clear_all_data(self):
        self.intra_file = None
        self.extra_file = None
        
        self.lbl_intra.setText("未选择文件")
        self.lbl_intra.setStyleSheet("color: #757575; font-size: 11px;")
        
        self.lbl_extra.setText("未选择文件")
        self.lbl_extra.setStyleSheet("color: #757575; font-size: 11px;")
        
        if hasattr(self, 'ax_zernike'):
            self.ax_zernike.clear()
            self.ax_zernike.text(0.5, 0.5, "Data Cleared", 
                                 ha='center', va='center', color='gray')
            self.canvas_zernike.draw()
            self.zernike_line = None 
            
        for i in reversed(range(self.zernike_grid_layout.count())): 
            widget = self.zernike_grid_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)
        self.zernike_checkboxes.clear()

        if hasattr(self, 'fig_images'):
            self.fig_images.clear()
            ax = self.fig_images.add_subplot(111)
            ax.text(0.5, 0.5, "No Images", ha='center', va='center', color='gray')
            ax.axis('off')
            self.canvas_images.draw()

        if hasattr(self, 'log_text'):
            self.append_log("\n" + "="*30)
            self.append_log(">>> 用户执行了清空操作")
            self.append_log("="*30 + "\n")

        self.tabs.setCurrentIndex(0)
        QMessageBox.information(self, "清空完成", "所有输入文件和解算结果已重置。")

    def update_annot(self, ind):
        idx = ind["ind"][0]
        x, y = self.zernike_line.get_data()
        self.annot.xy = (x[idx], y[idx])
        text = f"Z{int(x[idx])}\n{y[idx]:.2f} nm"
        self.annot.set_text(text)
    
    def on_hover(self, event):
        if self.ax_zernike is None or self.zernike_line is None:
            return
        vis = self.annot.get_visible()
        if event.inaxes == self.ax_zernike:
            cont, ind = self.zernike_line.contains(event)
            if cont:
                self.update_annot(ind)
                self.annot.set_visible(True)
                self.canvas_zernike.draw_idle()
            else:
                if vis:
                    self.annot.set_visible(False)
                    self.canvas_zernike.draw_idle()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = CWFSWindow()
    win.show()
    sys.exit(app.exec_())