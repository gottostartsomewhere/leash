"""Runtime configuration, read from the environment."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything the app needs to know that is not in the code.

    Credentials come from the environment or a local `.env`, never from a
    literal. With none set the app runs on the simulated gateway, which is
    what makes the whole thing developable before any sandbox exists.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
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
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    #: Point every seeded payee at one address, so a single env var makes the
    #: demo pay into a real sandbox personal account instead of example.com.
    demo_receiver_email: str | None = None

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_secret)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
