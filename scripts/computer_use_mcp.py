import base64
import io
import os
import subprocess
import time
import winreg

import pyautogui
import win32con
import win32gui
from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN_DIR = os.path.join(BASE_DIR, "screen")

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# Logical screen dimensions (what pyautogui.click/moveTo use as coordinate space).
# Screenshots may be captured at higher physical resolution due to DPI scaling,
# so we resize them back to these dimensions so image coordinates == click coordinates.
_LOGICAL_W, _LOGICAL_H = pyautogui.size()
os.makedirs(SCREEN_DIR, exist_ok=True)

try:
    _GRID_FONT = ImageFont.truetype("arial.ttf", 11)
except OSError:
    _GRID_FONT = ImageFont.load_default()

_user32 = None
_kernel32 = None


def _win32_dlls():
    global _user32, _kernel32
    if _user32 is None:
        import ctypes
        _user32 = ctypes.windll.user32
        _kernel32 = ctypes.windll.kernel32
    return _user32, _kernel32


def _ensure_png(name: str) -> str:
    return name if name.endswith(".png") else f"{name}.png"


def _save_png(img: Image.Image, file_path: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    with open(file_path, "wb") as f:
        f.write(png_bytes)
    return png_bytes


def _draw_grid_line(draw: ImageDraw.ImageDraw, img_w: int, img_h: int,
                    pos: int, label: str | None, vertical: bool) -> None:
    color = (220, 80, 80) if label else (220, 180, 180)
    if vertical:
        draw.line([(pos, 0), (pos, img_h)], fill=color, width=1)
        if label:
            box_w = len(label) * 7 + 2
            draw.rectangle([(pos + 1, 0), (pos + box_w, 13)], fill=(255, 255, 255))
            draw.text((pos + 2, 1), label, fill=(180, 0, 0), font=_GRID_FONT)
    else:
        draw.line([(0, pos), (img_w, pos)], fill=color, width=1)
        if label:
            box_w = len(label) * 7 + 2
            draw.rectangle([(0, pos + 1), (box_w, pos + 13)], fill=(255, 255, 255))
            draw.text((1, pos + 2), label, fill=(180, 0, 0), font=_GRID_FONT)


mcp = FastMCP("computer-use")

# ── Browser (Selenium) ────────────────────────────────────────────────────────

EDGE_DEBUG_PORT = 9222
EDGE_PROFILE_DIR = r"C:\temp\selenium_edge"
_EDGE_FALLBACK_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _find_edge_exe():
    reg_keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
    ]
    for key_path in reg_keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
                path, _ = winreg.QueryValueEx(k, "")
                if os.path.exists(path):
                    return path
        except OSError:
            pass
    for path in _EDGE_FALLBACK_PATHS:
        if os.path.exists(path):
            return path
    return None


def _get_driver():
    """Connect to existing Edge debug session, or start a new Edge with debug port.
    Uses a separate user-data-dir so it doesn't conflict with an already-running Edge."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    attach_options = Options()
    attach_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{EDGE_DEBUG_PORT}")
    try:
        driver = webdriver.Edge(options=attach_options)
        return driver
    except Exception:
        pass

    # Start a fresh Edge with debug port (separate profile — won't affect existing Edge)
    edge_exe = _find_edge_exe()
    if not edge_exe:
        raise RuntimeError("Edge not found. Install Microsoft Edge.")
    subprocess.Popen([
        edge_exe,
        f"--remote-debugging-port={EDGE_DEBUG_PORT}",
        f"--user-data-dir={EDGE_PROFILE_DIR}",
    ])
    time.sleep(2.5)
    return webdriver.Edge(options=attach_options)


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
        if "'" not in selector:
            xpath_val = f"'{selector}'"
        elif '"' not in selector:
            xpath_val = f'"{selector}"'
        else:
            parts = selector.split("'")
            concat_args = ", \"'\", ".join(f"'{p}'" for p in parts)
            xpath_val = f"concat({concat_args})"
        return f"//*[contains(normalize-space(.), {xpath_val})]"
    return selector


@mcp.tool()
def browser_open(url: str) -> str:
    """Open or navigate to a URL. Starts Edge with a debug port if not already running.
    Returns the page title."""
    driver = _get_driver()
    driver.get(url)
    time.sleep(1)
    return f"Navigated to: {driver.title}"


@mcp.tool()
def browser_click(selector: str, by: str = "css") -> str:
    """Click a page element.
    by: css (default) / xpath / id / name / text (fuzzy match on visible text)
    Example: browser_click('button[type=submit]') or browser_click('Add an OAuth Scope', by='text')"""
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
    return f"Clicked: {selector}"


@mcp.tool()
def browser_type(selector: str, text: str, by: str = "css", clear: bool = True) -> str:
    """Type text into an input field. clear=True clears the field first."""
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
    return f"Typed into '{selector}'"


@mcp.tool()
def browser_get_text(selector: str, by: str = "css") -> str:
    """Get the text content of an element."""
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
    """Find all matching elements and return [{text, tag, id, class}] list."""
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
    """Execute JavaScript in the browser and return the result.
    Example: browser_run_js('return document.title')"""
    driver = _get_driver()
    result = driver.execute_script(script)
    return str(result)


@mcp.tool()
def browser_get_url() -> str:
    """Return the current page URL and title."""
    driver = _get_driver()
    return f"URL: {driver.current_url}\nTitle: {driver.title}"


@mcp.tool()
def browser_wait_for(selector: str, by: str = "css", timeout: int = 15) -> str:
    """Wait for an element to appear on the page; raises on timeout."""
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    driver = _get_driver()
    sel = _selector(selector, by)
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((_by(by), sel))
    )
    return f"Element appeared: {selector}"


@mcp.tool()
def browser_close() -> str:
    """Close the current browser tab (does not quit the Edge process)."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{EDGE_DEBUG_PORT}")
    try:
        driver = webdriver.Edge(options=options)
        driver.close()
        return "Tab closed"
    except Exception as e:
        return f"Close failed: {e}"


