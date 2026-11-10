from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_uri: str
    mongodb_db: str = "linkedin_agent"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
