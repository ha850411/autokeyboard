# AutoKeyboard script wizard for Windows.
# Tkinter UI + Win32 hotkeys/keyboard input.

from __future__ import annotations

import ctypes
import io
import json
import os
import platform
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from PIL import Image, ImageChops, ImageGrab, ImageStat
except ImportError:
    Image = None
    ImageChops = None
    ImageGrab = None
    ImageStat = None

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


APP_TITLE = "AutoKeyboard 腳本精靈"
APP_NAME = "AutoKeyboard"
CONFIG_FILENAME = "scripts.json"
MONITOR_CONFIG_FILENAME = "recaptcha_monitor.json"
RUNNING_OVERLAY_CONFIG_FILENAME = "running_overlay.json"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(relative_path: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return app_directory() / relative_path


def user_data_directory() -> Path:
    if platform.system() == "Windows":
        fallback = Path.home() / "AppData" / "Local"
        base_directory = Path(os.environ.get("LOCALAPPDATA", str(fallback)))
        return base_directory / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


LEGACY_CONFIG_PATH = app_directory() / CONFIG_FILENAME
CONFIG_PATH = user_data_directory() / CONFIG_FILENAME
MONITOR_CONFIG_PATH = user_data_directory() / MONITOR_CONFIG_FILENAME
RUNNING_OVERLAY_CONFIG_PATH = user_data_directory() / RUNNING_OVERLAY_CONFIG_FILENAME
RECAPTCHA_TEMPLATE_PATH = resource_path("assets/check/recaptcha.jpg")
RECAPTCHA_FULL_TEMPLATE_PATH = resource_path("assets/check/full-recaptcha.png")
RECAPTCHA_SCAN_INTERVAL_SECONDS = 0.5
RECAPTCHA_FEATURE_SCAN_INTERVAL_SECONDS = 0.33
RECAPTCHA_CONFIRM_SECONDS = 1.0
RECAPTCHA_MATCH_DOWNSAMPLE = 0.5
RECAPTCHA_FULL_RES_MAX_PIXELS = 1_000_000
RECAPTCHA_MATCH_THRESHOLD = 22.0
RECAPTCHA_CV_MATCH_THRESHOLD = 0.94
RECAPTCHA_FULL_CV_MATCH_THRESHOLD = 0.90
RECAPTCHA_TINY_CV_MATCH_THRESHOLD = 0.88
RECAPTCHA_SMALL_CV_MATCH_THRESHOLD = 0.9
RECAPTCHA_VERIFY_MEAN_THRESHOLD = 20.0
RECAPTCHA_VERIFY_GOOD_PIXEL_THRESHOLD = 42.0
RECAPTCHA_VERIFY_GOOD_PIXEL_RATIO = 0.88
RECAPTCHA_MATCH_SCALE_MIN = 0.12
RECAPTCHA_MATCH_SCALE_MAX = 2.0
RECAPTCHA_MATCH_SCALE_STEP_RATIO = 1.035
RECAPTCHA_PREFERRED_MATCH_SCALE = 1.0
RECAPTCHA_NOTIFY_INTERVAL_SECONDS = 2.0
RECAPTCHA_MAX_NOTIFICATION_WORKERS = 3
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2


def build_recaptcha_match_scales(
    *,
    min_scale: float = RECAPTCHA_MATCH_SCALE_MIN,
    max_scale: float = RECAPTCHA_MATCH_SCALE_MAX,
    step_ratio: float = RECAPTCHA_MATCH_SCALE_STEP_RATIO,
) -> tuple[float, ...]:
    if min_scale <= 0 or max_scale < min_scale or step_ratio <= 1:
        return ()

    scales: list[float] = []
    scale = min_scale
    rounded_max_scale = round(max_scale, 3)
    while scale <= max_scale:
        rounded_scale = round(scale, 3)
        if not scales or rounded_scale > scales[-1]:
            scales.append(rounded_scale)
        scale *= step_ratio

    if not scales or scales[-1] < rounded_max_scale:
        scales.append(rounded_max_scale)
    return tuple(scales)


RECAPTCHA_MATCH_SCALES = build_recaptcha_match_scales()
RECAPTCHA_FOCUS_ROI = (0.06, 0.04, 0.94, 0.98)
RECAPTCHA_FOCUS_STABLE_SECONDS = 0.3
RECAPTCHA_ALLOWED_WINDOW_TITLES = ("MapleStory Worlds",)
WINDOW_EVENT_POLL_INTERVAL_MS = 50
RUNNING_OVERLAY_OFFSET_X = 8
RUNNING_OVERLAY_OFFSET_Y = 8
RUNNING_OVERLAY_ALPHA = 0.72
RUNNING_OVERLAY_MAX_SCRIPT_NAMES = 6
RUNNING_OVERLAY_RADIUS = 8
DISCORD_NOTIFICATION_TEXT = "愣住！你被測謊啦"


if platform.system() == "Windows":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    WINEVENTPROC = ctypes.WINFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
else:
    user32 = None
    gdi32 = None
    kernel32 = None
    WNDENUMPROC = None
    WINEVENTPROC = None


def configure_process_dpi_awareness() -> None:
    if platform.system() != "Windows":
        return

    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return

    try:
        set_context = windll.user32.SetProcessDpiAwarenessContext
        set_context.argtypes = (ctypes.c_void_p,)
        set_context.restype = ctypes.c_bool
        if set_context(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
            return
    except (AttributeError, OSError):
        pass

    try:
        set_awareness = windll.shcore.SetProcessDpiAwareness
        set_awareness.argtypes = (ctypes.c_int,)
        set_awareness.restype = ctypes.c_long
        if set_awareness(PROCESS_PER_MONITOR_DPI_AWARE) == 0:
            return
    except (AttributeError, OSError):
        pass

    try:
        set_dpi_aware = windll.user32.SetProcessDPIAware
        set_dpi_aware.restype = ctypes.c_bool
        set_dpi_aware()
    except (AttributeError, OSError):
        pass


VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_PAUSE = 0x13
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_SNAPSHOT = 0x2C
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
PM_NOREMOVE = 0x0000
WM_QUIT = 0x0012
MONITOR_DEFAULTTONEAREST = 0x00000002
GA_ROOT = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
OBJID_WINDOW = 0
WINEVENT_OUTOFCONTEXT = 0x0000

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
MAPVK_VK_TO_VSC = 0
HOLD_REPEAT_MS = 35

ACTION_KEY_DOWN = "key_down"
ACTION_DELAY = "delay"
ACTION_KEY_UP = "key_up"
ACTION_SCRIPT_CALL = "script_call"
ACTION_LABELS = {
    ACTION_KEY_DOWN: "按下按鍵↓",
    ACTION_DELAY: "延遲",
    ACTION_KEY_UP: "放開按鍵↑",
    ACTION_SCRIPT_CALL: "呼叫腳本",
}
ACTION_BY_LABEL = {label: action for action, label in ACTION_LABELS.items()}

FORM_ACTION_KEY_COMMAND = "key_command"
FORM_ACTION_DELAY = ACTION_DELAY
FORM_ACTION_SCRIPT_CALL = ACTION_SCRIPT_CALL
FORM_ACTION_LABELS = {
    FORM_ACTION_KEY_COMMAND: "按鍵指令",
    FORM_ACTION_DELAY: "延遲",
    FORM_ACTION_SCRIPT_CALL: "呼叫腳本",
}
FORM_ACTION_BY_LABEL = {label: action for action, label in FORM_ACTION_LABELS.items()}

KEY_MODE_DOWN = "key_down"
KEY_MODE_UP = "key_up"
KEY_MODE_BOTH = "both"
KEY_MODE_LABELS = {
    KEY_MODE_BOTH: "按下 + 放開",
    KEY_MODE_DOWN: "按下",
    KEY_MODE_UP: "放開",
}

KEYCODE_TEXT: dict[int, str] = {
    VK_BACK: "BACKSPACE",
    VK_TAB: "TAB",
    VK_RETURN: "ENTER",
    VK_ESCAPE: "ESC",
    VK_SPACE: "SPACE",
    VK_PRIOR: "PAGEUP",
    VK_NEXT: "PAGEDOWN",
    VK_END: "END",
    VK_HOME: "HOME",
    VK_LEFT: "LEFT",
    VK_UP: "UP",
    VK_RIGHT: "RIGHT",
    VK_DOWN: "DOWN",
    VK_SNAPSHOT: "PRINTSCREEN",
    VK_INSERT: "INSERT",
    VK_DELETE: "DELETE",
    VK_LWIN: "WIN",
    VK_RWIN: "WIN",
    VK_APPS: "APPS",
    VK_PAUSE: "PAUSE",
    VK_CAPITAL: "CAPSLOCK",
    VK_NUMLOCK: "NUMLOCK",
    VK_SCROLL: "SCROLLLOCK",
    0x6A: "NUMMULTIPLY",
    0x6B: "NUMADD",
    0x6D: "NUMSUBTRACT",
    0x6E: "NUMDECIMAL",
    0x6F: "NUMDIVIDE",
    0xBA: "SEMICOLON",
    0xBB: "EQUAL",
    0xBC: "COMMA",
    0xBD: "MINUS",
    0xBE: "PERIOD",
    0xBF: "SLASH",
    0xC0: "GRAVE",
    0xDB: "LBRACKET",
    0xDC: "BACKSLASH",
    0xDD: "RBRACKET",
    0xDE: "QUOTE",
}
for _number in range(10):
    KEYCODE_TEXT[ord(str(_number))] = str(_number)
    KEYCODE_TEXT[0x60 + _number] = f"NUM{_number}"
for _index in range(1, 25):
    KEYCODE_TEXT[0x70 + _index - 1] = f"F{_index}"
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    KEYCODE_TEXT[ord(_letter)] = _letter

SHIFTED_CHAR_BASE = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "MINUS",
    "+": "EQUAL",
    "{": "LBRACKET",
    "}": "RBRACKET",
    "|": "BACKSLASH",
    ":": "SEMICOLON",
    '"': "QUOTE",
    "<": "COMMA",
    ">": "PERIOD",
    "?": "SLASH",
    "~": "GRAVE",
}


NAMED_KEYS: dict[str, int] = {
    "BACKSPACE": VK_BACK,
    "BKSP": VK_BACK,
    "TAB": VK_TAB,
    "ENTER": VK_RETURN,
    "RETURN": VK_RETURN,
    "SHIFT": VK_SHIFT,
    "CTRL": VK_CONTROL,
    "CONTROL": VK_CONTROL,
    "ALT": VK_MENU,
    "ESC": VK_ESCAPE,
    "ESCAPE": VK_ESCAPE,
    "SPACE": VK_SPACE,
    "PAGEUP": VK_PRIOR,
    "PGUP": VK_PRIOR,
    "PAGEDOWN": VK_NEXT,
    "PGDN": VK_NEXT,
    "END": VK_END,
    "HOME": VK_HOME,
    "LEFT": VK_LEFT,
    "UP": VK_UP,
    "RIGHT": VK_RIGHT,
    "DOWN": VK_DOWN,
    "PRINTSCREEN": VK_SNAPSHOT,
    "PRTSC": VK_SNAPSHOT,
    "INSERT": VK_INSERT,
    "INS": VK_INSERT,
    "DELETE": VK_DELETE,
    "DEL": VK_DELETE,
    "WIN": VK_LWIN,
    "WINDOWS": VK_LWIN,
    "LWIN": VK_LWIN,
    "RWIN": VK_RWIN,
    "MENU": VK_APPS,
    "APPS": VK_APPS,
    "PAUSE": VK_PAUSE,
    "CAPSLOCK": VK_CAPITAL,
    "CAPS": VK_CAPITAL,
    "NUMLOCK": VK_NUMLOCK,
    "SCROLLLOCK": VK_SCROLL,
}

for number in range(10):
    NAMED_KEYS[str(number)] = ord(str(number))
    NAMED_KEYS[f"NUM{number}"] = 0x60 + number
    NAMED_KEYS[f"NUMPAD{number}"] = 0x60 + number

for index in range(1, 25):
    NAMED_KEYS[f"F{index}"] = 0x70 + index - 1

for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    NAMED_KEYS[letter] = ord(letter)

NAMED_KEYS.update(
    {
        "MULTIPLY": 0x6A,
        "NUMMULTIPLY": 0x6A,
        "ADD": 0x6B,
        "NUMADD": 0x6B,
        "SEPARATOR": 0x6C,
        "SUBTRACT": 0x6D,
        "NUMSUBTRACT": 0x6D,
        "DECIMAL": 0x6E,
        "NUMDECIMAL": 0x6E,
        "DIVIDE": 0x6F,
        "NUMDIVIDE": 0x6F,
    }
)

PUNCTUATION_ALIASES = {
    "PLUS": "+",
    "EQUALS": "=",
    "EQUAL": "=",
    "MINUS": "-",
    "DASH": "-",
    "COMMA": ",",
    "PERIOD": ".",
    "DOT": ".",
    "SLASH": "/",
    "FORWARDSLASH": "/",
    "BACKSLASH": "\\",
    "SEMICOLON": ";",
    "QUOTE": "'",
    "APOSTROPHE": "'",
    "GRAVE": "`",
    "BACKTICK": "`",
    "LBRACKET": "[",
    "LEFTBRACKET": "[",
    "RBRACKET": "]",
    "RIGHTBRACKET": "]",
}

MODIFIER_NAMES = {
    "CTRL": VK_CONTROL,
    "CONTROL": VK_CONTROL,
    "ALT": VK_MENU,
    "SHIFT": VK_SHIFT,
    "WIN": VK_LWIN,
    "WINDOWS": VK_LWIN,
    "LWIN": VK_LWIN,
    "RWIN": VK_RWIN,
}

MODIFIER_FLAGS = {
    VK_CONTROL: MOD_CONTROL,
    VK_MENU: MOD_ALT,
    VK_SHIFT: MOD_SHIFT,
    VK_LWIN: MOD_WIN,
    VK_RWIN: MOD_WIN,
}

EXTENDED_KEYS = {
    VK_INSERT,
    VK_DELETE,
    VK_HOME,
    VK_END,
    VK_PRIOR,
    VK_NEXT,
    VK_UP,
    VK_DOWN,
    VK_LEFT,
    VK_RIGHT,
    VK_RWIN,
    VK_LWIN,
    VK_APPS,
    VK_SNAPSHOT,
    0x6F,
}


def normalize_token(value: str) -> str:
    return value.strip().upper().replace(" ", "").replace("_", "")


def unique_preserve_order(values: Iterable[int]) -> tuple[int, ...]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return tuple(ordered)


def is_vk_down(*vks: int) -> bool:
    if user32 is None:
        return False
    return any(bool(user32.GetAsyncKeyState(vk) & 0x8000) for vk in vks)


def normalize_step_action(value: str) -> str:
    token = value.strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "down": ACTION_KEY_DOWN,
        "keydown": ACTION_KEY_DOWN,
        "key_down": ACTION_KEY_DOWN,
        "press_down": ACTION_KEY_DOWN,
        "delay": ACTION_DELAY,
        "wait": ACTION_DELAY,
        "sleep": ACTION_DELAY,
        "延遲": ACTION_DELAY,
        "up": ACTION_KEY_UP,
        "keyup": ACTION_KEY_UP,
        "key_up": ACTION_KEY_UP,
        "press_up": ACTION_KEY_UP,
        "script": ACTION_SCRIPT_CALL,
        "script_call": ACTION_SCRIPT_CALL,
        "call_script": ACTION_SCRIPT_CALL,
        "run_script": ACTION_SCRIPT_CALL,
        "insert_script": ACTION_SCRIPT_CALL,
        "按下按鍵": ACTION_KEY_DOWN,
        "放開按鍵": ACTION_KEY_UP,
        "呼叫腳本": ACTION_SCRIPT_CALL,
        "插入腳本": ACTION_SCRIPT_CALL,
    }
    if value in ACTION_BY_LABEL:
        return ACTION_BY_LABEL[value]
    return aliases.get(token, ACTION_KEY_DOWN)


@dataclass(frozen=True)
class KeyAction:
    vk: int
    modifiers: tuple[int, ...] = ()


def unique_key_actions(actions: Iterable[KeyAction]) -> list[KeyAction]:
    seen: set[KeyAction] = set()
    ordered: list[KeyAction] = []
    for action in actions:
        if action not in seen:
            ordered.append(action)
            seen.add(action)
    return ordered


class KeyResolver:
    @staticmethod
    def resolve_key_actions(text: str) -> list[KeyAction]:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) == 1:
            return [KeyResolver.resolve_key_action(text)]
        if any(part == "" for part in parts):
            raise ValueError("多按鍵請用逗號分隔，例如 X, SPACE。")
        return [KeyResolver.resolve_key_action(part) for part in parts]

    @staticmethod
    def resolve_key_action(text: str) -> KeyAction:
        raw = text.strip()
        if not raw:
            raise ValueError("請輸入按鍵。")

        if raw != "+" and "+" in raw:
            parts = [part.strip() for part in raw.split("+")]
            if any(part == "" for part in parts):
                raise ValueError("如果要輸入加號，請使用 PLUS，例如 CTRL+PLUS。")

            modifiers: list[int] = []
            for part in parts[:-1]:
                token = normalize_token(part)
                if token not in MODIFIER_NAMES:
                    raise ValueError("組合鍵只能把 CTRL、ALT、SHIFT、WIN 放在前面。")
                modifiers.append(MODIFIER_NAMES[token])

            base = KeyResolver._resolve_single_key(parts[-1])
            return KeyAction(base.vk, unique_preserve_order([*modifiers, *base.modifiers]))

        return KeyResolver._resolve_single_key(raw)

    @staticmethod
    def parse_hotkey(text: str) -> tuple[int, int]:
        raw = text.strip()
        if not raw:
            raise ValueError("快捷鍵不能是空白。")

        action = KeyResolver.resolve_key_action(raw)
        if action.vk in {VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN}:
            raise ValueError("快捷鍵需要包含一般按鍵，例如 CTRL+F8。")

        flags = 0
        for modifier in action.modifiers:
            if modifier not in MODIFIER_FLAGS:
                continue
            flags |= MODIFIER_FLAGS[modifier]

        return flags, action.vk

    @staticmethod
    def _resolve_single_key(text: str) -> KeyAction:
        raw = text.strip()
        token = normalize_token(raw)

        if token in NAMED_KEYS:
            return KeyAction(NAMED_KEYS[token])

        if token in PUNCTUATION_ALIASES:
            return KeyResolver._resolve_character(PUNCTUATION_ALIASES[token])

        if len(raw) == 1:
            return KeyResolver._resolve_character(raw)

        raise ValueError(f"不支援的按鍵：{text}")

    @staticmethod
    def _resolve_character(character: str) -> KeyAction:
        if user32 is None:
            raise ValueError("此工具目前只支援 Windows。")

        if character.isalpha():
            return KeyAction(ord(character.upper()))

        if character.isdigit():
            return KeyAction(ord(character))

        result = user32.VkKeyScanW(ord(character))
        if result == -1:
            raise ValueError(f"這個字元無法轉成 Windows 按鍵：{character}")

        vk = result & 0xFF
        shift_state = (result >> 8) & 0xFF
        modifiers: list[int] = []
        if shift_state & 1:
            modifiers.append(VK_SHIFT)
        if shift_state & 2:
            modifiers.append(VK_CONTROL)
        if shift_state & 4:
            modifiers.append(VK_MENU)
        return KeyAction(vk, tuple(modifiers))


class WindowsKeyboard:
    def __init__(self) -> None:
        if user32 is None:
            raise RuntimeError("此工具目前只支援 Windows。")

        user32.SendInput.argtypes = (ctypes.c_uint, ctypes.c_void_p, ctypes.c_int)
        user32.SendInput.restype = ctypes.c_uint
        user32.MapVirtualKeyW.argtypes = (ctypes.c_uint, ctypes.c_uint)
        user32.MapVirtualKeyW.restype = ctypes.c_uint
        self._send_lock = threading.Lock()

    def key_down(self, action: KeyAction) -> None:
        for modifier in action.modifiers:
            self._send_vk(modifier, True)
        self._send_vk(action.vk, True)

    def key_up(self, action: KeyAction) -> None:
        self._send_vk(action.vk, False)
        for modifier in reversed(action.modifiers):
            self._send_vk(modifier, False)

    def key_down_many(self, actions: list[KeyAction]) -> None:
        modifiers = unique_preserve_order(modifier for action in actions for modifier in action.modifiers)
        for modifier in modifiers:
            self._send_vk(modifier, True)
        for action in actions:
            self._send_vk(action.vk, True)

    def key_up_many(self, actions: list[KeyAction]) -> None:
        modifiers = unique_preserve_order(modifier for action in actions for modifier in action.modifiers)
        for action in reversed(actions):
            self._send_vk(action.vk, False)
        for modifier in reversed(modifiers):
            self._send_vk(modifier, False)

    def press(self, action: KeyAction, press_ms: int, stop_event: threading.Event) -> bool:
        pressed: list[int] = []
        try:
            for modifier in action.modifiers:
                self._send_vk(modifier, True)
                pressed.append(modifier)

            self._send_vk(action.vk, True)
            pressed.append(action.vk)

            end_at = time.monotonic() + max(press_ms, 0) / 1000
            repeat_interval = HOLD_REPEAT_MS / 1000
            while True:
                remaining = end_at - time.monotonic()
                if remaining <= 0:
                    return True

                if stop_event.wait(min(repeat_interval, remaining)):
                    return False

                if time.monotonic() < end_at:
                    self._send_vk(action.vk, True)
        finally:
            for vk in reversed(pressed):
                try:
                    self._send_vk(vk, False)
                except OSError:
                    pass

    def _send_vk(self, vk: int, is_down: bool) -> None:
        scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        flags = 0 if is_down else KEYEVENTF_KEYUP
        if vk in EXTENDED_KEYS:
            flags |= KEYEVENTF_EXTENDEDKEY

        extra_info = ctypes.c_ulong(0)

        class KeyBdInput(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class HardwareInput(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.c_ulong),
                ("wParamL", ctypes.c_short),
                ("wParamH", ctypes.c_ushort),
            ]

        class MouseInput(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class InputUnion(ctypes.Union):
            _fields_ = [
                ("ki", KeyBdInput),
                ("mi", MouseInput),
                ("hi", HardwareInput),
            ]

        class Input(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_ulong),
                ("union", InputUnion),
            ]

        keyboard_input = KeyBdInput(vk, scan, flags, 0, ctypes.pointer(extra_info))
        input_struct = Input(INPUT_KEYBOARD, InputUnion(ki=keyboard_input))

        with self._send_lock:
            sent = user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(input_struct))
        if sent != 1:
            raise ctypes.WinError(ctypes.get_last_error())


