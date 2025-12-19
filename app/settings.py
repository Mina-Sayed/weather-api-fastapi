from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    weatherstack_api_key: str = Field(validation_alias="WEATHERSTACK_API_KEY")
    weatherstack_base_url: str = Field(
        default="https://api.weatherstack.com",
        validation_alias="WEATHERSTACK_BASE_URL",
    )

    http_timeout_seconds: float = Field(default=5.0, validation_alias="HTTP_TIMEOUT_SECONDS")

    cache_enabled: bool = Field(default=True, validation_alias="CACHE_ENABLED")
    cache_ttl_seconds: int = Field(default=300, validation_alias="CACHE_TTL_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
