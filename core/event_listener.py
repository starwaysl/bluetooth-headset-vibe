"""
Quartz Event Tap 模块 — 监听蓝牙耳机媒体键事件。

macOS 上蓝牙耳机的按键通过 AVRCP 协议上报，表现为 NSD (NSSystemDefined)
事件。我们用 Quartz Event Tap 全局监听，并通过 NSEvent 桥接读取 subtype
和 data1 字段，从而区分按下/释放、识别按键类型。

权限要求：Accessibility（辅助功能）权限。
"""

from __future__ import annotations

import logging
import time
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
    CGEventGetFlags,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    NSEvent,
    NSSystemDefinedMask,
    NSSystemDefined,
)
from Quartz import (
    CGEventMaskBit as _CGEventMaskBit,
)

logger = logging.getLogger(__name__)


# AVRCP 按键 keyCode 映射
# macOS AVRCP keyCode 来自 IOKit/IOHIDUsageTables.h 的 kHIDUsage_MediaKey_*
AVRP_KEY_MAP: dict[int, str] = {
    0x0E: "play_pause",
    0x0B: "next_track",
    0x0C: "previous_track",
    0x9E: "volume_up",          # kHIDUsage_MediaKey_VolumeUp
    0x9F: "volume_down",        # kHIDUsage_MediaKey_VolumeDown
    0x00: "custom_single_tap",  # 很多耳机的"自定义"单击会发 0x00
}

# keyCode 反向查找表
KEY_NAME_TO_CODE = {v: k for k, v in AVRP_KEY_MAP.items()}


class MediaKey(Enum):
    """媒体键类型。"""
    PLAY_PAUSE = "play_pause"
    NEXT = "next_track"
    PREVIOUS = "previous_track"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    CUSTOM = "custom_single_tap"     # 单击自定义
    UNKNOWN = "unknown"

    @classmethod
    def from_key_code(cls, key_code: int) -> "MediaKey":
        name = AVRP_KEY_MAP.get(key_code)
        if name is None:
            return cls.UNKNOWN
        return cls(name)


@dataclass
class MediaKeyEvent:
    """一次蓝牙耳机按键事件。"""
    key: MediaKey
    key_code: int           # 原始 AVRCP keyCode
    is_down: bool           # True = 按下，False = 释放
    flags: int              # CGEvent flags（含修饰键）
    timestamp: float        # 时间戳（秒）

    @property
    def has_option(self) -> bool:
        return bool(self.flags & int(kCGEventFlagMaskAlternate))

    @property
    def has_command(self) -> bool:
        return bool(self.flags & int(kCGEventFlagMaskCommand))


# ── 自定义异常 ────────────────────────────────────────────

class EventListenerError(Exception):
    pass


class AccessibilityPermissionError(EventListenerError):
    """未获得辅助功能权限"""
    pass


class EventTapDisabledError(EventListenerError):
    """Event Tap 被系统禁用"""
    pass


# ── 事件解码 ──────────────────────────────────────────────

def _decode_nsd_event(event) -> Optional[MediaKeyEvent]:
    """把 CGEvent 解码为 MediaKeyEvent；如果不是按键事件，返回 None。"""
    ns_event = NSEvent.eventWithCGEvent_(event)
    if ns_event is None:
        return None

    # NSD 事件必须是 NSSystemDefined 类型
    if ns_event.type() != NSSystemDefined:
        return None

    subtype = ns_event.subtype()
    if subtype != 8:  # NX_SUBTYPE_AUX_CONTROL_BUTTONS
        return None

    data1 = ns_event.data1()
    # data1 编码：
    #   bits 16-31 → keyCode
    #   bit 0      → keyState (1=down, 0=up)
    key_code = (data1 >> 16) & 0xFFFF
    is_down = bool(data1 & 1)

    if key_code == 0:
        logger.debug(f"NSD event data1=0x{data1:08x}, subtype=subtype, 可能是非标准 AVRCP 事件")
        return None

    flags = CGEventGetFlags(event)
    key = MediaKey.from_key_code(key_code)

    return MediaKeyEvent(
        key=key,
        key_code=key_code,
        is_down=is_down,
        flags=flags,
        timestamp=time.monotonic(),
    )


# ── 回调桥接（C ↔ Python）──────────────────────────────────

import ctypes
from ctypes import c_void_p, c_int

# 当前活跃的监听器引用（避免被 GC）
_active_listener: Optional["EventListener"] = None

CALLBACK_FUNC_TYPE = ctypes.CFUNCTYPE(
    c_void_p,       # return (CGEventRef)
    c_void_p,       # proxy
    c_int,          # type
    c_void_p,       # event
    c_void_p,       # refcon
)


