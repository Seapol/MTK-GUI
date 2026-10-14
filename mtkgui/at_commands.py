# -*- coding: utf-8 -*-
"""Common AT commands for MTK / generic cellular modules.

Item 1 is the button label, item 2 the actual AT command sent
(without line ending; the ending is controlled by the
"append CR+LF" option), item 3 the tooltip description.
Command support varies slightly between module firmwares;
refer to the module AT command manual.
"""

AT_COMMANDS = [
    ("AT", "AT", "Connectivity check, expects OK"),
    ("ATE0", "ATE0", "Disable echo"),
    ("ATE1", "ATE1", "Enable echo"),
    ("AT+CGMI", "AT+CGMI", "Query manufacturer name"),
    ("AT+CGMM", "AT+CGMM", "Query model"),
    ("AT+CGMR", "AT+CGMR", "Query firmware revision"),
    ("AT+CGSN", "AT+CGSN", "Query serial number / IMEI"),
    ("AT+CIMI", "AT+CIMI", "Query SIM IMSI"),
    ("AT+CPIN?", "AT+CPIN?", "Query SIM / PIN state"),
    ("AT+CSQ", "AT+CSQ", "Query signal quality (RSSI)"),
    ("AT+CEREG?", "AT+CEREG?", "Query LTE/5G network registration"),
    ("AT+CREG?", "AT+CREG?", "Query CS network registration"),
    ("AT+COPS?", "AT+COPS?", "Query current operator"),
    ("AT+CGACT?", "AT+CGACT?", "Query PDP activation state"),
    ("AT+CGCONTRDP", "AT+CGCONTRDP", "Query assigned IP and PDP parameters"),
    ("AT+CFUN?", "AT+CFUN?", "Query phone functionality mode"),
    ("AT+CMGF?", "AT+CMGF?", "Query SMS format (0=PDU, 1=text)"),
    ("AT+IPR?", "AT+IPR?", "Query serial baud rate"),
    ("AT&V", "AT&V", "Show current full configuration"),
    ("AT+CFUN=1,1", "AT+CFUN=1,1", "Reboot module (drops the connection)"),
]
