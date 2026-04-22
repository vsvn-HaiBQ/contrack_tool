from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Contrack"
    api_prefix: str = "/api"
    database_url: str = "postgresql+psycopg://contrack:contrack@localhost:5439/contrack"
    redis_url: str = "redis://localhost:6379/0"
    session_cookie_name: str = "contrack_session"
    session_ttl_seconds: int = 7 * 24 * 60 * 60
    master_key: str = "change-me"
    cors_origins: str = "http://localhost:8888,http://127.0.0.1:8888"
    http_verify_ssl: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_prefix="CONTRACK_", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
