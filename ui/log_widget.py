"""
日志显示组件 - 修复递归错误与多线程崩溃问题
"""
import datetime
import logging
import re
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                             QTextEdit, QPushButton, QComboBox,
                             QFileDialog, QCheckBox, QLabel, 
                             QGroupBox, QSpinBox, QMenu, QAction,
                             QMessageBox)
# 引入 pyqtSignal
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QSettings, QPoint
from PyQt5.QtGui import QTextCharFormat, QColor, QFont, QTextCursor, QContextMenuEvent

class LogWidget(QWidget):
    """日志显示组件 - 修复递归错误与多线程安全"""
    
    # 信号定义
    log_added = pyqtSignal(str, str)  # 原有的信号
    
    # [新增] 内部使用的线程安全信号
    # 用于将子线程的日志请求转发到主线程
    _sig_thread_safe_log = pyqtSignal(str, str, str) 
    
    def __init__(self):
        super().__init__()
        self.log_count = 0
        self.max_logs = 1000
        self.auto_scroll = True
        self.show_timestamp = True
        self.show_level = True
        self.show_source = True
        self.is_trimming = False
        
        # 日志级别定义
        self.log_levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        
        # 级别颜色映射
        self.level_colors = {
            "DEBUG": QColor("#868e96"),     # 灰色
            "INFO": QColor("#228be6"),      # 蓝色
            "WARNING": QColor("#ff922b"),   # 橙色
            "ERROR": QColor("#fa5252"),     # 红色
            "CRITICAL": QColor("#c92a2a")   # 深红色
        }
        
        # 显示名称映射
        self.level_names = {
            "DEBUG": "调试",
            "INFO": "信息",
            "WARNING": "警告",
            "ERROR": "错误",
            "CRITICAL": "严重"
        }
        
        # 特殊日志类型
        self.special_log_types = {
            "DATA": "数据",
            "NETWORK": "网络",
            "CONTROL": "控制",
            "MOTOR": "电机",
            "SYSTEM": "系统"
        }
        
        # 级别过滤设置
        self.level_filter = {
            "DEBUG": False,
            "INFO": True,
            "WARNING": True,
            "ERROR": True,
            "CRITICAL": True,
            "DATA": False,
            "NETWORK": True,
            "CONTROL": True,
            "SYSTEM": True
        }
        
        # 存储所有日志条目
        self.log_entries = []
        
        # 存储过滤后的日志条目
        self.filtered_entries = []
        
        # 初始化UI
        self.init_ui()
        
        # 加载设置
        self.load_settings()
        
        # [新增] 连接线程安全信号到实际处理槽
        self.update_log_format()
        self._sig_thread_safe_log.connect(self._add_log_impl)
        
        # 添加初始日志（使用安全方式）
        self.add_log_safe("INFO", "日志系统初始化完成", "SYSTEM")
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # 控制栏
        control_layout = QHBoxLayout()
        
        # 级别过滤组
        level_group = QGroupBox("日志级别")
        level_layout = QHBoxLayout(level_group)
        level_layout.setContentsMargins(8, 8, 8, 8)
        level_layout.setSpacing(8)
        
        # 创建级别复选框
        self.level_checkboxes = {}
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        for level in levels:
            checkbox = QCheckBox(self.level_names[level])
            checkbox.setChecked(self.level_filter[level])
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: {self.level_colors[level].name()};
                    font-weight: bold;
                }}
                QCheckBox::indicator {{
                    width: 14px;
                    height: 14px;
                }}
            """)
            checkbox.stateChanged.connect(self.on_level_filter_changed)
            self.level_checkboxes[level] = checkbox
            level_layout.addWidget(checkbox)
        
        level_layout.addStretch()
        control_layout.addWidget(level_group)
        
        # 源过滤组
        source_group = QGroupBox("日志来源")
        source_layout = QHBoxLayout(source_group)
        source_layout.setContentsMargins(8, 8, 8, 8)
        source_layout.setSpacing(8)
        
        # 特殊日志类型复选框
        self.source_checkboxes = {}
        sources = ["DATA", "NETWORK", "CONTROL", "SYSTEM"]
        for source in sources:
            checkbox = QCheckBox(self.special_log_types.get(source, source))
            checkbox.setChecked(self.level_filter.get(source, True))
            
            source_colors = {
                "DATA": "#0ca678",
                "NETWORK": "#339af0",
                "CONTROL": "#cc5de8",
                "SYSTEM": "#f76707"
            }
            
            color = source_colors.get(source, "#666666")
            checkbox.setStyleSheet(f"""
                QCheckBox {{
                    color: {color};
                    font-weight: bold;
                }}
                QCheckBox::indicator {{
                    width: 14px;
                    height: 14px;
                }}
            """)
            
            checkbox.stateChanged.connect(self.on_source_filter_changed)
            self.source_checkboxes[source] = checkbox
            source_layout.addWidget(checkbox)
        
        source_layout.addStretch()
        control_layout.addWidget(source_group)
        
        # 其他控制组
        other_group = QGroupBox("显示设置")
        other_layout = QHBoxLayout(other_group)
        other_layout.setContentsMargins(8, 8, 8, 8)
        other_layout.setSpacing(8)
        
        self.auto_scroll_checkbox = QCheckBox("自动滚动")
        self.auto_scroll_checkbox.setChecked(True)
        self.auto_scroll_checkbox.stateChanged.connect(self.on_auto_scroll_changed)
        other_layout.addWidget(self.auto_scroll_checkbox)
        
        self.show_timestamp_checkbox = QCheckBox("时间")
        self.show_timestamp_checkbox.setChecked(True)
        self.show_timestamp_checkbox.stateChanged.connect(self.on_show_timestamp_changed)
        other_layout.addWidget(self.show_timestamp_checkbox)
        
        self.show_level_checkbox = QCheckBox("级别")
        self.show_level_checkbox.setChecked(True)
        self.show_level_checkbox.stateChanged.connect(self.on_show_level_changed)
        other_layout.addWidget(self.show_level_checkbox)
        
        self.show_source_checkbox = QCheckBox("来源")
        self.show_source_checkbox.setChecked(True)
        self.show_source_checkbox.stateChanged.connect(self.on_show_source_changed)
        other_layout.addWidget(self.show_source_checkbox)
        
        other_layout.addStretch()
        control_layout.addWidget(other_group)
        
        # 操作按钮组
        action_group = QGroupBox("操作")
        action_layout = QHBoxLayout(action_group)
        action_layout.setContentsMargins(8, 8, 8, 8)
        action_layout.setSpacing(8)
        
        action_layout.addWidget(QLabel("最大:"))
        self.max_logs_spinbox = QSpinBox()
        self.max_logs_spinbox.setRange(100, 10000)
        self.max_logs_spinbox.setValue(self.max_logs)
        self.max_logs_spinbox.setSingleStep(100)
        self.max_logs_spinbox.valueChanged.connect(self.on_max_logs_changed)
        self.max_logs_spinbox.setFixedWidth(70)
        action_layout.addWidget(self.max_logs_spinbox)
        
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setToolTip("清空所有日志")
        self.clear_btn.clicked.connect(self.clear_logs)
        self.clear_btn.setFixedWidth(60)
        action_layout.addWidget(self.clear_btn)
        
        self.save_btn = QPushButton("保存")
        self.save_btn.setToolTip("保存日志到文件")
        self.save_btn.clicked.connect(self.save_logs)
        self.save_btn.setFixedWidth(60)
        action_layout.addWidget(self.save_btn)
        
        self.quick_filter_btn = QPushButton("快速过滤")
        self.quick_filter_btn.setToolTip("快速过滤设置")
        self.quick_filter_btn.clicked.connect(self.show_quick_filter_menu)
        self.quick_filter_btn.setFixedWidth(80)
        action_layout.addWidget(self.quick_filter_btn)
        
        action_layout.addStretch()
        control_layout.addWidget(action_group)
        
        control_layout.addStretch()
        layout.addLayout(control_layout)
        
        # 日志显示区域
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setReadOnly(True)
        self.log_text_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_text_edit.customContextMenuRequested.connect(self.show_context_menu)
        
        self.log_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
            }
        """)
        layout.addWidget(self.log_text_edit, 1)
        
        # 状态栏
        status_layout = QHBoxLayout()
        
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666666; font-size: 9pt;")
        status_layout.addWidget(self.status_label)
        
        status_layout.addStretch()
        
        self.count_label = QLabel("日志: 0")
        self.count_label.setStyleSheet("color: #228be6; font-weight: bold;")
        status_layout.addWidget(self.count_label)
        
        self.filtered_label = QLabel("显示: 0")
        self.filtered_label.setStyleSheet("color: #51cf66; font-weight: bold;")
        status_layout.addWidget(self.filtered_label)
        
        layout.addLayout(status_layout)
        
        # 设置按钮样式
        self.update_button_styles()
    
    def update_button_styles(self):
        """更新按钮样式"""
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff6b6b;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #fa5252;
            }
            QPushButton:pressed {
                background-color: #e03131;
            }
        """)
        
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #51cf66;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #40c057;
            }
            QPushButton:pressed {
                background-color: #2b8a3e;
            }
        """)
        
        self.quick_filter_btn.setStyleSheet("""
            QPushButton {
                background-color: #4dabf7;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #339af0;
            }
            QPushButton:pressed {
                background-color: #228be6;
            }
        """)
    
    def add_log(self, level, message, source=""):
        """
        [修改] 线程安全的日志添加入口
        如果是子线程调用，会通过信号自动转发到主线程执行
        """
        self._sig_thread_safe_log.emit(level, str(message), source)
    
    def _add_log_impl(self, level, message, source):
        """[新增] 实际处理日志的槽函数，由信号触发"""
        self.add_log_safe(level, message, source)

    def add_log_safe(self, level, message, source="", is_trim_log=False):
        """安全添加日志条目（防止递归）"""
        # 确保级别是大写
        level_upper = level.upper()
        
        # 获取当前时间
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # 检测特殊日志类型
        log_type = self.detect_log_type(message, source)
        
        # 创建日志条目
        log_entry = {
            "id": len(self.log_entries),
            "timestamp": timestamp,
            "level": level_upper,
            "source": source,
            "type": log_type,
            "message": str(message),
            "raw_time": datetime.datetime.now()
        }
        
        # 添加到所有日志条目
        self.log_entries.append(log_entry)
        
        # 检查是否应该显示（根据过滤设置）
        if self.should_display_log(log_entry):
            self.display_log_entry(log_entry)
            self.filtered_entries.append(log_entry)
        
        # 更新计数
        self.update_count_labels()
        
        # 发射信号
        self.log_added.emit(level_upper, message)
        
        # 自动滚动
        if self.auto_scroll:
            self.scroll_to_bottom()
        
        # 限制日志数量（如果是清理日志则不触发清理）
        if not is_trim_log and len(self.log_entries) > self.max_logs:
            self.trim_logs()
    
    def detect_log_type(self, message, source):
        """检测日志类型"""
        message_str = str(message).lower()
        
        # 检测数据传输相关日志
        data_keywords = ["数据", "接收", "发送", "字节", "长度", "motor", "position", "force"]
        if any(keyword in message_str for keyword in data_keywords):
            return "DATA"
        
        # 检测网络相关日志
        network_keywords = ["连接", "断开", "ip", "端口", "网络", "socket"]
        if any(keyword in message_str for keyword in network_keywords):
            return "NETWORK"
        
        # 检测控制相关日志
        control_keywords = ["控制", "命令", "启动", "停止", "设置", "配置"]
        if any(keyword in message_str for keyword in control_keywords):
            return "CONTROL"
        
        # 根据源判断
        if source in ["NETWORK", "网络"]:
            return "NETWORK"
        elif source in ["DATA", "数据"]:
            return "DATA"
        elif source in ["CONTROL", "控制"]:
            return "CONTROL"
        elif source in ["SYSTEM", "系统"]:
            return "SYSTEM"
        
        return "INFO"
    
    def should_display_log(self, log_entry):
        """判断是否应该显示日志"""
        level = log_entry["level"]
        log_type = log_entry["type"]
        
        # 检查级别过滤
        if not self.level_filter.get(level, True):
            return False
        
        # 检查类型过滤
        if not self.level_filter.get(log_type, True):
            return False
        
        return True
    
    def display_log_entry(self, entry):
        """在文本框中显示日志条目"""
        cursor = self.log_text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # 构建显示文本
        display_parts = []
        
        if self.show_timestamp:
            time_part = entry["timestamp"].split(" ")[1]  # 只显示时间部分
            display_parts.append(f"[{time_part}]")
        
        if self.show_level:
            level_name = self.level_names.get(entry["level"], entry["level"])
            display_parts.append(f"[{level_name}]")
        
        if self.show_source and entry["source"]:
            source_name = self.special_log_types.get(entry["source"], entry["source"])
            display_parts.append(f"[{source_name}]")
        
        # 消息部分
        message = entry["message"]
        
        # 合并所有部分
        prefix = " ".join(display_parts)
        if prefix:
            full_text = f"{prefix} {message}\n"
        else:
            full_text = f"{message}\n"
        
        # 设置颜色
        format = QTextCharFormat()
        format.setFontFamily("Consolas, 'Courier New', monospace")
        format.setFontPointSize(9)
        
        # 根据类型设置颜色
        if entry["type"] == "DATA":
            color = QColor("#0ca678")  # 绿色
        elif entry["type"] == "NETWORK":
            color = QColor("#339af0")  # 蓝色
        elif entry["type"] == "CONTROL":
            color = QColor("#cc5de8")  # 紫色
        elif entry["type"] == "SYSTEM":
            color = QColor("#f76707")  # 橙色
        else:
            # 否则使用级别颜色
            color = self.level_colors.get(entry["level"], QColor("#666666"))
        
        format.setForeground(color)
        
        # 插入文本
        cursor.insertText(full_text, format)
    
    def on_level_filter_changed(self):
        """级别过滤改变"""
        # 更新过滤设置
        for level, checkbox in self.level_checkboxes.items():
            self.level_filter[level] = checkbox.isChecked()
        
        # 重新应用过滤
        self.apply_filters()
    
    def on_source_filter_changed(self):
        """源过滤改变"""
        # 更新过滤设置
        for source, checkbox in self.source_checkboxes.items():
            self.level_filter[source] = checkbox.isChecked()
        
        # 重新应用过滤
        self.apply_filters()
    
    def apply_filters(self):
        """应用所有过滤器"""
        # 防止在清理时应用过滤
        if self.is_trimming:
            return
            
        # 清空文本框
        self.log_text_edit.clear()
        self.filtered_entries.clear()
        
        # 重新添加符合条件的日志
        for entry in self.log_entries:
            if self.should_display_log(entry):
                self.display_log_entry(entry)
                self.filtered_entries.append(entry)
        
        # 更新计数
        self.update_count_labels()
        
        # 更新状态
        self.update_filter_status()
        
        # 自动滚动
        if self.auto_scroll:
            self.scroll_to_bottom()
    
    def update_count_labels(self):
        """更新计数标签"""
        total_count = len(self.log_entries)
        filtered_count = len(self.filtered_entries)
        
        self.count_label.setText(f"日志: {total_count}")
        self.filtered_label.setText(f"显示: {filtered_count}")
    
    def update_filter_status(self):
        """更新过滤状态"""
        enabled_levels = []
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            if self.level_filter.get(level, False):
                enabled_levels.append(self.level_names.get(level, level))
        
        enabled_sources = []
        for source in ["DATA", "NETWORK", "CONTROL", "SYSTEM"]:
            if self.level_filter.get(source, False):
                enabled_sources.append(self.special_log_types.get(source, source))
        
        if enabled_levels or enabled_sources:
            level_text = "、".join(enabled_levels)
            source_text = "、".join(enabled_sources)
            
            if level_text and source_text:
                self.status_label.setText(f"显示: {level_text} | {source_text}")
            elif level_text:
                self.status_label.setText(f"显示级别: {level_text}")
            elif source_text:
                self.status_label.setText(f"显示来源: {source_text}")
        else:
            self.status_label.setText("无显示内容")
    
    def on_auto_scroll_changed(self, state):
        """自动滚动设置改变"""
        self.auto_scroll = (state == Qt.Checked)
    
    def on_show_timestamp_changed(self, state):
        """显示时间戳设置改变"""
        self.show_timestamp = (state == Qt.Checked)
        self.refresh_display()
    
    def on_show_level_changed(self, state):
        """显示级别设置改变"""
        self.show_level = (state == Qt.Checked)
        self.refresh_display()
    
    def on_show_source_changed(self, state):
        """显示来源设置改变"""
        self.show_source = (state == Qt.Checked)
        self.refresh_display()
    
    def on_max_logs_changed(self, value):
        """最大日志数改变"""
        self.max_logs = value
        
        # 如果当前日志超过最大限制，进行清理
        if len(self.log_entries) > self.max_logs:
            self.trim_logs()
    
    def refresh_display(self):
        """刷新显示"""
        # 清空文本框
        self.log_text_edit.clear()
        
        # 重新显示过滤后的日志
        for entry in self.filtered_entries:
            self.display_log_entry(entry)
        
        # 自动滚动
        if self.auto_scroll:
            self.scroll_to_bottom()
    
    def scroll_to_bottom(self):
        """滚动到底部"""
        cursor = self.log_text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.log_text_edit.setTextCursor(cursor)
        self.log_text_edit.ensureCursorVisible()
    
    def trim_logs(self):
        """清理过多的日志 - 修复递归错误"""
        # 如果已经在清理中，直接返回
        if self.is_trimming:
            return
            
        try:
            self.is_trimming = True
            
            if len(self.log_entries) > self.max_logs:
                # 计算需要删除的数量
                remove_count = len(self.log_entries) - self.max_logs
                
                # 删除最早的日志
                self.log_entries = self.log_entries[remove_count:]
                
                # 重新应用过滤（不触发再次清理）
                self.log_text_edit.clear()
                self.filtered_entries.clear()
                
                # 重新添加符合条件的日志
                for entry in self.log_entries:
                    if self.should_display_log(entry):
                        self.display_log_entry(entry)
                        self.filtered_entries.append(entry)
                
                # 更新计数
                self.update_count_labels()
                
                # 只在状态栏显示，不添加日志，避免递归
                self.status_label.setText(f"已清理 {remove_count} 条旧日志，保留最近 {self.max_logs} 条")
                
                # 3秒后恢复状态
                QTimer.singleShot(3000, lambda: self.update_filter_status())
        finally:
            self.is_trimming = False
    
    def clear_logs(self):
        """清空所有日志"""
        # 确认对话框
        reply = QMessageBox.question(
            self, '确认清空',
            '确定要清空所有日志吗？',
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.log_text_edit.clear()
            self.log_entries.clear()
            self.filtered_entries.clear()
            
            # 更新标签
            self.count_label.setText("日志: 0")
            self.filtered_label.setText("显示: 0")
            self.status_label.setText("日志已清空")
            
            # 添加日志记录（使用安全方式）
            self.add_log_safe("INFO", "日志已清空", "SYSTEM")
    
    def save_logs(self):
        """保存日志到文件"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", 
            f"motor_control_log_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
            "日志文件 (*.log);;文本文件 (*.txt);;所有文件 (*.*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    # 写入头部信息
                    f.write(f"=== 电机控制系统日志导出 ===\n")
                    f.write(f"导出时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"日志数量: {len(self.log_entries)}\n")
                    f.write(f"显示数量: {len(self.filtered_entries)}\n")
                    f.write("=" * 50 + "\n\n")
                    
                    # 写入所有日志条目
                    for entry in self.log_entries:
                        timestamp = entry["timestamp"]
                        level = self.level_names.get(entry["level"], entry["level"])
                        source = entry["source"]
                        message = entry["message"]
                        
                        if source:
                            log_line = f"[{timestamp}] [{level}] [{source}] {message}\n"
                        else:
                            log_line = f"[{timestamp}] [{level}] {message}\n"
                        
                        f.write(log_line)
                
                self.add_log_safe("INFO", f"日志已保存到: {file_path}", "SYSTEM")
                self.status_label.setText(f"日志已保存到: {file_path}")
                
            except Exception as e:
                error_msg = f"保存日志失败: {str(e)}"
                self.add_log_safe("ERROR", error_msg, "SYSTEM")
                self.status_label.setText(error_msg)
    
    def show_quick_filter_menu(self):
        """显示快速过滤菜单"""
        menu = QMenu(self)
        
        # 只显示错误和警告
        action_errors_only = QAction("只显示错误和警告", self)
        action_errors_only.triggered.connect(self.filter_errors_only)
        menu.addAction(action_errors_only)
        
        # 隐藏所有数据传输
        action_hide_data = QAction("隐藏所有数据传输", self)
        action_hide_data.triggered.connect(self.hide_all_data)
        menu.addAction(action_hide_data)
        
        # 只显示系统日志
        action_system_only = QAction("只显示系统日志", self)
        action_system_only.triggered.connect(self.filter_system_only)
        menu.addAction(action_system_only)
        
        menu.addSeparator()
        
        # 显示所有日志
        action_show_all = QAction("显示所有日志", self)
        action_show_all.triggered.connect(self.show_all_logs)
        menu.addAction(action_show_all)
        
        # 显示位置
        pos = self.quick_filter_btn.mapToGlobal(QPoint(0, self.quick_filter_btn.height()))
        menu.exec_(pos)
    
    def filter_errors_only(self):
        """只显示错误和警告"""
        for level in ["DEBUG", "INFO"]:
            if level in self.level_checkboxes:
                self.level_checkboxes[level].setChecked(False)
        
        for level in ["WARNING", "ERROR", "CRITICAL"]:
            if level in self.level_checkboxes:
                self.level_checkboxes[level].setChecked(True)
        
        # 隐藏数据传输
        if "DATA" in self.source_checkboxes:
            self.source_checkboxes["DATA"].setChecked(False)
    
    def hide_all_data(self):
        """隐藏所有数据传输"""
        if "DATA" in self.source_checkboxes:
            self.source_checkboxes["DATA"].setChecked(False)
        
        self.apply_filters()
    
    def filter_system_only(self):
        """只显示系统日志"""
        # 关闭所有级别
        for level in self.level_checkboxes.values():
            level.setChecked(False)
        
        # 关闭所有源
        for source in self.source_checkboxes.values():
            source.setChecked(False)
        
        # 只打开系统和错误
        if "SYSTEM" in self.source_checkboxes:
            self.source_checkboxes["SYSTEM"].setChecked(True)
        
        if "ERROR" in self.level_checkboxes:
            self.level_checkboxes["ERROR"].setChecked(True)
        
        if "CRITICAL" in self.level_checkboxes:
            self.level_checkboxes["CRITICAL"].setChecked(True)
    
    def show_all_logs(self):
        """显示所有日志"""
        # 打开所有级别
        for level in self.level_checkboxes.values():
            level.setChecked(True)
        
        # 打开所有源
        for source in self.source_checkboxes.values():
            source.setChecked(True)
    
    def show_context_menu(self, pos):
        """显示上下文菜单"""
        menu = self.log_text_edit.createStandardContextMenu()
        
        # 添加自定义动作
        menu.addSeparator()
        
        copy_all_action = QAction("复制所有日志", self)
        copy_all_action.triggered.connect(self.copy_all_logs)
        menu.addAction(copy_all_action)
        
        find_action = QAction("查找...", self)
        find_action.triggered.connect(self.show_find_dialog)
        menu.addAction(find_action)
        
        menu.exec_(self.log_text_edit.mapToGlobal(pos))
    
    def copy_all_logs(self):
        """复制所有日志"""
        all_text = self.log_text_edit.toPlainText()
        if all_text:
            from PyQt5.QtWidgets import QApplication
            QApplication.clipboard().setText(all_text)
            self.add_log_safe("INFO", "已复制所有日志到剪贴板", "SYSTEM")
    
    def show_find_dialog(self):
        """显示查找对话框"""
        from PyQt5.QtWidgets import QInputDialog
        
        text, ok = QInputDialog.getText(self, "查找", "输入要查找的内容:")
        if ok and text:
            self.find_text(text)
    
    def find_text(self, text):
        """查找文本"""
        if not text:
            return
        
        cursor = self.log_text_edit.textCursor()
        format = QTextCharFormat()
        format.setBackground(QColor("#fff3cd"))  # 黄色背景
        
        # 清除之前的高亮
        cursor.movePosition(QTextCursor.Start)
        self.log_text_edit.setTextCursor(cursor)
        
        # 查找并高亮
        found = False
        while self.log_text_edit.find(text):
            found = True
            cursor = self.log_text_edit.textCursor()
            cursor.mergeCharFormat(format)
        
        if found:
            self.add_log_safe("INFO", f"找到包含 '{text}' 的日志", "SYSTEM")
        else:
            self.add_log_safe("INFO", f"未找到包含 '{text}' 的日志", "SYSTEM")
    
    def update_log_format(self):
        """更新日志格式"""
        pass
    
    def load_settings(self):
        """加载设置"""
        try:
            settings = QSettings("MotorControl", "LogWidget")
            
            # 加载级别过滤
            for level in self.level_filter.keys():
                self.level_filter[level] = settings.value(f"level_{level}", 
                                                         self.level_filter[level], 
                                                         type=bool)
            
            # 更新复选框状态
            for level, checkbox in self.level_checkboxes.items():
                checkbox.setChecked(self.level_filter.get(level, False))
            
            for source, checkbox in self.source_checkboxes.items():
                checkbox.setChecked(self.level_filter.get(source, False))
            
            # 加载其他设置
            self.auto_scroll = settings.value("auto_scroll", True, type=bool)
            self.show_timestamp = settings.value("show_timestamp", True, type=bool)
            self.show_level = settings.value("show_level", True, type=bool)
            self.show_source = settings.value("show_source", True, type=bool)
            self.max_logs = settings.value("max_logs", 1000, type=int)
            
            # 更新UI控件
            self.auto_scroll_checkbox.setChecked(self.auto_scroll)
            self.show_timestamp_checkbox.setChecked(self.show_timestamp)
            self.show_level_checkbox.setChecked(self.show_level)
            self.show_source_checkbox.setChecked(self.show_source)
            self.max_logs_spinbox.setValue(self.max_logs)
            
        except Exception as e:
            self.add_log_safe("WARNING", f"加载设置失败: {str(e)}", "SYSTEM")
    
    def save_settings(self):
        """保存设置"""
        try:
            settings = QSettings("MotorControl", "LogWidget")
            
            # 保存级别过滤
            for level, enabled in self.level_filter.items():
                settings.setValue(f"level_{level}", enabled)
            
            # 保存其他设置
            settings.setValue("auto_scroll", self.auto_scroll)
            settings.setValue("show_timestamp", self.show_timestamp)
            settings.setValue("show_level", self.show_level)
            settings.setValue("show_source", self.show_source)
            settings.setValue("max_logs", self.max_logs)
            
            settings.sync()
            
        except Exception as e:
            self.add_log_safe("ERROR", f"保存设置失败: {str(e)}", "SYSTEM")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        self.save_settings()
        super().closeEvent(event)