@CALLBACK_FUNC_TYPE
def _cg_event_callback(proxy, type_, event, refcon) -> c_void_p:
    """Quartz Event Tap 的 C 回调。"""
    global _active_listener

    # 系统禁用事件 → 尝试重启用
    if type_ == kCGEventTapDisabledByTimeout or type_ == kCGEventTapDisabledByUserInput:
        logger.warning("Event Tap 被系统禁用，尝试重新启用...")
        if _active_listener and _active_listener._tap:
            _active_listener._tap_enable()
        return event

    # 尝试解码为媒体键事件
    try:
        evt = _decode_nsd_event(event)
    except Exception:
        # 不是 NSD 事件或解码失败，白白交给系统
        return event

    if evt is None:
        return event

    if _active_listener is None:
        return event

    try:
        if evt.is_down:
            logger.debug(f"[{time.strftime('%H:%M:%S')}] 按下: {evt.key.name} (keyCode=0x{evt.key_code:02x})")
            handler = _active_listener.on_press
        else:
            logger.debug(f"[{time.strftime('%H:%M:%S')}] 释放: {evt.key.name}")
            handler = _active_listener.on_release

        if handler:
            handler(evt)
    except Exception:
        logger.exception("处理事件回调时出错")

    # 拦截事件：返回 None（c_void_p 转 null）阻止系统默认行为
    return None if _active_listener._suppress else event


# Event Tap 掩码：只监听 NSSystemDefined 事件
_NSD_MASK = _CGEventMaskBit(NSSystemDefined)


# ── EventListener 类 ──────────────────────────────────────

class EventListener:
    """
    全局监听蓝牙耳机媒体键。

    使用方式：
        listener = EventListener(suppress_system_events=True)
        listener.on_press   = lambda e: print(f"Down: {e.key}")
        listener.on_release = lambda e: print(f"Up  : {e.key}")
        listener.start()   # 阻塞直到 Ctrl+C
    """

    def __init__(self, suppress_system_events: bool = True):
        self._suppress = suppress_system_events
        self._tap: Optional[c_void_p] = None
        self._on_press: Optional[Callable[[MediaKeyEvent], None]] = None
        self._on_release: Optional[Callable[[MediaKeyEvent], None]] = None

    # ── 对外回调属性 ──────────────────────────────────────

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
        """检查并弹出权限申请。"""
        import ApplicationServices as AS
        options = {AS.kAXTrustedCheckOptionPrompt: True}
        return bool(AS.AXIsProcessTrustedWithOptions(options))

    # ── 启停 Tap ───────────────────────────────────────────

    def start(self) -> None:
        """启动事件监听（阻塞 RunLoop）。"""
        if not self.check_accessibility_permission():
            raise AccessibilityPermissionError(
                "脚本需要「辅助功能」权限。\n"
                "请打开：系统设置 → 隐私与安全性 → 辅助功能 → 添加当前终端程序。"
            )

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault if self._suppress else kCGEventTapOptionListenOnly,
            _NSD_MASK,
            _cg_event_callback,
            None,
        )
        if tap is None:
            raise EventTapDisabledError(
                "CGEventTapCreate 返回 NULL。可能原因：\n"
                "  - 辅助功能权限未生效\n"
                "  - 其他程序正在占用事件拦截"
            )

        global _active_listener
        _active_listener = self
        self._tap = tap

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
        """停止监听并清理。"""
        if self._tap:
            CGEventTapEnable(self._tap, False)
            self._tap = None
            logger.info("Event Tap 已停止。")

    def _tap_enable(self) -> None:
        """重新启用 Tap（被系统禁用后调用）。"""
        if self._tap:
            CGEventTapEnable(self._tap, True)

    # ── 公开工具方法 ──────────────────────────────────────

    @staticmethod
    def tap_active_media_keys(timeout: float = 5.0) -> list[MediaKeyEvent]:
        """
        阻塞式收集接下来几秒内的所有媒体键事件，用于探测耳机 keyCode。
        仅用于调试，不要在正常监听流程中使用。
        """
        keys: list[MediaKeyEvent] = []

        def on_press(e: MediaKeyEvent):
            keys.append(e)
            logger.info(f"[{len(keys)}] 捕获: {e.key.name} (keyCode=0x{e.key_code:02x}) down={e.is_down}")

        listener = EventListener(suppress_system_events=False)
        listener.on_press = on_press
        listener.on_release = on_press  # 也捕获释放

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            time.sleep(0.05)
        # 注意：这个方法是简化的占位 — 真正的调用需要 start() 阻塞 RunLoop
        return keys
