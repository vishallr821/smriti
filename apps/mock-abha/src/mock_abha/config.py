"""Configuration for the MockABHA service."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for MockABHA."""

    mock_abha_signing_key: str
    port: int = Field(default=8001, alias="MOCK_ABHA_PORT")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


settings = Settings()