# ── Template Matching ─────────────────────────────────────────────────────────

TEMPLATE_DIR = os.path.join(BASE_DIR, "screen", "templates")


@mcp.tool()
def capture_template(name: str, x: int, y: int, width: int, height: int) -> dict:
    """Capture a screen region and save it as a reusable template image.
    Call this once to record a button or control, then use find_template_on_screen to locate it anytime.
    x, y: top-left corner of the region in screen coordinates.
    width, height: size of the region in pixels.
    Returns the saved template path."""
    img = pyautogui.screenshot(region=(x, y, width, height))
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    path = os.path.join(TEMPLATE_DIR, _ensure_png(name))
    _save_png(img, path)
    return {"saved": path, "size": f"{width}×{height}"}


@mcp.tool()
def find_template_on_screen(name: str, confidence: float = 0.8, click: bool = False,
                             button: str = "left") -> dict:
    """Find a previously captured template image on the current screen using pixel matching.
    Works for any app including legacy and custom-drawn controls — no accessibility API needed.
    name: template name passed to capture_template (with or without .png).
    confidence: match threshold 0.0–1.0; lower = more lenient (default 0.8).
    click: if True, click the center of the found region.
    Returns {found, x, y, elapsed_ms} or {found: False, error}."""
    template_path = os.path.join(TEMPLATE_DIR, _ensure_png(name))
    t0 = time.time()
    try:
        location = pyautogui.locateOnScreen(template_path, confidence=confidence)
    except Exception as e:
        return {"found": False, "error": str(e), "elapsed_ms": int((time.time() - t0) * 1000)}

    elapsed = int((time.time() - t0) * 1000)
    if location is None:
        return {"found": False, "elapsed_ms": elapsed}

    cx, cy = pyautogui.center(location)
    if click:
        pyautogui.click(cx, cy, button=button)
    return {"found": True, "x": cx, "y": cy, "elapsed_ms": elapsed}


@mcp.tool()
def list_templates() -> list:
    """List all saved template images available for find_template_on_screen."""
    try:
        return [f[:-4] for f in os.listdir(TEMPLATE_DIR) if f.endswith(".png")]
    except FileNotFoundError:
        return []


# ── Screenshot ────────────────────────────────────────────────────────────────

def _add_coordinate_grid(img: Image.Image, steps: int = 100) -> Image.Image:
    """Overlay a pixel-coordinate grid with labels showing actual x/y pixel values."""
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)
    w, h = img.size
    for i in range(1, steps):
        xp, yp = w * i // steps, h * i // steps
        labeled = (i % 5 == 0)
        _draw_grid_line(draw, w, h, xp, str(xp) if labeled else None, vertical=True)
        _draw_grid_line(draw, w, h, yp, str(yp) if labeled else None, vertical=False)
    return img


def _take_screenshot(name: str, grid: bool = False) -> dict:
    img = pyautogui.screenshot()
    if img.width != _LOGICAL_W or img.height != _LOGICAL_H:
        img = img.resize((_LOGICAL_W, _LOGICAL_H), Image.LANCZOS)
    if grid:
        img = _add_coordinate_grid(img)
    file_path = os.path.join(SCREEN_DIR, _ensure_png(name))
    png_bytes = _save_png(img, file_path)
    return {
        "image_base64": base64.b64encode(png_bytes).decode(),
        "file_path": file_path,
        "format": "png",
        "screen_width": _LOGICAL_W,
        "screen_height": _LOGICAL_H,
    }


