#!/usr/bin/env python3
"""
Redmi Buds 7S 按键探测器（两种方案并行）。

方案 A：pynput 监听媒体键（listen 模式）
方案 B：CGEventTap 全量 NSD 监听

如果都捕获不到，就尝试方案 C：直接 hook NSEvent 全局通知。
"""

from __future__ import annotations

import sys
import time
import subprocess

def run_pynput_probe(timeout_sec: int):
    """方案 A：用 pynput 全局监听媒体键。"""
    print()
    print("=" * 60)
    print("  方案 A：pynput 媒体键监听")
    print("=" * 60)
    print()

    try:
        from pynput import keyboard
    except ImportError:
        print("  pynput 未安装，跳过。")
        print()
        return

    keys_seen = []

    def on_press(key):
        keys_seen.append(("press", key, time.monotonic()))
        print(f"  press: {key!r}")
        sys.stdout.flush()

    def on_release(key):
        keys_seen.append(("release", key, time.monotonic()))
        print(f"  release: {key!r}")
        sys.stdout.flush()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    print(f"  采集 {timeout_sec} 秒，请单击/双击/长按耳机...")
    print()
    time.sleep(timeout_sec)
    listener.stop()

    print()
    print(f"  pynput 捕获到 {len(keys_seen)} 个事件。")
    if not keys_seen:
        print("  pynput 没有捕获到 ── 可能 macOS 在 pynput 可见层之外消费了媒体键。")
    print()


def run_cgprobe(timeout_sec: int):
    """方案 B：CGEventTap 全量 NSD 监听（精确版）。"""
    print("=" * 60)
    print("  方案 B：CGEventTap NSD 全量监听")
    print("=" * 60)
    print()

    import Quartz
    from Quartz import (
        CGEventTapCreate,
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        CGEventTapEnable,
        kCGEventTapDisabledByTimeout,
        kCGEventTapDisabledByUserInput,
        NSEvent,
        NSSystemDefined,
    )
    import ApplicationServices as AS

    import ctypes
    from ctypes import c_void_p, c_int

    collected = 0
    tap_holder = [None]

    CALLBACK_TYPE = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_int, c_void_p, c_void_p)

    @CALLBACK_TYPE
    def callback(proxy, type_, event, refcon):
        nonlocal collected

        if type_ == kCGEventTapDisabledByTimeout or type_ == kCGEventTapDisabledByUserInput:
            if tap_holder[0]:
                CGEventTapEnable(tap_holder[0], True)
            return event

        ns_event = NSEvent.eventWithCGEvent_(event)

        # 只关心 NSD 事件（type=14）
        if type_ != 14:
            return event

        subtype = ns_event.subtype() if ns_event else -1
        data1 = ns_event.data1() if ns_event and hasattr(ns_event, 'data1') else 0

        if subtype == 8:
            key_code = (data1 >> 16) & 0xFFFF
            is_down = bool(data1 & 1)
            collected += 1
            direction = "↓down" if is_down else "↑up  "
            print(f"  [{collected:3d}] MEDIA_KEY  keyCode=0x{key_code:02X}  {direction}  subtype=8")
        else:
            collected += 1
            print(f"  [{collected:3d}] NSD  subtype={subtype}  (非媒体键事件)")
        sys.stdout.flush()
        return event

    if not AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}):
        print("  ❌ 辅助功能权限未授予")
        return

    # 用位掩码 bit 14
    mask = (1 << 14)

    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionListenOnly,
        mask,
        callback,
        None,
    )
    if tap is None:
        print("  ❌ CGEventTapCreate 失败")
        return

    tap_holder[0] = tap
    rl_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
    Quartz.CFRunLoopAddSource(
        Quartz.CFRunLoopGetCurrent(),
        rl_source,
        Quartz.kCFRunLoopDefaultMode,
    )
    CGEventTapEnable(tap, True)

    print(f"  采集 {timeout_sec} 秒，请单击/双击/长按耳机...")
    print()

    deadline = time.monotonic() + timeout_sec
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, min(remaining, 0.5), False)
    except KeyboardInterrupt:
        pass

    CGEventTapEnable(tap, False)

    print()
    print(f"  CGEventTap 捕获到 {collected} 个 NSD 事件。")
    print()


def run_swift_capse_probe(timeout_sec: int):
    """方案 C：用内嵌 Swift + NSEvent addGlobalMonitorForEventsMatchingMask 监听。"""
    print("=" * 60)
    print("  方案 C：Swift 全局 NSEvent 监听（最宽松）")
    print("=" * 60)
    print()

    # Swift 字符串插值用 \(name)，但 Python f-string 用 {{}}，所以用 format 代替
    swift_code = """
import Foundation
import Cocoa

let timeout = %(timeout)d
var count = 0
let startTime = Date()

let mask: NSEvent.EventTypeMask = [.systemDefined]

let monitor = NSEvent.addGlobalMonitorForEvents(matching: mask) { event in
    let subtype = event.subtype.rawValue
    let data1 = event.data1
    let keyCode = (data1 >> 16) & 0xFFFF
    let isDown = (data1 & 1) != 0
    count += 1
    let dir = isDown ? "↓down" : "↑up  "
    print("[\\(count)] NSD subtype=\\(subtype) keyCode=0x\\(String(keyCode, radix: 16, uppercase: true)) \\(dir) data1=0x\\(String(data1, radix: 16, uppercase: true))")
    fflush(stdout)
}

let localMonitor = NSEvent.addLocalMonitorForEvents(matching: mask) { event in
    return event
}

print("开始监听...")
fflush(stdout)

let loop = RunLoop.main
let deadline = Date().addingTimeInterval(Double(timeout))
while Date() < deadline {
    loop.run(until: Date().addingTimeInterval(0.5))
}

NSEvent.removeMonitor(monitor)
NSEvent.removeMonitor(localMonitor)
print("监听结束，共 \\(count) 个事件。")
""" % {"timeout": timeout_sec}

    swift_file = "/tmp/probe_nsd.swift"
    try:
        with open(swift_file, "w") as f:
            f.write(swift_code)
        print(f"  编译并运行 Swift 探测...")
        print()
        subprocess.run(
            ["swift", swift_file],
            timeout=timeout_sec + 30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("  ⚠️  Swift 运行超时")
    except FileNotFoundError:
        print("  ⚠️  Swift 编译器未找到（理论上 macOS 自带）")
    except Exception as e:
        print(f"  ⚠️  Swift 运行出错: {e}")

    print()


def main():
    timeout_sec = int(sys.argv[1]) if len(sys.argv) > 1 else 20

    print()
    print("#" * 60)
    print("  Redmi Buds 7S 按键探测器")
    print(f"  全面采集 {timeout_sec} 秒")
    print("#" * 60)
    print()
    print("  请播放一首歌，然后依次做：")
    print("    1. 单击一下")
    print("    2. 双击一下")
    print("    3. 长按 2 秒松开")
    print()

    run_pynput_probe(timeout_sec)
    run_cgprobe(timeout_sec)
    run_swift_capse_probe(timeout_sec)

    print()
    print("=" * 60)
    print("  探测完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
