"""
数据转换器
"""
class DataConverter:
    """数据转换器"""
    
    def convert_force_target_to_cmd(self, force):
        """目标力转换为单片机内部与AD对应的控制命令"""
        # 传感器输出0-1.5V-3V，2.5V基准
        # 受压时传感器输出减小，受拉时输出电压增大
        fx = 39321 + force * (65535 - 39321) / 200
        return int(fx)
    
    def convert_pos_target_to_cmd(self, position):
        """目标位置转换为单片机内部与AD对应的控制命令"""
        pos = 65535 * (position / 5000.0)
        return int(pos)
    
    def convert_ad_to_force(self, ad_value):
        """单片机AD值转换为拉压力值显示"""
        # 传感器输出0-1.5V-3V，2.5V基准
        # 受压时传感器输出减小，受拉时输出电压增大
        force = 200.0 * (ad_value - 39321) / 26215
        return force