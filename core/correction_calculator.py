"""
校正力计算模块 - 基于Zernike多项式的力分布计算
"""
import sys
import numpy as np
import pandas as pd
import os
from numpy.linalg import lstsq
import threading
import time
from PyQt5.QtCore import QObject, pyqtSignal

# --- 路径配置 (修复版) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
# [修复] ui 文件夹的上一级就是项目根目录 (弯月镜支撑控制)
project_root = os.path.dirname(current_dir) 
cwfs_lib_path = os.path.join(project_root, "cwfs-master", "python")


# 调试打印，方便确认路径是否正确
print(f"DEBUG: CWFS Lib Path: {cwfs_lib_path}")

if os.path.exists(cwfs_lib_path):
    if cwfs_lib_path not in sys.path:
        sys.path.append(cwfs_lib_path)
        print("DEBUG: 已添加 CWFS 路径到 sys.path")
else:
    print(f"WARNING: 未找到 CWFS 库路径: {cwfs_lib_path}")
    # 备用路径查找 (保留原有逻辑作为后备)
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
    # 定义伪对象防止IDE报错 (实际运行时会检查 cwfs_available)
    Instrument = None
    Algorithm = None
    Image = None
    readFile = None


class ZernikeCalculator:
    """Zernike多项式计算器"""
    
    @staticmethod
    def zerniker(x, y, n):
        """计算Zernike多项式"""
        x = np.asarray(x)
        y = np.asarray(y)
        r = np.sqrt(x**2 + y**2)
        # 避免除以零或极小值
        if np.max(r) == 0:
            radMax = 1.0
        else:
            radMax = np.max(r) * 1.01
            
        rad = r / radMax  # 归一化半径
        ang = np.arctan2(y, x)  # 角度
        
        # 根据n值返回对应的Zernike多项式 (Noll indices)
        if n == 0:   return np.ones_like(rad)
        elif n == 1: return rad * np.cos(ang)
        elif n == 2: return rad * np.sin(ang)
        elif n == 3: return 2 * rad**2 - 1
        elif n == 4: return rad**2 * np.cos(2 * ang)
        elif n == 5: return rad**2 * np.sin(2 * ang)
        elif n == 6: return (3 * rad**3 - 2 * rad) * np.cos(ang)
        elif n == 7: return (3 * rad**3 - 2 * rad) * np.sin(ang)
        elif n == 8: return 6 * rad**4 - 6 * rad**2 + 1
        elif n == 9: return rad**3 * np.cos(3 * ang)
        elif n == 10: return rad**3 * np.sin(3 * ang)
        elif n == 11: return (4 * rad**2 - 3) * rad**2 * np.cos(2 * ang)
        elif n == 12: return (4 * rad**2 - 3) * rad**2 * np.sin(2 * ang)
        elif n == 13: return (10 * rad**5 - 12 * rad**3 + 3 * rad) * np.cos(ang)
        elif n == 14: return (10 * rad**5 - 12 * rad**3 + 3 * rad) * np.sin(ang)
        elif n == 15: return 20 * rad**6 - 30 * rad**4 + 12 * rad**2 - 1
        elif n == 16: return rad**4 * np.cos(4 * ang)
        elif n == 17: return rad**4 * np.sin(4 * ang)
        elif n == 18: return (5 * rad**2 - 4) * rad**3 * np.cos(3 * ang)
        elif n == 19: return (5 * rad**2 - 4) * rad**3 * np.sin(3 * ang)
        elif n == 20: return (15 * rad**4 - 20 * rad**2 + 6) * rad**2 * np.cos(2 * ang)
        elif n == 21: return (15 * rad**4 - 20 * rad**2 + 6) * rad**2 * np.sin(2 * ang)
        elif n == 22: return (35 * rad**7 - 60 * rad**5 + 30 * rad**3 - 4 * rad) * np.cos(ang)
        elif n == 23: return (35 * rad**7 - 60 * rad**5 + 30 * rad**3 - 4 * rad) * np.sin(ang)
        elif n == 24: return 70 * rad**8 - 140 * rad**6 + 90 * rad**4 - 20 * rad**2 + 1
        elif n == 25: return rad**5 * np.cos(5 * ang)
        elif n == 26: return rad**5 * np.sin(5 * ang)
        elif n == 27: return (6 * rad**2 - 5) * rad**4 * np.cos(4 * ang)
        elif n == 28: return (6 * rad**2 - 5) * rad**4 * np.sin(4 * ang)
        elif n == 29: return (21 * rad**4 - 30 * rad**2 + 10) * rad**3 * np.cos(3 * ang)
        elif n == 30: return (21 * rad**4 - 30 * rad**2 + 10) * rad**3 * np.sin(3 * ang)
        elif n == 31: return (56 * rad**6 - 105 * rad**4 + 60 * rad**2 - 10) * rad**2 * np.cos(2 * ang)
        elif n == 32: return (56 * rad**6 - 105 * rad**4 + 60 * rad**2 - 10) * rad**2 * np.sin(2 * ang)
        elif n == 33: return (126 * rad**9 - 280 * rad**7 + 210 * rad**5 - 60 * rad**3 + 5 * rad) * np.cos(ang)
        elif n == 34: return (126 * rad**9 - 280 * rad**7 + 210 * rad**5 - 60 * rad**3 + 5 * rad) * np.sin(ang)
        elif n == 35: return 252 * rad**10 - 630 * rad**8 + 560 * rad**6 - 210 * rad**4 + 30 * rad**2 - 1
        elif n == 36: return 924 * rad**12 - 2772 * rad**10 + 3150 * rad**8 - 1680 * rad**6 + 420 * rad**4 - 42 * rad**2 + 1
        else:
            # 简单的防崩溃处理
            return np.zeros_like(rad)


