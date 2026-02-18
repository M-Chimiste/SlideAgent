"""BedrockClient: Wrapper around boto3 Bedrock converse API with structured output.

Uses tool use to enforce Pydantic model schemas on LLM output.
"""

import asyncio
import json
import logging
import time
from typing import TypeVar

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _pydantic_to_tool_definition(model_class: type[BaseModel], tool_name: str = "output") -> dict:
    """Convert a Pydantic model's JSON schema to a Bedrock tool definition."""
    schema = model_class.model_json_schema()

    # Strip Pydantic-specific keys that Bedrock doesn't understand
    def _clean_schema(obj: dict) -> dict:
        cleaned = {}
        for k, v in obj.items():
            if k in ("title", "$defs", "definitions"):
                continue
            if isinstance(v, dict):
                cleaned[k] = _clean_schema(v)
            elif isinstance(v, list):
                cleaned[k] = [_clean_schema(i) if isinstance(i, dict) else i for i in v]
            else:
                cleaned[k] = v
        return cleaned

    # Resolve $ref references inline
    defs = schema.get("$defs", schema.get("definitions", {}))

    def _resolve_refs(obj: dict) -> dict:
        if "$ref" in obj:
            ref_name = obj["$ref"].split("/")[-1]
            if ref_name in defs:
                return _resolve_refs(_clean_schema(defs[ref_name]))
            return obj
        result = {}
        for k, v in obj.items():
            if isinstance(v, dict):
                result[k] = _resolve_refs(v)
            elif isinstance(v, list):
                result[k] = [_resolve_refs(i) if isinstance(i, dict) else i for i in v]
            else:
                result[k] = v
        return result

    cleaned = _resolve_refs(_clean_schema(schema))

    return {
        "toolSpec": {
            "name": tool_name,
            "description": f"Return structured output as {model_class.__name__}",
            "inputSchema": {"json": cleaned},
        }
    }


class BedrockClient:
    def __init__(self, region: str = "us-east-1", profile_name: str = ""):
        if profile_name:
            session = boto3.Session(profile_name=profile_name, region_name=region)
            self._client = session.client("bedrock-runtime")
        else:
            self._client = boto3.client("bedrock-runtime", region_name=region)
        self._region = region

    async def converse_structured(
        self,
        model_id: str,
        system_prompt: str,
        user_prompt: str,
        output_schema: type[T],
        max_tokens: int = 2048,
        temperature: float = 0.3,
        max_retries: int = 3,
    ) -> T:
        """Call Bedrock converse API and parse structured output from tool use.

        Retries with exponential backoff on transient failures.
        """
        tool_def = _pydantic_to_tool_definition(output_schema)

        for attempt in range(max_retries):
            start = time.monotonic()
            try:
                response = await asyncio.to_thread(
                    self._client.converse,
                    modelId=model_id,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    toolConfig={
                        "tools": [tool_def],
                        "toolChoice": {"tool": {"name": "output"}},
                    },
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                )

                elapsed = time.monotonic() - start
                usage = response.get("usage", {})
                logger.info(
                    "Bedrock call: model=%s tokens_in=%s tokens_out=%s latency=%.1fs",
                    model_id,
                    usage.get("inputTokens", "?"),
                    usage.get("outputTokens", "?"),
                    elapsed,
                )

                # Extract tool use result
                content = response.get("output", {}).get("message", {}).get("content", [])
                for block in content:
                    if "toolUse" in block:
                        tool_input = block["toolUse"]["input"]
                        return output_schema.model_validate(tool_input)

                raise ValueError("No tool use block in Bedrock response")

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code in ("ThrottlingException", "ServiceUnavailableException"):
                    if attempt < max_retries - 1:
                        wait = 2**attempt
                        logger.warning(
                            "Bedrock transient error (%s), retrying in %ds (attempt %d/%d)",
                            error_code, wait, attempt + 1, max_retries,
                        )
                        await asyncio.sleep(wait)
                        continue
                raise

            except Exception as e:
                if attempt < max_retries - 1:
                    wait = 2**attempt
                    logger.warning(
                        "Bedrock call failed (%s), retrying in %ds (attempt %d/%d)",
                        str(e), wait, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"Bedrock call failed after {max_retries} retries")
