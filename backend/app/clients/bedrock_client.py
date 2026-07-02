import base64
from typing import Any, Iterable

import boto3
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import Settings


class BedrockClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        session = boto3.Session(profile_name=settings.aws_profile)
        self.runtime = session.client(
            "bedrock-runtime", region_name=settings.aws_region
        )
        self.control = session.client("bedrock", region_name=settings.aws_region)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def validate(self) -> None:
        self.control.list_foundation_models(maxResults=1)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def converse_text(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        response = self.runtime.converse(
            modelId=model_id,
            messages=[
                {"role": "system", "content": [{"text": system_prompt}]},
                {"role": "user", "content": [{"text": user_prompt}]},
            ],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        return self._extract_text(response)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def converse_vision(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        image_format: str = "jpeg",
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        response = self.runtime.converse(
            modelId=model_id,
            messages=[
                {"role": "system", "content": [{"text": system_prompt}]},
                {
                    "role": "user",
                    "content": [
                        {"text": user_prompt},
                        {
                            "image": {
                                "format": image_format,
                                "source": {"bytes": encoded},
                            }
                        },
                    ],
                },
            ],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        return self._extract_text(response)

    def batch_converse_vision(
        self,
        model_id: str,
        system_prompt: str,
        requests: Iterable[tuple[str, bytes]],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> list[str]:
        responses = []
        for user_prompt, image_bytes in requests:
            responses.append(
                self.converse_vision(
                    model_id=model_id,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    image_bytes=image_bytes,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            )
        return responses

    @staticmethod
    def _extract_text(response: dict[str, Any]) -> str:
        output = response.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])
        for item in content:
            if "text" in item:
                return item["text"]
        return ""
