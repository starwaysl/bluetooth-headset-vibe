"""
AI 客户端模块 — 调用 Claude / OpenAI / OpenAI 兼容 API。

支持：
  - Anthropic Claude API（默认）
  - OpenAI Chat Completions API
  - OpenAI 兼容的自部署服务（如 Ollama、vLLM 等）
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class AIMessage:
    role: str       # "system" | "user" | "assistant"
    content: str


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    latency_ms: int


class AIClientError(Exception):
    pass


class AIClient:
    """AI API 客户端。"""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        system_prompt: str = "",
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        self.provider = provider.lower()
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.base_url = base_url
        self.timeout = timeout

        if self.provider == "claude":
            self._api_url = base_url or "https://api.anthropic.com/v1/messages"
        elif self.provider in ("openai", "custom"):
            self._api_url = base_url or "https://api.openai.com/v1/chat/completions"
        else:
            raise AIClientError(f"不支持的 AI provider: '{provider}'")

    # ── 公开接口 ──────────────────────────────────────────

    def chat(self, user_message: str) -> AIResponse:
        """发送用户消息，返回 AI 回复。"""
        if not user_message.strip():
            raise AIClientError("消息内容为空")

        messages: List[AIMessage] = []
        if self.system_prompt.strip():
            messages.append(AIMessage(role="system", content=self.system_prompt.strip()))
        messages.append(AIMessage(role="user", content=user_message))

        start = time.monotonic()
        if self.provider == "claude":
            text = self._call_claude(messages)
        else:
            text = self._call_openai(messages)
        latency = int((time.monotonic() - start) * 1000)

        logger.info(f"[{self.provider}] 响应耗时 {latency}ms，长度 {len(text)} 字符")

        return AIResponse(
            text=text,
            provider=self.provider,
            model=self.model,
            latency_ms=latency,
        )

    # ── Claude API ─────────────────────────────────────────

    def _call_claude(self, messages: List[AIMessage]) -> str:
        """调用 Anthropic Messages API。"""
        # Claude 只支持 system 单独传，对话部分需要 user/assistant 交替
        system_content = None
        conversation: List[Dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                system_content = msg.content
            else:
                conversation.append({"role": msg.role, "content": msg.content})

        payload: Dict = {
            "model": self.model,
            "messages": conversation,
            "max_tokens": 1024,
        }
        if system_content:
            payload["system"] = system_content

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            resp = requests.post(
                self._api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise AIClientError(f"请求 Claude API 失败: {e}")

        if resp.status_code != 200:
            raise AIClientError(
                f"Claude API 返回 {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        content_blocks = data.get("content", [])
        text_parts = [block.get("text", "") for block in content_blocks if block.get("type") == "text"]
        return "".join(text_parts)

    # ── OpenAI API ─────────────────────────────────────────

    def _call_openai(self, messages: List[AIMessage]) -> str:
        """调用 OpenAI Chat Completions API。"""
        payload = {
            "model": self.model,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ],
            "max_tokens": 1024,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                self._api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise AIClientError(f"请求 OpenAI API 失败: {e}")

        if resp.status_code != 200:
            raise AIClientError(
                f"OpenAI API 返回 {resp.status_code}: {resp.text[:500]}"
            )

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise AIClientError("API 响应中没有 choices")

        return choices[0].get("message", {}).get("content", "")
