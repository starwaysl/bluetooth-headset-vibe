"""
语音触发逻辑 — 根据蓝牙耳机按键时序，决定触发语音输入还是发给 AI。

核心状态机：
    IDLE → (按住) → RECORDING → (松开) → IDLE
    IDLE → (单击) → WAIT_DOUBLE → (双击) → SENDING_AI → IDLE
    IDLE → (单击) → WAIT_DOUBLE → (超时) → IDLE（正常单击被忽略）

这样区分「长按录音」和「双击发 AI」：
    - 按住不放 = 录音
    - 快速双击 = 发 AI
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from core.event_listener import MediaKeyEvent, MediaKey

logger = logging.getLogger(__name__)


class State(Enum):
    IDLE = "idle"
    RECORDING = "recording"
    WAIT_DOUBLE = "wait_double"
    SENDING_AI = "sending_ai"


@dataclass
class VoiceTriggerConfig:
    """触发配置。"""
    double_click_max_interval_ms: int = 350    # 双击最大间隔
    press_hold_threshold_ms: int = 150         # 超过这个时间算"按住"（不算点击）
    shortcuts: Optional[dict] = None           # 快捷键配置


class VoiceTrigger:
    """
    蓝牙耳机按键 → 动作的状态机。

    用法：
        trigger = VoiceTrigger(config)
        trigger.on_start_recording = lambda: sim.press_shortcut("opt+cmd+s")
        trigger.on_stop_recording = lambda: sim.release_shortcut("opt+cmd+s")
        trigger.on_send_to_ai = lambda text: print(f"发给 AI: {text}")
    """

    def __init__(self, config: VoiceTriggerConfig):
        self._config = config
        self._state = State.IDLE
        self._press_start_time: float = 0
        self._last_release_time: float = 0
        self._double_click_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

        # 回调（由外部注入）
        self._on_start_recording: Optional[Callable[[], None]] = None
        self._on_stop_recording: Optional[Callable[[], None]] = None
        self._on_clipboard_captured: Optional[Callable[[str], None]] = None
        self._on_send_to_ai: Optional[Callable[[str], None]] = None
        self._on_ai_response: Optional[Callable[[str], None]] = None

    # ── 回调设置 ──────────────────────────────────────────

    def set_callbacks(
        self,
        on_start_recording: Optional[Callable[[], None]] = None,
        on_stop_recording: Optional[Callable[[], None]] = None,
        on_send_to_ai: Optional[Callable[[str], None]] = None,
        on_ai_response: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_start_recording = on_start_recording
        self._on_stop_recording = on_stop_recording
        self._on_send_to_ai = on_send_to_ai
        self._on_ai_response = on_ai_response

    # ── 事件入口 ──────────────────────────────────────────

    def handle_key_down(self, event: MediaKeyEvent) -> None:
        """处理按键按下事件。"""
        with self._lock:
            now = time.monotonic()

            if self._state == State.IDLE:
                self._press_start_time = now
                self._state = State.RECORDING  # 先假设是录音，等待后续判断
                logger.debug("状态: IDLE → RECORDING (可能)")

            elif self._state == State.WAIT_DOUBLE:
                # 在 WAIT_DOUBLE 期间再次按下 → 可能是双击的一部分
                interval = (now - self._last_release_time) * 1000
                if interval <= self._config.double_click_max_interval_ms:
                    # 进入预双击状态，等待释放确认
                    logger.debug(f"可能的第二次按下，间隔 {interval:.0f}ms")
                else:
                    # 间隔过长，当作新的一次单击
                    self._cancel_double_timer()
                    self._press_start_time = now
                    self._state = State.RECORDING

    def handle_key_up(self, event: MediaKeyEvent) -> None:
        """处理按键释放事件。"""
        with self._lock:
            now = time.monotonic()
            duration = (now - self._press_start_time) * 1000
            logger.debug(f"释放，持续 {duration:.0f}ms，当前状态 {self._state.value}")

            if self._state == State.RECORDING:
                if duration >= self._config.press_hold_threshold_ms:
                    # 真正的长按释放 → 结束录音
                    self._state = State.IDLE
                    if self._on_stop_recording:
                        try:
                            self._on_stop_recording()
                        except Exception as e:
                            logger.error(f"on_stop_recording 回调出错: {e}")
                    logger.info("📝 录音结束，等待输入法转文字...")
                else:
                    # 短按释放 → 可能是双击的第一下
                    self._last_release_time = now
                    self._state = State.WAIT_DOUBLE
                    self._start_double_timer()
                    logger.debug("短按，进入 WAIT_DOUBLE")

            elif self._state == State.WAIT_DOUBLE:
                # 第二次释放 → 双击确认！
                interval = (now - self._last_release_time) * 1000
                if interval <= self._config.double_click_max_interval_ms:
                    self._cancel_double_timer()
                    self._fire_double_click()
                else:
                    # 间隔过长，忽略
                    self._state = State.IDLE

    # ── 双击定时器 ────────────────────────────────────────

    def _start_double_timer(self) -> None:
        """启动双击超时定时器。"""
        timeout = self._config.double_click_max_interval_ms / 1000.0
        self._double_click_timer = threading.Timer(timeout, self._on_double_timeout)
        self._double_click_timer.daemon = True
        self._double_click_timer.start()

    def _cancel_double_timer(self) -> None:
        """取消双击超时定时器。"""
        if self._double_click_timer:
            self._double_click_timer.cancel()
            self._double_click_timer = None

    def _on_double_timeout(self) -> None:
        """双击超时：确认这是一次普通单击，不触发任何动作。"""
        with self._lock:
            if self._state == State.WAIT_DOUBLE:
                logger.debug("双击超时，确认为普通单击 → IDLE")
                self._state = State.IDLE

    # ── 双击触发 ──────────────────────────────────────────

    def _fire_double_click(self) -> None:
        """双击确认触发：读取剪贴板并发给 AI。"""
        self._state = State.SENDING_AI
        logger.info("🎯 双击确认！读取剪贴板发给 AI...")

        # 在新线程中执行，避免阻塞事件回调
        threading.Thread(target=self._do_send_to_ai, daemon=True).start()

    def _do_send_to_ai(self) -> None:
        """实际执行发给 AI 的逻辑。"""
        try:
            from core.clipboard import get_selected_text_via_copy

            # 模拟 Cmd+C 复制输入框中的当前文本
            text = get_selected_text_via_copy()
            if not text or not text.strip():
                logger.warning("剪贴板为空，没有内容可发给 AI")
                self._state = State.IDLE
                return

            text = text.strip()
            logger.info(f"准备发给 AI ({len(text)} 字符): {text[:50]}...")

            if self._on_send_to_ai:
                self._on_send_to_ai(text)

        except Exception as e:
            logger.exception(f"发给 AI 时出错: {e}")
        finally:
            self._state = State.IDLE

    @property
    def state(self) -> State:
        return self._state
