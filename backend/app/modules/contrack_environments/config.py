from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class EnvironmentError(Exception):
    def __init__(self, message: str, code: str = "ENVIRONMENT_ERROR", status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def contained(root: Path, relative: str) -> Path:
    part = Path(relative)
    if not relative or part.is_absolute() or ".." in part.parts or "\\" in relative or ":" in relative:
        raise EnvironmentError("Invalid relative catalog/runtime path", "INVALID_PATH")
    result = (root / part).resolve()
    if not result.is_relative_to(root.resolve()) or result == root.resolve():
        raise EnvironmentError("Path escapes its managed directory", "INVALID_PATH")
    return result


class EnvironmentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    operation_mode: Literal["prepare_environment", "deploy_war"] = "prepare_environment"
    root: Path = Path("/srv/contrack-env")
    wars: str = "catalog/wars"
    databases: str = "catalog/databases"
    repositories: str = "catalog/repositories"
    bundles: str = "catalog/bundles"
    server: str = "runtime/server"
    runtime_databases: str = "runtime/databases"
    runtime_repositories: str = "runtime/repositories"
    current: str = "runtime/current"
    runs: str = "runs"
    lock: str = "runtime/environment.lock"
    pg_host: str = "127.0.0.1"
    pg_port: int = Field(default=5432, ge=1, le=65535)
    pg_user: str = "contrack_runtime"
    pg_password: SecretStr = SecretStr("")
    pg_passfile: str = ""
    pg_bin: str = ""
    schema_version_query: str = ""
    tomcat_home: str = ""
    config_templates: str = ""
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8080, ge=1, le=65535)
    health_url: str = "http://127.0.0.1:8080/contrack/"
    command_timeout: int = Field(default=900, ge=1, le=7200)
    health_timeout: int = Field(default=120, ge=1, le=600)

    @model_validator(mode="after")
    def validate_paths(self):
        if self.enabled and not self.root.is_absolute():
            raise ValueError("Environment root must be absolute")
        directories = [self.wars, self.databases, self.repositories, self.bundles, self.server,
                       self.runtime_databases, self.runtime_repositories, self.current, self.runs]
        paths = [contained(self.root, item) for item in directories]
        lock = contained(self.root, self.lock)
        for index, first in enumerate(paths):
            for second in paths[index + 1:]:
                if first.is_relative_to(second) or second.is_relative_to(first):
                    raise ValueError("Managed directories must not overlap")
            if lock.is_relative_to(first) or first.is_relative_to(lock):
                raise ValueError("Lock must be outside managed data directories")
        return self

    def path(self, name: str) -> Path:
        return contained(self.root, str(getattr(self, name)))


def load_settings() -> EnvironmentSettings:
    config_path = os.environ.get("CONTRACK_ENV_CONFIG", "")
    values = {}
    try:
        if config_path:
            values = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        if os.environ.get("CONTRACK_ENV_ROOT"):
            values["root"] = os.environ["CONTRACK_ENV_ROOT"]
        if os.environ.get("CONTRACK_ENV_PG_PASSWORD"):
            values["pg_password"] = os.environ["CONTRACK_ENV_PG_PASSWORD"]
        return EnvironmentSettings.model_validate(values)
    except Exception as exc:
        # Validation errors can contain original configuration values/secrets.
        raise EnvironmentError("Invalid environment manager configuration; check the administrator config file",
                               "CONFIGURATION_ERROR", 503) from exc
