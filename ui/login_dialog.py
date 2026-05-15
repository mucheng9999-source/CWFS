"""
登录与权限验证模块
"""
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QLineEdit, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt


USER_DB = {
    "admin": {"password": "123", "role": "ADMIN"},    # 管理员
    "user": {"password": "123", "role": "USER"},      # 用户
}

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.user_role = None
        self.username = ""
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("提权登录 - 主动支撑控制")
        self.setFixedSize(300, 180)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # 账号输入
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("账号: "))
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("admin 或 user")
        h1.addWidget(self.user_input)
        layout.addLayout(h1)

        # 密码输入
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("密码: "))
        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        h2.addWidget(self.pwd_input)
        layout.addLayout(h2)

        # 按钮
        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("登录提权")
        self.login_btn.setDefault(True)
        self.login_btn.setStyleSheet("background-color: #2196F3; color: white; height: 30px;")
        self.login_btn.clicked.connect(self.check_login)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def check_login(self):
        u = self.user_input.text().strip()
        p = self.pwd_input.text().strip()

        if u in USER_DB and USER_DB[u]["password"] == p:
            self.user_role = USER_DB[u]["role"]
            self.username = u
            self.accept()
        else:
            QMessageBox.critical(self, "登录失败", "账号或密码错误！")