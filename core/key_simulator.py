"""
键盘模拟模块 — 通过 pynput 模拟快捷键。

兼容 macOS / Windows / Linux。
用于触发输入法的语音输入快捷键（如微信输入法的 ⌥⌘S）。

使用方式：
    sim = KeySimulator()
    sim.tap_shortcut("opt+cmd+s")   # 模拟一次 ⌥⌘S
    sim.hold_shortcut("opt+cmd+s")  # 返回上下文管理器，with 期间一直按住
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from pynput.keyboard import Key, KeyCode, Controller

logger = logging.getLogger(__name__)

# 修饰键映射（pynput 名称 → pynput Key）
MODIFIER_MAP: Dict[str, Key] = {
    "cmd": Key.cmd,
    "command": Key.cmd,
    "opt": Key.alt,
    "option": Key.alt,
    "alt": Key.alt,
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "shift": Key.shift,
    "cmd_r": Key.cmd_r,
    "command_r": Key.cmd_r,
    "opt_r": Key.alt_r,
    "ctrl_r": Key.ctrl_r,
    "shift_r": Key.shift_r,
}

# 特殊键名映射（小写）
KEY_MAP: Dict[str, Key] = {
    "a": KeyCode.from_char("a"),
    "b": KeyCode.from_char("b"),
    "c": KeyCode.from_char("c"),
    "d": KeyCode.from_char("d"),
    "e": KeyCode.from_char("e"),
    "f": KeyCode.from_char("f"),
    "g": KeyCode.from_char("g"),
    "h": KeyCode.from_char("h"),
    "i": KeyCode.from_char("i"),
    "j": KeyCode.from_char("j"),
    "k": KeyCode.from_char("k"),
    "l": KeyCode.from_char("l"),
    "m": KeyCode.from_char("m"),
    "n": KeyCode.from_char("n"),
    "o": KeyCode.from_char("o"),
    "p": KeyCode.from_char("p"),
    "q": KeyCode.from_char("q"),
    "r": KeyCode.from_char("r"),
    "s": KeyCode.from_char("s"),
    "t": KeyCode.from_char("t"),
    "u": KeyCode.from_char("u"),
    "v": KeyCode.from_char("v"),
    "w": KeyCode.from_char("w"),
    "x": KeyCode.from_char("x"),
    "y": KeyCode.from_char("y"),
    "z": KeyCode.from_char("z"),
    "0": KeyCode.from_char("0"),
    "1": KeyCode.from_char("1"),
    "2": KeyCode.from_char("2"),
    "3": KeyCode.from_char("3"),
    "4": KeyCode.from_char("4"),
    "5": KeyCode.from_char("5"),
    "6": KeyCode.from_char("6"),
    "7": KeyCode.from_char("7"),
    "8": KeyCode.from_char("8"),
    "9": KeyCode.from_char("9"),
    "space": Key.space,
    "return": Key.enter,
    "enter": Key.enter,
    "tab": Key.tab,
    "delete": Key.delete,
    "backspace": Key.backspace,
    "escape": Key.esc,
    "esc": Key.esc,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
    "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
    "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
}


class Shortcut:
    """解析后的快捷键组合。"""
    __slots__ = ("modifiers", "key")

    def __init__(self, modifiers: List[Key], key: Key):
        self.modifiers = modifiers
        self.key = key

    def __repr__(self):
        mod_names = [str(m) for m in self.modifiers]
        return f"Shortcut({'+'.join(mod_names)}+{self.key})"


class KeySimulatorError(Exception):
    pass


class KeySimulator:
    """通过 pynput 模拟键盘快捷键。"""

    def __init__(self):
        self._controller = Controller()

    # ── 解析快捷键字符串 ──────────────────────────────────

    @staticmethod
    def parse_shortcut(shortcut_str: str) -> Shortcut:
        """
        解析快捷键字符串，如 "opt+cmd+s" → Shortcut([alt, cmd], s)。
        """
        parts = [p.strip().lower() for p in shortcut_str.split("+")]
        if not parts:
            raise KeySimulatorError(f"快捷键字符串为空: '{shortcut_str}'")

        modifiers: List[Key] = []
        for part in parts[:-1]:
            if part in MODIFIER_MAP:
                modifiers.append(MODIFIER_MAP[part])
            else:
                raise KeySimulatorError(
                    f"未知修饰键: '{part}'。支持: {list(MODIFIER_MAP.keys())}"
                )

        key_name = parts[-1]
        if key_name in KEY_MAP:
            key = KEY_MAP[key_name]
        else:
            raise KeySimulatorError(
                f"未知键名: '{key_name}'。支持: {list(KEY_MAP.keys())}"
            )

        return Shortcut(modifiers=modifiers, key=key)

    # ── 模拟按键 ──────────────────────────────────────────

    def tap_shortcut(self, shortcut_str: str, hold_ms: int = 50) -> None:
        """模拟按下-释放一次快捷键。"""
        shortcut = self.parse_shortcut(shortcut_str)
        self._press(shortcut)
        time.sleep(hold_ms / 1000.0)
        self._release(shortcut)
        logger.debug(f"模拟点击: {shortcut_str}")

    def press_shortcut(self, shortcut_str: str) -> None:
        """按下快捷键（不释放）。"""
        shortcut = self.parse_shortcut(shortcut_str)
        self._press(shortcut)
        logger.debug(f"按下: {shortcut_str}")

    def release_shortcut(self, shortcut_str: str) -> None:
        """释放快捷键。"""
        shortcut = self.parse_shortcut(shortcut_str)
        self._release(shortcut)
        logger.debug(f"释放: {shortcut_str}")

    # ── 内部实现 ──────────────────────────────────────────

    def _press(self, shortcut: Shortcut) -> None:
        for mod in shortcut.modifiers:
            self._controller.press(mod)
        self._controller.press(shortcut.key)

    def _release(self, shortcut: Shortcut) -> None:
        self._controller.release(shortcut.key)
        for mod in reversed(shortcut.modifiers):
            self._controller.release(mod)

    # ── 便捷：发送文本（通过剪贴板粘贴）──────────────────

    @staticmethod
    def paste_text(text: str) -> None:
        """把文本写入剪贴板，然后 Cmd+V 粘贴。"""
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.05)
        sim = KeySimulator()
        sim.tap_shortcut("cmd+v")
        time.sleep(0.05)
