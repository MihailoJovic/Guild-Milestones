"""The little GM icon by the clock (Windows system tray). Built-in Python only (ctypes), no extra installs.
Left-click opens the window; right-click shows a small menu. It can also pop up a Windows notification."""
import ctypes, sys, threading
from ctypes import wintypes

WM_USER, WM_DESTROY, WM_CLOSE, WM_COMMAND = 0x0400, 0x0002, 0x0010, 0x0111
WM_LBUTTONUP, WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x0202, 0x0205, 0x0203
CALLBACK = WM_USER + 20
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO, NIIF_WARNING = 0x1, 0x2
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
TPM_RETURNCMD, TPM_NONOTIFY, TPM_RIGHTBUTTON = 0x100, 0x80, 0x2
MF_STRING, MF_SEPARATOR = 0x0, 0x800

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


def supported():
    return sys.platform == "win32"


class Tray:
    """Runs its own little Windows message loop on a background thread.
    on_open and on_quit are called from that thread, so they should only queue work for the window."""
    MENU_OPEN, MENU_QUIT = 1, 2

    def __init__(self, icon_path, tip, on_open, on_quit):
        self.icon_path, self.tip, self.on_open, self.on_quit = str(icon_path), tip, on_open, on_quit
        self.hwnd, self.nid, self.ready = None, None, threading.Event()
        self._proc = WNDPROC(self._wndproc)                    # keep a reference so it isn't garbage collected
        self.thread = threading.Thread(target=self._run, name="tray", daemon=True)

    def start(self):
        self.thread.start()
        self.ready.wait(3)
        return self.hwnd is not None

    # ---------------------------------------------------------------- windows plumbing
    def _run(self):
        try:
            u, k, s = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.shell32
            u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            u.DefWindowProcW.restype = LRESULT
            u.CreateWindowExW.restype = wintypes.HWND
            u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                          ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                          wintypes.HINSTANCE, wintypes.LPVOID]
            u.LoadImageW.restype = wintypes.HANDLE
            u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            u.CreatePopupMenu.restype = wintypes.HMENU
            u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
            u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         wintypes.HWND, wintypes.LPVOID]
            u.DestroyMenu.argtypes = [wintypes.HMENU]
            u.SetForegroundWindow.argtypes = [wintypes.HWND]
            u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            s.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
            k.GetModuleHandleW.restype = wintypes.HMODULE

            hinst = k.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._proc
            wc.hInstance = hinst
            wc.lpszClassName = "GuildMilestonesTray"
            u.RegisterClassW(ctypes.byref(wc))
            self.hwnd = u.CreateWindowExW(0, wc.lpszClassName, "Guild Milestones", 0, 0, 0, 0, 0, None, None, hinst, None)
            icon = u.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd, nid.uID = self.hwnd, 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage, nid.hIcon = CALLBACK, icon
            nid.szTip = self.tip[:127]
            s.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
            self.nid = nid
        except Exception:
            self.hwnd = None
            self.ready.set()
            return
        self.ready.set()
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u.TranslateMessage(ctypes.byref(msg))
            u.DispatchMessageW(ctypes.byref(msg))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        u = ctypes.windll.user32
        if msg == CALLBACK:
            if lparam in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self.on_open()
            elif lparam == WM_RBUTTONUP:
                self._menu(hwnd)
            return 0
        if msg == WM_CLOSE:
            u.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            if self.nid:
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
                self.nid = None
            u.PostQuitMessage(0)
            return 0
        return u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self, hwnd):
        u = ctypes.windll.user32
        menu = u.CreatePopupMenu()
        u.AppendMenuW(menu, MF_STRING, self.MENU_OPEN, "Open Guild Milestones")
        u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u.AppendMenuW(menu, MF_STRING, self.MENU_QUIT, "Quit")
        pt = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(pt))
        u.SetForegroundWindow(hwnd)
        choice = u.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)
        u.DestroyMenu(menu)
        if choice == self.MENU_OPEN:
            self.on_open()
        elif choice == self.MENU_QUIT:
            self.on_quit()

    # ---------------------------------------------------------------- what the app calls
    def set_tip(self, text):
        if self.nid and self.hwnd:
            self.nid.uFlags = NIF_TIP
            self.nid.szTip = str(text)[:127]
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def notify(self, title, text, warning=False):
        """A Windows notification from the tray icon."""
        if self.nid and self.hwnd:
            self.nid.uFlags = NIF_INFO
            self.nid.szInfoTitle = str(title)[:63]
            self.nid.szInfo = str(text)[:255]
            self.nid.dwInfoFlags = NIIF_WARNING if warning else NIIF_INFO
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self.nid))

    def stop(self):
        if self.hwnd:
            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self.thread.join(2)
            self.hwnd = None