class CorrectionForceCalculator(QObject):
    """校正力计算器"""
    
    # 信号定义
    calculation_started = pyqtSignal()
    # 参数: 力列表, PV值, RMS值, 残差, 坐标, Zernike值
    calculation_finished = pyqtSignal(list, float, float, list, list, list)  
    calculation_error = pyqtSignal(str)
    progress_updated = pyqtSignal(int)  # 进度百分比
    
    def __init__(self):
        super().__init__()
        
        # 路径处理
        data_dir = None
        # 尝试查找 data 目录
        potential_paths = [
            os.path.join(os.path.dirname(__file__), "data"),
            os.path.join(os.getcwd(), "data"),
            r"F:\DeskTop\弯月镜主动支撑仿真\VSProject\弯月镜支撑控制\data"
        ]
        
        for p in potential_paths:
            if os.path.exists(p):
                data_dir = p
                break
        
        if data_dir:
            self.data_dir = data_dir
        else:
            self.data_dir = os.path.join(os.path.dirname(__file__), "data")
  
        self.force_distribution = None
        self.pv_value = 0.0
        self.rms_value = 0.0
        self.x_coords = None
        self.y_coords = None
        self.dispz_matrix = None
        self.residuals = None
        
        # 默认参数
        self.zernike_order = 4
        self.zernike_scale = 0.01
        self.damping_factor = 0
        
        if not os.path.exists(self.data_dir):
            try:
                os.makedirs(self.data_dir)
                print(f"已创建数据目录: {self.data_dir}")
            except:
                pass
    
    def load_data_files(self):
        """加载数据文件"""
        try:
            data_files = {
                'xyz': None, 'force1': None, 'force2': None, 'force3': None
            }
            
            possible_paths = [
                self.data_dir,
                os.path.dirname(__file__),
                os.path.join(os.path.dirname(__file__), "..", "data"),
                os.path.join(os.path.dirname(__file__), "data"),
                os.getcwd(),
                os.path.join(os.getcwd(), "data"),
            ]
            
            file_patterns = {
                'xyz': ['ao-700-150-XYZ27pt24h.dat', 'XYZ27pt24h.dat'],
                'force1': ['OneN-Hex-Rev27pt-f1h24-10.dat', 'f1h24-10.dat'],
                'force2': ['OneN-Hex-Rev27pt-f1h24-20.dat', 'f1h24-20.dat'],
                'force3': ['OneN-Hex-Rev27pt-f1h24-27.dat', 'f1h24-27.dat']
            }
            
            for file_type, patterns in file_patterns.items():
                for base_path in possible_paths:
                    for pattern in patterns:
                        file_path = os.path.join(base_path, pattern)
                        if os.path.exists(file_path):
                            data_files[file_type] = file_path
                            break
                    if data_files[file_type]: break
            
            missing_files = [ftype for ftype, path in data_files.items() if path is None]
            if missing_files:
                print(f"警告: 找不到文件 {missing_files}，使用示例数据")
                return self.create_sample_data()
            
            # 读取数据
            df4 = pd.read_csv(data_files['xyz'], header=None, sep='\s+')
            x, z, y = np.array([df4[i].values for i in range(3)], dtype=float)
            
            df1 = pd.read_csv(data_files['force1'], header=None, sep='\s+')
            df2 = pd.read_csv(data_files['force2'], header=None, sep='\s+')
            df3 = pd.read_csv(data_files['force3'], header=None, sep='\s+')
            
            data = np.column_stack((df1.values, df2.values, df3.values))
            return x, y, data
            
        except Exception as e:
            print(f"加载数据文件失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise Exception(f"加载数据文件失败: {str(e)}")
    
    def create_sample_data(self):
        n_points = 27
        radius = 150
        angles = np.linspace(0, 2*np.pi, n_points, endpoint=False)
        x = radius * np.cos(angles)
        y = radius * np.sin(angles)
        data = np.random.randn(n_points, 27) * 10
        return x, y, data
    
    def plane(self, x, y, coeffs):
        return coeffs[0] + coeffs[1] * x + coeffs[2] * y
    
    def detilt(self, x, y, dispz):
        A = np.c_[np.ones_like(x), x, y]
        coeffs, _, _, _ = lstsq(A, dispz, rcond=None)
        residual_z = dispz - self.plane(x, y, coeffs)
        return residual_z
    
    def process_all_columns(self, x, y, data):
        processed_columns = []
        total_cols = data.shape[1]
        for col_idx in range(total_cols):
            current_col = data[:, col_idx]
            processed_col = self.detilt(x, y, current_col)
            processed_columns.append(processed_col)
            progress = 10 + int(30 * (col_idx + 1) / total_cols)
            self.progress_updated.emit(progress)
        return np.column_stack(processed_columns)
    
    def damped_ls(self, A, b, p=0):
        p = p * 1
        ATA = np.dot(A.T, A)
        ATA = ATA + p * np.eye(ATA.shape[0])
        ATA_inv = np.linalg.inv(ATA)
        ATA_inv_AT = np.dot(ATA_inv, A.T)
        x_sol = np.dot(ATA_inv_AT, b)
        return x_sol
    
    def calculate_correction_forces(self, zernike_order=4, scale=0.01, damping=0):
        """[原有方法] 计算校正力 (基于单一阶数)"""
        try:
            self.calculation_started.emit()
            self.progress_updated.emit(5)
            
            # 1. 加载数据
            x, y, data = self.load_data_files()
            self.x_coords = x
            self.y_coords = y
            self.progress_updated.emit(15)
            
            # 2. 去倾斜处理
            self.dispz_matrix = self.process_all_columns(x, y, data)
            self.progress_updated.emit(50)
            
            # 3. 生成Zernike多项式
            z_calculator = ZernikeCalculator()
            z_zer = z_calculator.zerniker(x, y, zernike_order)
            z_zer = scale * z_zer
            self.progress_updated.emit(70)
            
            # 4. 计算校正力
            if self.dispz_matrix.shape[0] != len(z_zer):
                self.dispz_matrix = self.dispz_matrix.T
            
            f_sol = self.damped_ls(self.dispz_matrix, -z_zer, damping)
            self.progress_updated.emit(85)
            
            # 5. 计算残差和统计
            z_sum = self.dispz_matrix @ f_sol
            residual = z_sum + z_zer
            self.residuals = residual
            
            if residual.ndim > 1:
                if residual.shape[1] > 1:
                    residual_for_plot = np.mean(residual, axis=1)
                else:
                    residual_for_plot = residual.flatten()
            else:
                residual_for_plot = residual
            
            if len(residual_for_plot) != len(x):
                if len(residual_for_plot) > len(x):
                    residual_for_plot = residual_for_plot[:len(x)]
                else:
                    residual_for_plot = np.pad(residual_for_plot, (0, len(x) - len(residual_for_plot)), 'constant')
            
            if len(residual_for_plot) > 0:
                self.pv_value = np.max(residual_for_plot) - np.min(residual_for_plot)
                self.rms_value = np.std(residual_for_plot)
            
            self.force_distribution = f_sol.tolist()
            self.progress_updated.emit(100)
            
            # 发射完成信号
            # [修复] 强制类型转换，避免 numpy 类型导致信号失败
            self.calculation_finished.emit(
                [float(f) for f in self.force_distribution], 
                float(self.pv_value), 
                float(self.rms_value),
                [float(r) for r in residual_for_plot],
                [(float(x[i]), float(y[i])) for i in range(len(x))],
                [float(z) for z in z_zer]
            )
            
            return self.force_distribution, self.pv_value, self.rms_value, residual_for_plot
            
        except Exception as e:
            print(f"计算校正力时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            self.calculation_error.emit(str(e))
            return None, 0, 0, None
    
    def start_calculation_thread(self, zernike_order=4, scale=0.01, damping=0):
        self.zernike_order = zernike_order
        self.zernike_scale = scale
        self.damping_factor = damping
        thread = threading.Thread(
            target=self.calculate_correction_forces,
            args=(zernike_order, scale, damping),
            daemon=True
        )
        thread.start()
        return thread
    
    def get_force_for_motor(self, motor_id):
        if self.force_distribution is not None and 0 <= motor_id < len(self.force_distribution):
            return self.force_distribution[motor_id]
        return 0.0
    
    def get_all_forces(self):
        return self.force_distribution if self.force_distribution is not None else []

    # =========================================================================
    # CWFS 相关计算逻辑
    # =========================================================================

    def calculate_from_coeffs(self, coeffs, obs=0.0, damping=0):
        """
        基于输入的 Zernike 系数数组计算校正力 (纯计算部分)
        """
        try:
            self.calculation_started.emit()
            self.progress_updated.emit(5)

  
            
            # 1. 加载数据
            x, y, data = self.load_data_files()
            self.x_coords = x
            self.y_coords = y
            self.progress_updated.emit(15)
            
            # 2. 去倾斜处理
            if self.dispz_matrix is None:
                self.dispz_matrix = self.process_all_columns(x, y, data)
            self.progress_updated.emit(40)
            
            # 3. 重建目标波前
            unit_conversion = 1e3 
            
            z_calculator = ZernikeCalculator()
            e_obs = obs
            if e_obs <= 0:
                e_obs = 0.214
                
            r_dist = np.sqrt(x**2 + y**2)
            max_r = np.max(r_dist)
            if max_r == 0: 
                max_r = 1.0
            
            # 归一化坐标
            x_norm = x / max_r
            y_norm = y / max_r

            target_wavefront = np.zeros_like(x_norm)
            
            try:
                # 尝试使用 CWFS 的环形域评估 (可能因 1D 散点阵列报错返回 None)
                tmp_wave = ZernikeAnnularEval(coeffs, x_norm, y_norm, e_obs)
                if tmp_wave is not None:
                    target_wavefront = tmp_wave
                else:
                    raise ValueError("None")
            except:
                # [关键修复] 降级：使用内置 Zernike 多项式生成器，完美兼容 1D 离散支撑点阵列
                for i, c in enumerate(coeffs):
                    if c != 0.0:
                        target_wavefront += c * z_calculator.zerniker(x, y, i)

            target_wavefront = target_wavefront * unit_conversion
            
            self.progress_updated.emit(70)
            
            # 4. 计算校正力
            matrix_to_solve = self.dispz_matrix
            if matrix_to_solve.shape[0] != len(target_wavefront):
                matrix_to_solve = matrix_to_solve.T
            
            f_sol = self.damped_ls(matrix_to_solve, -target_wavefront, damping)
            self.progress_updated.emit(85)
            
            # 5. 计算残差和统计
            fitting_wavefront = matrix_to_solve @ f_sol
            residual = fitting_wavefront + target_wavefront 
            self.residuals = residual
            
            if residual.ndim > 1:
                residual_for_plot = residual.flatten() if residual.shape[1] == 1 else np.mean(residual, axis=1)
            else:
                residual_for_plot = residual
            
            if len(residual_for_plot) != len(x):
                if len(residual_for_plot) > len(x):
                    residual_for_plot = residual_for_plot[:len(x)]
                else:
                    residual_for_plot = np.pad(residual_for_plot, (0, len(x) - len(residual_for_plot)), 'constant')
            
            if len(residual_for_plot) > 0:
                self.pv_value = np.max(residual_for_plot) - np.min(residual_for_plot)
                self.rms_value = np.std(residual_for_plot)
            
            self.force_distribution = f_sol.tolist()
            self.progress_updated.emit(100)
            
            # 1. Force List (list of float)
            forces_list = [float(f) for f in self.force_distribution]
            # 2. PV (float)
            pv_val = float(self.pv_value)
            # 3. RMS (float)
            rms_val = float(self.rms_value)
            # 4. Residuals (list of float)
            resid_list = [float(r) for r in residual_for_plot]
            # 5. Coords (list of tuples of float)
            coords_list = [(float(x[i]), float(y[i])) for i in range(len(x))]
            # 6. Zernike Wavefront (list of float)
            z_vals_list = [float(z) for z in target_wavefront]
            
            return (forces_list, pv_val, rms_val, resid_list, coords_list, z_vals_list)
            
        except Exception as e:
            # 如果计算本身出错，这里抛出，由线程函数捕获
            print(f"基于系数计算校正力时出错: {str(e)}")
            import traceback
            traceback.print_exc()
            raise e

   # [修改] 增加 obs 参数
    def _run_calculation_from_coeffs(self, coeffs, obs, damping):
        """线程包裹函数"""
        try:
            # 传递 obs 给计算函数
            result = self.calculate_from_coeffs(coeffs, obs, damping)
            
            if result is not None and len(result) == 6:
                self.calculation_finished.emit(*result)
            else:
                self.calculation_error.emit("计算返回结果格式不正确")
                
        except Exception as e:
            self.calculation_error.emit(f"CWFS计算流程错误: {str(e)}")


    def start_calculation_from_coeffs_thread(self, coeffs, obs=0.0, damping=0):
        """启动基于系数的计算线程"""
        thread = threading.Thread(
            target=self._run_calculation_from_coeffs,
            args=(coeffs, obs, damping), # 传递参数
            daemon=True
        )
        thread.start()
        return thread
    
    def calculate_displacement_correction(self, zernike_coeffs):
        """
        [修改] 计算位移促动器的校正量 (基于前3项 Zernike: Piston, Tip, Tilt)
        增强鲁棒性：自动补齐系数、处理NaN、确保浮点数格式
        """
        # 1. 安全检查
        if zernike_coeffs is None:
            return None
        
        # 2. 转换为标准列表并补齐长度 (防止 IndexError)
        coeffs_list = []
        if hasattr(zernike_coeffs, 'tolist'):
            coeffs_list = zernike_coeffs.tolist()
        else:
            coeffs_list = list(zernike_coeffs)

        # 至少需要前3项 (Z1, Z2, Z3)
        while len(coeffs_list) < 3:
            coeffs_list.append(0.0)

        # 3. 辅助函数：安全转float (处理 numpy 类型或 NaN)
        def safe_float(val):
            try:
                if hasattr(val, 'item'): val = val.item()
                f_val = float(val)
                if np.isnan(f_val): return 0.0
                return f_val
            except:
                return 0.0

        # 4. 获取系数 (单位: 米)
        c_piston_m = safe_float(coeffs_list[0])
        c_x_tilt_m = safe_float(coeffs_list[1])
        c_y_tilt_m = safe_float(coeffs_list[2])
        
        # 5. 单位转换: 米 -> 毫米 (x 1000)
        c_piston_mm = c_piston_m * 1000.0
        c_x_tilt_mm = c_x_tilt_m * 1000.0
        c_y_tilt_mm = c_y_tilt_m * 1000.0
        
        # 6. 刚体位移计算 (运动学模型)
        R_pupil = 350.0  # mm (出瞳半径)
        R_act = 220.2    # mm (促动器分布半径)
        sqrt3 = 1.73205
        
        target_P = -0.5 * c_piston_mm
        target_Ty = -0.5 * (c_x_tilt_mm / R_pupil) 
        target_Tx = -0.5 * (c_y_tilt_mm / R_pupil) 
        
        # 三角形布局解算
        d28_delta = target_P + R_act * target_Tx
        d27_delta = target_P - 0.5 * R_act * target_Tx - (sqrt3 / 2.0) * R_act * target_Ty
        d29_delta = target_P - 0.5 * R_act * target_Tx + (sqrt3 / 2.0) * R_act * target_Ty
        
        # 7. 返回微米 (um)
        to_microns = 1000.0
        return {
            27: d27_delta * to_microns,
            28: d28_delta * to_microns,
            29: d29_delta * to_microns
        }