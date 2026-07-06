#!/usr/bin/env python3
"""
小米电视蓝牙遥控器 按键探测器

通过 pynput 监听蓝牙键盘事件，帮助你：
  1. 验证遥控器按键能被 macOS 识别
  2. 找出每个物理按键对应的 pynput keyCode
  3. 根据输出，我们可以决定用哪个键来触发语音输入 / 发 AI

用法：
    venv/bin/python3 probe_remote.py
"""

from __future__ import annotations

import sys
import time

try:
    from pynput import keyboard
except ImportError:
    print("❌ pynput 未安装。请执行：pip install pynput")
    sys.exit(1)


def main():
    print()
    print("=" * 60)
    print("  小米电视遥控器按键探测器")
    print("=" * 60)
    print()
    print("  说明：")
    print("  - 蓝牙遥控器已作为键盘设备配对到 Mac")
    print("  - 按下的每个物理键都会触发一个 keyCode 事件")
    print("  - 每个物理键通常有两次事件：press + release")
    print()
    print("  请依次尝试遥控器的按键，观察终端输出：")
    print("    OK（确认）、上下左右、主页、菜单、音量+/-、电源、语音")
    print()
    print("  如果某个按键按了没有任何输出，说明该按键不走标准 HID")
    print("  （不太可能，但也可能是指纹/AI 等私有功能键）")
    print()
    print("  按 Ctrl+C 退出")
    print()
    print("-" * 60)
    print()

    count = 0
    last_key = None
    last_time = 0

    def on_press(key):
        nonlocal count, last_key, last_time
        count += 1
        now = time.monotonic()
        interval = (now - last_time) * 1000 if last_time > 0 else 0
        last_time = now

        # 过滤重复事件（按住不放时 pynput 会重复发 press）
        if key == last_key and interval < 200:
            return
        last_key = key

        key_name = _format_key(key)
        print(f"  [按下 {count:3d}]  keyCode: {key!r}  ({key_name})")

    def on_release(key):
        key_name = _format_key(key)
        print(f"  [释放      ]  keyCode: {key!r}  ({key_name})")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            pass

    print()
    print(f"  监听结束，共捕获 {count} 个按压事件。")
    print()


def _format_key(key) -> str:
    """将 pynput key 对象格式化为可读字符串。"""
    try:
        # 普通字符键
        return key.char
    except AttributeError:
        pass

    # 特殊键
    name = str(key)
    # pynput 的 Key.xxx 格式
    if name.startswith("Key."):
        return name[4:]
    return name


if __name__ == "__main__":
    main()
