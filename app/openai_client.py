import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(self, api_key: str, timeout: float = 8.0) -> None:
        self._client = None
        self._timeout = timeout
        self._enabled = bool(api_key)
        if not self._enabled:
            return
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=api_key, timeout=timeout)
        except Exception:
            logger.exception("Failed to initialize OpenAI client")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def decision_response(self, *, model: str, input_text: str, json_schema: Dict[str, Any], instructions: str) -> Dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("OpenAI client is disabled")
        response = self._client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "decision_result",
                    "schema": json_schema,
                    "strict": True,
                }
            },
        )
        raw = getattr(response, "output_text", "") or ""
        if not raw:
            raise RuntimeError("Decision response was empty")
        return json.loads(raw)

    def generate_reply(self, *, model: str, instructions: str, input_text: str) -> str:
        if not self.enabled:
            raise RuntimeError("OpenAI client is disabled")
        response = self._client.responses.create(
            model=model,
            instructions=instructions,
            input=input_text,
        )
        return (getattr(response, "output_text", "") or "").strip()

    def moderate(self, text: str) -> Optional[bool]:
        if not self.enabled:
            return None
        try:
            result = self._client.moderations.create(model="omni-moderation-latest", input=text)
            if result and result.results:
                return bool(result.results[0].flagged)
        except Exception:
            logger.exception("Moderation call failed")
            return True
        return None
