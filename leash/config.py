"""Runtime configuration, read from the environment."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: The repository root, found from this file rather than from the working
#: directory. `env_file=".env"` alone resolves against wherever the process
#: happened to be started, so running uvicorn from one directory up would
#: silently ignore the credentials and fall back to the simulated gateway.
#: Failing that way during a demo is worse than failing loudly.
_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Everything the app needs to know that is not in the code.

    Credentials come from the environment or a local `.env`, never from a
    literal. With none set the app runs on the simulated gateway, which is
    what makes the whole thing developable before any sandbox exists.
    """

    # Both, in that order: the repository's own .env always loads, and a .env
    # beside whoever started the process still wins if they meant to override.
    model_config = SettingsConfigDict(
        env_file=(_ROOT / ".env", ".env"),
        env_prefix="LEASH_",
        extra="ignore",
    )

    paypal_client_id: str | None = None
    paypal_secret: str | None = None
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"

    email_subject: str = "A payment from your agent"
    email_message: str = "Released by Leash after the mandate checks passed."

    request_timeout_seconds: float = 20.0

    #: Groq's free tier carries the agents. No key means the deterministic
    #: adversary runs instead, which is the one the report is built on anyway.
    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    #: Point every seeded payee at one address, so a single env var makes the
    #: demo pay into a real sandbox personal account instead of example.com.
    demo_receiver_email: str | None = None

    #: Channel3 is the real product catalog the agent shops. Without a key the
    #: static catalog runs instead, so the demo and the tests stay offline.
    #: A search costs one credit against 1,000 free a month, so results are
    #: cached and nothing re-queries on a reload.
    channel3_api_key: str | None = None
    channel3_base_url: str = "https://api.trychannel3.com"
    channel3_cache_seconds: float = 900.0

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_secret)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def channel3_configured(self) -> bool:
        return bool(self.channel3_api_key)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