@dataclass
class Step:
    action: str
    key: str = ""
    delay_ms: int = 0
    script_id: str = ""

    @classmethod
    def from_dicts(cls, data: dict) -> list["Step"]:
        if "action" not in data and "kind" not in data:
            key = str(data.get("key", "SPACE"))
            press_ms = max(1, int(data.get("press_ms", 100)))
            wait_ms = max(0, int(data.get("wait_ms", 0)))
            steps = [
                cls(ACTION_KEY_DOWN, key=key),
                cls(ACTION_DELAY, delay_ms=press_ms),
                cls(ACTION_KEY_UP, key=key),
            ]
            if wait_ms > 0:
                steps.append(cls(ACTION_DELAY, delay_ms=wait_ms))
            return steps

        action = normalize_step_action(str(data.get("action") or data.get("kind") or ACTION_KEY_DOWN))
        if action == ACTION_DELAY:
            return [cls(action, delay_ms=max(0, int(data.get("delay_ms", data.get("ms", 0)))))]
        if action == ACTION_SCRIPT_CALL:
            script_id = data.get("script_id", data.get("target_script_id", data.get("script", "")))
            return [cls(action, script_id=str(script_id or ""))]
        return [cls(action, key=str(data.get("key", "SPACE")))]

    def to_dict(self) -> dict:
        if self.action == ACTION_DELAY:
            return {"action": self.action, "delay_ms": self.delay_ms}
        if self.action == ACTION_SCRIPT_CALL:
            return {"action": self.action, "script_id": self.script_id}
        return {"action": self.action, "key": self.key}

    def needs_key(self) -> bool:
        return self.action in {ACTION_KEY_DOWN, ACTION_KEY_UP}

    def needs_script(self) -> bool:
        return self.action == ACTION_SCRIPT_CALL

    def display_action(self) -> str:
        return ACTION_LABELS.get(self.action, self.action)


@dataclass
class Script:
    id: str
    name: str
    hotkey: str = ""
    repeat: bool = True
    steps: list[Step] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        steps: list[Step] = []
        for step_data in data.get("steps", []):
            steps.extend(Step.from_dicts(step_data))

        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            name=str(data.get("name") or "未命名腳本"),
            hotkey=str(data.get("hotkey") or ""),
            repeat=bool(data.get("repeat", True)),
            steps=steps,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "hotkey": self.hotkey,
            "repeat": self.repeat,
            "steps": [step.to_dict() for step in self.steps],
        }

    def clone(self) -> "Script":
        return Script.from_dict(self.to_dict())


def scripts_by_id(scripts: Iterable[Script]) -> dict[str, Script]:
    return {script.id: script for script in scripts}


def _script_cycle_text(script_ids: list[str], script_lookup: dict[str, Script]) -> str:
    names = [script_lookup[script_id].name for script_id in script_ids if script_id in script_lookup]
    return " -> ".join(names) if names else "未知腳本"


def validate_script_references(
    script: Script,
    script_lookup: dict[str, Script],
    stack: list[str] | None = None,
) -> None:
    stack = stack or []
    stack.append(script.id)
    try:
        for index, step in enumerate(script.steps, start=1):
            if step.needs_key():
                KeyResolver.resolve_key_actions(step.key)
            elif step.needs_script():
                target_id = step.script_id.strip()
                if not target_id:
                    raise ValueError(f"{script.name} 的第 {index} 格尚未選擇要呼叫的腳本。")

                target = script_lookup.get(target_id)
                if target is None:
                    raise ValueError(f"{script.name} 的第 {index} 格找不到要呼叫的腳本。")

                if target.id in stack:
                    cycle_ids = stack[stack.index(target.id):] + [target.id]
                    raise ValueError(f"腳本呼叫形成循環：{_script_cycle_text(cycle_ids, script_lookup)}")

                validate_script_references(target, script_lookup, stack)
    finally:
        stack.pop()


def default_scripts() -> list[Script]:
    return [
        Script(
            id=str(uuid.uuid4()),
            name="範例：每秒按一次 Space",
            hotkey="F8",
            repeat=True,
            steps=[
                Step(ACTION_KEY_DOWN, key="SPACE"),
                Step(ACTION_DELAY, delay_ms=100),
                Step(ACTION_KEY_UP, key="SPACE"),
                Step(ACTION_DELAY, delay_ms=900),
            ],
        )
    ]


def _copy_legacy_config_if_needed() -> None:
    if CONFIG_PATH.exists() or not LEGACY_CONFIG_PATH.exists() or LEGACY_CONFIG_PATH == CONFIG_PATH:
        return

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(LEGACY_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def _read_scripts_from_config(path: Path) -> list[Script]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Script.from_dict(item) for item in data.get("scripts", [])]


def load_scripts() -> list[Script]:
    try:
        _copy_legacy_config_if_needed()
        if not CONFIG_PATH.exists():
            return default_scripts()
        return _read_scripts_from_config(CONFIG_PATH)
    except Exception as exc:
        messagebox.showwarning(APP_TITLE, f"讀取設定檔失敗，已載入預設範例。\n\n{exc}")
        return default_scripts()


def save_scripts(scripts: list[Script]) -> None:
    data = {"scripts": [script.to_dict() for script in scripts]}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass
class DiscordRecipient:
    name: str
    user_id: str
    webhook_url: str


DISCORD_RECIPIENTS = (
    DiscordRecipient(
        name="客服",
        user_id="383460422457753602",
        webhook_url=(
            "https://discord.com/api/webhooks/1502681017071308960/"
            "Pd3QwbC3JKY3qy44HX8QMI9IShY30ujBIQYZZdlAIuq8tHbb9vGX8INiUQSjmyD4pi1p"
        ),
    ),
    DiscordRecipient(
        name="羅總",
        user_id="446938994727714817",
        webhook_url=(
            "https://discord.com/api/webhooks/1502681053847097494/"
            "It3RWUWICoqwycFtvDOh3g-u1fz5Rs_tp22IjYoeDSDSHfbJNK-dnLwq3TvXqi1wHJVp"
        ),
    ),
    DiscordRecipient(
        name="蔡董",
        user_id="464337253880299520",
        webhook_url=(
            "https://discord.com/api/webhooks/1502679542790095020/"
            "BZDzq_bLaKLFPTTutJ6PCgejMtSr-CgmQ2STgbJmfTRd5kEi0enhQ6xDjW_XYvXMaXkU"
        ),
    ),
)
DISCORD_RECIPIENTS_BY_NAME = {recipient.name: recipient for recipient in DISCORD_RECIPIENTS}
DEFAULT_DISCORD_RECIPIENT_NAME = ""


@dataclass
class RecaptchaMonitorSettings:
    enabled: bool = True
    recipient_name: str = DEFAULT_DISCORD_RECIPIENT_NAME
    only_maplestory_window: bool = True


@dataclass
class RunningOverlaySettings:
    enabled: bool = True


def normalize_discord_user_id(value: str) -> str:
    return "".join(character for character in value.strip() if character.isdigit())


def normalize_discord_webhook_url(value: str) -> str:
    return value.strip().strip("<>")


def discord_recipient_names() -> tuple[str, ...]:
    return tuple(recipient.name for recipient in DISCORD_RECIPIENTS)


def discord_recipient_for_name(value: str) -> DiscordRecipient | None:
    return DISCORD_RECIPIENTS_BY_NAME.get(value.strip())


def normalized_discord_recipient_name(value: str) -> str:
    recipient = discord_recipient_for_name(value)
    return recipient.name if recipient is not None else ""


def discord_recipient_for_legacy_settings(user_id: str, webhook_url: str) -> DiscordRecipient | None:
    normalized_user_id = normalize_discord_user_id(user_id)
    normalized_webhook_url = normalize_discord_webhook_url(webhook_url)
    for recipient in DISCORD_RECIPIENTS:
        if normalized_user_id and recipient.user_id == normalized_user_id:
            return recipient
        if normalized_webhook_url and recipient.webhook_url == normalized_webhook_url:
            return recipient
    return None


def load_recaptcha_monitor_settings() -> RecaptchaMonitorSettings:
    try:
        if not MONITOR_CONFIG_PATH.exists():
            return RecaptchaMonitorSettings()
        data = json.loads(MONITOR_CONFIG_PATH.read_text(encoding="utf-8"))
        recipient_name = str(data.get("recipient_name", ""))
        if recipient_name:
            recipient = discord_recipient_for_name(recipient_name)
        else:
            recipient = discord_recipient_for_legacy_settings(
                str(data.get("user_id", "")),
                str(data.get("webhook_url", "")),
            )
        return RecaptchaMonitorSettings(
            enabled=bool(data.get("enabled", True)),
            recipient_name=recipient.name if recipient is not None else "",
            only_maplestory_window=bool(data.get("only_maplestory_window", True)),
        )
    except Exception:
        return RecaptchaMonitorSettings()


def save_recaptcha_monitor_settings(settings: RecaptchaMonitorSettings) -> None:
    data = {
        "enabled": bool(settings.enabled),
        "recipient_name": normalized_discord_recipient_name(settings.recipient_name),
        "only_maplestory_window": bool(settings.only_maplestory_window),
    }
    MONITOR_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    MONITOR_CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_running_overlay_settings() -> RunningOverlaySettings:
    try:
        if not RUNNING_OVERLAY_CONFIG_PATH.exists():
            return RunningOverlaySettings()
        data = json.loads(RUNNING_OVERLAY_CONFIG_PATH.read_text(encoding="utf-8"))
        return RunningOverlaySettings(enabled=bool(data.get("enabled", True)))
    except Exception:
        return RunningOverlaySettings()


def save_running_overlay_settings(settings: RunningOverlaySettings) -> None:
    data = {"enabled": bool(settings.enabled)}
    RUNNING_OVERLAY_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNNING_OVERLAY_CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_running_overlay_text(script_names: Iterable[str]) -> str:
    names = [name.strip() for name in script_names if name.strip()]
    if not names:
        return ""

    visible_names = names[:RUNNING_OVERLAY_MAX_SCRIPT_NAMES]
    remaining_count = len(names) - len(visible_names)
    if remaining_count > 0:
        visible_names.append(f"... 另 {remaining_count} 個")
    return "執行中\n" + "\n".join(visible_names)


class HotkeyManager:
    def __init__(self) -> None:
        if user32 is None:
            raise RuntimeError("此工具目前只支援 Windows。")

        user32.RegisterHotKey.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint)
        user32.RegisterHotKey.restype = ctypes.c_bool
        user32.UnregisterHotKey.argtypes = (ctypes.c_void_p, ctypes.c_int)
        user32.UnregisterHotKey.restype = ctypes.c_bool
        user32.PeekMessageW.argtypes = (
            ctypes.POINTER(MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        user32.PeekMessageW.restype = ctypes.c_bool
        user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
        user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)

        self.events: queue.Queue[str] = queue.Queue()
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="HotkeyManager", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2)

    def set_hotkeys(self, scripts: list[Script]) -> list[str]:
        result_queue: queue.Queue[list[str]] = queue.Queue()
        payload = [(script.id, script.name, script.hotkey.strip()) for script in scripts if script.hotkey.strip()]
        self._commands.put(("set", payload, result_queue))
        try:
            return result_queue.get(timeout=2)
        except queue.Empty:
            return ["快捷鍵註冊逾時。"]

    def close(self) -> None:
        result_queue: queue.Queue[None] = queue.Queue()
        self._commands.put(("close", result_queue))
        try:
            result_queue.get(timeout=1)
        except queue.Empty:
            pass

    def _loop(self) -> None:
        registered: dict[int, str] = {}
        self._ready.set()

        while True:
            while self._process_messages(registered):
                pass

            should_close = False
            while True:
                try:
                    command = self._commands.get_nowait()
                except queue.Empty:
                    break

                if command[0] == "set":
                    _, payload, result_queue = command
                    errors = self._register_payload(payload, registered)
                    result_queue.put(errors)
                elif command[0] == "close":
                    _, result_queue = command
                    self._unregister_all(registered)
                    result_queue.put(None)
                    should_close = True

            if should_close:
                return

            time.sleep(0.02)

    def _register_payload(self, payload: list[tuple[str, str, str]], registered: dict[int, str]) -> list[str]:
        self._unregister_all(registered)
        errors: list[str] = []
        seen: set[tuple[int, int]] = set()
        next_id = 1000

        for script_id, name, hotkey in payload:
            try:
                flags, vk = KeyResolver.parse_hotkey(hotkey)
            except ValueError as exc:
                errors.append(f"{name}: {exc}")
                continue

            signature = (flags, vk)
            if signature in seen:
                errors.append(f"{name}: 快捷鍵 {hotkey} 和其他腳本重複。")
                continue
            seen.add(signature)

            hotkey_id = next_id
            next_id += 1
            ok = user32.RegisterHotKey(None, hotkey_id, flags | MOD_NOREPEAT, vk)
            if not ok:
                errors.append(f"{name}: 快捷鍵 {hotkey} 無法註冊，可能已被其他程式使用。")
                continue
            registered[hotkey_id] = script_id

        return errors

    def _unregister_all(self, registered: dict[int, str]) -> None:
        for hotkey_id in list(registered):
            user32.UnregisterHotKey(None, hotkey_id)
        registered.clear()

    def _process_messages(self, registered: dict[int, str]) -> bool:
        msg = MSG()
        has_message = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
        if not has_message:
            return False

        if msg.message == WM_HOTKEY:
            script_id = registered.get(int(msg.wParam))
            if script_id:
                self.events.put(script_id)
        else:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return True


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_ulong),
        ("pt", POINT),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


class MapleStoryWindowLocator:
    def __init__(
        self,
        *,
        allowed_titles: tuple[str, ...] = RECAPTCHA_ALLOWED_WINDOW_TITLES,
        excluded_pid: int | None = None,
    ) -> None:
        if user32 is None or WNDENUMPROC is None:
            raise RuntimeError("此工具目前只支援 Windows。")

        self._allowed_titles = tuple(token.casefold() for token in allowed_titles if token.strip())
        self._excluded_pid = excluded_pid
        self._configure_user32()

    def _configure_user32(self) -> None:
        user32.GetForegroundWindow.argtypes = ()
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.EnumWindows.argtypes = (WNDENUMPROC, ctypes.c_void_p)
        user32.EnumWindows.restype = ctypes.c_bool
        user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(RECT))
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.GetClientRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(RECT))
        user32.GetClientRect.restype = ctypes.c_bool
        user32.ClientToScreen.argtypes = (ctypes.c_void_p, ctypes.POINTER(POINT))
        user32.ClientToScreen.restype = ctypes.c_bool
        user32.GetWindowTextLengthW.argtypes = (ctypes.c_void_p,)
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.IsIconic.argtypes = (ctypes.c_void_p,)
        user32.IsIconic.restype = ctypes.c_bool

    def find_window_bbox(self) -> tuple[int, int, int, int] | None:
        foreground = user32.GetForegroundWindow()
        if foreground and self._is_candidate_window(int(foreground)):
            return self._best_bbox_for_window(int(foreground))

        matches: list[tuple[int, tuple[int, int, int, int]]] = []

        def callback(hwnd, _lparam) -> bool:
            hwnd_value = int(hwnd)
            if self._is_candidate_window(hwnd_value):
                bbox = self._best_bbox_for_window(hwnd_value)
                if bbox is not None:
                    matches.append((self._bbox_area(bbox), bbox))
            return True

        callback_ref = WNDENUMPROC(callback)
        if not user32.EnumWindows(callback_ref, None):
            return None
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]

    def find_foreground_window_bbox(self) -> tuple[int, int, int, int] | None:
        foreground = user32.GetForegroundWindow()
        if not foreground or not self._is_candidate_window(int(foreground)):
            return None
        return self._best_bbox_for_window(int(foreground))

    def _is_candidate_window(self, hwnd: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return False
        if self._excluded_pid is not None and self._window_process_id(hwnd) == self._excluded_pid:
            return False
        if self._allowed_titles:
            title = self._window_title(hwnd).casefold()
            if not any(token in title for token in self._allowed_titles):
                return False
        return self._best_bbox_for_window(hwnd) is not None

    def _best_bbox_for_window(self, hwnd: int) -> tuple[int, int, int, int] | None:
        return self._client_bbox(hwnd) or self._window_bbox(hwnd)

    def _client_bbox(self, hwnd: int) -> tuple[int, int, int, int] | None:
        rect = RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None

        top_left = POINT(0, 0)
        bottom_right = POINT(int(rect.right), int(rect.bottom))
        if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
            return None
        if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
            return None
        if bottom_right.x <= top_left.x or bottom_right.y <= top_left.y:
            return None
        return (int(top_left.x), int(top_left.y), int(bottom_right.x), int(bottom_right.y))

    def _window_bbox(self, hwnd: int) -> tuple[int, int, int, int] | None:
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))

    def _window_title(self, hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _window_process_id(self, hwnd: int) -> int | None:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None

    def _bbox_area(self, bbox: tuple[int, int, int, int]) -> int:
        return max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])


