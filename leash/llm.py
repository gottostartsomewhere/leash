"""The model behind an agent, when there is one.

One method, `think`, which takes a system and user prompt and returns a JSON
object. Narrow on purpose: an agent that can only emit structured proposals
cannot talk its way past anything, it can only propose, and the engine decides.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol

import httpx

from .config import Settings, settings as default_settings


class BrainError(RuntimeError):
    """The model was unreachable, or did not answer with usable JSON."""


class Brain(Protocol):
    name: str

    async def think(self, *, system: str, user: str) -> Mapping[str, Any]: ...


class GroqBrain:
    """Groq's OpenAI-compatible chat completions, in JSON mode."""

    def __init__(
        self,
        config: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or default_settings()
        if not self._config.groq_configured:
            raise BrainError("no Groq key; export LEASH_GROQ_API_KEY")
        self._client = client
        self.name = f"groq:{self._config.groq_model}"

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.groq_base_url,
                timeout=self._config.request_timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def think(self, *, system: str, user: str) -> Mapping[str, Any]:
        http = await self._http()
        response = await http.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._config.groq_api_key}"},
            json={
                "model": self._config.groq_model,
                "temperature": 0.7,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        if response.status_code == 429:
            raise BrainError("rate limited by the free tier")
        if response.status_code != 200:
            raise BrainError(f"chat completion failed ({response.status_code})")

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise BrainError("unexpected completion shape") from exc

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise BrainError(f"model did not return JSON: {content[:200]}") from exc

        if not isinstance(parsed, Mapping):
            raise BrainError("model returned JSON that was not an object")
        return parsed


def build_brain(config: Settings | None = None) -> Brain | None:
    """A brain if one is configured, otherwise None and the caller copes."""
    config = config or default_settings()
    if not config.groq_configured:
        return None
    return GroqBrain(config)
