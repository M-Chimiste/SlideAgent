import json
import re
import base64
from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.openai_compatible_base_url.rstrip("/")
        self.model = settings.openai_compatible_model
        self.api_key = settings.openai_compatible_api_key
        self.timeout = settings.openai_compatible_timeout_seconds

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    def complete_text(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 8192,
        temperature: float = 0.2,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        system_prompt = self._system_prompt(system_prompt)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format
        if self.settings.openai_compatible_reasoning_effort:
            payload["reasoning_effort"] = self.settings.openai_compatible_reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        return self._extract_message_text(data)

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 16384,
        temperature: float = 0.2,
    ) -> Optional[dict[str, Any]]:
        response_format = self._json_response_format()
        text = self.complete_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format,
        )
        payload = self.extract_json(text)
        if payload is not None:
            return payload
        repair_prompt = (
            f"{user_prompt}\n\n"
            "Your previous response was not parseable as a JSON object. "
            "Return the requested JSON object only. Do not include markdown, prose, "
            "reasoning, or code fences."
        )
        repaired = self.complete_text(
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            max_tokens=max_tokens,
            temperature=0,
            response_format=response_format,
        )
        return self.extract_json(repaired)

    def _json_response_format(self) -> dict[str, Any] | None:
        if "qwen3.6" not in self.model.lower():
            return None
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "JsonPayload",
                "schema": {"type": "object", "additionalProperties": True},
            },
        }

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=1, max=4))
    def complete_vision(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        image_format: str = "jpeg",
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        system_prompt = self._system_prompt(system_prompt)
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{encoded}"
                            },
                        },
                    ],
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.settings.openai_compatible_reasoning_effort:
            payload["reasoning_effort"] = self.settings.openai_compatible_reasoning_effort
        headers = {"Authorization": f"Bearer {self.api_key}"}
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
        return self._extract_message_text(data)

    @staticmethod
    def extract_json(text: str) -> Optional[dict[str, Any]]:
        if not text.strip():
            return None
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                return None
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last > first:
            try:
                payload = json.loads(text[first : last + 1])
                return payload if isinstance(payload, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _extract_message_text(data: dict[str, Any]) -> str:
        choices = data.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            joined = "\n".join(parts)
            if joined.strip():
                return joined
        reasoning_content = message.get("reasoning_content", "")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            return reasoning_content
        return ""

    def _system_prompt(self, system_prompt: str) -> str:
        if (
            self.settings.openai_compatible_reasoning_effort == "none"
            and "qwen" in self.model.lower()
            and "/no_think" not in system_prompt
        ):
            return f"{system_prompt}\n/no_think"
        return system_prompt
