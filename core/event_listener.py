"""
Quartz Event Tap 模块 — 监听蓝牙耳机媒体键事件。

macOS 上蓝牙耳机的按键通过 AVRCP 协议上报，表现为系统媒体键事件
(NSystemDefinedEventType)。我们使用 Quartz Event Tap 在全局层面
监听这些事件，并支持拦截（阻止系统默认行为，如音乐播放/暂停）。

权限要求：Accessibility（辅助功能）权限。

参考：
  - https://developer.apple.com/documentation/coregraphics/quartz_event_taps
  - https://stackoverflow.com/questions/29083647/capture-media-key-events-in-macos
"""

from __future__ import annotations

import logging
from ctypes import c_void_p, c_int
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import Quartz
from Quartz import (
    CGEventTapCreate,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    kCGEventTapOptionDefault,
    CGEventTapEnable,
    kCGEventTapDisabledByTimeout,
    kCGEventTapDisabledByUserInput,
    CGEventGetIntegerValueField,
    kCGEventSubtypeHIDMediaKey,
    CGEventGetFlags,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
)

logger = logging.getLogger(__name__)


class MediaKey(Enum):
    """ macOS 系统定义的媒体键类型
    来自 IOKit/hidsystem/IOHIDUsageTables.h 的 kHIDUsage_MediaKey_* 系列。
    我们通过 event subtype 的 data1 字段解码。
    """
    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    PREVIOUS = "previous"
    FAST_FORWARD = "fast_forward"
    REWIND = "rewind"
    UNKNOWN = "unknown"

    @classmethod
    def from_event_data(cls, data1: int) -> "MediaKey":
        """ 从 CGEvent 的 data1 字段解码媒体键类型。
        data1 的高 16 位是 keyCode，低 16 位中 Bit 0 表示 keyState
        (0=up, 1=down)。
        """
        # AVRCP 按键的 keyCode 在 macOS 上映射参考：
        # 0x0E = Play/Pause, 0x0B = Next, 0x0C = Previous
        key_code = (data1 >> 16) & 0xFFFF
        AVRCP_MAP = {
            0x0E: cls.PLAY_PAUSE,
            0x0B: cls.NEXT,
            0x0C: cls.PREVIOUS,
        }
        return AVRCP_MAP.get(key_code, cls.UNKNOWN)


@dataclass
class MediaKeyEvent:
    key: MediaKey
    is_down: bool       # True = 按下，False = 释放
    flags: int          # CGEvent flags（含修饰键）
    timestamp: float    # 事件时间戳（用于双击检测）

    @property
    def has_option(self) -> bool:
        return bool(self.flags & int(kCGEventFlagMaskAlternate))

    @property
    def has_command(self) -> bool:
        return bool(self.flags & int(kCGEventFlagMaskCommand))


class EventListenerError(Exception):
    pass


class AccessibilityPermissionError(EventListenerError):
    """未获得辅助功能权限"""
    pass


class EventTapDisabledError(EventListenerError):
    """Event Tap 被系统禁用（通常由超时或权限丢失引起）"""
    pass


