#!/usr/bin/env python3
"""
Alita AI Assistant — 100% Borderless Crystal Orb Desktop Overlay Launcher
========================================================================
1. Waits until both Alita Backend (http://127.0.0.1:8000/health) and
   Frontend (http://localhost:5173) are fully booted (HTTP 200).
2. Spawns an ultra-clean 100% borderless, transparent, topmost window
   hosting ONLY the 3D Möbius Crystal Orb entity.
3. Zero window titlebar, zero minimize/maximize/close buttons, zero boundary box.
4. Auto-activates Alita in full listening mode from the very beginning.
"""

import sys
import time
import urllib.request
import ctypes
import os
import threading

OVERLAY_URL = "http://localhost:5173/?mode=overlay"
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
FRONTEND_HEALTH_URL = "http://localhost:5173"
WINDOW_SIZE = 380


def wait_for_services(max_retries: int = 120, delay_sec: float = 0.5) -> bool:
    """Polls backend and frontend until both respond with HTTP 200."""
    print("[Alita Launcher] Synchronizing services...")
    be_ready = False
    fe_ready = False

    for i in range(max_retries):
        # Check backend
        if not be_ready:
            try:
                req = urllib.request.Request(BACKEND_HEALTH_URL, headers={"User-Agent": "MJOverlay/1.0"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        be_ready = True
                        print("[Alita Launcher] Backend health verified: OK (HTTP 200)")
            except Exception:
                pass

        # Check frontend
        if not fe_ready:
            try:
                req = urllib.request.Request(FRONTEND_HEALTH_URL, headers={"User-Agent": "MJOverlay/1.0"})
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        fe_ready = True
                        print("[Alita Launcher] Frontend dev server verified: OK (HTTP 200)")
            except Exception:
                pass

        if be_ready and fe_ready:
            print("[Alita Launcher] All core services operational! Deploying crystal overlay...")
            return True

        time.sleep(delay_sec)

    print(f"[Alita Launcher] Timeout waiting for services (Backend: {be_ready}, Frontend: {fe_ready})")
    return be_ready and fe_ready


def get_screen_position(width: int = WINDOW_SIZE, height: int = WINDOW_SIZE):
    """Calculates bottom-right desktop placement above taskbar."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        # Position at bottom right (with 24px padding from taskbar/edge)
        pos_x = max(20, screen_w - width - 24)
        pos_y = max(20, screen_h - height - 64)
        return pos_x, pos_y
    except Exception:
        return 1200, 500


def toggle_overlay(target_hwnd: int, pos_x: int, pos_y: int):
    """Toggles Alita overlay visibility and focus upon hotkey press."""
    import win32gui
    import win32con
    import json

    try:
        is_visible = win32gui.IsWindowVisible(target_hwnd)
        fg_hwnd = win32gui.GetForegroundWindow()

        # If already visible and active in foreground -> dismiss/hide
        if is_visible and fg_hwnd == target_hwnd:
            win32gui.ShowWindow(target_hwnd, win32con.SW_HIDE)
            print("[Alita Hotkey] Overlay dismissed (hidden).")
            return

        # Summoning: Capture active window context before shifting focus
        if fg_hwnd and fg_hwnd != target_hwnd:
            try:
                fg_title = win32gui.GetWindowText(fg_hwnd).strip()
                if fg_title and fg_title != "Program Manager":
                    print(f"[Alita Hotkey] Summoned! Captured active context: '{fg_title}'")
                    lower = fg_title.lower()
                    if any(term in lower for term in ("code", "py", "js", "ts", "html", "css", "project")):
                        chips = ["Explain Active Code", "Debug Traceback", "Run Test Suite"]
                    elif any(term in lower for term in ("chrome", "edge", "firefox", "brave")):
                        chips = ["Summarize Page", "Extract Key Points", "Read Article"]
                    elif any(term in lower for term in ("powershell", "cmd", "terminal", "bash", "wsl")):
                        chips = ["Explain Command", "Fix Exit Code", "Generate Script"]
                    else:
                        chips = ["Scan Screen UI", "What's on my screen?", "Take Screenshot"]

                    ctx_dir = os.path.join(os.path.dirname(__file__), "data")
                    os.makedirs(ctx_dir, exist_ok=True)
                    with open(os.path.join(ctx_dir, "active_context.json"), "w", encoding="utf-8") as f:
                        json.dump({
                            "title": fg_title,
                            "hwnd": fg_hwnd,
                            "timestamp": time.time(),
                            "chips": chips,
                        }, f)
            except Exception as e:
                print(f"[Alita Hotkey] Context capture note: {e}")

        # Show, restore, and set topmost
        win32gui.ShowWindow(target_hwnd, win32con.SW_SHOW)
        win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(
            target_hwnd,
            win32con.HWND_TOPMOST,
            pos_x,
            pos_y,
            WINDOW_SIZE,
            WINDOW_SIZE,
            win32con.SWP_SHOWWINDOW
        )

        # Force foreground attachment to bypass Windows focus-stealing prevention
        try:
            user32 = ctypes.windll.user32
            cur_fg = user32.GetForegroundWindow()
            cur_thread = user32.GetWindowThreadProcessId(cur_fg, None)
            target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)
            user32.AttachThreadInput(cur_thread, target_thread, True)
            user32.SetForegroundWindow(target_hwnd)
            user32.AttachThreadInput(cur_thread, target_thread, False)
        except Exception:
            try:
                win32gui.SetForegroundWindow(target_hwnd)
            except Exception:
                pass

        print("[Alita Hotkey] Alita Crystal Orb summoned to foreground.")

    except Exception as exc:
        print(f"[Alita Hotkey] Toggle error: {exc}")


# ── Win32 System Tray Resident Daemon ──────────────────────────────────────────
WM_TRAY_ICON = 0x0400 + 20  # WM_USER + 20


class AlitaSystemTray:
    """Pure Win32 System Tray notification icon daemon with native popup menu."""

    def __init__(self, toggle_fn, exit_fn):
        self.toggle_fn = toggle_fn
        self.exit_fn = exit_fn
        self.hwnd = None
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_tray_loop, daemon=True, name="alita-tray-daemon")
        self._thread.start()
        print("[Alita Tray] System Tray resident daemon active in notification area.")

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        import win32gui
        import win32con

        if msg == WM_TRAY_ICON:
            if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
                self.toggle_fn()
            elif lparam == win32con.WM_RBUTTONUP:
                self._show_tray_menu()
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_tray_menu(self):
        import win32gui
        import win32con

        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, 101, "🔮 Summon / Hide MJ (Alt+A)")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 102, "⚙️ Open Web Dashboard")
        win32gui.AppendMenu(menu, win32con.MF_STRING, 103, "❌ Exit MJ")

        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self.hwnd)
        cmd = win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY,
            pos[0],
            pos[1],
            0,
            self.hwnd,
            None,
        )
        win32gui.DestroyMenu(menu)

        if cmd == 101:
            self.toggle_fn()
        elif cmd == 102:
            import webbrowser
            webbrowser.open("http://localhost:5173")
        elif cmd == 103:
            self.remove()
            self.exit_fn()

    def _run_tray_loop(self):
        import win32gui
        import win32con

        try:
            wc = win32gui.WNDCLASS()
            wc.hInstance = win32gui.GetModuleHandle(None)
            wc.lpszClassName = "AlitaTrayWindow"
            wc.lpfnWndProc = self._wnd_proc
            try:
                win32gui.RegisterClass(wc)
            except Exception:
                pass

            self.hwnd = win32gui.CreateWindow(
                wc.lpszClassName,
                "Alita Tray",
                0, 0, 0, 0, 0,
                win32con.HWND_MESSAGE,
                0,
                wc.hInstance,
                None,
            )

            hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            nid = (
                self.hwnd,
                1,
                win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP,
                WM_TRAY_ICON,
                hicon,
                "MJ AI Assistant (Alt+A)",
            )
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)

            while self._running:
                win32gui.PumpWaitingMessages()
                time.sleep(0.05)
        except Exception as exc:
            print(f"[Alita Tray] Error in tray loop: {exc}")

    def remove(self):
        self._running = False
        if self.hwnd:
            try:
                import win32gui
                nid = (self.hwnd, 1)
                win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, nid)
            except Exception:
                pass


def run_hotkey_message_loop(target_hwnd: int, pos_x: int, pos_y: int, proc=None):
    """Registers global summon hotkey (Alt+A / Ctrl+Shift+A) and handles event loop."""
    user32 = ctypes.windll.user32
    from ctypes import wintypes

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_NOREPEAT = 0x4000
    WM_HOTKEY = 0x0312
    HOTKEY_ID = 999
    VK_A = ord('A')

    # Primary: Alt+A, Fallback: Ctrl+Shift+A
    registered = user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT | MOD_NOREPEAT, VK_A)
    hotkey_name = "Alt+A"
    if not registered:
        registered = user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_A)
        hotkey_name = "Ctrl+Shift+A"

    if registered:
        print(f"[Alita Hotkey] Global summon hotkey activated: [{hotkey_name}]")
        print("[Alita Hotkey] Press hotkey anywhere in Windows to summon/dismiss Alita.")
    else:
        print("[Alita Hotkey] Note: Global hotkey could not be bound (hotkey in use).")

    # Start System Tray daemon alongside hotkey
    tray = AlitaSystemTray(
        toggle_fn=lambda: toggle_overlay(target_hwnd, pos_x, pos_y),
        exit_fn=lambda: os._exit(0),
    )
    tray.start()

    msg = wintypes.MSG()
    try:
        while True:
            if proc is not None and proc.poll() is not None:
                print("[Alita Launcher] Overlay host process terminated. Exiting.")
                break

            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE = 1
                if msg.message == WM_HOTKEY:
                    toggle_overlay(target_hwnd, pos_x, pos_y)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        tray.remove()
        if registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            print("[Alita Hotkey] Global hotkey cleaned up.")


def launch_pure_borderless_overlay():
    """Launches the 100% borderless, transparent, topmost crystal orb overlay."""
    pos_x, pos_y = get_screen_position(WINDOW_SIZE, WINDOW_SIZE)

    try:
        import webview

        print(f"[Alita Launcher] Opening pywebview borderless overlay at ({pos_x}, {pos_y})...")
        window = webview.create_window(
            title="MJ Crystal Core",
            url=OVERLAY_URL,
            width=WINDOW_SIZE,
            height=WINDOW_SIZE,
            x=pos_x,
            y=pos_y,
            frameless=True,          # 100% borderless: NO titlebar, NO close/min/max buttons
            easy_drag=True,          # Drag anywhere on the orb
            on_top=True,             # Always floats gracefully above all desktop windows
            transparent=True,        # 100% transparent background: zero boundary box
            background_color="#00000000",
        )

        # In pywebview mode, run hotkey and tray in background thread
        def _bg_hotkey_tray():
            time.sleep(1.0)
            try:
                import win32gui
                hwnd = win32gui.FindWindow(None, "MJ Crystal Core")
                if hwnd:
                    run_hotkey_message_loop(hwnd, pos_x, pos_y)
            except Exception as e:
                print(f"[Alita Launcher] Background daemon note: {e}")

        daemon_th = threading.Thread(target=_bg_hotkey_tray, daemon=True)
        daemon_th.start()

        webview.start(debug=False)
        return True

    except Exception as e:
        print(f"[Alita Launcher] pywebview notice: {e}. Utilizing Win32 frameless fallback...")
        return launch_win32_fallback(pos_x, pos_y)


def launch_win32_fallback(pos_x: int, pos_y: int):
    """Fallback frameless window stripper using Win32 API with global hotkey support."""
    import subprocess
    import win32gui
    import win32con

    cmd = [
        "msedge.exe",
        f"--app={OVERLAY_URL}",
        f"--window-size={WINDOW_SIZE},{WINDOW_SIZE}",
        f"--window-position={pos_x},{pos_y}",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-features=TranslateUI",
        "--disable-extensions",
    ]
    proc = subprocess.Popen(cmd)

    # Find window and strip borders
    target_hwnd = None
    for _ in range(40):
        time.sleep(0.2)

        def enum_cb(hwnd, _):
            nonlocal target_hwnd
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "MJ" in title or "Alita" in title or "localhost:5173" in title:
                    target_hwnd = hwnd

        win32gui.EnumWindows(enum_cb, None)
        if target_hwnd:
            style = win32gui.GetWindowLong(target_hwnd, win32con.GWL_STYLE)
            style &= ~(
                win32con.WS_CAPTION
                | win32con.WS_THICKFRAME
                | win32con.WS_MINIMIZEBOX
                | win32con.WS_MAXIMIZEBOX
                | win32con.WS_SYSMENU
            )
            style |= win32con.WS_POPUP
            win32gui.SetWindowLong(target_hwnd, win32con.GWL_STYLE, style)

            ex_style = win32gui.GetWindowLong(target_hwnd, win32con.GWL_EXSTYLE)
            ex_style |= win32con.WS_EX_LAYERED
            win32gui.SetWindowLong(target_hwnd, win32con.GWL_EXSTYLE, ex_style)

            win32gui.SetWindowPos(
                target_hwnd,
                win32con.HWND_TOPMOST,
                pos_x,
                pos_y,
                WINDOW_SIZE,
                WINDOW_SIZE,
                win32con.SWP_FRAMECHANGED | win32con.SWP_SHOWWINDOW,
            )
            print("[Alita Launcher] Win32 borderless styles applied successfully.")
            # Enter hotkey daemon loop
            run_hotkey_message_loop(target_hwnd, pos_x, pos_y, proc=proc)
            return True

    return False


if __name__ == "__main__":
    ready = wait_for_services()
    if not ready:
        print("[Alita Launcher] Warning: proceeding with launch after timeout...")
    launch_pure_borderless_overlay()

