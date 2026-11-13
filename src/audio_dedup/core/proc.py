"""统一子进程启动参数：让控制台子程序在窗口化 GUI 里不再弹黑窗。

打包版（`--windowed`）本身没有控制台，ffmpeg / ffprobe 这类控制台程序
被拉起时 Windows 会给每个进程各分配一个新控制台窗口——启动时批量解码
波形就会连续弹出一堆黑窗。这里统一加上 CREATE_NO_WINDOW 与隐藏窗口的
STARTUPINFO，让子进程在同一无窗口环境下运行。
"""
import os
import subprocess


def hidden_kwargs() -> dict:
    """返回屏蔽子进程窗口的启动参数；非 Windows 平台返回空字典。

    可直接展开进 subprocess.run / subprocess.Popen：
        subprocess.run(cmd, **hidden_kwargs())
    """
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }
