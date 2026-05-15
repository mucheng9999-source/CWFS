
import time
import ctypes as C
import numpy as np
import os
from astropy.io import fits

# 导入同目录下的驱动文件
from . import thorlabs_CS165MU1
from .thorlabs_CS165MU1 import Camera, dll

# =================================================================
#      🛡️ 移植过来的 V3 驱动热修复区 (核心稳定性保障)
# =================================================================

# --- 补丁1: 强制解锁 (Force Disarm) ---
def force_disarm(self, ch):
    try: dll.disarm_camera(self.handles[ch])
    except: pass
    self._armed[ch] = False

# --- 补丁2: 安全设置曝光 ---
def safe_set_exposure_time_us(self, ch, exposure_us):
    try: dll.set_exposure_time_us(self.handles[ch], exposure_us)
    except:
        force_disarm(self, ch) # 失败则暴力解锁
        try: dll.set_exposure_time_us(self.handles[ch], exposure_us)
        except: pass
    # 忽略读取回显的错误，防止 invalid stoll
    try: self._get_exposure_time_us(ch)
    except: pass

# --- 补丁3: 修复拍摄逻辑 (修复 NoneType 报错) ---
def fixed_record_to_memory(self, ch, allocated_memory=None, software_trigger=True):
    # 1. 确保已 Arm
    if not self._armed[ch]:
        try:
            dll.arm_camera(self.handles[ch], self.num_images[ch])
            self._armed[ch] = True
        except: pass 

    h_px, w_px = self.height_px[ch], self.width_px[ch]
    if allocated_memory is None:
        allocated_memory = np.zeros((self.num_images[ch], h_px, w_px), 'uint16')
    
    image_buffer_ptr = C.POINTER(C.c_ushort)()
    frame_count = C.c_int(0)
    metadata_ptr = C.POINTER(C.c_char)()
    metadata_size = C.c_int(0)
    
    # 3秒超时
    timeout_us = 3000000 
    
    # [关键修复] 初始化帧计数基准，防止 NoneType 比较错误
    start_frame_count = self._frame_count[ch]
    if start_frame_count is None:
        start_frame_count = 0

    if software_trigger:
        try: dll.send_software_trigger(self.handles[ch])
        except: pass
        
    for i in range(self.num_images[ch]):
        t0 = time.perf_counter()
        while True:
            dll.get_frame(self.handles[ch], C.byref(image_buffer_ptr), C.byref(frame_count), C.byref(metadata_ptr), C.byref(metadata_size))
            
            # 超时退出
            if (time.perf_counter() - t0) * 1e6 > timeout_us: break
            
            # [关键修复] 正确的帧数比较逻辑
            # frame_count.value 是相机从开机到现在总共拍了多少张
            # start_frame_count 是这次拍摄前已经拍了多少张
            if frame_count.value > start_frame_count: break 

        if bool(image_buffer_ptr):
            try:
                src = np.ctypeslib.as_array(image_buffer_ptr, shape=(h_px, w_px))
                allocated_memory[i, :, :] = src
            except: pass
            
        # 更新基准，准备下一张（如果是多帧拍摄）
        start_frame_count = frame_count.value

    # 更新全局计数
    self._frame_count[ch] = frame_count.value
    return allocated_memory

# --- 补丁4: 修复参数校验错误 (Legalize Image Size) ---
def fixed_legalize_image_size(height_px, width_px, **kwargs):
    # 强制返回默认全分辨率 (1440x1080)
    return (1080, 1440, {'left':0, 'right':1439, 'up':0, 'down':1079})

# === 💉 模块加载时自动注入所有补丁 ===
print(">>> 正在注入相机驱动 V4 补丁 (Fix NoneType/Stoll)...")
Camera._disarm = force_disarm
Camera._set_exposure_time_us = safe_set_exposure_time_us
Camera.record_to_memory = fixed_record_to_memory
thorlabs_CS165MU1.legalize_image_size = fixed_legalize_image_size
# =================================================================

class ThorCamController:
    """
    封装好的相机控制类，供 UI 直接调用
    """
    def __init__(self):
        self.cam = None
        self.ch = 0
        self.is_connected = False
        # 初始化时不立即连接，避免卡顿，由第一次拍照触发或手动连接
        
    def connect(self):
        """连接相机"""
        try:
            # 防止重复创建对象
            if self.cam is None:
                self.cam = Camera(verbose=False)
            
            if not self.cam.handles:
                print("未找到相机")
                return False
                
            self.cam.poll_timeout_ms[self.ch] = 5000
            self.is_connected = True
            print(f"相机初始化成功: {self.cam.list[0]}")
            return True
        except Exception as e:
            print(f"相机初始化失败: {e}")
            self.cam = None
            self.is_connected = False
            return False

    def select_camera(self, serial_keyword):
        """
        根据序列号片段选择相机 (例如 "22972")
        返回: 成功(True)/失败(False)
        """
        if not self.is_connected or not self.cam:
            return False
        
        # 遍历已连接的相机列表
        for idx, sn in enumerate(self.cam.list):
            if str(serial_keyword) in sn:
                self.ch = idx  # 切换当前通道
                print(f"已切换到相机: {sn} (通道 {idx})")
                return True
        
        print(f"未找到序列号包含 '{serial_keyword}' 的相机")
        return False

    def get_camera_list(self):
        if self.is_connected and self.cam:
            return self.cam.list
        return []


    def capture_image(self, exposure_ms=20, roi=None):
        """
        拍摄单张图片
        """
        # 自动重连机制
        if not self.is_connected or self.cam is None:
            if not self.connect(): return None
        
        try:
            # 1. 强制解锁 (清除可能的 Error 1004 / invalid stoll 状态)
            self.cam._disarm(self.ch)
            
            # 2. 设置参数
            sensor_w, sensor_h = 1440, 1080
            
            # 使用 apply_settings 设置曝光和尺寸
            # 注意：如果之前有 invalid stoll 报错，这里通常是第一次 apply 失败，重试一次即可
            try:
                self.cam.apply_settings(self.ch, num_images=1, 
                                        exposure_us=int(exposure_ms*1000), 
                                        width_px=sensor_w, height_px=sensor_h, 
                                        trigger='software')
            except Exception as e:
                print(f"参数设置初次失败 ({e})，尝试重置后重试...")
                self.cam._disarm(self.ch)
                time.sleep(0.1)
                self.cam.apply_settings(self.ch, num_images=1, 
                                        exposure_us=int(exposure_ms*1000), 
                                        width_px=sensor_w, height_px=sensor_h, 
                                        trigger='software')
            
            # 3. 拍摄
            buf = np.zeros((1, sensor_h, sensor_w), dtype='uint16')
            self.cam.record_to_memory(self.ch, allocated_memory=buf)
            img = buf[0]
            
            # 4. 软件裁剪
            if roi:
                target_w, target_h = roi
                cy, cx = sensor_h // 2, sensor_w // 2
                y1 = max(0, cy - target_h // 2)
                y2 = min(sensor_h, cy + target_h // 2)
                x1 = max(0, cx - target_w // 2)
                x2 = min(sensor_w, cx + target_w // 2)
                # img = img[y1:y2, x1:x2]
                
            return img
            
        except Exception as e:
            print(f"拍摄出错: {e}")
            # 标记为断开，迫使下次重新初始化 SDK，这通常能解决顽固的驱动错误
            self.is_connected = False 
            self.cam = None 
            return None

    def close(self):
        if self.cam:
            try: 
                self.cam.close()
            except: pass
        self.is_connected = False
        self.cam = None