class WindowEventHook:
    def __init__(self) -> None:
        self.events: queue.Queue[None] = queue.Queue()
        self._hooks: list[int] = []
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._thread_id = 0
        self._proc = WINEVENTPROC(self._handle_event) if WINEVENTPROC is not None else None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if user32 is None or self._proc is None or self._thread is not None:
            return

        self._thread = threading.Thread(target=self._run, name="WindowEventHook", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1)

    def close(self) -> None:
        self._closed.set()
        if user32 is not None and self._thread_id:
            try:
                user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        if user32 is None or kernel32 is None or self._proc is None:
            self._ready.set()
            return

        try:
            self._configure_winapi()
            self._thread_id = int(kernel32.GetCurrentThreadId())
            self._ensure_message_queue()
            self._install_hooks()
            self._ready.set()
            msg = MSG()
            while not self._closed.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._uninstall_hooks()
            self._ready.set()

    def _configure_winapi(self) -> None:
        kernel32.GetCurrentThreadId.argtypes = ()
        kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
        user32.SetWinEventHook.argtypes = (
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            WINEVENTPROC,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        )
        user32.SetWinEventHook.restype = ctypes.c_void_p
        user32.UnhookWinEvent.argtypes = (ctypes.c_void_p,)
        user32.UnhookWinEvent.restype = ctypes.c_bool
        user32.GetMessageW.argtypes = (
            ctypes.POINTER(MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        user32.GetMessageW.restype = ctypes.c_int
        user32.PostThreadMessageW.argtypes = (ctypes.c_ulong, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
        user32.PostThreadMessageW.restype = ctypes.c_bool
        user32.PeekMessageW.argtypes = (
            ctypes.POINTER(MSG),
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.c_uint,
        )
        user32.PeekMessageW.restype = ctypes.c_bool
        user32.TranslateMessage.argtypes = (ctypes.POINTER(MSG),)
        user32.DispatchMessageW.argtypes = (ctypes.POINTER(MSG),)

    def _ensure_message_queue(self) -> None:
        msg = MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)

    def _install_hooks(self) -> None:
        for event_min, event_max in (
            (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
            (EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE),
        ):
            hook = user32.SetWinEventHook(
                event_min,
                event_max,
                None,
                self._proc,
                0,
                0,
                WINEVENT_OUTOFCONTEXT,
            )
            if hook:
                self._hooks.append(int(hook))

    def _uninstall_hooks(self) -> None:
        for hook in self._hooks:
            try:
                user32.UnhookWinEvent(hook)
            except Exception:
                pass
        self._hooks.clear()

    def _handle_event(
        self,
        _hook,
        event: int,
        _hwnd,
        object_id: int,
        _child_id: int,
        _event_thread: int,
        _event_time: int,
    ) -> None:
        if self._closed.is_set():
            return
        if event == EVENT_OBJECT_LOCATIONCHANGE and object_id != OBJID_WINDOW:
            return
        try:
            self.events.put_nowait(None)
        except queue.Full:
            pass


@dataclass
class PreparedTemplate:
    image: object
    samples: list[tuple[int, int, int, int, int]]
    gray: object | None = None
    important_mask: object | None = None
    blue_mask: object | None = None
    important_samples: list[tuple[int, int, int, int, int]] = field(default_factory=list)
    scale: float = 1.0


@dataclass(frozen=True)
class ImageMatchResult:
    matched: bool
    has_features: bool
    match_scale: float | None = None


class FocusedWindowCapture:
    def __init__(self, excluded_pid: int | None = None) -> None:
        if user32 is None:
            raise RuntimeError("此工具目前只支援 Windows。")
        if ImageGrab is None:
            raise RuntimeError("缺少 Pillow，請先安裝 Pillow 才能截圖比對。")

        self._excluded_pid = excluded_pid
        self._last_signature: tuple[int, tuple[int, int, int, int]] | None = None
        self._last_signature_at = 0.0
        user32.GetForegroundWindow.argtypes = ()
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowRect.argtypes = (ctypes.c_void_p, ctypes.POINTER(RECT))
        user32.GetWindowRect.restype = ctypes.c_bool
        user32.GetWindowTextLengthW.argtypes = (ctypes.c_void_p,)
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
        user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
        user32.IsWindowVisible.restype = ctypes.c_bool
        user32.MonitorFromWindow.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
        user32.MonitorFromWindow.restype = ctypes.c_void_p
        user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(MONITORINFO))
        user32.GetMonitorInfoW.restype = ctypes.c_bool

    def capture(self, *, only_allowed_window: bool = True):
        hwnd = user32.GetForegroundWindow()
        if not hwnd or not user32.IsWindowVisible(hwnd):
            self._reset_focus_stability()
            return None
        process_id = self._window_process_id(hwnd)
        if self._excluded_pid is not None and process_id == self._excluded_pid:
            self._reset_focus_stability()
            return None
        if only_allowed_window and not self._is_allowed_window(hwnd):
            self._reset_focus_stability()
            return None

        window_bbox = self._window_bbox(hwnd)
        if window_bbox is None:
            return None

        monitor_bbox = self._focused_monitor_bbox(hwnd)
        if monitor_bbox is not None:
            window_bbox = self._intersect_bboxes(window_bbox, monitor_bbox)
            if window_bbox is None:
                return None
        if not self._is_focus_stable(int(hwnd), window_bbox):
            return None
        window_bbox = self._center_roi_bbox(window_bbox)
        return self._grab_bbox(window_bbox)

    def _is_allowed_window(self, hwnd: int) -> bool:
        if not RECAPTCHA_ALLOWED_WINDOW_TITLES:
            return True
        title = self._window_title(hwnd).casefold()
        return any(token.casefold() in title for token in RECAPTCHA_ALLOWED_WINDOW_TITLES)

    def _window_title(self, hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _reset_focus_stability(self) -> None:
        self._last_signature = None
        self._last_signature_at = 0.0

    def _window_process_id(self, hwnd: int) -> int | None:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None

    def _is_focus_stable(self, hwnd: int, bbox: tuple[int, int, int, int]) -> bool:
        signature = (hwnd, bbox)
        now = time.monotonic()
        if signature != self._last_signature:
            self._last_signature = signature
            self._last_signature_at = now
            return False
        return now - self._last_signature_at >= RECAPTCHA_FOCUS_STABLE_SECONDS

    def _focused_monitor_bbox(self, hwnd: int) -> tuple[int, int, int, int] | None:
        monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor:
            return None

        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None

        rect = info.rcMonitor
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))

    def _window_bbox(self, hwnd: int) -> tuple[int, int, int, int] | None:
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None

        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None

        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))

    def _intersect_bboxes(
        self,
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int] | None:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        if right <= left or bottom <= top:
            return None
        return (left, top, right, bottom)

    def _center_roi_bbox(self, bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        left, top, right, bottom = bbox
        width = right - left
        height = bottom - top
        if width < 640 or height < 360:
            return bbox

        left_ratio, top_ratio, right_ratio, bottom_ratio = RECAPTCHA_FOCUS_ROI
        roi = (
            int(left + width * left_ratio),
            int(top + height * top_ratio),
            int(left + width * right_ratio),
            int(top + height * bottom_ratio),
        )
        if roi[2] <= roi[0] or roi[3] <= roi[1]:
            return bbox
        return roi

    def _grab_bbox(self, bbox: tuple[int, int, int, int]):
        try:
            return ImageGrab.grab(
                bbox=bbox,
                all_screens=True,
                include_layered_windows=True,
            ).convert("RGB")
        except TypeError:
            try:
                return ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
            except TypeError:
                return ImageGrab.grab(bbox=bbox).convert("RGB")


class ImageTemplateMatcher:
    def __init__(
        self,
        template_path: Path,
        *,
        downsample: float = RECAPTCHA_MATCH_DOWNSAMPLE,
        threshold: float = RECAPTCHA_MATCH_THRESHOLD,
        scales: tuple[float, ...] | None = None,
        profile: str = "compact",
    ) -> None:
        if Image is None or ImageChops is None or ImageStat is None:
            raise RuntimeError("缺少 Pillow，請先安裝 Pillow 才能讀取與比對圖片。")
        if not template_path.exists():
            raise FileNotFoundError(f"找不到比對圖片：{template_path}")
        if profile not in {"compact", "full"}:
            raise ValueError(f"不支援的比對模式：{profile}")

        self._downsample = downsample
        self._threshold = threshold
        self._cv_threshold = RECAPTCHA_CV_MATCH_THRESHOLD
        self._scales = scales
        self._profile = profile
        self._resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        self._template = Image.open(template_path).convert("RGB")
        self._templates_by_downsample: dict[tuple[float, tuple[float, ...]], list[PreparedTemplate]] = {}
        self._last_match_scale: float | None = None

    def contains(self, screenshot) -> bool:
        return self.analyze(screenshot).matched

    def analyze(self, screenshot, *, preferred_scale: float | None = None) -> ImageMatchResult:
        if screenshot.width <= 0 or screenshot.height <= 0:
            return ImageMatchResult(matched=False, has_features=False)

        downsample = self._effective_downsample(screenshot)
        small_size = (
            max(1, int(screenshot.width * downsample)),
            max(1, int(screenshot.height * downsample)),
        )
        small_screenshot = screenshot.resize(small_size, self._resample)
        if not self._has_recaptcha_palette(small_screenshot):
            return ImageMatchResult(matched=False, has_features=False)

        scales = self._scales_for_screenshot(screenshot)
        templates = self._templates_for_downsample(downsample, scales)
        templates = self._prioritized_templates(templates, preferred_scale)

        if cv2 is not None and np is not None:
            return self._remember_match_scale(self._match_with_cv(small_screenshot, templates))

        for prepared in templates:
            if self._contains_template(small_screenshot, prepared):
                return self._remember_match_scale(
                    ImageMatchResult(matched=True, has_features=True, match_scale=prepared.scale)
                )
        return ImageMatchResult(matched=False, has_features=True)

    def _remember_match_scale(self, result: ImageMatchResult) -> ImageMatchResult:
        if result.matched and result.match_scale is not None:
            self._last_match_scale = result.match_scale
        return result

    def _effective_downsample(self, screenshot) -> float:
        if cv2 is None or np is None:
            return self._downsample
        if screenshot.width * screenshot.height <= RECAPTCHA_FULL_RES_MAX_PIXELS:
            return 1.0
        return self._downsample

    def _scales_for_screenshot(self, screenshot) -> tuple[float, ...]:
        if self._scales is not None:
            return self._scales

        max_scale_by_width = screenshot.width / self._template.width
        max_scale_by_height = screenshot.height / self._template.height
        max_scale = min(RECAPTCHA_MATCH_SCALE_MAX, max_scale_by_width, max_scale_by_height)
        return build_recaptcha_match_scales(max_scale=max_scale)

    def _has_recaptcha_palette(self, screenshot) -> bool:
        if np is None:
            return True

        pixels = np.asarray(screenshot)
        if pixels.size == 0:
            return False

        red = pixels[:, :, 0].astype(np.int16)
        green = pixels[:, :, 1].astype(np.int16)
        blue = pixels[:, :, 2].astype(np.int16)
        bright_pixels = (red > 210) & (green > 210) & (blue > 210)
        button_blue_pixels = (blue > 140) & (green > 70) & (green < 210) & (red < 140) & ((blue - red) > 45)
        area = screenshot.width * screenshot.height
        min_bright_pixels = max(80, int(area * 0.0004))
        min_blue_pixels = max(24, int(area * 0.00015))
        return int(bright_pixels.sum()) >= min_bright_pixels and int(button_blue_pixels.sum()) >= min_blue_pixels

    def _templates_for_downsample(self, downsample: float, scales: tuple[float, ...]) -> list[PreparedTemplate]:
        key = (round(downsample, 3), scales)
        templates = self._templates_by_downsample.get(key)
        if templates is None:
            templates = self._prepare_templates(scales, downsample)
            self._templates_by_downsample[key] = templates
        return templates

    def _prioritized_templates(
        self,
        templates: list[PreparedTemplate],
        preferred_scale: float | None,
    ) -> list[PreparedTemplate]:
        scale_hint = preferred_scale or self._last_match_scale or RECAPTCHA_PREFERRED_MATCH_SCALE
        if scale_hint <= 0:
            return templates
        return sorted(templates, key=lambda template: (abs(template.scale - scale_hint), template.scale))

    def _prepare_templates(self, scales: tuple[float, ...], downsample: float) -> list[PreparedTemplate]:
        templates: list[PreparedTemplate] = []
        for scale in scales:
            width = max(1, int(self._template.width * scale * downsample))
            height = max(1, int(self._template.height * scale * downsample))
            image = self._template.resize((width, height), self._resample)
            gray = None
            important_mask = None
            blue_mask = None
            samples: list[tuple[int, int, int, int, int]] = []
            important_samples: list[tuple[int, int, int, int, int]] = []
            if cv2 is not None and np is not None:
                gray = np.asarray(image.convert("L"))
                important_mask = self._important_pixel_mask(image)
                blue_mask = self._blue_pixel_mask(image)
            else:
                samples = self._sample_points(image)
                important_samples = self._important_samples(samples)
            templates.append(
                PreparedTemplate(
                    image=image,
                    samples=samples,
                    gray=gray,
                    important_mask=important_mask,
                    blue_mask=blue_mask,
                    important_samples=important_samples,
                    scale=scale,
                )
            )
        return templates

    def _important_pixel_mask(self, image):
        pixels = np.asarray(image)
        return (pixels[:, :, 0] < 245) | (pixels[:, :, 1] < 245) | (pixels[:, :, 2] < 245)

    def _blue_pixel_mask(self, image):
        return self._blue_pixels(np.asarray(image))

    def _blue_pixels(self, pixels):
        red = pixels[:, :, 0].astype(np.int16)
        green = pixels[:, :, 1].astype(np.int16)
        blue = pixels[:, :, 2].astype(np.int16)
        return (blue > 140) & (green > 70) & (green < 210) & (red < 140) & ((blue - red) > 45)

    def _important_samples(
        self,
        samples: list[tuple[int, int, int, int, int]],
    ) -> list[tuple[int, int, int, int, int]]:
        return [sample for sample in samples if sample[2] < 245 or sample[3] < 245 or sample[4] < 245]

    def _contains_with_cv(self, screenshot, templates: list[PreparedTemplate]) -> bool:
        return self._match_with_cv(screenshot, templates).matched

    def _match_with_cv(self, screenshot, templates: list[PreparedTemplate]) -> ImageMatchResult:
        screenshot_gray = np.asarray(screenshot.convert("L"))
        for prepared in templates:
            template_gray = prepared.gray
            if template_gray is None:
                continue
            if screenshot_gray.shape[0] < template_gray.shape[0] or screenshot_gray.shape[1] < template_gray.shape[1]:
                continue

            result = cv2.matchTemplate(screenshot_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            if result.size == 0:
                continue
            _, max_value, _, max_location = cv2.minMaxLoc(result)
            if max_value >= self._cv_threshold_for(prepared) and self._verify_candidate(screenshot, prepared, max_location):
                return ImageMatchResult(matched=True, has_features=True, match_scale=prepared.scale)
        return ImageMatchResult(matched=False, has_features=True)

    def _cv_threshold_for(self, template: PreparedTemplate) -> float:
        if self._profile == "full":
            return RECAPTCHA_FULL_CV_MATCH_THRESHOLD
        if template.scale <= 0.35:
            return RECAPTCHA_TINY_CV_MATCH_THRESHOLD
        if template.scale <= 0.55:
            return RECAPTCHA_SMALL_CV_MATCH_THRESHOLD
        return self._cv_threshold

    def _verify_candidate(self, screenshot, template: PreparedTemplate, location: tuple[int, int]) -> bool:
        x, y = location
        template_image = template.image
        if x < 0 or y < 0:
            return False
        if x + template_image.width > screenshot.width or y + template_image.height > screenshot.height:
            return False

        crop = screenshot.crop((x, y, x + template_image.width, y + template_image.height))
        if np is not None:
            crop_array = np.asarray(crop).astype(np.int16)
            if not self._verify_candidate_palette(crop_array):
                return False

            template_array = np.asarray(template_image).astype(np.int16)
            diff = np.abs(crop_array - template_array)
            per_pixel = diff.mean(axis=2)
            mean = float(per_pixel.mean())
            mean_threshold, good_pixel_threshold, good_pixel_ratio = self._verify_thresholds(template)
            good_ratio = float((per_pixel <= good_pixel_threshold).mean())
            if mean > mean_threshold or good_ratio < good_pixel_ratio:
                return False
            return self._verify_important_pixels(per_pixel, template) and self._verify_blue_pixels(crop_array, template)

        diff = ImageChops.difference(crop, template_image)
        mean = sum(ImageStat.Stat(diff).mean) / 3
        mean_threshold, _, _ = self._verify_thresholds(template)
        return mean <= max(self._threshold, mean_threshold)

    def _verify_thresholds(self, template: PreparedTemplate) -> tuple[float, float, float]:
        if template.scale <= 0.35:
            return 34.0, 70.0, 0.72
        if template.scale <= 0.55:
            return 28.0, 58.0, 0.78
        return (
            RECAPTCHA_VERIFY_MEAN_THRESHOLD,
            RECAPTCHA_VERIFY_GOOD_PIXEL_THRESHOLD,
            RECAPTCHA_VERIFY_GOOD_PIXEL_RATIO,
        )

    def _verify_candidate_palette(self, crop_array) -> bool:
        if crop_array.size == 0:
            return False

        red = crop_array[:, :, 0].astype(np.int16)
        green = crop_array[:, :, 1].astype(np.int16)
        blue = crop_array[:, :, 2].astype(np.int16)
        area = crop_array.shape[0] * crop_array.shape[1]
        bright = (red > 210) & (green > 210) & (blue > 210)
        blue_pixels = self._blue_pixels(crop_array)
        saturated = (np.maximum.reduce((red, green, blue)) - np.minimum.reduce((red, green, blue))) > 70
        saturated_not_blue = saturated & ~blue_pixels
        dark = (red < 80) & (green < 80) & (blue < 80)

        if self._profile == "full":
            return (
                int(bright.sum()) / area >= 0.70
                and int(blue_pixels.sum()) / area >= 0.025
                and int(saturated_not_blue.sum()) / area <= 0.11
                and int(dark.sum()) / area <= 0.05
            )

        return (
            int(bright.sum()) / area >= 0.66
            and int(blue_pixels.sum()) / area >= 0.12
            and int(saturated_not_blue.sum()) / area <= 0.05
            and int(dark.sum()) / area <= 0.06
        )

    def _verify_important_pixels(self, per_pixel, template: PreparedTemplate) -> bool:
        important_mask = template.important_mask
        if important_mask is None:
            return True

        important_count = int(important_mask.sum())
        if important_count < 8:
            return True

        important_errors = per_pixel[important_mask]
        mean_threshold, good_pixel_threshold, good_pixel_ratio = self._verify_thresholds(template)
        important_mean_threshold = mean_threshold * 1.4
        important_good_ratio = max(0.62, good_pixel_ratio - 0.1)
        return (
            float(important_errors.mean()) <= important_mean_threshold
            and float((important_errors <= good_pixel_threshold).mean()) >= important_good_ratio
        )

    def _verify_blue_pixels(self, crop_array, template: PreparedTemplate) -> bool:
        blue_mask = template.blue_mask
        if blue_mask is None:
            return True

        blue_count = int(blue_mask.sum())
        if blue_count < 8:
            return True

        crop_blue_pixels = self._blue_pixels(crop_array)
        if self._profile == "full":
            return float(crop_blue_pixels[blue_mask].mean()) >= 0.80

        required_ratio = 0.78 if template.scale <= 0.35 else 0.84 if template.scale <= 0.55 else 0.88
        return float(crop_blue_pixels[blue_mask].mean()) >= required_ratio

    def _verify_important_samples(
        self,
        screenshot_pixels,
        template: PreparedTemplate,
        origin_x: int,
        origin_y: int,
    ) -> bool:
        if not template.important_samples:
            return True

        mean_threshold, good_pixel_threshold, good_pixel_ratio = self._verify_thresholds(template)
        important_mean_threshold = mean_threshold * 1.4
        important_good_ratio = max(0.62, good_pixel_ratio - 0.1)
        total_error = 0.0
        good_count = 0
        for sample_x, sample_y, red, green, blue in template.important_samples:
            pixel_red, pixel_green, pixel_blue = screenshot_pixels[origin_x + sample_x, origin_y + sample_y]
            error = (abs(pixel_red - red) + abs(pixel_green - green) + abs(pixel_blue - blue)) / 3
            total_error += error
            if error <= good_pixel_threshold:
                good_count += 1

        sample_count = len(template.important_samples)
        return (
            total_error / sample_count <= important_mean_threshold
            and good_count / sample_count >= important_good_ratio
        )

    def _sample_points(self, image) -> list[tuple[int, int, int, int, int]]:
        pixels = image.load()
        points: list[tuple[int, int, int, int, int]] = []
        seen: set[tuple[int, int]] = set()

        def add_point(x: int, y: int) -> None:
            key = (x, y)
            if key in seen:
                return
            seen.add(key)
            red, green, blue = pixels[x, y]
            points.append((x, y, red, green, blue))

        sparse_step = max(4, min(image.width, image.height) // 12)
        content_step = max(2, min(image.width, image.height) // 28)

        for y in range(0, image.height, content_step):
            for x in range(0, image.width, content_step):
                red, green, blue = pixels[x, y]
                if red < 238 or green < 238 or blue < 238:
                    add_point(x, y)

        for y in range(0, image.height, sparse_step):
            for x in range(0, image.width, sparse_step):
                add_point(x, y)

        for x, y in (
            (0, 0),
            (image.width - 1, 0),
            (0, image.height - 1),
            (image.width - 1, image.height - 1),
            (image.width // 2, image.height // 2),
        ):
            add_point(max(0, x), max(0, y))

        points.sort(key=lambda point: -(abs(point[2] - 255) + abs(point[3] - 255) + abs(point[4] - 255)))
        if len(points) > 260:
            points = [points[int(index * len(points) / 260)] for index in range(260)]
        return points

    def _contains_template(self, screenshot, template: PreparedTemplate) -> bool:
        template_image = template.image
        max_x = screenshot.width - template_image.width
        max_y = screenshot.height - template_image.height
        if max_x < 0 or max_y < 0:
            return False

        screenshot_pixels = screenshot.load()
        stride = 1 if screenshot.width * screenshot.height < 100_000 else 2
        mean_threshold, _, _ = self._verify_thresholds(template)
        sample_limit = int(max(self._threshold, mean_threshold) * len(template.samples) * 3)

        for y in range(0, max_y + 1, stride):
            for x in range(0, max_x + 1, stride):
                error = 0
                for sample_x, sample_y, red, green, blue in template.samples:
                    pixel_red, pixel_green, pixel_blue = screenshot_pixels[x + sample_x, y + sample_y]
                    error += abs(pixel_red - red) + abs(pixel_green - green) + abs(pixel_blue - blue)
                    if error > sample_limit:
                        break
                else:
                    crop = screenshot.crop((x, y, x + template_image.width, y + template_image.height))
                    diff = ImageChops.difference(crop, template_image)
                    mean = sum(ImageStat.Stat(diff).mean) / 3
                    if (
                        mean <= max(self._threshold, mean_threshold)
                        and self._verify_important_samples(screenshot_pixels, template, x, y)
                    ):
                        return True

        return False


class LieDetectionMatcher:
    def __init__(
        self,
        compact_template_path: Path = RECAPTCHA_TEMPLATE_PATH,
        full_template_path: Path = RECAPTCHA_FULL_TEMPLATE_PATH,
    ) -> None:
        self._compact_matcher = ImageTemplateMatcher(compact_template_path, profile="compact")
        self._full_matcher = (
            ImageTemplateMatcher(full_template_path, profile="full") if full_template_path.exists() else None
        )

    def contains(self, screenshot) -> bool:
        return self.analyze(screenshot).matched

    def analyze(self, screenshot) -> ImageMatchResult:
        compact_result = self._compact_matcher.analyze(screenshot)
        if not compact_result.matched or self._full_matcher is None:
            return compact_result

        full_result = self._full_matcher.analyze(screenshot, preferred_scale=compact_result.match_scale)
        return ImageMatchResult(
            matched=full_result.matched,
            has_features=compact_result.has_features or full_result.has_features,
            match_scale=full_result.match_scale,
        )


class RecaptchaMonitor:
    def __init__(self, event_queue: queue.Queue[tuple[str, str]], excluded_pid: int | None = None) -> None:
        self.events = event_queue
        self._excluded_pid = excluded_pid
        self._settings = RecaptchaMonitorSettings()
        self._settings_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error = ""
        self._last_error_at = 0.0
        self._match_started_at: float | None = None
        self._last_notification_started_at = 0.0
        self._active_notifications = 0
        self._notification_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="RecaptchaMonitor", daemon=True)
        self._thread.start()

    def set_settings(self, settings: RecaptchaMonitorSettings) -> None:
        normalized = RecaptchaMonitorSettings(
            enabled=bool(settings.enabled),
            recipient_name=normalized_discord_recipient_name(settings.recipient_name),
            only_maplestory_window=bool(settings.only_maplestory_window),
        )
        with self._settings_lock:
            self._settings = normalized

    def close(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self) -> None:
        try:
            capture = FocusedWindowCapture(excluded_pid=self._excluded_pid)
            matcher = LieDetectionMatcher(RECAPTCHA_TEMPLATE_PATH, RECAPTCHA_FULL_TEMPLATE_PATH)
        except Exception as exc:
            self._publish("error", f"測謊偵測無法啟動：{exc}")
            return

        self._publish("ready", "測謊偵測已啟動。")
        while not self._stop_event.is_set():
            started_at = time.monotonic()
            scan_interval = RECAPTCHA_SCAN_INTERVAL_SECONDS
            settings = self._settings_snapshot()
            recipient = discord_recipient_for_name(settings.recipient_name)
            if settings.enabled and recipient is not None:
                try:
                    screenshot = capture.capture(only_allowed_window=settings.only_maplestory_window)
                    result = matcher.analyze(screenshot) if screenshot is not None else ImageMatchResult(
                        matched=False,
                        has_features=False,
                    )
                    matched = result.matched
                    if result.has_features:
                        scan_interval = RECAPTCHA_FEATURE_SCAN_INTERVAL_SECONDS
                    if matched and self._is_confirmed_match():
                        self._queue_detected_notification(recipient.webhook_url, recipient.user_id, screenshot)
                    elif not matched:
                        self._reset_match_confirmation()
                except Exception as exc:
                    self._publish_error(f"測謊偵測錯誤：{exc}")

            else:
                self._reset_match_confirmation()

            elapsed = time.monotonic() - started_at
            self._stop_event.wait(max(0.05, scan_interval - elapsed))

    def _is_confirmed_match(self) -> bool:
        now = time.monotonic()
        if self._match_started_at is None:
            self._match_started_at = now
            return False
        return now - self._match_started_at >= RECAPTCHA_CONFIRM_SECONDS

    def _reset_match_confirmation(self) -> None:
        self._match_started_at = None
        with self._notification_lock:
            self._last_notification_started_at = 0.0

    def _settings_snapshot(self) -> RecaptchaMonitorSettings:
        with self._settings_lock:
            return RecaptchaMonitorSettings(
                enabled=self._settings.enabled,
                recipient_name=self._settings.recipient_name,
                only_maplestory_window=self._settings.only_maplestory_window,
            )

    def _notify_detected(self, webhook_url: str, user_id: str, screenshot) -> None:
        self._queue_detected_notification(webhook_url, user_id, screenshot)

    def _queue_detected_notification(self, webhook_url: str, user_id: str, screenshot) -> None:
        now = time.monotonic()
        with self._notification_lock:
            if (
                self._last_notification_started_at
                and now - self._last_notification_started_at < RECAPTCHA_NOTIFY_INTERVAL_SECONDS
            ):
                return
            if self._active_notifications >= RECAPTCHA_MAX_NOTIFICATION_WORKERS:
                return
            self._last_notification_started_at = now
            self._active_notifications += 1

        notification_screenshot = screenshot.copy() if hasattr(screenshot, "copy") else screenshot
        thread = threading.Thread(
            target=self._send_detected_notification,
            args=(webhook_url, user_id, notification_screenshot),
            name="RecaptchaNotification",
            daemon=True,
        )
        try:
            thread.start()
        except Exception:
            with self._notification_lock:
                self._active_notifications = max(0, self._active_notifications - 1)
            raise

    def _send_detected_notification(self, webhook_url: str, user_id: str, screenshot) -> None:
        try:
            self._post_discord_webhook(webhook_url, user_id, screenshot)
        except Exception as exc:
            self._publish_error(f"Discord webhook notification failed: {exc}")
        else:
            self._publish("notified", "偵測到測謊，已通知 Discord 並附上截圖。")
        finally:
            with self._notification_lock:
                self._active_notifications = max(0, self._active_notifications - 1)

    def _notify_detected_sync(self, webhook_url: str, user_id: str, screenshot) -> None:
        self._post_discord_webhook(webhook_url, user_id, screenshot)
        self._publish("notified", "偵測到測謊，已通知 Discord 並附上截圖。")

    def _post_discord_webhook(self, webhook_url: str, user_id: str, screenshot) -> None:
        filename = f"recaptcha-detected-{int(time.time())}.jpg"
        payload = {
            "content": f"<@{user_id}> {DISCORD_NOTIFICATION_TEXT}",
            "allowed_mentions": {"users": [user_id]},
        }
        body, content_type = self._discord_multipart_body(
            payload=payload,
            screenshot_bytes=self._screenshot_jpeg_bytes(screenshot),
            filename=filename,
            image_content_type="image/jpeg",
        )
        request = urllib.request.Request(
            webhook_url,
            data=body,
            headers={
                "Content-Type": content_type,
                "User-Agent": f"{APP_NAME}/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status not in (200, 204):
                    raise RuntimeError(f"Discord webhook 回應 HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"Discord webhook 回應 HTTP {exc.code}: {detail}") from exc

    def _screenshot_png_bytes(self, screenshot) -> bytes:
        output = io.BytesIO()
        screenshot.save(output, format="PNG")
        return output.getvalue()

    def _screenshot_jpeg_bytes(self, screenshot) -> bytes:
        output = io.BytesIO()
        screenshot.convert("RGB").save(output, format="JPEG", quality=82)
        return output.getvalue()

    def _discord_multipart_body(
        self,
        *,
        payload: dict,
        screenshot_bytes: bytes,
        filename: str,
        image_content_type: str = "image/png",
    ) -> tuple[bytes, str]:
        boundary = f"----{APP_NAME}{uuid.uuid4().hex}"
        body = bytearray()

        def add_line(line: str) -> None:
            body.extend(line.encode("utf-8"))
            body.extend(b"\r\n")

        add_line(f"--{boundary}")
        add_line('Content-Disposition: form-data; name="payload_json"')
        add_line("Content-Type: application/json; charset=utf-8")
        add_line("")
        body.extend(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        body.extend(b"\r\n")

        add_line(f"--{boundary}")
        add_line(f'Content-Disposition: form-data; name="files[0]"; filename="{filename}"')
        add_line(f"Content-Type: {image_content_type}")
        add_line("")
        body.extend(screenshot_bytes)
        body.extend(b"\r\n")

        add_line(f"--{boundary}--")
        return bytes(body), f"multipart/form-data; boundary={boundary}"

    def _publish(self, event_type: str, detail: str) -> None:
        self.events.put((event_type, detail))

    def _publish_error(self, detail: str) -> None:
        now = time.monotonic()
        if detail == self._last_error and now - self._last_error_at < 30:
            return
        self._last_error = detail
        self._last_error_at = now
        self._publish("error", detail)


class ScriptRunner:
    def __init__(
        self,
        script: Script,
        keyboard: WindowsKeyboard,
        event_queue: queue.Queue[tuple],
        scripts: Iterable[Script] | None = None,
    ) -> None:
        self.script = script
        self._keyboard = keyboard
        self._event_queue = event_queue
        self._scripts_by_id = scripts_by_id(scripts or [script])
        self._scripts_by_id[script.id] = script
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"ScriptRunner:{script.name}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def join(self, timeout: float | None = None) -> bool:
        if self._thread.ident is None:
            return True
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _delay_with_held_keys(self, delay_ms: int, held_actions: list[KeyAction]) -> bool:
        if delay_ms <= 0:
            return self._stop_event.is_set()

        held = unique_key_actions(held_actions)
        if not held:
            return self._stop_event.wait(delay_ms / 1000)

        end_at = time.monotonic() + delay_ms / 1000
        repeat_interval = HOLD_REPEAT_MS / 1000
        while True:
            remaining = end_at - time.monotonic()
            if remaining <= 0:
                return False

            if self._stop_event.wait(min(repeat_interval, remaining)):
                return True

            if time.monotonic() < end_at:
                self._keyboard.key_down_many(held)

    def _execute_steps(
        self,
        script: Script,
        held_actions: list[KeyAction],
        *,
        prefix: str = "",
        stack: list[str] | None = None,
    ) -> bool:
        stack = stack or []
        if script.id in stack:
            cycle_ids = stack[stack.index(script.id):] + [script.id]
            raise ValueError(f"腳本呼叫形成循環：{_script_cycle_text(cycle_ids, self._scripts_by_id)}")

        stack.append(script.id)
        try:
            for index, step in enumerate(script.steps, start=1):
                if self._stop_event.is_set():
                    return True

                position = f"{prefix}{index}"
                if step.action == ACTION_KEY_DOWN:
                    actions = KeyResolver.resolve_key_actions(step.key)
                    self._event_queue.put(("step", self.script.id, f"{position}. {step.key} 按下按鍵"))
                    self._keyboard.key_down_many(actions)
                    held_actions.extend(actions)
                elif step.action == ACTION_KEY_UP:
                    actions = KeyResolver.resolve_key_actions(step.key)
                    self._event_queue.put(("step", self.script.id, f"{position}. {step.key} 放開按鍵"))
                    self._keyboard.key_up_many(actions)
                    for action in actions:
                        for held_index in range(len(held_actions) - 1, -1, -1):
                            if held_actions[held_index] == action:
                                del held_actions[held_index]
                                break
                elif step.action == ACTION_DELAY:
                    held_count = len(unique_key_actions(held_actions))
                    if held_count:
                        detail = f"{position}. 延遲 {step.delay_ms} ms (維持 {held_count} 個按鍵)"
                    else:
                        detail = f"{position}. 延遲 {step.delay_ms} ms"
                    self._event_queue.put(("step", self.script.id, detail))
                    if self._delay_with_held_keys(step.delay_ms, held_actions):
                        return True
                elif step.action == ACTION_SCRIPT_CALL:
                    target_id = step.script_id.strip()
                    target = self._scripts_by_id.get(target_id)
                    if target is None:
                        raise ValueError(f"{script.name} 的第 {position} 格找不到要呼叫的腳本。")

                    self._event_queue.put(("step", self.script.id, f"{position}. 呼叫腳本：{target.name}"))
                    if self._execute_steps(target, held_actions, prefix=f"{position}.", stack=stack):
                        return True

            return False
        finally:
            stack.pop()

    def _run(self) -> None:
        self._event_queue.put(("started", self.script.id, ""))
        held_actions: list[KeyAction] = []
        try:
            while not self._stop_event.is_set():
                if self._execute_steps(self.script, held_actions):
                    break

                if not self.script.repeat:
                    break
        except Exception as exc:
            self._event_queue.put(("error", self.script.id, str(exc)))
        finally:
            for action in reversed(held_actions):
                try:
                    self._keyboard.key_up(action)
                except OSError:
                    pass
            self._event_queue.put(("stopped", self.script.id, ""))


def seconds_to_ms(value: str, field_name: str, minimum_ms: int) -> int:
    try:
        seconds = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} 必須是數字。") from exc

    if seconds < 0:
        raise ValueError(f"{field_name} 不能是負數。")

    ms = int(round(seconds * 1000))
    if ms < minimum_ms:
        raise ValueError(f"{field_name} 太短。")
    return ms


def text_to_ms(value: str, field_name: str, minimum_ms: int = 0) -> int:
    try:
        ms = int(round(float(value.replace(",", ""))))
    except ValueError as exc:
        raise ValueError(f"{field_name} 必須是數字。") from exc

    if ms < minimum_ms:
        raise ValueError(f"{field_name} 太短。")
    return ms


def format_seconds(ms: int) -> str:
    value = ms / 1000
    return format_number(value)


def format_number(value: float) -> str:
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return text or "0"


def format_delay_ms(ms: int) -> str:
    if ms >= 60_000:
        minutes = ms // 60_000
        remaining_ms = ms % 60_000
        if remaining_ms == 0:
            return f"{minutes:,} 分鐘"
        return f"{minutes:,} 分鐘 {format_number(remaining_ms / 1000)} 秒"
    if ms >= 1_000:
        return f"{format_number(ms / 1000)} 秒"
    return f"{ms:,} ms"


class RoundedEntry(tk.Frame):
    def __init__(
        self,
        master: tk.Widget,
        textvariable: tk.StringVar,
        width: int | None = None,
        colors: dict[str, str] | None = None,
    ) -> None:
        self.colors = colors or {}
        self.bg_color = self.colors.get("surface", "#ffffff")
        super().__init__(master, bg=self.bg_color, highlightthickness=0, bd=0)

        self.radius = 9
        self.border_color = self.colors.get("input_border", "#cbd5e1")
        self.focus_color = self.colors.get("primary", "#2563eb")
        self.fill_color = "#ffffff"
        self.disabled_fill = self.colors.get("surface_alt", "#f1f5f9")
        self.disabled_text = self.colors.get("muted", "#64748b")
        self.text_color = self.colors.get("text", "#0f172a")
        self._focused = False
        self._state = "normal"

        self.canvas = tk.Canvas(self, height=40, bg=self.bg_color, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.entry = tk.Entry(
            self.canvas,
            textvariable=textvariable,
            width=width or 20,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=self.fill_color,
            fg=self.text_color,
            insertbackground=self.text_color,
            disabledbackground=self.disabled_fill,
            disabledforeground=self.disabled_text,
            font=("Microsoft JhengHei UI", 10),
        )
        self.entry_window = self.canvas.create_window(14, 20, anchor="w", window=self.entry)
        self.canvas.bind("<Configure>", self._redraw)
        self.entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")

    def _rounded_rect(self, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> int:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)

    def _redraw(self, _event: tk.Event | None = None) -> None:
        width = max(self.canvas.winfo_width(), 80)
        height = max(self.canvas.winfo_height(), 40)
        self.canvas.delete("bg")
        border = self.focus_color if self._focused else self.border_color
        fill = self.disabled_fill if self._state == "disabled" else self.fill_color
        self._rounded_rect(1, 1, width - 1, height - 1, self.radius, fill=fill, outline=border, width=1, tags="bg")
        self.canvas.tag_lower("bg")
        self.canvas.coords(self.entry_window, 14, height // 2)
        self.canvas.itemconfigure(self.entry_window, width=max(width - 28, 40), height=max(height - 14, 24))
        self.entry.configure(bg=fill)

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._focused = True
        self._redraw()

    def _on_focus_out(self, _event: tk.Event) -> None:
        self._focused = False
        self._redraw()

    def bind(self, sequence: str | None = None, func=None, add: str | None = None):  # type: ignore[override]
        return self.entry.bind(sequence, func, add)

    def configure(self, cnf=None, **kwargs):  # type: ignore[override]
        if cnf:
            kwargs.update(cnf)
        state = kwargs.pop("state", None)
        if state is not None:
            self._state = str(state)
            self.entry.configure(state=state)
            self._redraw()
        if kwargs:
            return super().configure(**kwargs)
        return None

    config = configure

    def focus_set(self) -> None:
        self.entry.focus_set()

    def selection_range(self, start: int, end: int | str) -> None:
        self.entry.selection_range(start, end)


class RunningScriptsOverlay:
    _transparent_color = "#ff00ff"
    _bg = "#0f172a"
    _fg = "#f8fafc"
    _pad_x = 12
    _pad_y = 8
    _text_width = 340

    def __init__(self, root: tk.Tk, on_moved=None) -> None:
        self._on_moved = on_moved
        self._window = tk.Toplevel(root)
        self._window.withdraw()
        self._window.overrideredirect(True)
        self._window.configure(bg=self._transparent_color)
        self._window.resizable(False, False)
        try:
            self._window.attributes("-topmost", True)
        except tk.TclError:
            pass

        self._canvas = tk.Canvas(self._window, bg=self._transparent_color, bd=0, highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)
        self._text_item = self._canvas.create_text(
            self._pad_x,
            self._pad_y,
            anchor="nw",
            fill=self._fg,
            font=("Microsoft JhengHei UI", 10, "bold"),
            justify="left",
            text="",
            width=self._text_width,
        )
        self._content_size = (1, 1)
        self._last_text = ""
        self._last_geometry = ""
        self._drag_start_pointer: tuple[int, int] | None = None
        self._drag_start_window: tuple[int, int] | None = None
        self._drag_bounds: tuple[int, int, int, int] | None = None
        self._dragging = False
        self._bind_drag_handlers()
        self._configure_window_style()

    def show(
        self,
        text: str,
        x: int,
        y: int,
        bounds: tuple[int, int, int, int] | None = None,
    ) -> None:
        if not text:
            self.hide()
            return

        self._drag_bounds = bounds
        width, height = self._set_text(text)
        x, y = self._clamp_position(x, y, width, height, bounds)
        geometry = f"{width}x{height}+{x}+{y}"
        if geometry != self._last_geometry:
            self._window.geometry(geometry)
            self._window.update_idletasks()
            self._last_geometry = geometry
            self._configure_window_style()
            self._apply_rounded_region(width, height)

        if not self._window.winfo_viewable():
            self._window.deiconify()
            self._window.update_idletasks()
            self._configure_window_style()
            self._apply_rounded_region(width, height)

    def hide(self) -> None:
        try:
            if not self._window.winfo_viewable():
                return
            self._window.withdraw()
            self._last_geometry = ""
        except tk.TclError:
            pass

    def destroy(self) -> None:
        try:
            self._window.destroy()
        except tk.TclError:
            pass

    def is_interacting_or_foreground(self) -> bool:
        return self._dragging or self.is_foreground()

    def is_foreground(self) -> bool:
        if user32 is None:
            return False

        try:
            foreground = user32.GetForegroundWindow()
            return bool(foreground) and int(foreground) == self._top_level_hwnd()
        except Exception:
            return False

    def _set_text(self, text: str) -> tuple[int, int]:
        if text == self._last_text:
            return self._content_size

        self._last_text = text
        self._canvas.itemconfigure(self._text_item, text=text)
        bbox = self._canvas.bbox(self._text_item) or (0, 0, 1, 1)
        width = max(80, int(bbox[2] - bbox[0] + self._pad_x * 2))
        height = max(34, int(bbox[3] - bbox[1] + self._pad_y * 2))
        self._canvas.configure(width=width, height=height)
        self._redraw_background(width, height)
        self._canvas.coords(self._text_item, self._pad_x, self._pad_y)
        self._canvas.tag_raise(self._text_item)
        self._content_size = (width, height)
        return self._content_size

    def _redraw_background(self, width: int, height: int) -> None:
        self._canvas.delete("overlay_bg")
        radius = max(1, min(RUNNING_OVERLAY_RADIUS, width // 2, height // 2))
        diameter = radius * 2
        items = [
            self._canvas.create_rectangle(radius, 0, width - radius, height, fill=self._bg, outline="", tags="overlay_bg"),
            self._canvas.create_rectangle(0, radius, width, height - radius, fill=self._bg, outline="", tags="overlay_bg"),
            self._canvas.create_oval(0, 0, diameter, diameter, fill=self._bg, outline="", tags="overlay_bg"),
            self._canvas.create_oval(width - diameter, 0, width, diameter, fill=self._bg, outline="", tags="overlay_bg"),
            self._canvas.create_oval(0, height - diameter, diameter, height, fill=self._bg, outline="", tags="overlay_bg"),
            self._canvas.create_oval(
                width - diameter,
                height - diameter,
                width,
                height,
                fill=self._bg,
                outline="",
                tags="overlay_bg",
            ),
        ]
        for item in items:
            self._canvas.tag_lower(item)

    def _bind_drag_handlers(self) -> None:
        for widget in (self._window, self._canvas):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)
            widget.bind("<ButtonRelease-1>", self._finish_drag)

    def _start_drag(self, event: tk.Event) -> str:
        self._dragging = True
        self._drag_start_pointer = (int(event.x_root), int(event.y_root))
        self._drag_start_window = (self._window.winfo_x(), self._window.winfo_y())
        return "break"

    def _drag(self, event: tk.Event) -> str:
        if self._drag_start_pointer is None or self._drag_start_window is None:
            return "break"

        dx = int(event.x_root) - self._drag_start_pointer[0]
        dy = int(event.y_root) - self._drag_start_pointer[1]
        x = self._drag_start_window[0] + dx
        y = self._drag_start_window[1] + dy
        width, height = self._content_size
        x, y = self._clamp_position(x, y, width, height, self._drag_bounds)
        geometry = f"{width}x{height}+{x}+{y}"
        if geometry != self._last_geometry:
            self._window.geometry(geometry)
            self._last_geometry = geometry
        if self._on_moved is not None:
            self._on_moved(x, y)
        return "break"

    def _finish_drag(self, event: tk.Event) -> str:
        if self._on_moved is not None and self._window.winfo_viewable():
            self._on_moved(self._window.winfo_x(), self._window.winfo_y())
        self._dragging = False
        self._drag_start_pointer = None
        self._drag_start_window = None
        return "break"

    def _clamp_position(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        bounds: tuple[int, int, int, int] | None,
    ) -> tuple[int, int]:
        if bounds is None:
            return x, y

        left, top, right, bottom = bounds
        max_x = max(left, right - width)
        max_y = max(top, bottom - height)
        return min(max(x, left), max_x), min(max(y, top), max_y)

    def _configure_window_style(self) -> None:
        if user32 is None:
            return

        try:
            hwnd = self._top_level_hwnd()
            get_window_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
            set_window_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
            get_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int)
            get_window_long.restype = ctypes.c_ssize_t
            set_window_long.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
            set_window_long.restype = ctypes.c_ssize_t
            style = int(get_window_long(hwnd, GWL_EXSTYLE))
            style = (style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_TRANSPARENT
            set_window_long(hwnd, GWL_EXSTYLE, style)
            self._set_layered_attributes(hwnd)
        except Exception:
            pass

    def _apply_rounded_region(self, width: int, height: int) -> None:
        if user32 is None or gdi32 is None:
            return

        try:
            hwnd = self._top_level_hwnd()
            diameter = RUNNING_OVERLAY_RADIUS * 2
            gdi32.CreateRoundRectRgn.argtypes = (
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            )
            gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            user32.SetWindowRgn.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)
            user32.SetWindowRgn.restype = ctypes.c_int
            gdi32.DeleteObject.argtypes = (ctypes.c_void_p,)
            gdi32.DeleteObject.restype = ctypes.c_bool

            region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, diameter, diameter)
            if region and not user32.SetWindowRgn(hwnd, region, True):
                gdi32.DeleteObject(region)
        except Exception:
            pass

    def _top_level_hwnd(self) -> int:
        hwnd = int(self._window.winfo_id())
        if user32 is None:
            return hwnd

        try:
            user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
            user32.GetAncestor.restype = ctypes.c_void_p
            root_hwnd = user32.GetAncestor(hwnd, GA_ROOT)
            return int(root_hwnd or hwnd)
        except Exception:
            return hwnd

    def _set_layered_attributes(self, hwnd: int) -> None:
        if user32 is None:
            return

        try:
            user32.SetLayeredWindowAttributes.argtypes = (
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_ubyte,
                ctypes.c_ulong,
            )
            user32.SetLayeredWindowAttributes.restype = ctypes.c_bool
            alpha = max(0, min(255, int(round(RUNNING_OVERLAY_ALPHA * 255))))
            user32.SetLayeredWindowAttributes(
                hwnd,
                self._color_ref(self._transparent_color),
                alpha,
                LWA_COLORKEY | LWA_ALPHA,
            )
        except Exception:
            try:
                self._window.attributes("-alpha", RUNNING_OVERLAY_ALPHA)
                self._window.attributes("-transparentcolor", self._transparent_color)
            except tk.TclError:
                pass

    def _color_ref(self, color: str) -> int:
        color = color.lstrip("#")
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
        return red | (green << 8) | (blue << 16)


class AutoKeyboardApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x720")
        self.root.minsize(980, 620)
        self._set_window_icon()

        self.scripts = load_scripts()
        self.recaptcha_settings = load_recaptcha_monitor_settings()
        self.running_overlay_settings = load_running_overlay_settings()
        self.keyboard = WindowsKeyboard()
        self.hotkeys = HotkeyManager()
        self.runtime_events: queue.Queue[tuple] = queue.Queue()
        self.monitor_events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.recaptcha_monitor = RecaptchaMonitor(self.monitor_events, excluded_pid=os.getpid())
        self.maplestory_window_locator = MapleStoryWindowLocator(excluded_pid=os.getpid())
        self.window_event_hook = WindowEventHook()
        self.runners: dict[str, ScriptRunner] = {}
        self.current_step: dict[str, str] = {}
        self._loading_script = False
        self._loading_step = False
        self._loading_recaptcha_settings = False
        self._recording_hotkey = False
        self._closing = False
        self._auto_save_after_id: str | None = None
        self._auto_save_step_after_id: str | None = None
        self._hotkey_register_after_id: str | None = None
        self._recaptcha_save_after_id: str | None = None
        self._poll_after_id: str | None = None
        self._window_event_after_id: str | None = None
        self._running_overlay_offset = (RUNNING_OVERLAY_OFFSET_X, RUNNING_OVERLAY_OFFSET_Y)
        self._running_overlay_window_size: tuple[int, int] | None = None
        self._running_overlay_window_bbox: tuple[int, int, int, int] | None = None
        self._script_drag_start_y: int | None = None
        self._script_drag_start_id: str | None = None
        self._script_dragging = False
        self._script_drag_insert_index: int | None = None
        self._step_drag_start_y: int | None = None
        self._step_drag_indices: list[int] = []
        self._step_dragging = False
        self._step_drag_insert_index: int | None = None
        self._step_drag_pulse_after_id: str | None = None
        self._step_drag_pulse_on = False
        self._step_drag_start_row: str | None = None
        self._step_drag_started_on_selection = False
        self._step_clipboard: list[Step] = []
        self._script_call_choice_by_label: dict[str, str] = {}
        self._script_call_label_by_id: dict[str, str] = {}

        self.name_var = tk.StringVar()
        self.hotkey_var = tk.StringVar()
        self.hotkey_hint_var = tk.StringVar(value="按「綁定」設定腳本快捷鍵")
        self.repeat_var = tk.BooleanVar(value=True)
        self.step_action_var = tk.StringVar(value=FORM_ACTION_LABELS[FORM_ACTION_KEY_COMMAND])
        self.step_key_mode_var = tk.StringVar(value=KEY_MODE_BOTH)
        self.step_key_var = tk.StringVar(value="SPACE")
        self.step_delay_ms_var = tk.StringVar(value="1,000")
        self.step_script_var = tk.StringVar()
        self.running_overlay_enabled_var = tk.BooleanVar(value=self.running_overlay_settings.enabled)
        self.recaptcha_enabled_var = tk.BooleanVar(value=self.recaptcha_settings.enabled)
        self.recaptcha_maplestory_only_var = tk.BooleanVar(value=self.recaptcha_settings.only_maplestory_window)
        self.recaptcha_recipient_name_var = tk.StringVar(value=self.recaptcha_settings.recipient_name)
        self.recaptcha_bound_user_id_var = tk.StringVar(value="")
        self.recaptcha_bound_webhook_var = tk.StringVar(value="")
        self.recaptcha_status_var = tk.StringVar(value="")
        self.banner_var = tk.StringVar(value="待命")
        self.status_var = tk.StringVar(value="準備就緒")

        self._configure_style()
        self._build_ui()
        self.running_overlay = RunningScriptsOverlay(self.root, on_moved=self._on_running_overlay_moved)
        self._bind_auto_save()
        self._refresh_recaptcha_binding_display()
        self.recaptcha_monitor.set_settings(self.recaptcha_settings)
        self.recaptcha_monitor.start()
        self._update_recaptcha_status_from_settings(saved=False)
        self._refresh_script_tree()
        self._select_first_script()
        self._register_hotkeys(show_dialog=False)
        self.window_event_hook.start()
        self._poll_events()
        self._poll_window_events()
        self._sync_running_overlay()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_window_icon(self) -> None:
        icon_path = resource_path("assets/AutoKeyboard.ico")
        if not icon_path.exists():
            return
        try:
            self.root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _configure_style(self) -> None:
        style = ttk.Style()
        self.colors = {
            "bg": "#f8fafc",
            "surface": "#ffffff",
            "surface_alt": "#f1f5f9",
            "line": "#e2e8f0",
            "input_border": "#cbd5e1",
            "text": "#0f172a",
            "muted": "#64748b",
            "primary": "#2563eb",
            "primary_hover": "#1d4ed8",
            "danger": "#dc2626",
            "danger_hover": "#b91c1c",
            "success_bg": "#dcfce7",
            "success_text": "#166534",
            "idle_bg": "#e2e8f0",
            "idle_text": "#334155",
            "warning_bg": "#fef3c7",
            "warning_text": "#92400e",
        }
        colors = self.colors

        self.root.configure(bg=colors["bg"])
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = ("Microsoft JhengHei UI", 10)
        title_font = ("Microsoft JhengHei UI", 12, "bold")
        app_font = ("Microsoft JhengHei UI", 15, "bold")

        style.configure(".", background=colors["bg"], foreground=colors["text"], font=base_font)
        style.configure("TFrame", background=colors["bg"])
        style.configure("Panel.TFrame", background=colors["surface"], relief="flat", borderwidth=0)
        style.configure("Header.TFrame", background=colors["surface"])
        style.configure("Toolbar.TFrame", background=colors["surface"])
        style.configure("TPanedwindow", background=colors["bg"])
        style.configure("TSeparator", background=colors["line"])
        style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
        style.configure("Panel.TLabel", background=colors["surface"], foreground=colors["text"])
        style.configure("AppTitle.TLabel", background=colors["surface"], foreground=colors["text"], font=app_font)
        style.configure("Title.TLabel", background=colors["surface"], foreground=colors["text"], font=title_font)
        style.configure("Small.TLabel", background=colors["surface"], foreground=colors["muted"])
        style.configure(
            "Banner.Idle.TLabel",
            background=colors["idle_bg"],
            foreground=colors["idle_text"],
            padding=(12, 7),
            font=("Microsoft JhengHei UI", 10, "bold"),
        )
        style.configure(
            "Banner.Running.TLabel",
            background=colors["success_bg"],
            foreground=colors["success_text"],
            padding=(12, 7),
            font=("Microsoft JhengHei UI", 10, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=colors["bg"],
            foreground=colors["muted"],
            padding=(16, 9),
        )
        style.configure(
            "TEntry",
            padding=(8, 6),
            fieldbackground="#ffffff",
            foreground=colors["text"],
            bordercolor=colors["line"],
            lightcolor=colors["line"],
            darkcolor=colors["line"],
            insertcolor=colors["text"],
        )
        style.map("TEntry", bordercolor=[("focus", colors["primary"])])
        style.configure(
            "Recipient.TCombobox",
            padding=(8, 6),
            fieldbackground="#ffffff",
            background="#ffffff",
            foreground=colors["text"],
            bordercolor=colors["input_border"],
            lightcolor=colors["input_border"],
            darkcolor=colors["input_border"],
            arrowcolor=colors["primary"],
        )
        style.map(
            "Recipient.TCombobox",
            fieldbackground=[("readonly", "#ffffff")],
            bordercolor=[("focus", colors["primary"])],
            arrowcolor=[("active", colors["primary_hover"])],
        )

        style.configure("TButton", padding=(12, 7), borderwidth=0, focusthickness=0, relief="flat")
        style.map(
            "TButton",
            background=[("active", "#e2e8f0"), ("pressed", "#cbd5e1")],
            foreground=[("disabled", "#94a3b8")],
        )
        style.configure("Primary.TButton", background=colors["primary"], foreground="#ffffff", padding=(14, 8))
        style.map(
            "Primary.TButton",
            background=[("active", colors["primary_hover"]), ("pressed", colors["primary_hover"])],
            foreground=[("disabled", "#dbeafe")],
        )
        style.configure("Danger.TButton", background="#fee2e2", foreground=colors["danger"], padding=(14, 8))
        style.map(
            "Danger.TButton",
            background=[("active", "#fecaca"), ("pressed", "#fecaca")],
            foreground=[("active", colors["danger_hover"])],
        )
        style.configure("Ghost.TButton", background=colors["surface_alt"], foreground=colors["text"], padding=(14, 8))
        style.map("Ghost.TButton", background=[("active", "#e2e8f0"), ("pressed", "#cbd5e1")])

        style.configure(
            "Treeview",
            background=colors["surface"],
            fieldbackground=colors["surface"],
            foreground=colors["text"],
            borderwidth=0,
            rowheight=30,
            relief="flat",
        )
        style.configure(
            "Treeview.Heading",
            background=colors["surface_alt"],
            foreground=colors["muted"],
            padding=(8, 7),
            relief="flat",
            font=("Microsoft JhengHei UI", 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", "#dbeafe")],
            foreground=[("selected", colors["text"])],
        )
        style.configure("TCheckbutton", background=colors["surface"], foreground=colors["text"])
        style.map("TCheckbutton", background=[("active", colors["surface"])])
        style.configure("TRadiobutton", background=colors["surface"], foreground=colors["text"])
        style.map("TRadiobutton", background=[("active", colors["surface"])])
        style.configure(
            "Large.TRadiobutton",
            background=colors["surface"],
            foreground=colors["text"],
            padding=(14, 10),
            font=("Microsoft JhengHei UI", 12),
        )
        style.map("Large.TRadiobutton", background=[("active", colors["surface"])])

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        header = ttk.Frame(self.root, style="Header.TFrame", padding=(18, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(header, text=APP_TITLE, style="AppTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.banner_label = ttk.Label(
            header,
            textvariable=self.banner_var,
            style="Banner.Idle.TLabel",
            anchor="center",
        )
        self.banner_label.grid(row=0, column=1, sticky="e")

        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.grid(row=1, column=0, sticky="nsew", padx=16, pady=16)

        left = ttk.Frame(paned, style="Panel.TFrame", padding=14)
        right = ttk.Frame(paned, style="Panel.TFrame", padding=14)
        paned.add(left, weight=1)
        paned.add(right, weight=3)

        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="腳本", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.script_tree = ttk.Treeview(left, columns=("name", "hotkey", "status"), show="headings", selectmode="browse")
        self.script_tree.heading("name", text="名稱")
        self.script_tree.heading("hotkey", text="快捷鍵")
        self.script_tree.heading("status", text="狀態")
        self.script_tree.column("name", width=180, minwidth=140)
        self.script_tree.column("hotkey", width=86, anchor="center", minwidth=70)
        self.script_tree.column("status", width=120, minwidth=100)
        self.script_tree.tag_configure("running", background="#dbeafe")
        self.script_tree.tag_configure("stopping", background="#fef3c7")
        self.script_tree.tag_configure("script_dragging", background="#bfdbfe")
        self.script_tree.grid(row=1, column=0, sticky="nsew")
        self.script_tree.bind("<<TreeviewSelect>>", self._on_script_selected)
        self.script_tree.bind("<ButtonPress-1>", self._on_script_drag_start)
        self.script_tree.bind("<B1-Motion>", self._on_script_drag_motion)
        self.script_tree.bind("<ButtonRelease-1>", self._on_script_drag_release)

        script_buttons = ttk.Frame(left, style="Toolbar.TFrame")
        script_buttons.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for column in range(3):
            script_buttons.columnconfigure(column, weight=1)

        ttk.Button(script_buttons, text="新增", style="Primary.TButton", command=self._add_script).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(script_buttons, text="複製", style="Ghost.TButton", command=self._duplicate_script).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(script_buttons, text="刪除", style="Danger.TButton", command=self._delete_script).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )
        ttk.Button(script_buttons, text="匯入", style="Ghost.TButton", command=self._import_scripts).grid(
            row=1, column=0, sticky="ew", padx=(0, 4), pady=(8, 0)
        )
        ttk.Button(script_buttons, text="匯出", style="Ghost.TButton", command=self._export_scripts).grid(
            row=1, column=1, sticky="ew", padx=4, pady=(8, 0)
        )
        self.toggle_button = ttk.Button(
            script_buttons,
            text="啟動",
            style="Primary.TButton",
            command=self._toggle_selected_script,
        )
        self.toggle_button.grid(row=1, column=2, sticky="ew", padx=(4, 0), pady=(8, 0))

        overlay_frame = ttk.Frame(left, style="Panel.TFrame")
        overlay_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(
            overlay_frame,
            text="顯示腳本懸浮提示",
            variable=self.running_overlay_enabled_var,
            command=self._on_running_overlay_toggled,
        ).grid(row=0, column=0, sticky="w")

        ttk.Separator(left).grid(row=4, column=0, sticky="ew", pady=(14, 10))
        monitor_frame = ttk.Frame(left, style="Panel.TFrame")
        monitor_frame.grid(row=5, column=0, sticky="ew")
        monitor_frame.columnconfigure(1, weight=1)

        ttk.Label(monitor_frame, text="測謊偵測", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )
        ttk.Checkbutton(
            monitor_frame,
            text="開啟測謊偵測",
            variable=self.recaptcha_enabled_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Checkbutton(
            monitor_frame,
            text="只偵測楓之谷視窗",
            variable=self.recaptcha_maplestory_only_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 8))
        ttk.Label(monitor_frame, text="通知對象", style="Panel.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 8)
        )
        self.recaptcha_recipient_combo = ttk.Combobox(
            monitor_frame,
            textvariable=self.recaptcha_recipient_name_var,
            values=discord_recipient_names(),
            state="readonly",
            style="Recipient.TCombobox",
        )
        self.recaptcha_recipient_combo.grid(row=3, column=1, sticky="ew")
        ttk.Label(monitor_frame, text="綁定 User", style="Panel.TLabel").grid(
            row=4, column=0, sticky="w", padx=(0, 8), pady=(8, 0)
        )
        ttk.Label(
            monitor_frame,
            textvariable=self.recaptcha_bound_user_id_var,
            style="Small.TLabel",
        ).grid(row=4, column=1, sticky="w", pady=(8, 0))
        ttk.Label(monitor_frame, text="Webhook", style="Panel.TLabel").grid(
            row=5, column=0, sticky="nw", padx=(0, 8), pady=(8, 0)
        )
        ttk.Label(
            monitor_frame,
            textvariable=self.recaptcha_bound_webhook_var,
            style="Small.TLabel",
            wraplength=240,
        ).grid(row=5, column=1, sticky="ew", pady=(8, 0))
        ttk.Label(
            monitor_frame,
            textvariable=self.recaptcha_status_var,
            style="Small.TLabel",
            wraplength=240,
        ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))

        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        editor = ttk.Frame(right, style="Panel.TFrame")
        editor.grid(row=0, column=0, sticky="ew")
        editor.columnconfigure(1, weight=1)

        ttk.Label(editor, text="腳本名稱", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 10)
        )
        self.name_entry = RoundedEntry(editor, textvariable=self.name_var, colors=self.colors)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(editor, text="快捷鍵", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 10)
        )
        hotkey_row = ttk.Frame(editor, style="Panel.TFrame")
        hotkey_row.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        hotkey_row.columnconfigure(0, weight=1)
        self.hotkey_entry = RoundedEntry(hotkey_row, textvariable=self.hotkey_var, colors=self.colors)
        self.hotkey_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.hotkey_entry.bind("<KeyPress>", self._capture_hotkey_from_entry)
        self.hotkey_entry.bind("<FocusOut>", self._cancel_hotkey_recording)
        self.hotkey_entry.configure(state="disabled")
        ttk.Button(hotkey_row, text="綁定", style="Ghost.TButton", command=self._capture_hotkey).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(hotkey_row, text="清除", style="Ghost.TButton", command=self._clear_hotkey).grid(row=0, column=2)
        ttk.Label(hotkey_row, textvariable=self.hotkey_hint_var, style="Small.TLabel").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        ttk.Checkbutton(editor, text="循環執行直到停止", variable=self.repeat_var).grid(
            row=2, column=1, sticky="w", pady=(0, 8)
        )

        editor_status = ttk.Label(editor, text="腳本設定會自動儲存", style="Small.TLabel")
        editor_status.grid(row=3, column=1, sticky="e")

        ttk.Separator(right).grid(row=1, column=0, sticky="ew", pady=10)
        ttk.Label(right, text="按鍵步驟", style="Title.TLabel").grid(row=2, column=0, sticky="w", pady=(0, 8))

        self.step_tree = ttk.Treeview(right, columns=("action", "key", "delay"), show="headings", selectmode="extended")
        self.step_tree.heading("action", text="動作")
        self.step_tree.heading("key", text="內容")
        self.step_tree.heading("delay", text="延遲")
        self.step_tree.column("action", width=120, minwidth=100)
        self.step_tree.column("key", width=180, minwidth=120)
        self.step_tree.column("delay", width=110, minwidth=90, anchor="center")
        self.step_tree.tag_configure("step_odd", background="#ffffff")
        self.step_tree.tag_configure("step_even", background="#f8fafc")
        self.step_tree.tag_configure("step_dragging", background="#bfdbfe")
        self.step_tree.tag_configure("step_drop_before", background="#fde68a")
        self.step_tree.tag_configure("step_drop_after", background="#fde68a")
        self.step_tree.grid(row=3, column=0, sticky="nsew")
        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_selected)
        self.step_tree.bind("<Delete>", self._delete_selected_steps_event)
        self.step_tree.bind("<Control-c>", self._copy_selected_steps_event)
        self.step_tree.bind("<Control-C>", self._copy_selected_steps_event)
        self.step_tree.bind("<Control-v>", self._paste_steps_event)
        self.step_tree.bind("<Control-V>", self._paste_steps_event)
        self.step_tree.bind("<Control-a>", self._select_all_steps_event)
        self.step_tree.bind("<Control-A>", self._select_all_steps_event)
        self.step_tree.bind("<ButtonPress-1>", self._on_step_drag_start)
        self.step_tree.bind("<B1-Motion>", self._on_step_drag_motion)
        self.step_tree.bind("<ButtonRelease-1>", self._on_step_drag_release)

        step_form = ttk.Frame(right, style="Panel.TFrame")
        step_form.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        step_form.columnconfigure(1, weight=1)

        ttk.Label(step_form, text="動作", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 6))
        action_options = ttk.Frame(step_form, style="Panel.TFrame")
        action_options.grid(row=0, column=1, sticky="w", padx=(0, 10))
        ttk.Radiobutton(
            action_options,
            text=FORM_ACTION_LABELS[FORM_ACTION_KEY_COMMAND],
            value=FORM_ACTION_LABELS[FORM_ACTION_KEY_COMMAND],
            variable=self.step_action_var,
            command=self._on_step_action_changed,
            style="Large.TRadiobutton",
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Radiobutton(
            action_options,
            text=FORM_ACTION_LABELS[FORM_ACTION_DELAY],
            value=FORM_ACTION_LABELS[FORM_ACTION_DELAY],
            variable=self.step_action_var,
            command=self._on_step_action_changed,
            style="Large.TRadiobutton",
        ).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Radiobutton(
            action_options,
            text=FORM_ACTION_LABELS[FORM_ACTION_SCRIPT_CALL],
            value=FORM_ACTION_LABELS[FORM_ACTION_SCRIPT_CALL],
            variable=self.step_action_var,
            command=self._on_step_action_changed,
            style="Large.TRadiobutton",
        ).grid(row=0, column=2, sticky="w")

        self.key_settings_frame = ttk.Frame(step_form, style="Panel.TFrame")
        self.key_settings_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.key_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.key_settings_frame, text="按鍵動作", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        key_mode_options = ttk.Frame(self.key_settings_frame, style="Panel.TFrame")
        key_mode_options.grid(row=0, column=1, columnspan=2, sticky="w", padx=(0, 6))
        for column, mode in enumerate((KEY_MODE_BOTH, KEY_MODE_DOWN, KEY_MODE_UP)):
            ttk.Radiobutton(
                key_mode_options,
                text=KEY_MODE_LABELS[mode],
                value=mode,
                variable=self.step_key_mode_var,
                style="Large.TRadiobutton",
            ).grid(row=0, column=column, sticky="w", padx=(0, 12))
        ttk.Label(self.key_settings_frame, text="按鍵", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 6), pady=(8, 0)
        )
        self.step_key_entry = RoundedEntry(
            self.key_settings_frame,
            textvariable=self.step_key_var,
            width=18,
            colors=self.colors,
        )
        self.step_key_entry.grid(row=1, column=1, sticky="ew", padx=(0, 6), pady=(8, 0))
        self.step_key_entry.bind("<KeyPress>", self._capture_step_key_from_entry)
        ttk.Button(self.key_settings_frame, text="錄製", style="Ghost.TButton", command=self._capture_step_key).grid(
            row=1, column=2, sticky="ew", pady=(8, 0)
        )
        ttk.Label(
            self.key_settings_frame,
            text="可輸入單鍵、組合鍵，或用逗號同時按多鍵，例如 X, SPACE。",
            style="Small.TLabel",
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0))

        self.delay_settings_frame = ttk.Frame(step_form, style="Panel.TFrame")
        self.delay_settings_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.delay_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.delay_settings_frame, text="延遲 ms", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.step_delay_entry = RoundedEntry(
            self.delay_settings_frame,
            textvariable=self.step_delay_ms_var,
            width=12,
            colors=self.colors,
        )
        self.step_delay_entry.grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(
            self.delay_settings_frame,
            text="延遲是獨立動作；若前面有按下按鍵，延遲期間會持續維持按住。",
            style="Small.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(6, 0))

        self.script_call_settings_frame = ttk.Frame(step_form, style="Panel.TFrame")
        self.script_call_settings_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.script_call_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.script_call_settings_frame, text="腳本", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.step_script_combo = ttk.Combobox(
            self.script_call_settings_frame,
            textvariable=self.step_script_var,
            values=(),
            state="readonly",
            style="Recipient.TCombobox",
        )
        self.step_script_combo.grid(row=0, column=1, sticky="ew")
        self._on_step_action_changed()

        step_buttons = ttk.Frame(right, style="Toolbar.TFrame")
        step_buttons.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        for column in range(5):
            step_buttons.columnconfigure(column, weight=1)

        ttk.Button(step_buttons, text="新增步驟", style="Primary.TButton", command=self._add_step).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(step_buttons, text="複製指令", style="Ghost.TButton", command=self._copy_steps).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(step_buttons, text="刪除步驟", style="Danger.TButton", command=self._delete_step).grid(
            row=0, column=2, sticky="ew", padx=4
        )
        ttk.Button(step_buttons, text="上移", style="Ghost.TButton", command=lambda: self._move_step(-1)).grid(
            row=0, column=3, sticky="ew", padx=4
        )
        ttk.Button(step_buttons, text="下移", style="Ghost.TButton", command=lambda: self._move_step(1)).grid(
            row=0, column=4, sticky="ew", padx=(4, 0)
        )

        ttk.Label(
            right,
            text="範例：X 按下按鍵 -> 延遲 1000 ms -> X 放開按鍵。延遲期間會持續補送已按住的鍵。",
            style="Small.TLabel",
        ).grid(row=6, column=0, sticky="w", pady=(8, 0))

        ttk.Label(self.root, textvariable=self.status_var, style="Status.TLabel", anchor="w").grid(
            row=2, column=0, sticky="ew"
        )

    def _selected_script_id(self) -> str | None:
        selection = self.script_tree.selection()
        return selection[0] if selection else None

    def _selected_script(self) -> Script | None:
        script_id = self._selected_script_id()
        if script_id is None:
            return None
        return self._find_script(script_id)

    def _find_script(self, script_id: str) -> Script | None:
        return next((script for script in self.scripts if script.id == script_id), None)

    def _script_call_label(self, script: Script, name_counts: dict[str, int] | None = None) -> str:
        if name_counts is None:
            name_counts = {item.name: sum(1 for script_item in self.scripts if script_item.name == item.name) for item in self.scripts}
        if name_counts.get(script.name, 0) > 1:
            return f"{script.name} ({script.id[:8]})"
        return script.name

    def _refresh_script_call_choices(self) -> None:
        if not hasattr(self, "step_script_combo"):
            return

        current_label = self.step_script_var.get()
        current_target_id = self._script_call_choice_by_label.get(current_label, "")
        current_script_id = self._selected_script_id()
        name_counts: dict[str, int] = {}
        for script in self.scripts:
            name_counts[script.name] = name_counts.get(script.name, 0) + 1

        options = [
            (self._script_call_label(script, name_counts), script.id)
            for script in self.scripts
            if script.id != current_script_id
        ]
        self._script_call_choice_by_label = {label: script_id for label, script_id in options}
        self._script_call_label_by_id = {script_id: label for label, script_id in options}
        self.step_script_combo.configure(values=[label for label, _script_id in options])

        if current_target_id in self._script_call_label_by_id:
            self.step_script_var.set(self._script_call_label_by_id[current_target_id])

    def _select_default_script_call_target(self) -> None:
        self._refresh_script_call_choices()
        if self.step_script_var.get() not in self._script_call_choice_by_label and self._script_call_label_by_id:
            first_label = next(iter(self._script_call_choice_by_label))
            self.step_script_var.set(first_label)

    def _set_script_call_target(self, script_id: str) -> None:
        self._refresh_script_call_choices()
        label = self._script_call_label_by_id.get(script_id)
        if label is not None:
            self.step_script_var.set(label)
            return

        script = self._find_script(script_id)
        if script is not None:
            self.step_script_var.set(f"{script.name} (目前腳本)")
        elif script_id:
            self.step_script_var.set(f"找不到腳本 ({script_id[:8]})")
        else:
            self.step_script_var.set("")

    def _selected_script_call_target_id(self) -> str:
        return self._script_call_choice_by_label.get(self.step_script_var.get(), "")

    def _step_script_display(self, step: Step) -> str:
        script = self._find_script(step.script_id)
        if script is not None:
            return script.name
        if step.script_id:
            return f"找不到腳本 ({step.script_id[:8]})"
        return "未選擇腳本"

    def _select_first_script(self) -> None:
        if self.scripts:
            self.script_tree.selection_set(self.scripts[0].id)
            self.script_tree.focus(self.scripts[0].id)
            self._load_script_into_editor(self.scripts[0])

    def _refresh_script_tree(self) -> None:
        selected = self._selected_script_id()
        existing = set(self.script_tree.get_children())
        wanted_order = [script.id for script in self.scripts]
        wanted = set(wanted_order)

        for item in existing - wanted:
            self.script_tree.delete(item)

        for index, script in enumerate(self.scripts):
            values = (script.name, script.hotkey or "綁定", self._status_for(script.id))
            tags = self._tags_for(script.id)
            if self._script_dragging and script.id == self._script_drag_start_id:
                tags = tags + ("script_dragging",)
            if script.id in existing:
                current_values = tuple(self.script_tree.item(script.id, "values"))
                current_tags = tuple(self.script_tree.item(script.id, "tags"))
                if current_values != values or current_tags != tags:
                    self.script_tree.item(script.id, values=values, tags=tags)
            else:
                self.script_tree.insert("", index, iid=script.id, values=values, tags=tags)

        if not self._script_dragging:
            self._sync_script_tree_order(wanted_order)
        if selected in wanted:
            if self.script_tree.selection() != (selected,):
                self.script_tree.selection_set(selected)
            if self.script_tree.focus() != selected:
                self.script_tree.focus(selected)

        self._update_banner()
        self._sync_running_overlay()
        self._update_toggle_button()
        self._refresh_script_call_choices()

    def _sync_script_tree_order(self, wanted_order: list[str]) -> None:
        if list(self.script_tree.get_children()) == wanted_order:
            return

        for index, script_id in enumerate(wanted_order):
            if self.script_tree.exists(script_id):
                self.script_tree.move(script_id, "", index)

    def _reset_script_drag_state(self) -> None:
        self._script_drag_start_y = None
        self._script_drag_start_id = None
        self._script_dragging = False
        self._script_drag_insert_index = None
        self._retag_script_tree_display_order()

    def _apply_script_drag_preview(self, insert_index: int) -> None:
        dragged_id = self._script_drag_start_id
        current_order = list(self.script_tree.get_children())
        if dragged_id is None or dragged_id not in current_order:
            return
        if self._script_drag_insert_index == insert_index:
            return

        self._script_drag_insert_index = insert_index
        dragged_position = current_order.index(dragged_id)
        adjusted_index = insert_index - (1 if dragged_position < insert_index else 0)
        adjusted_index = max(0, min(adjusted_index, len(current_order) - 1))

        if dragged_position != adjusted_index:
            self.script_tree.move(dragged_id, "", adjusted_index)
        self.script_tree.selection_set(dragged_id)
        self.script_tree.focus(dragged_id)
        self._retag_script_tree_display_order(dragging_id=dragged_id)

    def _retag_script_tree_display_order(self, dragging_id: str | None = None) -> None:
        for item in self.script_tree.get_children():
            tags = list(self._tags_for(item))
            if item == dragging_id:
                tags.append("script_dragging")
            self.script_tree.item(item, tags=tuple(tags))

    def _on_script_drag_start(self, event: tk.Event) -> str | None:
        if self.script_tree.identify_region(event.x, event.y) == "heading":
            return None

        row = self.script_tree.identify_row(event.y)
        if not row:
            self._reset_script_drag_state()
            return None

        self._script_drag_start_y = event.y
        self._script_drag_start_id = row
        self._script_dragging = False
        self._script_drag_insert_index = None
        return None

    def _on_script_drag_motion(self, event: tk.Event) -> str | None:
        if self._script_drag_start_y is None or self._script_drag_start_id is None:
            return None
        if not self._script_dragging and abs(event.y - self._script_drag_start_y) < 6:
            return None
        if self.script_tree.identify_region(event.x, event.y) == "heading":
            return None
        if self._script_drag_start_id not in self.script_tree.get_children():
            self._reset_script_drag_state()
            return None

        self._script_dragging = True
        insert_index = self._script_drop_index(event.y)
        self._apply_script_drag_preview(insert_index)
        if event.y < 0:
            self.script_tree.yview_scroll(-1, "units")
        elif event.y > self.script_tree.winfo_height():
            self.script_tree.yview_scroll(1, "units")
        self.status_var.set(f"拖曳排序腳本到第 {insert_index + 1} 個位置。")
        return "break"

    def _on_script_drag_release(self, _event: tk.Event) -> str | None:
        if not self._script_dragging or self._script_drag_start_id is None:
            self._reset_script_drag_state()
            return None

        moved_id = self._script_drag_start_id
        preview_order = list(self.script_tree.get_children())
        self._reset_script_drag_state()
        self._apply_script_preview_order(preview_order, moved_id)
        return "break"

    def _script_drop_index(self, y: int) -> int:
        script_count = len(self.scripts)
        children = list(self.script_tree.get_children())
        row = self.script_tree.identify_row(y)
        if not row:
            return script_count if y > self.script_tree.winfo_height() // 2 else 0

        try:
            row_index = children.index(row)
        except ValueError:
            return script_count

        bbox = self.script_tree.bbox(row)
        if bbox and y > bbox[1] + (bbox[3] // 2):
            row_index += 1
        return max(0, min(row_index, script_count))

    def _apply_script_preview_order(self, item_order: list[str], moved_id: str) -> None:
        script_by_id = {script.id: script for script in self.scripts}
        ordered_scripts = [script_by_id[item] for item in item_order if item in script_by_id]
        if len(ordered_scripts) != len(self.scripts):
            self._refresh_script_tree()
            return

        if ordered_scripts == self.scripts:
            self._refresh_script_tree()
            self.script_tree.selection_set(moved_id)
            self.script_tree.focus(moved_id)
            return

        self.scripts = ordered_scripts
        self._save_all()
        self._refresh_script_tree()
        self.script_tree.selection_set(moved_id)
        self.script_tree.focus(moved_id)
        self.status_var.set("已調整腳本順序。")

    def _refresh_step_tree(self, script: Script | None = None) -> None:
        self._stop_step_drag_pulse()
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)

        script = script or self._selected_script()
        if script is None:
            return

        for index, step in enumerate(script.steps):
            if step.needs_key():
                key = step.key
            elif step.needs_script():
                key = self._step_script_display(step)
            else:
                key = ""
            delay = format_delay_ms(step.delay_ms) if step.action == ACTION_DELAY else ""
            self.step_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(step.display_action(), key, delay),
                tags=self._step_base_tags(index),
            )

    def _step_base_tags(self, index: int) -> tuple[str, ...]:
        return ("step_odd",) if index % 2 == 0 else ("step_even",)

    def _status_for(self, script_id: str) -> str:
        if script_id in self.runners:
            detail = self.current_step.get(script_id, "執行中")
            return f"執行中: {detail}" if detail and detail != "執行中" else "執行中"
        if self.current_step.get(script_id) == "停止中":
            return "停止中"
        return "待命"

    def _tags_for(self, script_id: str) -> tuple[str, ...]:
        if script_id in self.runners:
            return ("running",)
        if self.current_step.get(script_id) == "停止中":
            return ("stopping",)
        return ()

    def _update_banner(self) -> None:
        running_names = self._running_script_names()
        if running_names:
            self.banner_var.set("執行中：" + "、".join(running_names))
            self.banner_label.configure(style="Banner.Running.TLabel")
        else:
            self.banner_var.set("待命")
            self.banner_label.configure(style="Banner.Idle.TLabel")

    def _running_script_names(self) -> list[str]:
        return [script.name for script in self.scripts if script.id in self.runners]

    def _sync_running_overlay(self) -> None:
        if not hasattr(self, "running_overlay"):
            return
        if not bool(self.running_overlay_enabled_var.get()):
            self.running_overlay.hide()
            return

        text = format_running_overlay_text(self._running_script_names())
        if not text:
            self.running_overlay.hide()
            return

        try:
            bbox = self.maplestory_window_locator.find_foreground_window_bbox()
        except Exception:
            bbox = None
        if bbox is None:
            if self.running_overlay.is_interacting_or_foreground():
                bbox = self._running_overlay_window_bbox
            if bbox is None:
                self._running_overlay_window_bbox = None
                self.running_overlay.hide()
                return
        else:
            self._running_overlay_window_bbox = bbox

        window_size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        if window_size != self._running_overlay_window_size:
            self._running_overlay_window_size = window_size
            self._running_overlay_offset = (RUNNING_OVERLAY_OFFSET_X, RUNNING_OVERLAY_OFFSET_Y)

        offset_x, offset_y = self._running_overlay_offset
        self.running_overlay.show(
            text,
            bbox[0] + offset_x,
            bbox[1] + offset_y,
            bounds=bbox,
        )

    def _on_running_overlay_moved(self, x: int, y: int) -> None:
        try:
            bbox = self.maplestory_window_locator.find_foreground_window_bbox()
        except Exception:
            bbox = None
        if bbox is None:
            bbox = self._running_overlay_window_bbox
        if bbox is None:
            return

        self._running_overlay_window_bbox = bbox

        self._running_overlay_window_size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        self._running_overlay_offset = (x - bbox[0], y - bbox[1])

    def _poll_window_events(self) -> None:
        if self._closing:
            return

        self._window_event_after_id = None
        should_sync = False
        while True:
            try:
                self.window_event_hook.events.get_nowait()
            except queue.Empty:
                break
            should_sync = True

        if should_sync:
            self._sync_running_overlay()

        self._window_event_after_id = self.root.after(
            WINDOW_EVENT_POLL_INTERVAL_MS,
            self._poll_window_events,
        )

    def _on_running_overlay_toggled(self) -> None:
        enabled = bool(self.running_overlay_enabled_var.get())
        self.running_overlay_settings = RunningOverlaySettings(enabled=enabled)
        try:
            save_running_overlay_settings(self.running_overlay_settings)
        except Exception as exc:
            self.status_var.set(f"儲存腳本懸浮提示設定失敗：{exc}")
        else:
            state = "開啟" if enabled else "關閉"
            self.status_var.set(f"已{state}腳本懸浮提示。")
        self._sync_running_overlay()

    def _update_toggle_button(self) -> None:
        script_id = self._selected_script_id()
        if script_id in self.runners:
            self.toggle_button.configure(text="停止", style="Danger.TButton")
        else:
            self.toggle_button.configure(text="啟動", style="Primary.TButton")

    def _on_script_selected(self, _event: tk.Event | None = None) -> None:
        script = self._selected_script()
        if script is None:
            return
        self._load_script_into_editor(script)
        self._update_toggle_button()

    def _load_script_into_editor(self, script: Script) -> None:
        self._loading_script = True
        try:
            self.name_var.set(script.name)
            self.hotkey_var.set(script.hotkey)
            self.repeat_var.set(script.repeat)
            self._refresh_script_call_choices()
            self._refresh_step_tree(script)
        finally:
            self._loading_script = False

    def _add_script(self) -> None:
        hotkeys = {script.hotkey.upper() for script in self.scripts}
        default_hotkey = ""
        for candidate in ["F8", "F9", "F10", "F11", "F12"]:
            if candidate not in hotkeys:
                default_hotkey = candidate
                break

        script = Script(
            id=str(uuid.uuid4()),
            name=f"新腳本 {len(self.scripts) + 1}",
            hotkey=default_hotkey,
            repeat=True,
            steps=[
                Step(ACTION_KEY_DOWN, key="SPACE"),
                Step(ACTION_DELAY, delay_ms=100),
                Step(ACTION_KEY_UP, key="SPACE"),
                Step(ACTION_DELAY, delay_ms=900),
            ],
        )
        self.scripts.append(script)
        self._save_all()
        self._refresh_script_tree()
        self.script_tree.selection_set(script.id)
        self.script_tree.focus(script.id)
        self._load_script_into_editor(script)
        self.status_var.set("已新增腳本。")

    def _duplicate_script(self) -> None:
        script = self._selected_script()
        if script is None:
            return

        copied = script.clone()
        copied.id = str(uuid.uuid4())
        copied.name = f"{script.name} 複本"
        copied.hotkey = ""
        self.scripts.append(copied)
        self._save_all()
        self._refresh_script_tree()
        self.script_tree.selection_set(copied.id)
        self.script_tree.focus(copied.id)
        self._load_script_into_editor(copied)
        self.status_var.set("已複製腳本，請設定新的快捷鍵。")

    def _delete_script(self) -> None:
        script = self._selected_script()
        if script is None:
            return

        referenced_by = [
            item.name
            for item in self.scripts
            if item.id != script.id and any(step.needs_script() and step.script_id == script.id for step in item.steps)
        ]
        message = f"確定刪除「{script.name}」？"
        if referenced_by:
            message += f"\n\n有 {len(referenced_by)} 個腳本正在呼叫它，刪除後那些步驟會無法執行。"
        if not messagebox.askyesno(APP_TITLE, message):
            return

        if script.id in self.runners:
            self.runners[script.id].stop()

        self.scripts = [item for item in self.scripts if item.id != script.id]
        self.current_step.pop(script.id, None)
        self._save_all()
        self._refresh_script_tree()
        self._select_first_script()
        self.status_var.set("已刪除腳本。")

    def _export_scripts(self) -> None:
        if not self.scripts:
            messagebox.showwarning(APP_TITLE, "沒有可匯出的腳本。")
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="匯出腳本",
            defaultextension=".json",
            initialfile="autokeyboard_scripts.json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return

        data = {
            "app": APP_NAME,
            "format": "autokeyboard.scripts",
            "version": 1,
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scripts": [script.to_dict() for script in self.scripts],
        }
        try:
            Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"匯出失敗：\n{exc}")
            return

        self.status_var.set(f"已匯出 {len(self.scripts)} 個腳本。")

    def _import_scripts(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="匯入腳本",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return

        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            imported_scripts = self._scripts_from_import_data(data)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror(APP_TITLE, f"匯入失敗：\n{exc}")
            return

        if not imported_scripts:
            messagebox.showwarning(APP_TITLE, "檔案中沒有可匯入的腳本。")
            return

        used_names = {script.name for script in self.scripts}
        imported_id_map: dict[str, str] = {}
        for script in imported_scripts:
            original_id = script.id
            script.id = str(uuid.uuid4())
            imported_id_map[original_id] = script.id
            script.hotkey = ""
            script.name = self._unique_imported_script_name(script.name, used_names)
            used_names.add(script.name)

        for script in imported_scripts:
            for step in script.steps:
                if step.needs_script() and step.script_id in imported_id_map:
                    step.script_id = imported_id_map[step.script_id]

        self.scripts.extend(imported_scripts)
        self._save_all()
        self._refresh_script_tree()
        first_imported = imported_scripts[0]
        self.script_tree.selection_set(first_imported.id)
        self.script_tree.focus(first_imported.id)
        self._load_script_into_editor(first_imported)
        self.status_var.set(f"已匯入 {len(imported_scripts)} 個腳本，快捷鍵已清空以避免衝突。")

    def _scripts_from_import_data(self, data) -> list[Script]:
        if isinstance(data, list):
            raw_scripts = data
        elif isinstance(data, dict) and isinstance(data.get("scripts"), list):
            raw_scripts = data["scripts"]
        elif isinstance(data, dict) and isinstance(data.get("script"), dict):
            raw_scripts = [data["script"]]
        elif isinstance(data, dict) and "steps" in data:
            raw_scripts = [data]
        else:
            raise ValueError("檔案格式不正確，找不到 scripts。")

        scripts: list[Script] = []
        for index, item in enumerate(raw_scripts, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index} 個腳本格式不正確。")
            scripts.append(Script.from_dict(item))
        return scripts

    def _unique_imported_script_name(self, name: str, existing_names: set[str]) -> str:
        if name not in existing_names:
            return name

        base = f"{name} 匯入"
        if base not in existing_names:
            return base

        counter = 2
        while f"{base} {counter}" in existing_names:
            counter += 1
        return f"{base} {counter}"

    def _save_current_script(self) -> None:
        script = self._selected_script()
        if script is None:
            return

        name = self.name_var.get().strip()
        hotkey = self.hotkey_var.get().strip().upper()
        if not name:
            messagebox.showerror(APP_TITLE, "腳本名稱不能是空白。")
            return

        if hotkey:
            try:
                KeyResolver.parse_hotkey(hotkey)
            except ValueError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
                return
            duplicate = self._find_duplicate_hotkey_script(script.id, hotkey)
            if duplicate is not None:
                messagebox.showerror(APP_TITLE, f"快捷鍵 {hotkey} 已被「{duplicate.name}」使用。")
                return

        script.name = name
        script.hotkey = hotkey
        script.repeat = bool(self.repeat_var.get())
        self._save_all()
        self._refresh_script_tree()
        self._register_hotkeys(show_dialog=True)

    def _bind_auto_save(self) -> None:
        for variable in (self.name_var, self.hotkey_var, self.repeat_var):
            variable.trace_add("write", self._schedule_auto_save_script_settings)
        for variable in (self.step_key_mode_var, self.step_key_var, self.step_delay_ms_var, self.step_script_var):
            variable.trace_add("write", self._schedule_auto_save_selected_step)
        for variable in (
            self.recaptcha_enabled_var,
            self.recaptcha_maplestory_only_var,
            self.recaptcha_recipient_name_var,
        ):
            variable.trace_add("write", self._schedule_recaptcha_settings_save)

    def _schedule_auto_save_script_settings(self, *_args) -> None:
        if self._loading_script:
            return
        if self._auto_save_after_id is not None:
            self.root.after_cancel(self._auto_save_after_id)
        self._auto_save_after_id = self.root.after(300, self._auto_save_script_settings)

    def _auto_save_script_settings(self) -> None:
        self._auto_save_after_id = None
        script = self._selected_script()
        if script is None:
            return

        name = self.name_var.get().strip()
        hotkey = self.hotkey_var.get().strip().upper()
        if not name:
            self.status_var.set("腳本名稱不能空白，尚未自動儲存。")
            return

        if hotkey:
            try:
                KeyResolver.parse_hotkey(hotkey)
            except ValueError as exc:
                self.status_var.set(f"快捷鍵無效，尚未自動儲存：{exc}")
                return
            duplicate = self._find_duplicate_hotkey_script(script.id, hotkey)
            if duplicate is not None:
                self._loading_script = True
                try:
                    self.hotkey_var.set(script.hotkey)
                finally:
                    self._loading_script = False
                self.status_var.set(f"快捷鍵 {hotkey} 已被「{duplicate.name}」使用，未套用。")
                return

        changed = script.name != name or script.hotkey != hotkey or script.repeat != bool(self.repeat_var.get())
        script.name = name
        script.hotkey = hotkey
        script.repeat = bool(self.repeat_var.get())
        self._save_all()
        self._refresh_script_tree()
        if changed:
            self.status_var.set("腳本設定已自動儲存。")
        self._schedule_hotkey_register()

    def _schedule_recaptcha_settings_save(self, *_args) -> None:
        if self._loading_recaptcha_settings:
            return
        if self._recaptcha_save_after_id is not None:
            self.root.after_cancel(self._recaptcha_save_after_id)
        self._recaptcha_save_after_id = self.root.after(300, self._save_recaptcha_settings_from_ui)

    def _save_recaptcha_settings_from_ui(self) -> None:
        self._recaptcha_save_after_id = None
        recipient_name = normalized_discord_recipient_name(self.recaptcha_recipient_name_var.get())
        if recipient_name != self.recaptcha_recipient_name_var.get().strip():
            self._loading_recaptcha_settings = True
            try:
                self.recaptcha_recipient_name_var.set(recipient_name)
            finally:
                self._loading_recaptcha_settings = False

        settings = RecaptchaMonitorSettings(
            enabled=bool(self.recaptcha_enabled_var.get()),
            recipient_name=recipient_name,
            only_maplestory_window=bool(self.recaptcha_maplestory_only_var.get()),
        )
        self.recaptcha_settings = settings
        self._refresh_recaptcha_binding_display()
        try:
            save_recaptcha_monitor_settings(settings)
        except OSError as exc:
            self.recaptcha_status_var.set(f"儲存測謊偵測設定失敗：{exc}")
            return

        self.recaptcha_monitor.set_settings(settings)
        self._update_recaptcha_status_from_settings(saved=True)

    def _refresh_recaptcha_binding_display(self) -> None:
        recipient = discord_recipient_for_name(self.recaptcha_recipient_name_var.get())
        if recipient is None:
            self.recaptcha_bound_user_id_var.set("尚未選擇")
            self.recaptcha_bound_webhook_var.set("尚未選擇")
            return
        self.recaptcha_bound_user_id_var.set(f"{recipient.name} / {recipient.user_id}")
        self.recaptcha_bound_webhook_var.set(recipient.webhook_url)

    def _update_recaptcha_status_from_settings(self, *, saved: bool) -> None:
        if not self.recaptcha_enabled_var.get():
            message = "偵測已關閉。"
        elif discord_recipient_for_name(self.recaptcha_recipient_name_var.get()) is None:
            message = "請先選擇通知對象，才會開始測謊偵測。"
        else:
            scope = "只偵測楓之谷視窗" if self.recaptcha_maplestory_only_var.get() else "偵測目前 focus 視窗"
            message = f"{scope}中央區域；連續命中才通知。"

        if saved:
            message = f"{message} 已儲存。"
        self.recaptcha_status_var.set(message)

    def _schedule_hotkey_register(self) -> None:
        if self._hotkey_register_after_id is not None:
            self.root.after_cancel(self._hotkey_register_after_id)
        self._hotkey_register_after_id = self.root.after(250, self._register_hotkeys_from_auto_save)

    def _register_hotkeys_from_auto_save(self) -> None:
        self._hotkey_register_after_id = None
        if self._recording_hotkey:
            return
        self._register_hotkeys(show_dialog=False)

    def _hotkey_signature(self, hotkey: str) -> tuple[int, int] | None:
        hotkey = hotkey.strip()
        if not hotkey:
            return None
        return KeyResolver.parse_hotkey(hotkey)

    def _find_duplicate_hotkey_script(self, current_script_id: str, hotkey: str) -> Script | None:
        try:
            signature = self._hotkey_signature(hotkey)
        except ValueError:
            return None
        if signature is None:
            return None

        for script in self.scripts:
            if script.id == current_script_id or not script.hotkey.strip():
                continue
            try:
                other_signature = self._hotkey_signature(script.hotkey)
            except ValueError:
                continue
            if other_signature == signature:
                return script
        return None

    def _save_all(self) -> None:
        save_scripts(self.scripts)

    def _register_hotkeys(self, show_dialog: bool) -> None:
        errors = self.hotkeys.set_hotkeys(self.scripts)
        if errors:
            message = "；".join(errors)
            self.status_var.set(message)
            if show_dialog:
                messagebox.showwarning(APP_TITLE, "\n".join(errors))
        else:
            self.status_var.set("快捷鍵已註冊。")

    def _clear_pending_hotkey_events(self) -> None:
        while True:
            try:
                self.hotkeys.events.get_nowait()
            except queue.Empty:
                return

    def _capture_hotkey(self) -> None:
        if self._hotkey_register_after_id is not None:
            self.root.after_cancel(self._hotkey_register_after_id)
            self._hotkey_register_after_id = None
        self.hotkeys.set_hotkeys([])
        self._clear_pending_hotkey_events()
        self._recording_hotkey = True
        self.hotkey_entry.configure(state="normal")
        self.hotkey_entry.focus_set()
        self.hotkey_entry.selection_range(0, tk.END)
        self.hotkey_hint_var.set("請按下要設定的快捷鍵")
        self.status_var.set("請按下要設定的快捷鍵。")

    def _clear_hotkey(self) -> None:
        script = self._selected_script()
        if script is None:
            return

        if self._hotkey_register_after_id is not None:
            self.root.after_cancel(self._hotkey_register_after_id)
            self._hotkey_register_after_id = None
        if self._recording_hotkey:
            self._recording_hotkey = False
            self.hotkey_entry.configure(state="disabled")
            self._clear_pending_hotkey_events()

        self._loading_script = True
        try:
            self.hotkey_var.set("")
        finally:
            self._loading_script = False
        self.hotkey_hint_var.set("按「綁定」設定腳本快捷鍵")

        if script.hotkey:
            script.hotkey = ""
            self._save_all()
            self._refresh_script_tree()
            errors = self.hotkeys.set_hotkeys(self.scripts)
            if errors:
                self.status_var.set("；".join(errors))
            else:
                self.status_var.set("已清除快捷鍵。")
        else:
            errors = self.hotkeys.set_hotkeys(self.scripts)
            if errors:
                self.status_var.set("；".join(errors))
            else:
                self.status_var.set("快捷鍵已是空白。")

    def _finish_hotkey_recording(self, message: str | None = None) -> None:
        self._recording_hotkey = False
        self.hotkey_entry.configure(state="disabled")
        self.hotkey_hint_var.set("按「綁定」設定腳本快捷鍵")
        if message:
            self.status_var.set(message)
        self._clear_pending_hotkey_events()
        errors = self.hotkeys.set_hotkeys(self.scripts)
        if errors:
            self.status_var.set("；".join(errors))
        elif message:
            self.status_var.set(message)
        else:
            self.status_var.set("快捷鍵已註冊。")

    def _cancel_hotkey_recording(self, _event: tk.Event | None = None) -> None:
        if self._recording_hotkey:
            self._finish_hotkey_recording("已取消快捷鍵綁定。")

    def _capture_step_key(self) -> None:
        self.step_key_entry.focus_set()
        self.step_key_entry.selection_range(0, tk.END)
        self.status_var.set("按鍵欄已進入錄製：直接按下按鍵即可。")

    def _capture_hotkey_from_entry(self, event: tk.Event) -> str:
        if not self._recording_hotkey:
            return "break"

        key_text = self._tk_event_to_key_text(event, include_modifiers=True, allow_modifier_key=False)
        if key_text is None:
            self.hotkey_hint_var.set("請按下要設定的快捷鍵，例如 CTRL+F8")
            self.status_var.set("快捷鍵需要包含一般按鍵，例如 CTRL+F8。")
            return "break"
        try:
            KeyResolver.parse_hotkey(key_text)
        except ValueError as exc:
            self.hotkey_hint_var.set("快捷鍵無效，請重新按下要設定的快捷鍵")
            self.status_var.set(str(exc))
            return "break"
        script = self._selected_script()
        if script is not None:
            duplicate = self._find_duplicate_hotkey_script(script.id, key_text)
            if duplicate is not None:
                self.hotkey_hint_var.set("快捷鍵已被使用，請按下另一組快捷鍵")
                message = f"快捷鍵 {key_text} 已經有腳本「{duplicate.name}」使用，未套用修改。"
                self._finish_hotkey_recording(message)
                messagebox.showwarning(APP_TITLE, message)
                return "break"
        self.hotkey_var.set(key_text)
        self._finish_hotkey_recording(f"已綁定快捷鍵：{key_text}")
        return "break"

    def _capture_step_key_from_entry(self, event: tk.Event) -> str:
        key_text = self._tk_event_to_key_text(event, include_modifiers=True, allow_modifier_key=True)
        if key_text is None:
            return "break"
        try:
            KeyResolver.resolve_key_action(key_text)
        except ValueError as exc:
            self.status_var.set(str(exc))
            return "break"
        self.step_key_var.set(key_text)
        self.step_key_entry.selection_range(0, tk.END)
        self.status_var.set(f"已錄製按鍵：{key_text}")
        return "break"

    def _capture_single_key(
        self,
        title: str,
        prompt: str,
        target_var: tk.StringVar,
        validator,
        allow_modifier_key: bool,
    ) -> None:
        window = tk.Toplevel(self.root)
        window.title(title)
        window.transient(self.root)
        window.grab_set()
        window.resizable(False, False)
        window.configure(bg=self.colors["bg"])

        frame = ttk.Frame(window, style="Panel.TFrame", padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(frame, text=prompt, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        preview_var = tk.StringVar(value="等待輸入")
        ttk.Label(frame, textvariable=preview_var, style="Small.TLabel", padding=(0, 10)).grid(
            row=1, column=0, sticky="w"
        )
        ttk.Button(frame, text="取消", style="Ghost.TButton", command=window.destroy).grid(row=2, column=0, sticky="e")

        def on_key(event: tk.Event) -> str:
            key_text = self._tk_event_to_key_text(
                event,
                include_modifiers=True,
                allow_modifier_key=allow_modifier_key,
            )
            if key_text:
                try:
                    validator(key_text)
                except ValueError as exc:
                    preview_var.set(str(exc))
                    return "break"

                preview_var.set(key_text)
                target_var.set(key_text)
                window.after(160, window.destroy)
            return "break"

        window.bind("<KeyPress>", on_key)
        self._center_window(window)
        window.focus_force()

    def _tk_event_to_hotkey(self, event: tk.Event) -> str | None:
        return self._tk_event_to_key_text(event, include_modifiers=True, allow_modifier_key=False)

    def _tk_event_to_key_text(
        self,
        event: tk.Event,
        include_modifiers: bool,
        allow_modifier_key: bool = False,
    ) -> str | None:
        keysym = str(event.keysym)
        modifier_key_map = {
            "Shift_L": "SHIFT",
            "Shift_R": "SHIFT",
            "Control_L": "CTRL",
            "Control_R": "CTRL",
            "Alt_L": "ALT",
            "Alt_R": "ALT",
            "Meta_L": "WIN",
            "Meta_R": "WIN",
        }
        if keysym in modifier_key_map:
            return modifier_key_map[keysym] if allow_modifier_key else None

        event_char = str(getattr(event, "char", "") or "")
        try:
            event_state = int(getattr(event, "state", 0) or 0)
        except (TypeError, ValueError):
            event_state = 0
        shift_down = is_vk_down(VK_SHIFT, VK_LSHIFT, VK_RSHIFT) or bool(event_state & 0x0001)
        ctrl_down = is_vk_down(VK_CONTROL, VK_LCONTROL, VK_RCONTROL)
        alt_down = is_vk_down(VK_MENU, VK_LMENU, VK_RMENU)

        parts: list[str] = []
        if include_modifiers:
            if ctrl_down:
                parts.append("CTRL")
            if alt_down:
                parts.append("ALT")
            if shift_down:
                parts.append("SHIFT")

        key_map = {
            "Escape": "ESC",
            "Return": "ENTER",
            "space": "SPACE",
            "BackSpace": "BACKSPACE",
            "Delete": "DELETE",
            "Insert": "INSERT",
            "Prior": "PAGEUP",
            "Next": "PAGEDOWN",
            "Left": "LEFT",
            "Right": "RIGHT",
            "Up": "UP",
            "Down": "DOWN",
            "Home": "HOME",
            "End": "END",
            "Tab": "TAB",
            "plus": "PLUS",
            "equal": "EQUAL",
            "minus": "MINUS",
            "comma": "COMMA",
            "period": "PERIOD",
            "slash": "SLASH",
            "backslash": "BACKSLASH",
            "semicolon": "SEMICOLON",
            "apostrophe": "QUOTE",
            "grave": "GRAVE",
            "bracketleft": "LBRACKET",
            "bracketright": "RBRACKET",
        }
        key = None
        if shift_down and event_char in SHIFTED_CHAR_BASE:
            key = SHIFTED_CHAR_BASE[event_char]
        if key is None:
            key = self._key_text_from_event_keycode(event)
        if key is None:
            key = key_map.get(keysym)
        if key is None and len(event_char) == 1 and ord(event_char[0]) >= 32:
            key = event_char
        if key is None:
            key = keysym.upper()
        return "+".join([*parts, key])

    def _key_text_from_event_keycode(self, event: tk.Event) -> str | None:
        try:
            keycode = int(getattr(event, "keycode", 0) or 0)
        except (TypeError, ValueError):
            return None
        return KEYCODE_TEXT.get(keycode)

    def _center_window(self, window: tk.Toplevel) -> None:
        window.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - window.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - window.winfo_height()) // 3)
        window.geometry(f"+{x}+{y}")

    def _current_step_index(self) -> int | None:
        selection = self.step_tree.selection()
        if not selection:
            return None
        focused = self.step_tree.focus()
        if focused in selection:
            try:
                return int(focused)
            except ValueError:
                pass
        try:
            return int(selection[0])
        except ValueError:
            return None

    def _selected_step_indices(self) -> list[int]:
        indices: list[int] = []
        for item in self.step_tree.selection():
            try:
                indices.append(int(item))
            except ValueError:
                continue
        return sorted(set(indices))

    def _clone_step(self, step: Step) -> Step:
        return Step(step.action, key=step.key, delay_ms=step.delay_ms, script_id=step.script_id)

    def _steps_for_key_mode(self, key: str) -> list[Step]:
        mode = self.step_key_mode_var.get()
        if mode == KEY_MODE_DOWN:
            return [Step(ACTION_KEY_DOWN, key=key)]
        if mode == KEY_MODE_UP:
            return [Step(ACTION_KEY_UP, key=key)]
        return [
            Step(ACTION_KEY_DOWN, key=key),
            Step(ACTION_KEY_UP, key=key),
        ]

    def _read_script_call_step(self) -> Step:
        script_id = self._selected_script_call_target_id()
        if not script_id:
            raise ValueError("請選擇要呼叫的腳本。")

        target = self._find_script(script_id)
        if target is None:
            raise ValueError("找不到要呼叫的腳本。")

        current_script = self._selected_script()
        if current_script is not None and current_script.id == target.id:
            raise ValueError("腳本不能呼叫自己。")

        return Step(ACTION_SCRIPT_CALL, script_id=target.id)

    def _read_step_form(self, *, show_errors: bool = True, existing_step: Step | None = None) -> list[Step] | None:
        form_action = FORM_ACTION_BY_LABEL.get(self.step_action_var.get(), FORM_ACTION_KEY_COMMAND)
        try:
            if existing_step is not None:
                if existing_step.action == ACTION_DELAY:
                    delay_ms = text_to_ms(self.step_delay_ms_var.get().strip(), "延遲 ms", 0)
                    return [Step(ACTION_DELAY, delay_ms=delay_ms)]
                if existing_step.action == ACTION_SCRIPT_CALL:
                    return [self._read_script_call_step()]

                key = self.step_key_var.get().strip()
                KeyResolver.resolve_key_actions(key)
                key_text = key.upper() if len(key) > 1 else key
                return self._steps_for_key_mode(key_text)

            if form_action == FORM_ACTION_DELAY:
                delay_ms = text_to_ms(self.step_delay_ms_var.get().strip(), "延遲 ms", 0)
                return [Step(ACTION_DELAY, delay_ms=delay_ms)]
            if form_action == FORM_ACTION_SCRIPT_CALL:
                return [self._read_script_call_step()]

            key = self.step_key_var.get().strip()
            KeyResolver.resolve_key_actions(key)
            key_text = key.upper() if len(key) > 1 else key
            return self._steps_for_key_mode(key_text)
        except ValueError as exc:
            if show_errors:
                messagebox.showerror(APP_TITLE, str(exc))
            else:
                self.status_var.set(f"步驟尚未自動儲存：{exc}")
            return None

    def _add_step(self) -> None:
        script = self._selected_script()
        if script is None:
            return

        steps = self._read_step_form()
        if steps is None:
            return

        current_index = self._current_step_index()
        if current_index is None or current_index >= len(script.steps):
            start_index = len(script.steps)
        else:
            start_index = current_index + 1
        script.steps[start_index:start_index] = steps
        self._save_all()
        self._refresh_step_tree(script)
        self.step_tree.selection_remove(*self.step_tree.selection())
        self.step_tree.focus("")
        self.status_var.set(f"已在第 {start_index + 1} 格新增 {len(steps)} 個指令。")

    def _schedule_auto_save_selected_step(self, *_args) -> None:
        if self._loading_script or self._loading_step:
            return
        if not self._selected_step_matches_step_form():
            if self._auto_save_step_after_id is not None:
                self.root.after_cancel(self._auto_save_step_after_id)
                self._auto_save_step_after_id = None
            return
        if self._auto_save_step_after_id is not None:
            self.root.after_cancel(self._auto_save_step_after_id)
        self._auto_save_step_after_id = self.root.after(250, self._auto_save_selected_step)

    def _selected_step_matches_step_form(self) -> bool:
        script = self._selected_script()
        index = self._current_step_index()
        if script is None or index is None or index >= len(script.steps):
            return False

        form_action = FORM_ACTION_BY_LABEL.get(self.step_action_var.get(), FORM_ACTION_KEY_COMMAND)
        selected_step = script.steps[index]
        if form_action == FORM_ACTION_DELAY:
            return selected_step.action == ACTION_DELAY
        if form_action == FORM_ACTION_SCRIPT_CALL:
            return selected_step.action == ACTION_SCRIPT_CALL
        return selected_step.needs_key()

    def _auto_save_selected_step(self) -> None:
        self._auto_save_step_after_id = None
        script = self._selected_script()
        index = self._current_step_index()
        if script is None or index is None or index >= len(script.steps):
            return
        if not self._selected_step_matches_step_form():
            return

        steps = self._read_step_form(show_errors=False, existing_step=script.steps[index])
        if steps is None:
            return

        script.steps[index : index + 1] = steps
        self._save_all()
        self._loading_step = True
        try:
            self._refresh_step_tree(script)
            end_index = index + len(steps)
            self.step_tree.selection_set(*[str(item) for item in range(index, end_index)])
            self.step_tree.focus(str(index))
        finally:
            self._loading_step = False
        self.status_var.set(f"第 {index + 1} 格已自動更新。")

    def _delete_step(self) -> None:
        script = self._selected_script()
        indices = self._selected_step_indices()
        if script is None or not indices:
            return

        for index in reversed(indices):
            if 0 <= index < len(script.steps):
                del script.steps[index]
        self._save_all()
        self._refresh_step_tree(script)
        if script.steps:
            next_index = min(indices[0], len(script.steps) - 1)
            self.step_tree.selection_set(str(next_index))
            self.step_tree.focus(str(next_index))
        self.status_var.set(f"已刪除 {len(indices)} 個指令。")

    def _delete_selected_steps_event(self, _event: tk.Event | None = None) -> str:
        self._delete_step()
        return "break"

    def _copy_selected_steps_event(self, _event: tk.Event | None = None) -> str:
        self._copy_selected_steps_to_clipboard()
        return "break"

    def _paste_steps_event(self, _event: tk.Event | None = None) -> str:
        self._paste_steps_from_clipboard()
        return "break"

    def _select_all_steps_event(self, _event: tk.Event | None = None) -> str:
        items = self.step_tree.get_children()
        if items:
            self.step_tree.selection_set(*items)
            self.step_tree.focus(items[0])
            self.status_var.set(f"已選取 {len(items)} 個步驟。")
        return "break"

    def _copy_selected_steps_to_clipboard(self) -> None:
        script = self._selected_script()
        indices = self._selected_step_indices()
        if script is None or not indices:
            self.status_var.set("請先選取要複製的步驟。")
            return

        self._step_clipboard = [
            self._clone_step(script.steps[index])
            for index in indices
            if 0 <= index < len(script.steps)
        ]
        self.status_var.set(f"已複製 {len(self._step_clipboard)} 個步驟，可用 Ctrl+V 貼上。")

    def _paste_steps_from_clipboard(self) -> None:
        script = self._selected_script()
        if script is None:
            return
        if not self._step_clipboard:
            self.status_var.set("剪貼簿沒有步驟可貼上。")
            return

        indices = self._selected_step_indices()
        if indices:
            insert_at = min(max(indices) + 1, len(script.steps))
        else:
            insert_at = len(script.steps)

        pasted = [self._clone_step(step) for step in self._step_clipboard]
        script.steps[insert_at:insert_at] = pasted
        self._save_all()
        self._refresh_step_tree(script)
        new_indices = [str(index) for index in range(insert_at, insert_at + len(pasted))]
        self.step_tree.selection_set(*new_indices)
        self.step_tree.focus(str(insert_at))
        self.status_var.set(f"已貼上 {len(pasted)} 個步驟。")

    def _reset_step_drag_state(self) -> None:
        self._step_drag_start_y = None
        self._step_drag_indices = []
        self._step_dragging = False
        self._step_drag_insert_index = None
        self._step_drag_start_row = None
        self._step_drag_started_on_selection = False
        self._clear_step_drag_preview()

    def _clear_step_selection(self) -> None:
        selection = self.step_tree.selection()
        if selection:
            self.step_tree.selection_remove(*selection)
        self.step_tree.focus("")
        self.status_var.set("已取消步驟選取；新增步驟會加到最後。")

    def _clear_step_drag_preview(self) -> None:
        self._stop_step_drag_pulse()
        self._retag_step_tree_display_order()

    def _apply_step_drag_preview(self, insert_index: int) -> None:
        self._step_drag_insert_index = insert_index
        current_order = list(self.step_tree.get_children())
        dragged_items = [str(index) for index in self._step_drag_indices]
        dragged = {str(index) for index in self._step_drag_indices}

        adjusted_index = insert_index - sum(1 for item in current_order[:insert_index] if item in dragged)
        remaining_items = [item for item in current_order if item not in dragged]
        adjusted_index = max(0, min(adjusted_index, len(remaining_items)))
        preview_order = remaining_items[:adjusted_index] + dragged_items + remaining_items[adjusted_index:]

        for position, item in enumerate(preview_order):
            self.step_tree.move(item, "", position)
        self.step_tree.selection_set(*dragged_items)
        self._retag_step_tree_display_order(dragged)

    def _retag_step_tree_display_order(self, dragging: set[str] | None = None) -> None:
        dragging = dragging or set()
        for position, item in enumerate(self.step_tree.get_children()):
            tags = list(self._step_base_tags(position))
            if item in dragging:
                tags.append("step_dragging")
            self.step_tree.item(item, tags=tuple(tags))

    def _start_step_drag_pulse(self) -> None:
        if self._step_drag_pulse_after_id is not None:
            return
        self._pulse_step_drop_marker()

    def _pulse_step_drop_marker(self) -> None:
        if not self._step_dragging:
            self._step_drag_pulse_after_id = None
            return

        color = "#fbbf24" if self._step_drag_pulse_on else "#fde68a"
        self.step_tree.tag_configure("step_drop_before", background=color)
        self.step_tree.tag_configure("step_drop_after", background=color)
        self._step_drag_pulse_on = not self._step_drag_pulse_on
        self._step_drag_pulse_after_id = self.root.after(140, self._pulse_step_drop_marker)

    def _stop_step_drag_pulse(self) -> None:
        if self._step_drag_pulse_after_id is not None:
            try:
                self.root.after_cancel(self._step_drag_pulse_after_id)
            except tk.TclError:
                pass
            self._step_drag_pulse_after_id = None
        self._step_drag_pulse_on = False
        if hasattr(self, "step_tree"):
            self.step_tree.tag_configure("step_drop_before", background="#fde68a")
            self.step_tree.tag_configure("step_drop_after", background="#fde68a")

    def _event_has_selection_modifier(self, event: tk.Event) -> bool:
        try:
            state = int(getattr(event, "state", 0) or 0)
        except (TypeError, ValueError):
            return False
        return bool(state & 0x0001 or state & 0x0004)

    def _on_step_drag_start(self, event: tk.Event) -> str | None:
        row = self.step_tree.identify_row(event.y)
        if not row:
            self._reset_step_drag_state()
            if self.step_tree.identify_region(event.x, event.y) != "heading":
                self._clear_step_selection()
                return "break"
            return None

        self._step_drag_start_y = event.y
        self._step_drag_start_row = row
        self._step_drag_started_on_selection = row in self.step_tree.selection() and not self._event_has_selection_modifier(event)
        self._step_drag_indices = []
        self._step_dragging = False
        self._step_drag_insert_index = None
        if self._step_drag_started_on_selection:
            self.step_tree.focus(row)
            return "break"
        return None

    def _on_step_drag_motion(self, event: tk.Event) -> str | None:
        if self._step_drag_start_y is None or self._step_drag_start_row is None:
            return None
        if not self._step_dragging and abs(event.y - self._step_drag_start_y) < 6:
            return None
        if self.step_tree.identify_region(event.x, event.y) == "heading":
            return None
        if not self._step_drag_started_on_selection:
            return None

        if not self._step_drag_indices:
            selection = self.step_tree.selection()
            if self._step_drag_start_row not in selection:
                return None
            self._step_drag_indices = self._selected_step_indices()
            if not self._step_drag_indices:
                return None

        self._step_dragging = True
        insert_index = self._step_drop_index(event.y)
        self._apply_step_drag_preview(insert_index)
        if event.y < 0:
            self.step_tree.yview_scroll(-1, "units")
        elif event.y > self.step_tree.winfo_height():
            self.step_tree.yview_scroll(1, "units")
        self.status_var.set(f"Move {len(self._step_drag_indices)} actions to position {insert_index + 1}")
        return "break"

    def _on_step_drag_release(self, event: tk.Event) -> str | None:
        if not self._step_dragging or not self._step_drag_indices:
            clicked_row = self._step_drag_start_row
            should_single_select = self._step_drag_started_on_selection and clicked_row is not None
            self._reset_step_drag_state()
            if should_single_select:
                self.step_tree.selection_set(clicked_row)
                self.step_tree.focus(clicked_row)
                return "break"
            return None

        script = self._selected_script()
        indices = [index for index in self._step_drag_indices if script is not None and 0 <= index < len(script.steps)]
        preview_order = list(self.step_tree.get_children())
        self._reset_step_drag_state()
        if script is None or not indices:
            return "break"

        self._apply_step_preview_order(script, preview_order, indices)
        return "break"

    def _step_drop_index(self, y: int) -> int:
        script = self._selected_script()
        step_count = len(script.steps) if script is not None else 0
        children = list(self.step_tree.get_children())
        row = self.step_tree.identify_row(y)
        if not row:
            return step_count if y > self.step_tree.winfo_height() // 2 else 0

        try:
            row_index = children.index(row)
        except ValueError:
            return step_count

        bbox = self.step_tree.bbox(row)
        if bbox and y > bbox[1] + (bbox[3] // 2):
            row_index += 1
        return max(0, min(row_index, step_count))

    def _apply_step_preview_order(self, script: Script, item_order: list[str], moved_indices: list[int]) -> None:
        old_steps = script.steps
        ordered_indices: list[int] = []
        for item in item_order:
            try:
                index = int(item)
            except ValueError:
                continue
            if 0 <= index < len(old_steps):
                ordered_indices.append(index)

        if len(ordered_indices) != len(old_steps):
            self._refresh_step_tree(script)
            return

        new_steps = [old_steps[index] for index in ordered_indices]
        if new_steps == old_steps:
            self._refresh_step_tree(script)
            return

        moved = set(moved_indices)
        selected_positions = [position for position, index in enumerate(ordered_indices) if index in moved]
        script.steps = new_steps
        self._save_all()
        self._loading_step = True
        try:
            self._refresh_step_tree(script)
            if selected_positions:
                selection = [str(position) for position in selected_positions]
                self.step_tree.selection_set(*selection)
                self.step_tree.focus(selection[0])
        finally:
            self._loading_step = False
        self.status_var.set(f"Moved {len(selected_positions)} actions.")

    def _move_steps_to_index(self, script: Script, indices: list[int], insert_index: int) -> None:
        indices = sorted(set(index for index in indices if 0 <= index < len(script.steps)))
        if not indices:
            return

        moved_steps = [script.steps[index] for index in indices]
        remaining_steps = [step for index, step in enumerate(script.steps) if index not in indices]
        adjusted_index = insert_index - sum(1 for index in indices if index < insert_index)
        adjusted_index = max(0, min(adjusted_index, len(remaining_steps)))

        new_steps = remaining_steps[:adjusted_index] + moved_steps + remaining_steps[adjusted_index:]
        if new_steps == script.steps:
            return

        script.steps = new_steps
        self._save_all()
        self._loading_step = True
        try:
            self._refresh_step_tree(script)
            new_indices = [str(index) for index in range(adjusted_index, adjusted_index + len(moved_steps))]
            self.step_tree.selection_set(*new_indices)
            self.step_tree.focus(str(adjusted_index))
        finally:
            self._loading_step = False
        self.status_var.set(f"Moved {len(moved_steps)} actions.")

    def _copy_steps(self) -> None:
        script = self._selected_script()
        indices = self._selected_step_indices()
        if script is None or not indices:
            return

        copied = [self._clone_step(script.steps[index]) for index in indices if 0 <= index < len(script.steps)]
        if not copied:
            return

        insert_at = min(max(indices) + 1, len(script.steps))
        script.steps[insert_at:insert_at] = copied
        self._save_all()
        self._refresh_step_tree(script)
        new_indices = [str(index) for index in range(insert_at, insert_at + len(copied))]
        self.step_tree.selection_set(*new_indices)
        self.step_tree.focus(str(insert_at))
        self.status_var.set(f"已複製 {len(copied)} 個指令。")

    def _move_step(self, direction: int) -> None:
        script = self._selected_script()
        if script is None:
            return

        indices = self._selected_step_indices()
        if not indices:
            return

        if direction < 0:
            if indices[0] <= 0:
                return
            self._move_steps_to_index(script, indices, indices[0] - 1)
        else:
            if indices[-1] >= len(script.steps) - 1:
                return
            self._move_steps_to_index(script, indices, indices[-1] + 2)
        self.status_var.set(f"已調整 {len(indices)} 個步驟順序。")

    def _on_step_selected(self, _event: tk.Event | None = None) -> None:
        if self._loading_step:
            return
        script = self._selected_script()
        index = self._current_step_index()
        if script is None or index is None or index >= len(script.steps):
            return

        step = script.steps[index]
        self._loading_step = True
        try:
            if step.action == ACTION_DELAY:
                self.step_action_var.set(FORM_ACTION_LABELS[FORM_ACTION_DELAY])
                self.step_key_mode_var.set(KEY_MODE_BOTH)
            elif step.action == ACTION_SCRIPT_CALL:
                self.step_action_var.set(FORM_ACTION_LABELS[FORM_ACTION_SCRIPT_CALL])
                self.step_key_mode_var.set(KEY_MODE_BOTH)
                self._set_script_call_target(step.script_id)
            else:
                self.step_action_var.set(FORM_ACTION_LABELS[FORM_ACTION_KEY_COMMAND])
                if step.action == ACTION_KEY_DOWN:
                    self.step_key_mode_var.set(KEY_MODE_DOWN)
                elif step.action == ACTION_KEY_UP:
                    self.step_key_mode_var.set(KEY_MODE_UP)
                else:
                    self.step_key_mode_var.set(KEY_MODE_BOTH)
            if step.needs_key():
                self.step_key_var.set(step.key)
            if step.action == ACTION_DELAY:
                self.step_delay_ms_var.set(f"{step.delay_ms:,}")
            self._on_step_action_changed()
        finally:
            self._loading_step = False

    def _on_step_action_changed(self, _event: tk.Event | None = None) -> None:
        form_action = FORM_ACTION_BY_LABEL.get(self.step_action_var.get(), FORM_ACTION_KEY_COMMAND)
        if (
            not hasattr(self, "key_settings_frame")
            or not hasattr(self, "delay_settings_frame")
            or not hasattr(self, "script_call_settings_frame")
        ):
            return

        if form_action == FORM_ACTION_DELAY:
            self.key_settings_frame.grid_remove()
            self.script_call_settings_frame.grid_remove()
            self.delay_settings_frame.grid()
            self.status_var.set("延遲是獨立動作，只使用延遲 ms 設定。")
        elif form_action == FORM_ACTION_SCRIPT_CALL:
            self.key_settings_frame.grid_remove()
            self.delay_settings_frame.grid_remove()
            self.script_call_settings_frame.grid()
            if self._loading_step:
                self._refresh_script_call_choices()
            else:
                self._select_default_script_call_target()
            self.status_var.set("呼叫腳本會在這個位置執行選取腳本的一輪步驟。")
        else:
            self.delay_settings_frame.grid_remove()
            self.script_call_settings_frame.grid_remove()
            self.key_settings_frame.grid()
            self.status_var.set("按鍵指令會自動新增「按下按鍵」與「放開按鍵」一組指令。")

    def _toggle_selected_script(self) -> None:
        script_id = self._selected_script_id()
        if script_id:
            self._toggle_script(script_id)

    def _toggle_script(self, script_id: str) -> None:
        if script_id in self.runners:
            self._stop_script(script_id)
        else:
            self._start_script(script_id)

    def _start_script(self, script_id: str) -> None:
        script = self._find_script(script_id)
        if script is None:
            return

        if not script.steps:
            messagebox.showwarning(APP_TITLE, f"「{script.name}」沒有任何步驟。")
            return

        script_snapshots = [item.clone() for item in self.scripts]
        snapshot_lookup = scripts_by_id(script_snapshots)
        script_snapshot = snapshot_lookup.get(script.id)
        if script_snapshot is None:
            return

        try:
            validate_script_references(script_snapshot, snapshot_lookup)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, f"{script.name} 無法啟動：\n{exc}")
            return

        runner = ScriptRunner(script_snapshot, self.keyboard, self.runtime_events, script_snapshots)
        self.runners[script_id] = runner
        self.current_step[script_id] = "執行中"
        runner.start()
        self._refresh_script_tree()
        self.status_var.set(f"已啟動「{script.name}」。")

    def _stop_script(self, script_id: str) -> None:
        runner = self.runners.get(script_id)
        script = self._find_script(script_id)
        if runner:
            runner.stop()
            self.current_step[script_id] = "停止中"
            self._refresh_script_tree()
            if script:
                self.status_var.set(f"正在停止「{script.name}」。")

    def _poll_events(self) -> None:
        if self._closing:
            return

        while True:
            try:
                script_id = self.hotkeys.events.get_nowait()
            except queue.Empty:
                break
            self._toggle_script(script_id)

        script_tree_needs_refresh = False
        while True:
            try:
                event_type, script_id, detail = self.runtime_events.get_nowait()
            except queue.Empty:
                break

            if event_type == "started":
                self.current_step[script_id] = "執行中"
            elif event_type == "step":
                self.current_step[script_id] = detail
            elif event_type == "error":
                self.status_var.set(f"腳本錯誤：{detail}")
            elif event_type == "stopped":
                self.runners.pop(script_id, None)
                self.current_step.pop(script_id, None)
            script_tree_needs_refresh = True

        if script_tree_needs_refresh:
            self._refresh_script_tree()

        while True:
            try:
                event_type, detail = self.monitor_events.get_nowait()
            except queue.Empty:
                break

            if event_type == "ready":
                self._update_recaptcha_status_from_settings(saved=False)
            elif event_type == "notified":
                self.recaptcha_status_var.set(detail)
                self.status_var.set(detail)
            elif event_type == "error":
                self.recaptcha_status_var.set(detail)
                self.status_var.set(detail)

        self._poll_after_id = self.root.after(80, self._poll_events)

    def _on_close(self) -> None:
        if self._closing:
            return

        self._closing = True
        pending_recaptcha_save = self._recaptcha_save_after_id is not None
        for after_id in (
            self._poll_after_id,
            self._auto_save_after_id,
            self._auto_save_step_after_id,
            self._hotkey_register_after_id,
            self._recaptcha_save_after_id,
            self._window_event_after_id,
            self._step_drag_pulse_after_id,
        ):
            if after_id is None:
                continue
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

        if pending_recaptcha_save:
            self._save_recaptcha_settings_from_ui()

        for runner in list(self.runners.values()):
            runner.stop()
        self.window_event_hook.close()
        self.running_overlay.hide()
        self.recaptcha_monitor.close()
        self.hotkeys.close()
        deadline = time.monotonic() + 1.0
        for runner in list(self.runners.values()):
            remaining = deadline - time.monotonic()
            runner.join(max(remaining, 0.0))
        self.running_overlay.destroy()
        self.root.destroy()


def run_self_test() -> int:
    checks = ["SPACE", "CTRL+C", "SHIFT+A", "PLUS", "F8", "LEFT", "ENTER"]
    multi_checks = ["X, SPACE", "LEFT, X", "CTRL+C, SPACE"]
    hotkeys = ["F8", "CTRL+F9", "ALT+SHIFT+P", "CTRL+PLUS"]
    for key in checks:
        KeyResolver.resolve_key_action(key)
    for key in multi_checks:
        assert len(KeyResolver.resolve_key_actions(key)) == 2
    for hotkey in hotkeys:
        KeyResolver.parse_hotkey(hotkey)
    print("self-test OK")
    return 0


def main() -> int:
    if platform.system() != "Windows":
        print("AutoKeyboard 目前只支援 Windows。")
        return 1

    if "--self-test" in sys.argv:
        return run_self_test()

    configure_process_dpi_awareness()
    root = tk.Tk()
    try:
        AutoKeyboardApp(root)
    except Exception as exc:
        messagebox.showerror(APP_TITLE, str(exc))
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
