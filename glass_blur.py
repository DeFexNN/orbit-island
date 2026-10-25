"""glass_blur.py — справжній DWM-блюр підкладки, тільки ctypes."""
import ctypes
from ctypes import wintypes

WCA_ACCENT_POLICY = 19

ACCENT_DISABLED = 0
ACCENT_ENABLE_GRADIENT = 1
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
ACCENT_ENABLE_HOSTBACKDROP = 5
ACCENT_INVALID_STATE = 6

DWM_BB_ENABLE = 0x1
DWM_BB_BLURREGION = 0x2
DWM_BB_TRANSITIONONMAXIMIZED = 0x4

# Win11 системний бекдроп (офіційний шлях, працює з Qt layered-вікнами)
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2      # Mica
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic (наш вибір)
DWMSBT_TABBEDWINDOW = 4


class DWM_BLURBEHIND(ctypes.Structure):
    _fields_ = [("dwFlags", wintypes.DWORD),
                ("fEnable", wintypes.BOOL),
                ("hRgnBlur", wintypes.HRGN),
                ("fTransitionOnMaximized", wintypes.BOOL)]


class ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("nAccentState", ctypes.c_int),
                ("nFlags", ctypes.c_int),
                ("nColor", ctypes.c_uint),
                ("nAnimationId", ctypes.c_int)]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [("Attrib", ctypes.c_int),
                ("pvData", ctypes.c_void_p),
                ("cbData", ctypes.c_size_t)]


_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi


def is_composition_enabled() -> bool:
    """Чи взагалі живий DWM-композитор. False = fallback."""
    try:
        enabled = wintypes.BOOL()
        if _dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled)) == 0:
            return bool(enabled)
    except Exception:
        pass
    return False


def enable_acrylic(hwnd: int, tint_rgb=(0, 0, 0), alpha: int = 0x99) -> bool:
    """Акрил-блюр для топ-вікна. alpha: 0x40 прозоро .. 0xCC темно."""
    try:
        r, g, b = tint_rgb
        color = (int(alpha) << 24) | (int(b) << 16) | (int(g) << 8) | int(r)
        policy = ACCENTPOLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 2, color, 0)
        data = WINDOWCOMPOSITIONATTRIBDATA(
            WCA_ACCENT_POLICY, ctypes.addressof(policy), ctypes.sizeof(policy))
        _user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


def enable_blur(hwnd: int) -> bool:
    """Класичний BlurBehind без тінту (запасний варіант)."""
    try:
        policy = ACCENTPOLICY(ACCENT_ENABLE_BLURBEHIND, 2, 0, 0)
        data = WINDOWCOMPOSITIONATTRIBDATA(
            WCA_ACCENT_POLICY, ctypes.addressof(policy), ctypes.sizeof(policy))
        _user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


def enable_dwm_blur(hwnd: int) -> bool:
    """Найстаріший шлях (dwmapi)."""
    try:
        bb = DWM_BLURBEHIND(DWM_BB_ENABLE, True, None, False)
        return _dwmapi.DwmEnableBlurBehindWindow(hwnd, ctypes.byref(bb)) == 0
    except Exception:
        return False


def set_system_backdrop(hwnd: int, kind: int = DWMSBT_TRANSIENTWINDOW) -> bool:
    """Офіційний Win11-бекдроп. Єдиний що працює з Qt layered-вікнами."""
    try:
        v = ctypes.c_int(kind)
        return _dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(v), ctypes.sizeof(v)) == 0
    except Exception:
        return False


def enable_glass(hwnd: int) -> str:
    """Вмикає скло першим робочим методом. Повертає ім'я методу або ''."""
    try:
        if set_system_backdrop(hwnd, DWMSBT_TRANSIENTWINDOW):
            return "system-acrylic"
    except Exception:
        pass
    try:
        if enable_acrylic(hwnd, (0, 0, 0), 0x40):
            return "accent"
    except Exception:
        pass
    try:
        if enable_dwm_blur(hwnd):
            return "dwm-blur"
    except Exception:
        pass
    return ""


def disable_blur(hwnd: int) -> bool:
    """Вимкнути будь-який блюр."""
    ok = True
    try:
        policy = ACCENTPOLICY(ACCENT_DISABLED, 0, 0, 0)
        data = WINDOWCOMPOSITIONATTRIBDATA(
            WCA_ACCENT_POLICY, ctypes.addressof(policy), ctypes.sizeof(policy))
        _user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        ok = False
    try:
        bb = DWM_BLURBEHIND(DWM_BB_ENABLE, False, None, False)
        if _dwmapi.DwmEnableBlurBehindWindow(hwnd, ctypes.byref(bb)) != 0:
            ok = False
    except Exception:
        ok = False
    return ok