class EventListener:
    """
    全局监听蓝牙耳机媒体键。

    使用方式：
        listener = EventListener()
        listener.on_key_down = lambda e: print(f"Pressed: {e.key}")
        listener.on_key_up   = lambda e: print(f"Released: {e.key}")
        listener.start()
    """

    def __init__(self, suppress_system_events: bool = True):
        self._suppress = suppress_system_events
        self._tap: Optional[c_void_p] = None
        self._run_loop_source: Optional[c_void_p] = None
        self._on_press: Optional[Callable[[MediaKeyEvent], None]] = None
        self._on_release: Optional[Callable[[MediaKeyEvent], None]] = None

    # ── 对外回调 ──────────────────────────────────────────

    @property
    def on_press(self) -> Optional[Callable[[MediaKeyEvent], None]]:
        return self._on_press

    @on_press.setter
    def on_press(self, callback: Optional[Callable[[MediaKeyEvent], None]]) -> None:
        self._on_press = callback

    @property
    def on_release(self) -> Optional[Callable[[MediaKeyEvent], None]]:
        return self._on_release

    @on_release.setter
    def on_release(self, callback: Optional[Callable[[MediaKeyEvent], None]]) -> None:
        self._on_release = callback

    # ── 权限检查 ──────────────────────────────────────────

    @staticmethod
    def check_accessibility_permission() -> bool:
        """检查是否具有辅助功能权限。"""
        options = {Quartz.kAXTrustedCheckOptionPrompt: True}
        trusted = Quartz.AXIsProcessTrustedWithOptions(options)
        return bool(trusted)

    # ── Tap 生命周期 ───────────────────────────────────────

    def start(self) -> None:
        """启动事件监听（阻塞当前线程的 RunLoop）。"""
        if not self.check_accessibility_permission():
            raise AccessibilityPermissionError(
                "脚本需要「辅助功能」权限。\n"
                "请打开：系统设置 → 隐私与安全性 → 辅助功能 → 添加当前终端程序。"
            )

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault if self._suppress else 0x01,  # kCGEventTapOptionListenOnly
            Quartz.CGEventMaskBit(Quartz.kCGEventSystemDefined),
            _event_tap_proxy,
            None,
        )
        if tap is None:
            raise EventTapDisabledError("CGEventTapCreate 返回 NULL，辅助功能权限可能未生效。")

        # 使用 ctypes 回调保持 Python 对象存活
        self._tap = tap
        self._callback_ref = _install_listener(self)

        run_loop_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(),
            run_loop_source,
            Quartz.kCFRunLoopDefaultMode,
        )
        CGEventTapEnable(tap, True)

        logger.info("Quartz Event Tap 已启动，等待蓝牙耳机按键事件...")
        try:
            Quartz.CFRunLoopRun()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        """停止事件监听。"""
        if self._tap:
            CGEventTapEnable(self._tap, False)
            self._tap = None
            logger.info("Event Tap 已停止。")

    @staticmethod
    def enable_tap_again(tap: c_void_p) -> None:
        """超时后尝试重新启用 tap。"""
        CGEventTapEnable(tap, True)


# ── 内部 Quartz 回调（C 函数级别的桥接） ───────────────────

import ctypes

# 存储当前活跃的 EventListener 实例，供 C 回调调用
_active_listener: Optional[EventListener] = None


def _install_listener(listener: EventListener) -> ctypes._CFuncPtr:
    """安装 C 级别的 Event Tap 回调，并保存全局引用。"""
    global _active_listener
    _active_listener = listener
    return _event_tap_callback


# 使用 ctypes 定义回调函数原型
CALLBACK_FUNC_TYPE = ctypes.CFUNCTYPE(
    c_void_p,       # return type (may be CGEventRef or None)
    c_void_p,       # proxy
    c_int,          # type
    c_void_p,       # event
    c_void_p,       # refcon
)


def _event_tap_callback(proxy, type_, event, refcon) -> c_void_p:
    """Event Tap 回调入口。

    - 当 tap 被系统禁用时（超时或用户输入），type 为
      kCGEventTapDisabledByTimeout/kCGEventTapDisabledByUserInput，
      此时需要重新启用。
    - 对于正常的 NSD 事件，解码 subtype 和 data1，构造 MediaKeyEvent，
      分发给 listener 的回调。
    """
    global _active_listener

    if type_ == kCGEventTapDisabledByTimeout or type_ == kCGEventTapDisabledByUserInput:
        logger.warning("Event Tap 被系统禁用，尝试重新启用...")
        if _active_listener and _active_listener._tap:
            _active_listener.enable_tap_again(_active_listener._tap)
        return event

    try:
        subtype = CGEventGetIntegerValueField(event, kCGEventSubtypeHIDMediaKey)
        # subtype=8 表示 AVRCP 媒体键
        if subtype != 8:
            return event
    except Exception:
        return event

    try:
        data1 = Quartz.CGEventGetIntegerValueField(
            event, Quartz.kCGMouseEventSubtype  # 复用同一 field
        )
        key = MediaKey.from_event_data(data1)
        # bit 0 of data1 = keyState (按下/释放)
        is_down = bool(data1 & 1)
        flags = CGEventGetFlags(event)
        import time
        timestamp = time.monotonic()

        evt = MediaKeyEvent(
            key=key,
            is_down=is_down,
            flags=flags,
            timestamp=timestamp,
        )

        if _active_listener is None:
            return event

        if is_down:
            logger.debug(f"按下: {key.name}")
            handler = _active_listener.on_press
        else:
            logger.debug(f"释放: {key.name}")
            handler = _active_listener.on_release

        if handler:
            handler(evt)
    except Exception as e:
        logger.exception(f"处理事件回调时出错: {e}")

    # 返回 None（c_void_p 转为 null）表示拦截事件，不交给系统
    return None if _active_listener and _active_listener._suppress else event


# 模块级别名
_event_tap_proxy = CALLBACK_FUNC_TYPE(_event_tap_callback)
