"""
网络管理器 - 修复日志重复记录问题
"""
import socket
import threading
import time
from PyQt5.QtCore import QObject, pyqtSignal

class NetworkManager(QObject):
    """网络管理器"""
    
    # 信号定义
    connection_status_changed = pyqtSignal(bool)
    data_received = pyqtSignal(bytes)
    error_occurred = pyqtSignal(str)
    log_message = pyqtSignal(str, str)  # 日志级别, 消息
    
    def __init__(self):
        super().__init__()
        self.server_socket = None
        self.client_socket = None
        self.client_address = None
        self.is_connected = False
        self.receive_thread = None
        self.receive_thread_running = False
        self.buffer_size = 1024
        self.accept_thread = None
        self.accept_thread_running = False
        self.last_wait_log_time = 0  # 记录上次等待日志的时间
        self.wait_log_interval = 30   # 等待日志间隔（秒）
    
    def create_server(self, ip, port, max_connections=5):
        """创建TCP服务器"""
        try:
            self.log_message.emit("网络", f"正在创建服务器 {ip}:{port}")
            
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.settimeout(2.0)  # 设置超时
            self.server_socket.bind((ip, port))
            self.server_socket.listen(max_connections)
            
            self.log_message.emit("网络", f"服务器创建成功，监听端口 {port}")
            
            # 在新线程中接受连接
            self.accept_thread_running = True
            self.accept_thread = threading.Thread(
                target=self.accept_connection_loop,
                daemon=True
            )
            self.accept_thread.start()
            
            return True
            
        except Exception as e:
            error_msg = f"创建服务器失败: {str(e)}"
            self.log_message.emit("错误", error_msg)
            self.error_occurred.emit(error_msg)
            return False
    
    def accept_connection_loop(self):
        """循环接受客户端连接"""
        self.last_wait_log_time = 0
        
        while self.accept_thread_running:
            try:
                # 只在没有客户端连接且超过间隔时间时才记录等待日志
                current_time = time.time()
                if (not self.is_connected and 
                    current_time - self.last_wait_log_time > self.wait_log_interval):
                    self.log_message.emit("网络", "等待客户端连接...")
                    self.last_wait_log_time = current_time
                
                self.client_socket, self.client_address = self.server_socket.accept()
                self.client_socket.settimeout(0.1)  # 设置接收超时
                
                self.is_connected = True
                self.connection_status_changed.emit(True)
                
                msg = f"客户端连接: {self.client_address}"
                self.log_message.emit("网络", msg)
                
                # 启动接收线程
                self.start_receive_thread()
                
                # 有客户端连接后，暂停等待循环
                self.wait_for_disconnection()
                
            except socket.timeout:
                continue  # 超时是正常的，继续等待
            except Exception as e:
                if hasattr(e, 'errno') and e.errno == 10038:
                    # 套接字已关闭
                    break
                if self.accept_thread_running:
                    error_msg = f"接受连接失败: {str(e)}"
                    self.log_message.emit("错误", error_msg)
                    time.sleep(1)  # 避免频繁尝试
    
    def wait_for_disconnection(self):
        """等待客户端断开连接"""
        # 等待接收线程结束（即客户端断开）
        while self.receive_thread_running and self.is_connected:
            time.sleep(0.5)
        
        # 客户端断开后，重置状态
        self.is_connected = False
        self.connection_status_changed.emit(False)
        self.log_message.emit("网络", "客户端已断开，重新等待连接...")
        self.last_wait_log_time = 0  # 重置等待日志时间
    
    def start_receive_thread(self):
        """启动接收线程"""
        if self.receive_thread_running:
            return
        
        self.receive_thread_running = True
        self.receive_thread = threading.Thread(
            target=self.receive_data_loop,
            daemon=True
        )
        self.receive_thread.start()
    
    def receive_data_loop(self):
        """接收数据循环"""
        buffer = bytearray(self.buffer_size)
        
        while self.receive_thread_running and self.is_connected:
            try:
                if not self.client_socket:
                    time.sleep(0.1)
                    continue
                
                # 接收数据
                recv_bytes = self.client_socket.recv_into(buffer)
                
                if recv_bytes == 0:
                    # 连接已关闭
                    self.log_message.emit("网络", "客户端断开连接")
                    self.is_connected = False
                    self.connection_status_changed.emit(False)
                    break
                
                if recv_bytes > 0:
                    data = bytes(buffer[:recv_bytes])
                    
                    # 记录接收到的数据（调试时可以开启）
                    # self.log_message.emit("调试", 
                    #     f"收到 {recv_bytes} 字节: {data.hex()[:50]}...")
                    
                    # 发射接收到的数据信号
                    self.data_received.emit(data)
                
            except socket.timeout:
                continue  # 超时是正常的
            except Exception as e:
                if self.receive_thread_running:
                    error_msg = f"接收数据错误: {str(e)}"
                    self.log_message.emit("错误", error_msg)
                    self.is_connected = False
                    self.connection_status_changed.emit(False)
                break
    
    def send_data(self, data):
        """发送数据"""
        try:
            if not self.is_connected or not self.client_socket:
                self.log_message.emit("警告", "未连接，无法发送数据")
                return False
            
            sent = self.client_socket.send(data)
            # self.log_message.emit("调试", f"发送 {sent} 字节")
            return sent > 0
            
        except Exception as e:
            error_msg = f"发送数据失败: {str(e)}"
            self.log_message.emit("错误", error_msg)
            return False
    
    def close_connection(self):
        """关闭连接"""
        try:
            self.receive_thread_running = False
            
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None
                self.log_message.emit("网络", "客户端连接已关闭")
            
            self.is_connected = False
            self.connection_status_changed.emit(False)
            
        except Exception as e:
            error_msg = f"关闭连接失败: {str(e)}"
            self.log_message.emit("错误", error_msg)
    
    def close_server(self):
        """关闭服务器"""
        try:
            self.accept_thread_running = False
            self.receive_thread_running = False
            
            self.close_connection()
            
            if self.server_socket:
                self.server_socket.close()
                self.server_socket = None
                self.log_message.emit("网络", "服务器已关闭")
            
        except Exception as e:
            error_msg = f"关闭服务器失败: {str(e)}"
            self.log_message.emit("错误", error_msg)