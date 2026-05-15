"""
日志模块 - 用于记录所有操作和事件
"""
import os
import sys
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path

class MotorControlLogger:
    """电机控制日志管理器"""
    
    def __init__(self, app_name="MotorControlSystem"):
        self.app_name = app_name
        self.logger = None
        self.log_dir = "logs"
        self.setup_logging()
    
    def setup_logging(self):
        """设置日志系统"""
        # 创建日志目录
        Path(self.log_dir).mkdir(exist_ok=True)
        
        # 创建logger
        self.logger = logging.getLogger(self.app_name)
        self.logger.setLevel(logging.DEBUG)
        
        # 清除已有的处理器
        self.logger.handlers.clear()
        
        # 设置日志格式
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        
        # 文件处理器 - 按天滚动
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=os.path.join(self.log_dir, f"{self.app_name}.log"),
            when='midnight',  # 每天午夜滚动
            interval=1,
            backupCount=30,   # 保留30天的日志
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        
        # 错误日志处理器 - 单独记录错误
        error_handler = logging.handlers.RotatingFileHandler(
            filename=os.path.join(self.log_dir, f"{self.app_name}_error.log"),
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.WARNING)
        error_handler.setFormatter(formatter)
        
        # 添加处理器
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(error_handler)
    
    def log_connection(self, ip, port, status, message=""):
        """记录连接事件"""
        if status == "connecting":
            self.logger.info(f"正在连接服务器 - IP: {ip}, 端口: {port} {message}")
        elif status == "connected":
            self.logger.info(f"连接成功 - IP: {ip}, 端口: {port} {message}")
        elif status == "disconnected":
            self.logger.info(f"连接断开 - IP: {ip}, 端口: {port} {message}")
        elif status == "error":
            self.logger.error(f"连接错误 - IP: {ip}, 端口: {port} - {message}")
    
    def log_motor_control(self, motor_id, command, params=None, status="sent"):
        """记录电机控制事件"""
        param_str = f", 参数: {params}" if params else ""
        
        if status == "sent":
            self.logger.info(f"电机控制命令发送 - 电机ID: {motor_id}, 命令: {command}{param_str}")
        elif status == "received":
            self.logger.info(f"电机控制响应接收 - 电机ID: {motor_id}, 命令: {command}{param_str}")
        elif status == "error":
            self.logger.error(f"电机控制错误 - 电机ID: {motor_id}, 命令: {command}{param_str}")
    
    def log_data_receive(self, data_length, motor_id=None, data_type=None):
        """记录数据接收事件"""
        motor_info = f", 电机ID: {motor_id}" if motor_id is not None else ""
        type_info = f", 数据类型: {data_type}" if data_type else ""
        
        self.logger.debug(f"接收到数据 - 长度: {data_length}字节{motor_info}{type_info}")
    
    def log_user_action(self, user, action, details=""):
        """记录用户操作"""
        details_str = f", 详情: {details}" if details else ""
        self.logger.info(f"用户操作 - 用户: {user}, 操作: {action}{details_str}")
    
    def log_system_event(self, event, level="info", details=""):
        """记录系统事件"""
        details_str = f", 详情: {details}" if details else ""
        
        if level == "info":
            self.logger.info(f"系统事件 - {event}{details_str}")
        elif level == "warning":
            self.logger.warning(f"系统事件 - {event}{details_str}")
        elif level == "error":
            self.logger.error(f"系统事件 - {event}{details_str}")
        elif level == "critical":
            self.logger.critical(f"系统事件 - {event}{details_str}")
    
    def log_performance(self, operation, execution_time):
        """记录性能指标"""
        self.logger.debug(f"性能指标 - 操作: {operation}, 执行时间: {execution_time:.3f}秒")
    
    def get_log_file_path(self):
        """获取当前日志文件路径"""
        return os.path.join(self.log_dir, f"{self.app_name}.log")
    
    def get_error_log_file_path(self):
        """获取错误日志文件路径"""
        return os.path.join(self.log_dir, f"{self.app_name}_error.log")
    
    def clear_old_logs(self, days_to_keep=30):
        """清理旧日志文件"""
        try:
            log_dir = Path(self.log_dir)
            current_time = datetime.now()
            
            for log_file in log_dir.glob("*.log"):
                if log_file.is_file():
                    file_time = datetime.fromtimestamp(log_file.stat().st_mtime)
                    days_old = (current_time - file_time).days
                    
                    if days_old > days_to_keep:
                        log_file.unlink()
                        self.logger.info(f"清理旧日志文件: {log_file.name}")
            
        except Exception as e:
            self.logger.error(f"清理日志文件失败: {e}")


# 全局日志管理器实例
_logger_instance = None

def get_logger(app_name="MotorControlSystem"):
    """获取日志管理器实例（单例模式）"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = MotorControlLogger(app_name)
    return _logger_instance