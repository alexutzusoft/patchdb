"""HTTP client for OpenRouter API requests in PatchDB."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Optional

from .errors import InvalidJSONError, ModelSaidNo, PatchDBError


class OpenRouterClient:
    """Handles communication with the OpenRouter API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        """Initialize the client with connection and authentication details."""
        if not api_key:
            raise PatchDBError("An API key must be provided.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

    def _headers(self) -> Dict[str, str]:
        """Generate common headers for OpenRouter API requests."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/lupc9102/PatchDB",
            "X-Title": "PatchDB",
        }

    def request_json(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Send a JSON payload to the OpenRouter chat completions API endpoint with retries."""
        url = f"{self.base_url}/chat/completions"
        try:
            data = json.dumps(payload).encode("utf-8")
        except TypeError as exc:
            raise PatchDBError("Failed to serialize request payload to JSON.") from exc

        request = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ModelSaidNo(f"OpenRouter returned non-object JSON: {type(parsed).__name__}")
                if "error" in parsed:
                    raise ModelSaidNo(f"OpenRouter returned an error: {parsed['error']}")
                return parsed
            except ModelSaidNo:
                raise
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(0.5 * attempt)

        raise PatchDBError(f"Model request failed after {self.retries} attempt(s): {last_error}")

    def extract_json_object(self, text: str) -> Dict[str, Any]:
        """Locate and extract a single JSON object block from the AI's response text."""
        stripped = text.strip()
        in_string = False
        escape = False
        start = -1
        for idx, char in enumerate(stripped):
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                start = idx
                break

        if start == -1:
            raise InvalidJSONError("Model did not return a JSON object.")

        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(stripped)):
            char = stripped[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start : idx + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError as exc:
                        raise InvalidJSONError(f"Model returned malformed JSON: {exc}") from exc
                    if not isinstance(parsed, dict):
                        raise InvalidJSONError("Model returned JSON, but not an object.")
                    return parsed

        raise InvalidJSONError("Model returned an unclosed JSON object.")
