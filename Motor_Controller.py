#!/usr/bin/env python3
"""
电机控制系统 - 带校正力求解功能
"""
import sys
import os
import platform  
import traceback 

# 添加当前目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# 检查数据目录
data_dir = os.path.join(current_dir, "data")
if not os.path.exists(data_dir):
    os.makedirs(data_dir)
    print(f"已创建数据目录: {data_dir}")
    print("请将以下数据文件放入数据目录:")
    print("  - ao-700-150-XYZ27pt24h.dat (坐标数据)")
    print("  - OneN-Hex-Rev27pt-f1h24-10.dat (力数据1)")
    print("  - OneN-Hex-Rev27pt-f1h24-20.dat (力数据2)")
    print("  - OneN-Hex-Rev27pt-f1h24-27.dat (力数据3)")
    print("\n如果没有这些文件，系统将使用示例数据进行测试。")

# 检查matplotlib后端
import matplotlib
matplotlib.use('Qt5Agg')

from PyQt5.QtWidgets import QApplication, QStyleFactory, QDialog
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

try:
    from ui.main_window import MainWindow
    # 注意：这里去掉了 login_dialog 的导入，因为启动时不再需要弹窗
except Exception as e:
    print("="*50)
    print("❌ 导入主窗口失败！真正的错误原因如下：")
    traceback.print_exc()
    print("="*50)
    print("请根据上方的 'ModuleNotFoundError' 提示，使用 pip install 安装缺失的库，")
    print("或者检查对应的文件路径是否正确。")
    sys.exit(1)
# =========================================================

def main():
    """主函数"""
    # 启用高DPI支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("电机控制系统")
    app.setApplicationVersion("2.0.0")
    
    # 设置默认字体
    font = QFont("Microsoft YaHei", 10)
    app.setFont(font)
    
    # 设置Fusion样式
    app.setStyle(QStyleFactory.create('Fusion'))
    
    # 创建主窗口
    main_window = MainWindow(user_role="GUEST", username="访客")
    main_window.show()
        
    return app.exec_()

if __name__ == "__main__":
    sys.exit(main())