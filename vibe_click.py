#!/usr/bin/env python3
"""
Bluetooth Headset Vibe — 主入口

用蓝牙耳机按键触发语音输入 + 双击发给 AI。

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

from core.event_listener import (
    EventListener,
    AccessibilityPermissionError,
    EventTapDisabledError,
)
from core.key_simulator import KeySimulator
from core.voice_trigger import VoiceTrigger, VoiceTriggerConfig
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
    required_keys = ["keyboard_shortcut", "ai"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"配置缺少必要字段: '{key}'")

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

        # 语音触发状态机
        trigger_config = VoiceTriggerConfig(
            double_click_max_interval_ms=self.config.get("double_click", {}).get(
                "max_interval_ms", 350
            ),
        )
        self.trigger = VoiceTrigger(trigger_config)

        # AI 客户端
        ai_cfg = self.config["ai"]
        self.ai_client = AIClient(
            provider=ai_cfg.get("provider", "claude"),
            api_key=ai_cfg["api_key"],
            model=ai_cfg.get("model", "claude-sonnet-5"),
            system_prompt=self.config.get("system_prompt", ""),
            base_url=ai_cfg.get("base_url"),
        )

        # 快捷键字符串
        self.shortcut = self.config["keyboard_shortcut"]["voice_input"]

        # 绑定回调
        self.trigger.set_callbacks(
            on_start_recording=self._on_start_recording,
            on_stop_recording=self._on_stop_recording,
            on_send_to_ai=self._on_send_to_ai,
        )

    # ── 回调实现 ──────────────────────────────────────────

    def _on_start_recording(self) -> None:
        """开始录音：模拟快捷键触发输入法语音输入。"""
        logger.info("🎤 开始录音（触发语音输入）...")
        self.simulator.press_shortcut(self.shortcut)

    def _on_stop_recording(self) -> None:
        """停止录音：释放快捷键。"""
        self.simulator.release_shortcut(self.shortcut)
        logger.info("📝 录音结束，等待输入法转文字...")

    def _on_send_to_ai(self, text: str) -> None:
        """把文字发给 AI，结果写入剪贴板。"""
        logger.info(f"🤖 发给 AI: {text[:80]}{'...' if len(text) > 80 else ''}")

        try:
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
        listener = EventListener(suppress_system_events=True)
        listener.on_press = self.trigger.handle_key_down
        listener.on_release = self.trigger.handle_key_up

        print()
        print("=" * 50)
        print("  🎧 Bluetooth Headset Vibe 已启动")
        print("=" * 50)
        print()
        print(f"  快捷键: {self.shortcut}")
        print(f"  AI 模型: {self.config['ai'].get('model', 'default')}")
        print()
        print("  操作说明：")
        print("    按住耳机键 → 语音输入")
        print("    松开耳机键 → 结束语音")
        print("    双击耳机键 → 发给 AI")
        print()
        print("  按 Ctrl+C 退出")
        print()
        print("=" * 50)
        print()

        try:
            listener.start()
        except AccessibilityPermissionError as e:
            logger.error(str(e))
            sys.exit(1)
        except EventTapDisabledError as e:
            logger.error(str(e))
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n👋 再见！")


# ── 命令行入口 ────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bluetooth Headset Vibe — 蓝牙耳机变 Vibe Coding 控制器"
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

        # 检查辅助功能权限
        if EventListener.check_accessibility_permission():
            print("  ✅ 辅助功能权限：已授权")
        else:
            print("  ❌ 辅助功能权限：未授权")
            print("     请打开：系统设置 → 隐私与安全性 → 辅助功能")

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
        try:
            import Quartz
            print("  ✅ pyobjc-framework-Quartz 已安装")
        except ImportError:
            print("  ❌ pyobjc-framework-Quartz 未安装")

        try:
            import yaml
            print("  ✅ PyYAML 已安装")
        except ImportError:
            print("  ❌ PyYAML 未安装")

        try:
            import requests
            print("  ✅ requests 已安装")
        except ImportError:
            print("  ❌ requests 未安装")

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
