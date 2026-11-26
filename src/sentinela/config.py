from functools import lru_cache

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "sentinela"
    postgres_password: SecretStr
    postgres_db: str = "sentinela"
    webhook_api_key: SecretStr
    evolution_api_url: HttpUrl
    evolution_api_key: SecretStr
    evolution_instance: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    openai_api_key: SecretStr
    openai_model: str = "gpt-5.4-mini"
    openai_transcription_model: str = "gpt-transcribe"
    safe_browsing_api_key: SecretStr = SecretStr("")
    max_body_bytes: int = Field(default=256_000, ge=1024, le=2_000_000)
    max_media_bytes: int = Field(default=8_000_000, ge=1024, le=20_000_000)

    @field_validator("postgres_password", "webhook_api_key")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 24:
            raise ValueError("Use um segredo de pelo menos 24 caracteres")
        return value

    @field_validator("evolution_api_key", "openai_api_key")
    @classmethod
    def nonempty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Chave obrigatória")
        return value

    @field_validator("evolution_api_url")
    @classmethod
    def no_url_credentials(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("URL base sem credenciais, query ou fragmento")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # valores fornecidos pelo ambiente
