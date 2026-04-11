from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Auth
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 8        # 8 hours
    API_KEY: str = "dev-api-key-change-in-production"  # static API key for machine clients
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""               # empty = JWT login disabled

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
