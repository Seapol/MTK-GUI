# -*- coding: utf-8 -*-
"""MTK / 通用蜂窝模块常用 AT 命令快捷表。

第一项为按钮文字，第二项为实际发送的 AT 命令（不含行尾，行尾由
"追加 CR+LF" 选项控制），第三项为说明提示。
不同模组固件的命令支持略有差异，以模组 AT 命令手册为准。
"""

AT_COMMANDS = [
    ("AT", "AT", "AT 连通测试，应返回 OK"),
    ("ATE0", "ATE0", "关闭回显"),
    ("ATE1", "ATE1", "开启回显"),
    ("AT+CGMI", "AT+CGMI", "查询厂商名称 (Manufacturer)"),
    ("AT+CGMM", "AT+CGMM", "查询型号 (Model)"),
    ("AT+CGMR", "AT+CGMR", "查询固件版本 (Revision)"),
    ("AT+CGSN", "AT+CGSN", "查询序列号 / IMEI"),
    ("AT+CIMI", "AT+CIMI", "查询 SIM 卡 IMSI"),
    ("AT+CPIN?", "AT+CPIN?", "查询 SIM 卡 / PIN 状态"),
    ("AT+CSQ", "AT+CSQ", "查询信号质量 (RSSI)"),
    ("AT+CEREG?", "AT+CEREG?", "查询 LTE/5G 网络注册状态"),
    ("AT+CREG?", "AT+CREG?", "查询 CS 网络注册状态"),
    ("AT+COPS?", "AT+COPS?", "查询当前运营商"),
    ("AT+CGACT?", "AT+CGACT?", "查询 PDP 激活状态"),
    ("AT+CGCONTRDP", "AT+CGCONTRDP", "查询动态分配的 IP 等参数"),
    ("AT+CFUN?", "AT+CFUN?", "查询电话功能模式"),
    ("AT+CMGF?", "AT+CMGF?", "查询短信格式 (0=PDU,1=文本)"),
    ("AT+IPR?", "AT+IPR?", "查询串口波特率"),
    ("AT&V", "AT&V", "显示当前全部配置"),
    ("AT+CFUN=1,1", "AT+CFUN=1,1", "重启模组 (注意会断连)"),
]
