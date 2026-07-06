"""
剪贴板操作模块 — 读取和设置剪贴板内容。

macOS 上通过 pyperclip 或 subprocess 调用 pbcopy/pbpaste。
"""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    pass


def get_text() -> Optional[str]:
    """读取剪贴板内容。"""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        pass

    # 回退：使用 macOS 原生命令
    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception as e:
        logger.error(f"读取剪贴板失败: {e}")

    return None


def set_text(text: str) -> None:
    """设置剪贴板内容。"""
    try:
        import pyperclip
        pyperclip.copy(text)
        return
    except Exception:
        pass

    # 回退：使用 macOS 原生命令
    try:
        subprocess.run(
            ["pbcopy"],
            input=text,
            text=True,
            timeout=5,
            check=True,
        )
    except Exception as e:
        raise ClipboardError(f"写入剪贴板失败: {e}")


def get_selected_text_via_copy() -> Optional[str]:
    """
    通过模拟 Cmd+C 复制当前选中文本。

    注意：这会修改剪贴板内容，调用者应负责恢复。
    """
    import time
    from core.key_simulator import KeySimulator

    sim = KeySimulator()
    sim.tap_shortcut("cmd+c")
    time.sleep(0.1)  # 等待系统处理复制
    return get_text()