@mcp.tool()
def app_screenshot(title_keyword: str, name: str, launch_cmd: str = None,
                   launch_wait: float = 3.0, grid: bool = False) -> dict:
    """Focus an application window, maximize it, then take a full-screen screenshot.
    Use this whenever you need to screenshot a specific application — it guarantees
    the app is in the foreground before capturing.
    title_keyword: substring of the window title to match.
    name: screenshot filename (without extension).
    launch_cmd: optional shell command to launch the app if the window is not found.
    launch_wait: seconds to wait after launching before retrying the window search.
    grid: if True, overlay a pixel-coordinate grid. Labels show actual x/y pixel values
          that can be passed directly to mouse_click(x, y) — no conversion needed.
    Returns base64 PNG and file path; use [IMAGE:file_path] to send the image to the user."""
    hwnd = _find_window(title_keyword, launch_cmd=launch_cmd, launch_wait=launch_wait)
    if hwnd is None:
        return {"error": f"Window containing '{title_keyword}' not found"}
    _force_foreground(hwnd)
    return _take_screenshot(name, grid=grid)


@mcp.tool()
def screenshot(name: str, grid: bool = False) -> dict:
    """Take a full-screen screenshot of whatever is currently on screen.
    Use app_screenshot() instead if you need to capture a specific application.
    name: filename (without extension).
    grid: if True, overlay a pixel-coordinate grid. Labels show actual x/y pixel values
          that can be passed directly to mouse_click(x, y) — no conversion needed.
    Returns base64 PNG and file path; use [IMAGE:file_path] to send the image to the user."""
    return _take_screenshot(name, grid=grid)


@mcp.tool()
def screenshot_region(name: str, x: int, y: int, width: int, height: int,
                      scale: int = 4) -> dict:
    """Capture a small screen region and scale it up for precise coordinate identification.
    Use this as a two-step workflow to improve click accuracy:
      1. Call app_screenshot(..., grid=True) to get an overview and estimate the target area.
      2. Call screenshot_region(...) on that area — the zoomed image shows exact pixel labels
         so you can pass the correct x/y directly to mouse_click(x, y).
    x, y: top-left corner of the region in absolute screen coordinates.
    width, height: size of the region to capture (pixels).
    scale: how much to enlarge the image (default 4× — a 200×100 region becomes 800×400).
    Grid lines are drawn every 10 pixels; labels show absolute screen coordinates.
    Returns base64 PNG and file path."""
    img = pyautogui.screenshot(region=(x, y, width, height))
    img = img.resize((width * scale, height * scale), Image.NEAREST).convert("RGB")
    draw = ImageDraw.Draw(img)
    sw, sh = img.size

    step_px = 10
    label_every = 50
    for lx in range(0, width + 1, step_px):
        sx = lx * scale
        if sx >= sw:
            break
        label = str(x + lx) if (lx % label_every == 0) and lx > 0 else None
        _draw_grid_line(draw, sw, sh, sx, label, vertical=True)

    for ly in range(0, height + 1, step_px):
        sy = ly * scale
        if sy >= sh:
            break
        label = str(y + ly) if (ly % label_every == 0) and ly > 0 else None
        _draw_grid_line(draw, sw, sh, sy, label, vertical=False)

    file_path = os.path.join(SCREEN_DIR, _ensure_png(name))
    png_bytes = _save_png(img, file_path)
    return {
        "image_base64": base64.b64encode(png_bytes).decode(),
        "file_path": file_path,
        "format": "png",
        "region": {"x": x, "y": y, "width": width, "height": height},
        "scale": scale,
    }


# ── Mouse ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def mouse_move(x: int, y: int, duration: float = 0.3) -> str:
    """Move the mouse to screen coordinates (x, y)."""
    pyautogui.moveTo(x, y, duration=duration)
    return f"Mouse moved to ({x}, {y})"


@mcp.tool()
def mouse_click(x: int, y: int, button: str = "left", clicks: int = 1, interval: float = 0.1) -> str:
    """Click the mouse at screen coordinates (x, y).
    button: left / right / middle. clicks: number of clicks (2 = double-click)."""
    pyautogui.click(x, y, button=button, clicks=clicks, interval=interval)
    return f"{button} click ({x}, {y}) × {clicks}"


