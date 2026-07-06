#!/usr/bin/env python3
"""
Bluetooth Headset Vibe — 主入口

用蓝牙遥控器（或其他 HID 键盘设备）的按键触发语音输入 + 发给 AI。

工作原理：
  1. 用 pynput 全局监听键盘事件
  2. 当检测到触发键（如 F5、回车）时，模拟输入法的语音快捷键
  3. 当检测到发送键（如右 Command）时，复制当前输入框文字 → 发给 AI → 结果写入剪贴板

用法：
    python vibe_click.py                # 使用默认 config.yaml
    python vibe_click.py -c my.yaml     # 指定配置文件
    python vibe_click.py --check        # 仅检查权限和环境
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from pynput import keyboard
from pynput.keyboard import Key, KeyCode

from core.key_simulator import KeySimulator
from core.ai_client import AIClient, AIClientError
from core.clipboard import set_text

logger = logging.getLogger("vibe")


# ── 配置加载 ──────────────────────────────────────────────

def load_config(config_path: str) -> dict:
    """加载 YAML 配置文件。"""
    path = Path(config_path)
    if not path.exists():
        print(f"❌ 配置文件不存在: {path}")
        print(f"   请先复制 config.yaml.example 为 config.yaml 并修改配置。")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config:
        raise ValueError("配置文件为空")

    return config


def validate_config(config: dict) -> None:
    """验证配置完整性。"""
    required_keys = ["triggers", "keyboard_shortcut", "ai"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"配置缺少必要字段: '{key}'")

    if "voice_input" not in config["triggers"]:
        raise ValueError("triggers.voice_input 未配置")
    if "send_to_ai" not in config["triggers"]:
        raise ValueError("triggers.send_to_ai 未配置")
    if "voice_input" not in config["keyboard_shortcut"]:
        raise ValueError("keyboard_shortcut.voice_input 未配置")

    ai = config["ai"]
    if ai.get("api_key") in (None, "", "YOUR_API_KEY_HERE"):
        raise ValueError("ai.api_key 未设置，请在 config.yaml 中填入你的 API Key")


# ── 日志配置 ──────────────────────────────────────────────

def setup_logging(debug: bool = False) -> None:
    """配置日志输出。"""
    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt = "%H:%M:%S"

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # 降低第三方库的日志级别
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# ── 按键解析工具 ──────────────────────────────────────────

def parse_trigger_key(trigger_str: str) -> Key | KeyCode:
    """
    把配置里的触发键字符串（如 "Key.f5"、"Key.enter"）解析为 pynput Key/KeyCode。

    支持格式：
      - "Key.f5"       → Key.f5
      - "Key.enter"    → Key.enter
      - "Key.cmd_r"    → Key.cmd_r
      - "a"            → KeyCode.from_char("a")
      - "1"            → KeyCode.from_char("1")
    """
    s = trigger_str.strip()

    # Key.xxx 格式
    if s.startswith("Key."):
        key_name = s[4:]
        if hasattr(Key, key_name):
            return getattr(Key, key_name)
        raise ValueError(f"未知的 Key 名称: '{key_name}'。可用: {[k for k in dir(Key) if not k.startswith('_')]}")

    # 单字符
    if len(s) == 1:
        return KeyCode.from_char(s)

    raise ValueError(f"无法解析触发键: '{trigger_str}'。请使用 Key.xxx 格式（如 Key.f5）")


# ── 主程序 ────────────────────────────────────────────────

class VibeApp:
    """应用主类，组装所有模块。"""

    def __init__(self, config: dict):
        self.config = config
        self._setup_modules()

    def _setup_modules(self) -> None:
        """初始化所有模块。"""
        # 按键模拟
        self.simulator = KeySimulator()

        # 解析触发键
        self.voice_trigger_key = parse_trigger_key(self.config["triggers"]["voice_input"])
        self.ai_trigger_key = parse_trigger_key(self.config["triggers"]["send_to_ai"])

        # 快捷键字符串
        self.shortcut = self.config["keyboard_shortcut"]["voice_input"]

        # AI 客户端
        ai_cfg = self.config["ai"]
        self.ai_client = AIClient(
            provider=ai_cfg.get("provider", "claude"),
            api_key=ai_cfg["api_key"],
            model=ai_cfg.get("model", "claude-sonnet-5"),
            system_prompt=self.config.get("system_prompt", ""),
            base_url=ai_cfg.get("base_url"),
        )

        # 状态：当前是否正在录音（按着语音键）
        self._is_recording = False
        # 防抖：上次触发 AI 的时间
        self._last_ai_trigger = 0.0

    # ── 按键事件处理 ──────────────────────────────────────

    def on_press(self, key) -> None:
        """按键按下事件。"""
        logger.debug(f"按下: {key!r}")

        if key == self.voice_trigger_key:
            # 触发语音输入：按下快捷键
            logger.info("🎤 触发语音输入...")
            self.simulator.press_shortcut(self.shortcut)
            self._is_recording = True

        elif key == self.ai_trigger_key:
            # 防抖：避免连续触发
            now = time.monotonic()
            if now - self._last_ai_trigger < 0.5:
                return
            self._last_ai_trigger = now
            self._send_to_ai()

    def on_release(self, key) -> None:
        """按键释放事件。"""
        logger.debug(f"释放: {key!r}")

        if key == self.voice_trigger_key and self._is_recording:
            # 释放语音键：松开快捷键
            self.simulator.release_shortcut(self.shortcut)
            self._is_recording = False
            logger.info("📝 语音输入结束，等待文字输入编辑器...")

    # ── 发给 AI ──────────────────────────────────────────

    def _send_to_ai(self) -> None:
        """复制当前输入框文字 → 发给 AI → 结果写入剪贴板。"""
        logger.info("🤖 准备发给 AI...")

        # 在新线程中执行，避免阻塞键盘监听
        import threading
        threading.Thread(target=self._do_send_to_ai, daemon=True).start()

    def _do_send_to_ai(self) -> None:
        """实际执行发给 AI 的逻辑。"""
        try:
            from core.clipboard import get_selected_text_via_copy

            # 模拟 Cmd+C 复制当前选中文本
            text = get_selected_text_via_copy()
            if not text or not text.strip():
                logger.warning("⚠️ 剪贴板为空，没有内容可发给 AI")
                logger.warning("   请先在编辑器里输入文字，再按发送键")
                return

            text = text.strip()
            logger.info(f"发给 AI ({len(text)} 字符): {text[:80]}{'...' if len(text) > 80 else ''}")

            response = self.ai_client.chat(text)
            logger.info(f"✅ AI 回复 ({response.latency_ms}ms): {response.text[:120]}...")

            # 把 AI 回复写入剪贴板
            set_text(response.text)
            logger.info("📋 AI 回复已写入剪贴板，Cmd+V 粘贴即可")

        except AIClientError as e:
            logger.error(f"❌ AI 调用失败: {e}")
        except Exception as e:
            logger.exception(f"❌ 未知错误: {e}")

    # ── 启动 ──────────────────────────────────────────────

    def run(self) -> None:
        """启动应用（阻塞）。"""
        print()
        print("=" * 50)
        print("  🎧 Bluetooth Headset Vibe 已启动")
        print("=" * 50)
        print()
        print(f"  语音触发键: {self.config['triggers']['voice_input']}")
        print(f"  AI 发送键:  {self.config['triggers']['send_to_ai']}")
        print(f"  输入法快捷键: {self.shortcut}")
        print(f"  AI 模型: {self.config['ai'].get('model', 'default')}")
        print()
        print("  操作说明：")
        print("    按语音键 → 启动微信语音输入")
        print("    松语音键 → 结束语音，文字输入编辑器")
        print("    按 AI 键 → 复制文字 → 发给 Claude → 结果写入剪贴板")
        print()
        print("  按 Ctrl+C 退出")
        print()
        print("=" * 50)
        print()

        with keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
        ) as listener:
            try:
                listener.join()
            except KeyboardInterrupt:
                pass

        print("\n👋 再见！")


# ── 命令行入口 ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bluetooth Headset Vibe — 蓝牙遥控器变 Vibe Coding 控制器"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="配置文件路径（默认: config.yaml）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查权限和环境，不启动监听",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启调试日志",
    )
    args = parser.parse_args()

    setup_logging(debug=args.debug or os.environ.get("VIBE_DEBUG") == "1")

    # 检查模式
    if args.check:
        print("🔍 环境检查")
        print()

        # 检查配置文件
        config_path = Path(args.config)
        if config_path.exists():
            print(f"  ✅ 配置文件：{config_path}")
            try:
                config = load_config(args.config)
                validate_config(config)
                print("  ✅ 配置验证通过")
            except Exception as e:
                print(f"  ❌ 配置验证失败: {e}")
        else:
            print(f"  ⚠️  配置文件不存在：{config_path}")

        # 检查依赖
        for pkg, name in [
            ("pynput", "pynput"),
            ("yaml", "PyYAML"),
            ("requests", "requests"),
            ("pyperclip", "pyperclip"),
        ]:
            try:
                __import__(pkg)
                print(f"  ✅ {name} 已安装")
            except ImportError:
                print(f"  ❌ {name} 未安装")

        return

    # 正常启动
    try:
        config = load_config(args.config)
        validate_config(config)
    except (ValueError, FileNotFoundError) as e:
        logger.error(str(e))
        sys.exit(1)

    app = VibeApp(config)
    app.run()


if __name__ == "__main__":
    main()
