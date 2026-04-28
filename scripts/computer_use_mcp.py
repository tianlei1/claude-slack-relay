import base64
import io
import os
import subprocess
import time

import pyautogui
import win32api
import win32con
from mcp.server.fastmcp import FastMCP
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN_DIR = os.path.join(BASE_DIR, "screen")

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.3

mcp = FastMCP("computer-use")

# ── Browser (Selenium) ────────────────────────────────────────────────────────

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
CHROME_DEBUG_PORT = 9222


def _get_driver():
    """Connect to existing Chrome debug session, or start Chrome with debug port."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")
    options.add_argument("--no-sandbox")
    try:
        driver = webdriver.Chrome(options=options)
        return driver
    except Exception:
        # Chrome not running with debug port — start it
        for path in CHROME_PATHS:
            if os.path.exists(path):
                subprocess.Popen([path, f"--remote-debugging-port={CHROME_DEBUG_PORT}"])
                time.sleep(2.5)
                break
        else:
            raise RuntimeError("Chrome not found. Install Chrome or start it manually with --remote-debugging-port=9222")
        return webdriver.Chrome(options=options)


def _by(by: str):
    from selenium.webdriver.common.by import By
    return {
        "css": By.CSS_SELECTOR,
        "xpath": By.XPATH,
        "id": By.ID,
        "name": By.NAME,
        "text": By.XPATH,  # handled specially below
        "tag": By.TAG_NAME,
    }.get(by.lower(), By.CSS_SELECTOR)


def _selector(selector: str, by: str) -> str:
    """For 'text' mode, wrap selector in an XPath contains expression."""
    if by.lower() == "text":
        return f"//*[contains(normalize-space(.), '{selector}')]"
    return selector


@mcp.tool()
def browser_open(url: str) -> str:
    """打开或导航到指定 URL。如果 Chrome 未以调试端口启动则自动启动。
    返回页面标题。"""
    driver = _get_driver()
    driver.get(url)
    time.sleep(1)
    return f"已导航到: {driver.title}"


@mcp.tool()
def browser_click(selector: str, by: str = "css") -> str:
    """点击页面元素。
    by: css (默认) / xpath / id / name / text (按可见文字模糊匹配)
    示例: browser_click('button[type=submit]') 或 browser_click('Add an OAuth Scope', by='text')"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()
    sel = _selector(selector, by)
    element = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((_by(by), sel))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    time.sleep(0.3)
    element.click()
    return f"已点击: {selector}"


@mcp.tool()
def browser_type(selector: str, text: str, by: str = "css", clear: bool = True) -> str:
    """在输入框中输入文字。
    clear=True 先清空再输入。"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()
    sel = _selector(selector, by)
    element = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((_by(by), sel))
    )
    if clear:
        element.clear()
    element.send_keys(text)
    return f"已输入文字到 '{selector}'"


@mcp.tool()
def browser_get_text(selector: str, by: str = "css") -> str:
    """获取元素的文字内容。"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()
    sel = _selector(selector, by)
    element = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((_by(by), sel))
    )
    return element.text


@mcp.tool()
def browser_find_elements(selector: str, by: str = "css") -> list:
    """查找所有匹配元素，返回 [{text, tag, id, class}] 列表。"""
    driver = _get_driver()
    sel = _selector(selector, by)
    elements = driver.find_elements(_by(by), sel)
    return [
        {
            "text": e.text[:100],
            "tag": e.tag_name,
            "id": e.get_attribute("id") or "",
            "class": (e.get_attribute("class") or "")[:80],
        }
        for e in elements
    ]


@mcp.tool()
def browser_run_js(script: str) -> str:
    """在浏览器中执行 JavaScript，返回结果。
    示例: browser_run_js('return document.title')"""
    driver = _get_driver()
    result = driver.execute_script(script)
    return str(result)


@mcp.tool()
def browser_get_url() -> str:
    """返回当前页面的 URL 和标题。"""
    driver = _get_driver()
    return f"URL: {driver.current_url}\nTitle: {driver.title}"


@mcp.tool()
def browser_wait_for(selector: str, by: str = "css", timeout: int = 15) -> str:
    """等待元素出现在页面上，超时返回错误。"""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()
    sel = _selector(selector, by)
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((_by(by), sel))
    )
    return f"元素已出现: {selector}"


@mcp.tool()
def browser_close() -> str:
    """关闭当前浏览器标签页（不退出 Chrome 进程）。"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_DEBUG_PORT}")
    try:
        driver = webdriver.Chrome(options=options)
        driver.close()
        return "标签页已关闭"
    except Exception as e:
        return f"关闭失败: {e}"


# ── Screenshot ────────────────────────────────────────────────────────────────

@mcp.tool()
def screenshot(name: str, x: int = None, y: int = None, width: int = None, height: int = None) -> dict:
    """截取屏幕截图，保存到 screen/ 目录。
    name: 文件名（不含扩展名）。不传坐标则截全屏，否则截指定区域。
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


# ── Mouse ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def mouse_move(x: int, y: int, duration: float = 0.3) -> str:
    """将鼠标移动到屏幕坐标 (x, y)。"""
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
def get_mouse_position() -> dict:
    """返回当前鼠标坐标。"""
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


# ── Keyboard ──────────────────────────────────────────────────────────────────

@mcp.tool()
def keyboard_type(text: str, interval: float = 0.05) -> str:
    """输入文本字符串（支持中文及特殊字符，通过剪贴板粘贴）。"""
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
    """按住某键的同时点击坐标（如 shift+click 多选）。"""
    with pyautogui.hold(hold_key):
        pyautogui.click(click_x, click_y)
    return f"按住 {hold_key} 点击 ({click_x}, {click_y})"


# ── Windows ───────────────────────────────────────────────────────────────────

@mcp.tool()
def list_windows() -> list:
    """列出所有可见窗口的标题。"""
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
    """将包含 title_keyword 的窗口切换到前台。"""
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
    """启动一个程序或执行 shell 命令（异步，不等待结束）。"""
    subprocess.Popen(command, shell=True)
    time.sleep(0.5)
    return f"已启动: {command}"


@mcp.tool()
def wait(seconds: float) -> str:
    """等待指定秒数。"""
    time.sleep(seconds)
    return f"已等待 {seconds} 秒"


if __name__ == "__main__":
    mcp.run(transport="stdio")