@mcp.tool()
def mouse_drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> str:
    """Drag from (start_x, start_y) to (end_x, end_y)."""
    pyautogui.drag(start_x, start_y, end_x - start_x, end_y - start_y, duration=duration, button="left")
    return f"Dragged: ({start_x},{start_y}) → ({end_x},{end_y})"


@mcp.tool()
def mouse_scroll(x: int, y: int, clicks: int) -> str:
    """Scroll the mouse wheel at (x, y). Positive clicks scroll up, negative scroll down."""
    pyautogui.scroll(clicks, x=x, y=y)
    return f"Scrolled {clicks} clicks at ({x}, {y})"


@mcp.tool()
def get_mouse_position() -> dict:
    """Return the current mouse cursor coordinates."""
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


# ── Keyboard ──────────────────────────────────────────────────────────────────

@mcp.tool()
def keyboard_type(text: str) -> str:
    """Type a string (supports Unicode and Chinese characters via clipboard paste)."""
    subprocess.run("clip", input=text.encode("utf-16-le"), check=True)
    pyautogui.hotkey("ctrl", "v")
    return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"


@mcp.tool()
def keyboard_press(keys: str) -> str:
    """Press a key or keyboard shortcut. Use + to combine keys.
    Examples: ctrl+c / alt+F4 / enter / tab / esc"""
    key_list = [k.strip() for k in keys.split("+")]
    if len(key_list) == 1:
        pyautogui.press(key_list[0])
    else:
        pyautogui.hotkey(*key_list)
    return f"Pressed: {keys}"


@mcp.tool()
def keyboard_hold_and_click(hold_key: str, click_x: int, click_y: int) -> str:
    """Hold a key while clicking at (click_x, click_y), e.g. shift+click for multi-select."""
    with pyautogui.hold(hold_key):
        pyautogui.click(click_x, click_y)
    return f"Held {hold_key} and clicked ({click_x}, {click_y})"


# ── Windows ───────────────────────────────────────────────────────────────────

def _force_foreground(hwnd: int) -> None:
    """Maximize and bring hwnd to foreground, bypassing Windows focus-steal prevention.
    AttachThreadInput is more reliable than keybd_event for background processes."""
    user32, kernel32 = _win32_dlls()
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)

    fg_hwnd = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
    our_tid = kernel32.GetCurrentThreadId()
    need_attach = bool(fg_tid and fg_tid != our_tid)

    if need_attach:
        user32.AttachThreadInput(fg_tid, our_tid, True)
    win32gui.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if need_attach:
        user32.AttachThreadInput(fg_tid, our_tid, False)
    time.sleep(0.5)


@mcp.tool()
def list_windows() -> list:
    """List titles of all visible windows."""
    windows = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                windows.append(title)

    win32gui.EnumWindows(callback, None)
    return windows


def _find_window(title_keyword: str, launch_cmd: str = None, launch_wait: float = 3.0) -> int | None:
    result = []

    class _Stop(Exception):
        pass

    def find(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and title_keyword.lower() in win32gui.GetWindowText(hwnd).lower():
            result.append(hwnd)
            raise _Stop()

    try:
        win32gui.EnumWindows(find, None)
    except _Stop:
        pass

    if not result and launch_cmd:
        subprocess.Popen(launch_cmd, shell=True)
        time.sleep(launch_wait)
        try:
            win32gui.EnumWindows(find, None)
        except _Stop:
            pass

    return result[0] if result else None


@mcp.tool()
def focus_window(title_keyword: str, launch_cmd: str = None, launch_wait: float = 3.0) -> str:
    """Bring a window containing title_keyword to the foreground and maximize it.
    If no matching window is found and launch_cmd is provided, the command is executed
    and the tool waits launch_wait seconds before retrying the window search."""
    hwnd = _find_window(title_keyword, launch_cmd=launch_cmd, launch_wait=launch_wait)
    if hwnd is None:
        return f"Window containing '{title_keyword}' not found"
    _force_foreground(hwnd)
    return f"Focused and maximized: {win32gui.GetWindowText(hwnd)}"


@mcp.tool()
def run_program(command: str) -> str:
    """Launch a program or run a shell command asynchronously."""
    subprocess.Popen(command, shell=True)
    time.sleep(0.5)
    return f"Launched: {command}"


@mcp.tool()
def wait(seconds: float) -> str:
    """Wait for the specified number of seconds."""
    time.sleep(seconds)
    return f"Waited {seconds} seconds"


if __name__ == "__main__":
    import sys
    transport = "stdio"
    port = 8000
    host = "127.0.0.1"
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--transport" and i + 1 < len(args):
            transport = args[i + 1]
        elif arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
    if transport == "sse":
        mcp.settings.port = port
        mcp.settings.host = host
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
