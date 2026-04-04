' Stealth launcher for launch_cowork_simple.py
' Runs Python with NO visible console window.
' Usage: wscript start-simple-launcher.vbs
'
' For Task Scheduler or startup: wscript "C:\Users\ccimi\rudy-workhorse\scripts\start-simple-launcher.vbs"

Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "C:\Python312\pythonw.exe C:\Users\ccimi\rudy-workhorse\scripts\launch_cowork_simple.py --loop", 0, False
