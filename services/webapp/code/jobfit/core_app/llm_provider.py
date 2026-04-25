"""LLM provider abstraction — swap between OpenAI and Anthropic."""
from __future__ import annotations

import base64
import json
import logging
from abc import ABC, abstractmethod

from django.conf import settings

log = logging.getLogger(__name__)


_MAX_OUTPUT_TOKENS = 16384


class LLMUsage:
    __slots__ = ("prompt_tokens", "completion_tokens", "output_truncated")

    def __init__(self, prompt_tokens: int = 0, completion_tokens: int = 0,
                 output_truncated: bool = False):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.output_truncated = output_truncated


class LLMProvider(ABC):
    provider: str

    @abstractmethod
    def complete_json(
        self,
        prompt: str,
        *,
        model_tier: str = "cheap",
        pdf_bytes: bytes | None = None,
        pdf_filename: str = "document.pdf",
        timeout: int = 300,
    ) -> tuple[dict, LLMUsage]:
        """Send prompt, get parsed JSON + usage. model_tier is 'cheap' or 'expensive'."""

    @abstractmethod
    def model_name(self, tier: str = "cheap") -> str:
        """Return the concrete model id for a tier."""


class OpenAIProvider(LLMProvider):
    provider = "openai"

    MODELS = {"cheap": "gpt-4o-mini", "expensive": "gpt-4o"}

    def __init__(self, api_key: str):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)

    def model_name(self, tier: str = "cheap") -> str:
        return self.MODELS.get(tier, self.MODELS["cheap"])

    def complete_json(self, prompt, *, model_tier="cheap", pdf_bytes=None,
                      pdf_filename="document.pdf", timeout=300):
        model = self.model_name(model_tier)
        content: list[dict] = [{"type": "text", "text": prompt}]
        if pdf_bytes:
            b64 = base64.standard_b64encode(pdf_bytes).decode()
            content.append({
                "type": "file",
                "file": {"filename": pdf_filename,
                         "file_data": f"data:application/pdf;base64,{b64}"},
            })
        response = self._client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": content}],
            temperature=0,
            seed=42,
            timeout=timeout,
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
        parsed = json.loads(response.choices[0].message.content)
        truncated = response.choices[0].finish_reason == "length"
        usage = LLMUsage(response.usage.prompt_tokens, response.usage.completion_tokens, truncated)
        return parsed, usage


class AnthropicProvider(LLMProvider):
    provider = "anthropic"

    MODELS = {"cheap": "claude-haiku-4-5-20251001", "expensive": "claude-sonnet-4-6-20250514"}

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def model_name(self, tier: str = "cheap") -> str:
        return self.MODELS.get(tier, self.MODELS["cheap"])

    def complete_json(self, prompt, *, model_tier="cheap", pdf_bytes=None,
                      pdf_filename="document.pdf", timeout=300):
        model = self.model_name(model_tier)
        content: list[dict] = []
        if pdf_bytes:
            b64 = base64.standard_b64encode(pdf_bytes).decode()
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            })
        content.append({"type": "text", "text": prompt})
        response = self._client.messages.create(
            model=model,
            max_tokens=_MAX_OUTPUT_TOKENS,
            messages=[{"role": "user", "content": content}],
            temperature=0,
            timeout=timeout,
        )
        text = response.content[0].text
        parsed = json.loads(text)
        truncated = response.stop_reason == "max_tokens"
        usage = LLMUsage(response.usage.input_tokens, response.usage.output_tokens, truncated)
        return parsed, usage


def get_provider() -> LLMProvider | None:
    provider_name = getattr(settings, "LLM_PROVIDER", "openai")
    if provider_name == "anthropic":
        api_key = getattr(settings, "ANTHROPIC_KEY", None)
        if not api_key:
            return None
        return AnthropicProvider(api_key)
    else:
        api_key = getattr(settings, "OPENAI_KEY", None)
        if not api_key:
            return None
        return OpenAIProvider(api_key)
