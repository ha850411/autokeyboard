# AutoKeyboard script wizard for Windows.
# Python standard library only: Tkinter UI + Win32 hotkeys/keyboard input.

from __future__ import annotations

import ctypes
import json
import os
import platform
import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import tkinter as tk
from tkinter import messagebox, ttk


APP_TITLE = "AutoKeyboard 腳本精靈"
APP_NAME = "AutoKeyboard"
CONFIG_FILENAME = "scripts.json"


def app_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_data_directory() -> Path:
    if platform.system() == "Windows":
        fallback = Path.home() / "AppData" / "Local"
        base_directory = Path(os.environ.get("LOCALAPPDATA", str(fallback)))
        return base_directory / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


LEGACY_CONFIG_PATH = app_directory() / CONFIG_FILENAME
CONFIG_PATH = user_data_directory() / CONFIG_FILENAME


if platform.system() == "Windows":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
else:
    user32 = None


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

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
MAPVK_VK_TO_VSC = 0
HOLD_REPEAT_MS = 35

ACTION_KEY_DOWN = "key_down"
ACTION_DELAY = "delay"
ACTION_KEY_UP = "key_up"
ACTION_LABELS = {
    ACTION_KEY_DOWN: "按下按鍵",
    ACTION_DELAY: "延遲",
    ACTION_KEY_UP: "放開按鍵",
}
ACTION_BY_LABEL = {label: action for action, label in ACTION_LABELS.items()}

FORM_ACTION_KEY_COMMAND = "key_command"
FORM_ACTION_DELAY = ACTION_DELAY
FORM_ACTION_LABELS = {
    FORM_ACTION_KEY_COMMAND: "按鍵指令",
    FORM_ACTION_DELAY: "延遲",
}
FORM_ACTION_BY_LABEL = {label: action for action, label in FORM_ACTION_LABELS.items()}

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
        "按下按鍵": ACTION_KEY_DOWN,
        "放開按鍵": ACTION_KEY_UP,
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
        return [cls(action, key=str(data.get("key", "SPACE")))]

    def to_dict(self) -> dict:
        if self.action == ACTION_DELAY:
            return {"action": self.action, "delay_ms": self.delay_ms}
        return {"action": self.action, "key": self.key}

    def needs_key(self) -> bool:
        return self.action in {ACTION_KEY_DOWN, ACTION_KEY_UP}

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


class ScriptRunner:
    def __init__(self, script: Script, keyboard: WindowsKeyboard, event_queue: queue.Queue[tuple]) -> None:
        self.script = script
        self._keyboard = keyboard
        self._event_queue = event_queue
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

    def _run(self) -> None:
        self._event_queue.put(("started", self.script.id, ""))
        held_actions: list[KeyAction] = []
        try:
            while not self._stop_event.is_set():
                for index, step in enumerate(self.script.steps, start=1):
                    if self._stop_event.is_set():
                        break

                    if step.action == ACTION_KEY_DOWN:
                        actions = KeyResolver.resolve_key_actions(step.key)
                        self._event_queue.put(("step", self.script.id, f"{index}. {step.key} 按下按鍵"))
                        self._keyboard.key_down_many(actions)
                        held_actions.extend(actions)
                    elif step.action == ACTION_KEY_UP:
                        actions = KeyResolver.resolve_key_actions(step.key)
                        self._event_queue.put(("step", self.script.id, f"{index}. {step.key} 放開按鍵"))
                        self._keyboard.key_up_many(actions)
                        for action in actions:
                            for held_index in range(len(held_actions) - 1, -1, -1):
                                if held_actions[held_index] == action:
                                    del held_actions[held_index]
                                    break
                    elif step.action == ACTION_DELAY:
                        held_count = len(unique_key_actions(held_actions))
                        if held_count:
                            detail = f"{index}. 延遲 {step.delay_ms} ms (維持 {held_count} 個按鍵)"
                        else:
                            detail = f"{index}. 延遲 {step.delay_ms} ms"
                        self._event_queue.put(("step", self.script.id, detail))
                        if self._delay_with_held_keys(step.delay_ms, held_actions):
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
        ms = int(round(float(value)))
    except ValueError as exc:
        raise ValueError(f"{field_name} 必須是數字。") from exc

    if ms < minimum_ms:
        raise ValueError(f"{field_name} 太短。")
    return ms


def format_seconds(ms: int) -> str:
    value = ms / 1000
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


class AutoKeyboardApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x720")
        self.root.minsize(980, 620)

        self.scripts = load_scripts()
        self.keyboard = WindowsKeyboard()
        self.hotkeys = HotkeyManager()
        self.runtime_events: queue.Queue[tuple] = queue.Queue()
        self.runners: dict[str, ScriptRunner] = {}
        self.current_step: dict[str, str] = {}
        self._loading_script = False
        self._loading_step = False
        self._recording_hotkey = False
        self._closing = False
        self._auto_save_after_id: str | None = None
        self._auto_save_step_after_id: str | None = None
        self._hotkey_register_after_id: str | None = None
        self._poll_after_id: str | None = None

        self.name_var = tk.StringVar()
        self.hotkey_var = tk.StringVar()
        self.hotkey_hint_var = tk.StringVar(value="按「錄製」設定腳本快捷鍵")
        self.repeat_var = tk.BooleanVar(value=True)
        self.step_action_var = tk.StringVar(value=FORM_ACTION_LABELS[FORM_ACTION_KEY_COMMAND])
        self.step_key_var = tk.StringVar(value="SPACE")
        self.step_delay_ms_var = tk.StringVar(value="1000")
        self.banner_var = tk.StringVar(value="待命")
        self.status_var = tk.StringVar(value="準備就緒")

        self._configure_style()
        self._build_ui()
        self._bind_auto_save()
        self._refresh_script_tree()
        self._select_first_script()
        self._register_hotkeys(show_dialog=False)
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self) -> None:
        style = ttk.Style()
        self.colors = {
            "bg": "#f5f7fb",
            "surface": "#ffffff",
            "surface_alt": "#eef2f7",
            "line": "#d9e2ec",
            "text": "#172033",
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
        style.configure("Panel.TFrame", background=colors["surface"], relief="solid", borderwidth=1)
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
            background=colors["surface"],
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

        style.configure("TButton", padding=(12, 7), borderwidth=0, focusthickness=0, relief="flat")
        style.map(
            "TButton",
            background=[("active", "#e2e8f0"), ("pressed", "#cbd5e1")],
            foreground=[("disabled", "#94a3b8")],
        )
        style.configure("Primary.TButton", background=colors["primary"], foreground="#ffffff")
        style.map(
            "Primary.TButton",
            background=[("active", colors["primary_hover"]), ("pressed", colors["primary_hover"])],
            foreground=[("disabled", "#dbeafe")],
        )
        style.configure("Danger.TButton", background="#fee2e2", foreground=colors["danger"])
        style.map(
            "Danger.TButton",
            background=[("active", "#fecaca"), ("pressed", "#fecaca")],
            foreground=[("active", colors["danger_hover"])],
        )
        style.configure("Ghost.TButton", background=colors["surface_alt"], foreground=colors["text"])
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
        self.script_tree.grid(row=1, column=0, sticky="nsew")
        self.script_tree.bind("<<TreeviewSelect>>", self._on_script_selected)

        script_buttons = ttk.Frame(left, style="Toolbar.TFrame")
        script_buttons.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        for column in range(4):
            script_buttons.columnconfigure(column, weight=1)

        ttk.Button(script_buttons, text="新增", style="Primary.TButton", command=self._add_script).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(script_buttons, text="複製", style="Ghost.TButton", command=self._duplicate_script).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(script_buttons, text="刪除", style="Danger.TButton", command=self._delete_script).grid(
            row=0, column=2, sticky="ew", padx=4
        )
        self.toggle_button = ttk.Button(
            script_buttons,
            text="啟動",
            style="Primary.TButton",
            command=self._toggle_selected_script,
        )
        self.toggle_button.grid(row=0, column=3, sticky="ew", padx=(4, 0))

        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        editor = ttk.Frame(right, style="Panel.TFrame")
        editor.grid(row=0, column=0, sticky="ew")
        editor.columnconfigure(1, weight=1)

        ttk.Label(editor, text="腳本名稱", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10), pady=(0, 10)
        )
        self.name_entry = ttk.Entry(editor, textvariable=self.name_var)
        self.name_entry.grid(row=0, column=1, sticky="ew", pady=(0, 8))

        ttk.Label(editor, text="快捷鍵", style="Panel.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 10), pady=(0, 10)
        )
        hotkey_row = ttk.Frame(editor, style="Panel.TFrame")
        hotkey_row.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        hotkey_row.columnconfigure(0, weight=1)
        self.hotkey_entry = ttk.Entry(hotkey_row, textvariable=self.hotkey_var)
        self.hotkey_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.hotkey_entry.bind("<KeyPress>", self._capture_hotkey_from_entry)
        self.hotkey_entry.bind("<FocusOut>", self._cancel_hotkey_recording)
        self.hotkey_entry.configure(state="disabled")
        ttk.Button(hotkey_row, text="錄製", style="Ghost.TButton", command=self._capture_hotkey).grid(row=0, column=1)
        ttk.Label(hotkey_row, textvariable=self.hotkey_hint_var, style="Small.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
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
        self.step_tree.heading("key", text="按鍵")
        self.step_tree.heading("delay", text="延遲 ms")
        self.step_tree.column("action", width=120, minwidth=100)
        self.step_tree.column("key", width=160, minwidth=120)
        self.step_tree.column("delay", width=110, minwidth=90, anchor="center")
        self.step_tree.grid(row=3, column=0, sticky="nsew")
        self.step_tree.bind("<<TreeviewSelect>>", self._on_step_selected)
        self.step_tree.bind("<Delete>", self._delete_selected_steps_event)

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
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Radiobutton(
            action_options,
            text=FORM_ACTION_LABELS[FORM_ACTION_DELAY],
            value=FORM_ACTION_LABELS[FORM_ACTION_DELAY],
            variable=self.step_action_var,
            command=self._on_step_action_changed,
        ).grid(row=0, column=1, sticky="w")

        self.key_settings_frame = ttk.Frame(step_form, style="Panel.TFrame")
        self.key_settings_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.key_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.key_settings_frame, text="按鍵", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        self.step_key_entry = ttk.Entry(self.key_settings_frame, textvariable=self.step_key_var, width=18)
        self.step_key_entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.step_key_entry.bind("<KeyPress>", self._capture_step_key_from_entry)
        ttk.Button(self.key_settings_frame, text="錄製", style="Ghost.TButton", command=self._capture_step_key).grid(
            row=0, column=2, sticky="ew"
        )
        ttk.Label(
            self.key_settings_frame,
            text="可輸入單鍵、組合鍵，或用逗號同時按多鍵，例如 X, SPACE。",
            style="Small.TLabel",
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

        self.delay_settings_frame = ttk.Frame(step_form, style="Panel.TFrame")
        self.delay_settings_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.delay_settings_frame.columnconfigure(1, weight=1)
        ttk.Label(self.delay_settings_frame, text="延遲 ms", style="Panel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 6)
        )
        ttk.Entry(self.delay_settings_frame, textvariable=self.step_delay_ms_var, width=12).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Label(
            self.delay_settings_frame,
            text="延遲是獨立動作；若前面有按下按鍵，延遲期間會持續維持按住。",
            style="Small.TLabel",
        ).grid(row=1, column=1, sticky="w", pady=(6, 0))
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

    def _select_first_script(self) -> None:
        if self.scripts:
            self.script_tree.selection_set(self.scripts[0].id)
            self.script_tree.focus(self.scripts[0].id)
            self._load_script_into_editor(self.scripts[0])

    def _refresh_script_tree(self) -> None:
        selected = self._selected_script_id()
        existing = set(self.script_tree.get_children())
        wanted = {script.id for script in self.scripts}

        for item in existing - wanted:
            self.script_tree.delete(item)

        for index, script in enumerate(self.scripts):
            values = (script.name, script.hotkey or "手動", self._status_for(script.id))
            tags = self._tags_for(script.id)
            if script.id in existing:
                self.script_tree.item(script.id, values=values, tags=tags)
            else:
                self.script_tree.insert("", index, iid=script.id, values=values, tags=tags)

        if selected in wanted:
            self.script_tree.selection_set(selected)
            self.script_tree.focus(selected)

        self._update_banner()
        self._update_toggle_button()

    def _refresh_step_tree(self, script: Script | None = None) -> None:
        for item in self.step_tree.get_children():
            self.step_tree.delete(item)

        script = script or self._selected_script()
        if script is None:
            return

        for index, step in enumerate(script.steps):
            key = step.key if step.needs_key() else ""
            delay = str(step.delay_ms) if step.action == ACTION_DELAY else ""
            self.step_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(step.display_action(), key, delay),
            )

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
        running_names = [script.name for script in self.scripts if script.id in self.runners]
        if running_names:
            self.banner_var.set("執行中：" + "、".join(running_names))
            self.banner_label.configure(style="Banner.Running.TLabel")
        else:
            self.banner_var.set("待命")
            self.banner_label.configure(style="Banner.Idle.TLabel")

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

        if not messagebox.askyesno(APP_TITLE, f"確定刪除「{script.name}」？"):
            return

        if script.id in self.runners:
            self.runners[script.id].stop()

        self.scripts = [item for item in self.scripts if item.id != script.id]
        self.current_step.pop(script.id, None)
        self._save_all()
        self._refresh_script_tree()
        self._select_first_script()
        self.status_var.set("已刪除腳本。")

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
        for variable in (self.step_action_var, self.step_key_var, self.step_delay_ms_var):
            variable.trace_add("write", self._schedule_auto_save_selected_step)

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

    def _finish_hotkey_recording(self, message: str | None = None) -> None:
        self._recording_hotkey = False
        self.hotkey_entry.configure(state="disabled")
        self.hotkey_hint_var.set("按「錄製」設定腳本快捷鍵")
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
            self._finish_hotkey_recording("已取消快捷鍵錄製。")

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
        self._finish_hotkey_recording(f"已錄製快捷鍵：{key_text}")
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
        return Step(step.action, key=step.key, delay_ms=step.delay_ms)

    def _read_step_form(self, *, show_errors: bool = True) -> list[Step] | None:
        form_action = FORM_ACTION_BY_LABEL.get(self.step_action_var.get(), FORM_ACTION_KEY_COMMAND)
        try:
            if form_action == FORM_ACTION_DELAY:
                delay_ms = text_to_ms(self.step_delay_ms_var.get().strip(), "延遲 ms", 0)
                return [Step(ACTION_DELAY, delay_ms=delay_ms)]

            key = self.step_key_var.get().strip()
            KeyResolver.resolve_key_actions(key)
            key_text = key.upper() if len(key) > 1 else key
            return [
                Step(ACTION_KEY_DOWN, key=key_text),
                Step(ACTION_KEY_UP, key=key_text),
            ]
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
        end_index = start_index + len(steps)
        self.step_tree.selection_set(*[str(index) for index in range(start_index, end_index)])
        self.step_tree.focus(str(start_index))
        self.status_var.set(f"已在第 {start_index + 1} 格新增 {len(steps)} 個指令。")

    def _schedule_auto_save_selected_step(self, *_args) -> None:
        if self._loading_script or self._loading_step:
            return
        if self._auto_save_step_after_id is not None:
            self.root.after_cancel(self._auto_save_step_after_id)
        self._auto_save_step_after_id = self.root.after(250, self._auto_save_selected_step)

    def _auto_save_selected_step(self) -> None:
        self._auto_save_step_after_id = None
        script = self._selected_script()
        index = self._current_step_index()
        if script is None or index is None or index >= len(script.steps):
            return

        steps = self._read_step_form(show_errors=False)
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
        index = self._current_step_index()
        if script is None or index is None:
            return

        new_index = index + direction
        if new_index < 0 or new_index >= len(script.steps):
            return

        script.steps[index], script.steps[new_index] = script.steps[new_index], script.steps[index]
        self._save_all()
        self._refresh_step_tree(script)
        self.step_tree.selection_set(str(new_index))
        self.status_var.set("已調整步驟順序。")

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
            else:
                self.step_action_var.set(FORM_ACTION_LABELS[FORM_ACTION_KEY_COMMAND])
            if step.needs_key():
                self.step_key_var.set(step.key)
            if step.action == ACTION_DELAY:
                self.step_delay_ms_var.set(str(step.delay_ms))
            self._on_step_action_changed()
        finally:
            self._loading_step = False

    def _on_step_action_changed(self, _event: tk.Event | None = None) -> None:
        form_action = FORM_ACTION_BY_LABEL.get(self.step_action_var.get(), FORM_ACTION_KEY_COMMAND)
        if not hasattr(self, "key_settings_frame") or not hasattr(self, "delay_settings_frame"):
            return

        if form_action == FORM_ACTION_DELAY:
            self.key_settings_frame.grid_remove()
            self.delay_settings_frame.grid()
            self.status_var.set("延遲是獨立動作，只使用延遲 ms 設定。")
        else:
            self.delay_settings_frame.grid_remove()
            self.key_settings_frame.grid()
            self.status_var.set("按鍵指令會自動新增「按下按鍵」與「放開按鍵」一組指令。")
        self._schedule_auto_save_selected_step()

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

        for step in script.steps:
            if not step.needs_key():
                continue
            try:
                KeyResolver.resolve_key_actions(step.key)
            except ValueError as exc:
                messagebox.showerror(APP_TITLE, f"{script.name} 的步驟「{step.key}」無效：\n{exc}")
                return

        runner = ScriptRunner(script.clone(), self.keyboard, self.runtime_events)
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
            self._refresh_script_tree()

        self._poll_after_id = self.root.after(80, self._poll_events)

    def _on_close(self) -> None:
        if self._closing:
            return

        self._closing = True
        for after_id in (
            self._poll_after_id,
            self._auto_save_after_id,
            self._auto_save_step_after_id,
            self._hotkey_register_after_id,
        ):
            if after_id is None:
                continue
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

        for runner in list(self.runners.values()):
            runner.stop()
        self.hotkeys.close()
        deadline = time.monotonic() + 1.0
        for runner in list(self.runners.values()):
            remaining = deadline - time.monotonic()
            runner.join(max(remaining, 0.0))
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
