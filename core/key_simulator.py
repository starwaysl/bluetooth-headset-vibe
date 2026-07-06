"""
键盘模拟模块 — 模拟快捷键触发输入法的语音输入。

macOS 上通过 Quartz CGEventCreateKeyboardEvent 合成键盘事件，
支持修饰键（Cmd/Opt/Ctrl/Shift）+ 普通键的组合。

使用方式：
    sim = KeySimulator()
    sim.press_shortcut("opt+cmd+s")   # 模拟按下 ⌥⌘S
    sim.release_shortcut("opt+cmd+s") # 模拟释放
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import Quartz
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventSetFlags,
    CGEventPost,
    kCGHIDEventTap,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventKeyDown,
    kCGEventKeyUp,
)

logger = logging.getLogger(__name__)


# 修饰键映射
MODIFIER_MAP: Dict[str, int] = {
    "cmd": kCGEventFlagMaskCommand,
    "command": kCGEventFlagMaskCommand,
    "opt": kCGEventFlagMaskAlternate,
    "option": kCGEventFlagMaskAlternate,
    "alt": kCGEventFlagMaskAlternate,
    "ctrl": kCGEventFlagMaskControl,
    "control": kCGEventFlagMaskControl,
    "shift": kCGEventFlagMaskShift,
}

# 键名 → macOS 虚拟键码（ANSI 键盘布局）
# 参考：https://stackoverflow.com/questions/3202629/where-can-i-find-a-list-of-mac-virtual-key-codes
KEY_CODE_MAP: Dict[str, int] = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03,
    "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0b, "q": 0x0c,
    "w": 0x0d, "e": 0x0e, "r": 0x0f, "y": 0x10,
    "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
    "4": 0x16, "6": 0x15, "5": 0x17, "=": 0x18,
    "9": 0x19, "7": 0x1a, "-": 0x1b, "8": 0x1c,
    "0": 0x1d, "]": 0x1e, "o": 0x1f, "u": 0x20,
    "[": 0x21, "i": 0x22, "p": 0x23, "return": 0x24,
    "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28,
    ";": 0x29, "\\": 0x2a, ",": 0x2b, "/": 0x2c,
    "n": 0x2d, "m": 0x2e, ".": 0x2f, "tab": 0x30,
    "space": 0x31, "`": 0x32, "delete": 0x33,
    "escape": 0x35, "cmd": 0x37, "shift": 0x38,
    "capslock": 0x39, "option": 0x3a, "control": 0x3b,
    "right": 0x7c, "left": 0x7b, "down": 0x7d, "up": 0x7e,
}


@dataclass
class ParsedShortcut:
    """解析后的快捷键结构。"""
    modifiers: int          # CGEvent flags 位掩码
    key_code: int           # 虚拟键码
    key_name: str           # 原始键名（用于日志）
    modifier_names: List[str]


class KeySimulatorError(Exception):
    pass


class KeySimulator:
    """模拟键盘快捷键。"""

    def __init__(self, tap_location: int = kCGHIDEventTap):
        self._tap = tap_location

    # ── 解析快捷键字符串 ──────────────────────────────────

    @staticmethod
    def parse_shortcut(shortcut_str: str) -> ParsedShortcut:
        """
        解析快捷键字符串，如 "opt+cmd+s" → ParsedShortcut。

        支持格式：
            - "cmd+c"
            - "opt+cmd+s"
            - "ctrl+shift+a"
        """
        parts = [p.strip().lower() for p in shortcut_str.split("+")]
        if not parts:
            raise KeySimulatorError(f"快捷键字符串为空: '{shortcut_str}'")

        modifiers = 0
        modifier_names: List[str] = []
        key_name = parts[-1]

        for part in parts[:-1]:
            if part in MODIFIER_MAP:
                modifiers |= MODIFIER_MAP[part]
                modifier_names.append(part)
            else:
                raise KeySimulatorError(f"未知修饰键: '{part}'")

        if key_name not in KEY_CODE_MAP:
            raise KeySimulatorError(
                f"未知键名: '{key_name}'。支持的键名: {list(KEY_CODE_MAP.keys())}"
            )

        return ParsedShortcut(
            modifiers=modifiers,
            key_code=KEY_CODE_MAP[key_name],
            key_name=key_name,
            modifier_names=modifier_names,
        )

    # ── 模拟按键 ──────────────────────────────────────────

    def press_shortcut(self, shortcut_str: str) -> None:
        """模拟按下快捷键（带修饰键）。"""
        shortcut = self.parse_shortcut(shortcut_str)
        self._post_key_event(shortcut, is_down=True)
        logger.debug(f"模拟按下: {'+'.join(shortcut.modifier_names)}+{shortcut.key_name}")

    def release_shortcut(self, shortcut_str: str) -> None:
        """模拟释放快捷键。"""
        shortcut = self.parse_shortcut(shortcut_str)
        self._post_key_event(shortcut, is_down=False)
        logger.debug(f"模拟释放: {'+'.join(shortcut.modifier_names)}+{shortcut.key_name}")

    def tap_shortcut(self, shortcut_str: str, hold_ms: int = 50) -> None:
        """模拟一次完整的按下-释放（带短暂保持）。"""
        self.press_shortcut(shortcut_str)
        time.sleep(hold_ms / 1000.0)
        self.release_shortcut(shortcut_str)

    # ── 内部实现 ──────────────────────────────────────────

    def _post_key_event(self, shortcut: ParsedShortcut, is_down: bool) -> None:
        """合成并发送单个键盘事件。"""
        event = CGEventCreateKeyboardEvent(None, shortcut.key_code, is_down)
        if event is None:
            raise KeySimulatorError("CGEventCreateKeyboardEvent 返回 NULL")

        if shortcut.modifiers:
            CGEventSetFlags(event, shortcut.modifiers)

        CGEventPost(self._tap, event)

    # ── 便捷方法 ──────────────────────────────────────────

    @staticmethod
    def send_text(text: str) -> None:
        """
        通过剪贴板粘贴方式发送文本（比逐字符模拟更可靠）。
        注意：会修改剪贴板内容。
        """
        import subprocess
        import pyperclip

        original = pyperclip.paste()
        try:
            pyperclip.copy(text)
            time.sleep(0.05)
            # 模拟 Cmd+V 粘贴
            sim = KeySimulator()
            sim.tap_shortcut("cmd+v")
            time.sleep(0.05)
        finally:
            pyperclip.copy(original)
