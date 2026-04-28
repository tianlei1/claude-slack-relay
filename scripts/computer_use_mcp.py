import base64
import io
import os
import time

import pyautogui
import win32api
import win32con
from mcp.server.fastmcp import FastMCP
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN_DIR = os.path.join(BASE_DIR, "screen")

pyautogui.FAILSAFE = True  # 鼠标移到左上角可紧急停止
pyautogui.PAUSE = 0.3

mcp = FastMCP("computer-use")


def _screenshot_base64(region=None) -> str:
    img = pyautogui.screenshot(region=region)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@mcp.tool()
def screenshot(name: str, x: int = None, y: int = None, width: int = None, height: int = None) -> dict:
    """截取屏幕截图，保存到 screen/ 目录。
    name: 文件名（不含扩展名），根据截图内容起有意义的名字，如 'slack_window' 或 'error_dialog'。
    不传 x/y/width/height 则截全屏；否则截指定区域。
    返回 base64 PNG 及保存路径，用 [IMAGE:file_path] 可将图片发送给用户。"""
    region = (x, y, width, height) if all(v is not None for v in [x, y, width, height]) else None
    img = pyautogui.screenshot(region=region)

    os.makedirs(SCREEN_DIR, exist_ok=True)
    filename = f"{name}.png" if not name.endswith(".png") else name
    file_path = os.path.join(SCREEN_DIR, filename)
    img.save(file_path)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    size = pyautogui.size()
    return {
        "image_base64": img_b64,
        "file_path": file_path,
        "format": "png",
        "screen_width": size.width,
        "screen_height": size.height,
        "region": region,
    }


@mcp.tool()
def mouse_move(x: int, y: int, duration: float = 0.3) -> str:
    """将鼠标移动到屏幕坐标 (x, y)。duration 是移动时间（秒）。"""
    pyautogui.moveTo(x, y, duration=duration)
    return f"鼠标已移至 ({x}, {y})"


@mcp.tool()
def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1, interval: float = 0.1) -> str:
    """在屏幕坐标 (x, y) 点击鼠标。button: left/right/middle，clicks: 点击次数（2=双击）。"""
    pyautogui.click(x, y, button=button, clicks=clicks, interval=interval)
    return f"{button} 点击 ({x}, {y}) × {clicks}"


@mcp.tool()
def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> str:
    """从 (start_x, start_y) 拖拽到 (end_x, end_y)。"""
    pyautogui.drag(start_x, start_y, end_x - start_x, end_y - start_y, duration=duration, button="left")
    return f"拖拽: ({start_x},{start_y}) → ({end_x},{end_y})"


@mcp.tool()
def mouse_scroll(x: int, y: int, clicks: int) -> str:
    """在 (x, y) 位置滚动鼠标滚轮。clicks 正数向上，负数向下。"""
    pyautogui.scroll(clicks, x=x, y=y)
    return f"滚动 {clicks} 格 at ({x}, {y})"


@mcp.tool()
def keyboard_type(text: str, interval: float = 0.05) -> str:
    """输入文本字符串（支持中文及特殊字符，通过剪贴板粘贴）。"""
    import subprocess
    subprocess.run("clip", input=text.encode("utf-16-le"), check=True)
    pyautogui.hotkey("ctrl", "v")
    return f"已输入: {text[:50]}{'...' if len(text) > 50 else ''}"


@mcp.tool()
def keyboard_press(keys: str) -> str:
    """按下键盘快捷键或单键。支持组合键，用+分隔，例如: ctrl+c / alt+F4 / enter / tab / esc。"""
    key_list = [k.strip() for k in keys.split("+")]
    if len(key_list) == 1:
        pyautogui.press(key_list[0])
    else:
        pyautogui.hotkey(*key_list)
    return f"已按键: {keys}"


@mcp.tool()
def keyboard_hold_and_click(hold_key: str, click_x: int, click_y: int) -> str:
    """按住某键的同时点击坐标（如 shift+click 多选）。hold_key 例如: shift / ctrl / alt。"""
    with pyautogui.hold(hold_key):
        pyautogui.click(click_x, click_y)
    return f"按住 {hold_key} 点击 ({click_x}, {click_y})"


@mcp.tool()
def get_mouse_position() -> dict:
    """返回当前鼠标坐标，用于确认位置或调试。"""
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


@mcp.tool()
def list_windows() -> list:
    """列出所有可见窗口的标题，用于确认哪些程序正在运行。"""
    import win32gui

    windows = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append(title)

    win32gui.EnumWindows(callback, None)
    return windows


@mcp.tool()
def focus_window(title_keyword: str) -> str:
    """将包含 title_keyword 的窗口切换到前台并获取焦点。"""
    import win32gui

    target = None

    def callback(hwnd, _):
        nonlocal target
        if win32gui.IsWindowVisible(hwnd) and title_keyword.lower() in win32gui.GetWindowText(hwnd).lower():
            target = hwnd

    win32gui.EnumWindows(callback, None)
    if target is None:
        return f"未找到包含 '{title_keyword}' 的窗口"

    win32gui.ShowWindow(target, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(target)
    time.sleep(0.3)
    return f"已切换到窗口: {win32gui.GetWindowText(target)}"


@mcp.tool()
def run_program(command: str) -> str:
    """启动一个程序或执行 shell 命令（异步，不等待结束）。例如: notepad.exe / calc.exe。"""
    import subprocess
    subprocess.Popen(command, shell=True)
    time.sleep(0.5)
    return f"已启动: {command}"


@mcp.tool()
def wait(seconds: float) -> str:
    """等待指定秒数，用于等待程序加载或动画完成。"""
    time.sleep(seconds)
    return f"已等待 {seconds} 秒"


if __name__ == "__main__":
    mcp.run(transport="stdio")
