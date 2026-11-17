from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .config import EnvironmentError, EnvironmentSettings, contained

Identifier = str
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


def valid_id(value: str) -> str:
    if not ID_PATTERN.fullmatch(value) or ".." in value:
        raise EnvironmentError("Invalid catalog ID", "INVALID_ID")
    return value


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Artifact(StrictModel):
    file: str
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class Compatibility(StrictModel):
    database_schema: str = Field(min_length=1, max_length=60)


class WarArtifact(StrictModel):
    war_id: Identifier
    display_version: str
    build_type: str
    build_id: str
    artifact: Artifact
    compatibility: Compatibility
    status: str


class DatabaseBaseline(StrictModel):
    database_id: Identifier
    schema_version: str = Field(min_length=1, max_length=60)
    profile_type: str
    artifact: Artifact
    status: str


class RepositoryProfile(StrictModel):
    repository_id: Identifier
    repository_type: Literal["git", "svn"]
    url: str = ""
    display_name: str = ""
    status: str


class ApplicationMapping(StrictModel):
    war_id: Identifier


class DatabaseMapping(StrictModel):
    schema_version: str
    default_database_id: Identifier


class RepositoryMapping(StrictModel):
    default_repository_id: Identifier


class ConTrackVersionBundle(StrictModel):
    bundle_id: Identifier
    display_name: str
    application: ApplicationMapping
    database: DatabaseMapping
    repository: RepositoryMapping
    status: str


class PrepareRequest(StrictModel):
    bundle_id: str = Field(min_length=1, max_length=120)
    database_profile_id: str | None = Field(default=None, max_length=120)
    repository_profile_id: str | None = Field(default=None, max_length=120)


class ResolvedRecipe:
    def __init__(self, bundle, war, database, repository, war_path, baseline_path):
        self.bundle = bundle
        self.war = war
        self.database = database
        self.repository = repository
        self.war_path = war_path
        self.baseline_path = baseline_path

    def public(self) -> dict:
        return {
            "bundle": self.bundle.bundle_id, "display_name": self.bundle.display_name,
            "war": self.war.war_id, "schema_version": self.database.schema_version,
            "database_baseline": self.database.database_id,
            "repository": self.repository.repository_id, "repository_type": self.repository.repository_type,
        }


class VersionCatalogService:
    def __init__(self, settings: EnvironmentSettings):
        self.settings = settings
        self.paths: dict[str, Path] = {}
        self.wars = self._read("wars", WarArtifact, "war_id")
        self.databases = self._read("databases", DatabaseBaseline, "database_id")
        self.repositories = self._read("repositories", RepositoryProfile, "repository_id")
        self.bundles = self._read("bundles", ConTrackVersionBundle, "bundle_id", bundles=True)

    def _read(self, kind, model, key, bundles=False):
        root = self.settings.path(kind)
        items = {}
        if not root.exists():
            return items
        candidates = sorted(root.glob("*.yaml")) if bundles else sorted(root.rglob("manifest.yaml"))
        for source in candidates:
            try:
                if not source.resolve().is_relative_to(root) or source.stat().st_size > 128 * 1024:
                    raise ValueError("Invalid manifest location/size")
                item = model.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
                identifier = valid_id(getattr(item, key))
                if identifier in items or identifier in self.paths:
                    raise ValueError("Duplicate catalog ID")
                if hasattr(item, "artifact"):
                    contained(source.parent, item.artifact.file)
                items[identifier] = item
                self.paths[identifier] = source.parent.resolve()
            except Exception as exc:
                raise EnvironmentError(f"Invalid {kind} manifest: {source.relative_to(root).as_posix()}",
                                       "INVALID_MANIFEST") from exc
        return items

    @staticmethod
    def _available(items, identifier, kind):
        valid_id(identifier)
        item = items.get(identifier)
        if item is None:
            raise EnvironmentError(f"{kind} not found: {identifier}", "ARTIFACT_NOT_FOUND", 404)
        if item.status != "available":
            raise EnvironmentError(f"{kind} is not available: {identifier}", "ARTIFACT_UNAVAILABLE")
        return item

    def artifact_path(self, item, identifier):
        target = contained(self.paths[identifier], item.artifact.file)
        if not target.is_file():
            raise EnvironmentError(f"Artifact file missing for {identifier}", "ARTIFACT_NOT_FOUND")
        if item.artifact.sha256 and digest(target) != item.artifact.sha256.lower():
            raise EnvironmentError(f"Artifact checksum mismatch for {identifier}", "CHECKSUM_MISMATCH")
        return target

    def resolve(self, request: PrepareRequest) -> ResolvedRecipe:
        bundle = self._available(self.bundles, request.bundle_id, "Bundle")
        war = self._available(self.wars, bundle.application.war_id, "WAR")
        # Defaults must be valid even when the caller selects another profile.
        default_db = self._available(self.databases, bundle.database.default_database_id, "Database")
        default_repo = self._available(self.repositories, bundle.repository.default_repository_id, "Repository")
        database = self._available(self.databases, request.database_profile_id or default_db.database_id, "Database")
        repository = self._available(self.repositories, request.repository_profile_id or default_repo.repository_id, "Repository")
        if any(db.schema_version != bundle.database.schema_version for db in (default_db, database)) or \
                war.compatibility.database_schema != database.schema_version:
            raise EnvironmentError("WAR, bundle and database schema versions must match", "SCHEMA_MISMATCH")
        war_path = self.artifact_path(war, war.war_id)
        baseline_path = self.artifact_path(database, database.database_id)
        if war_path.suffix.lower() != ".war":
            raise EnvironmentError("WAR artifact must be a .war file", "INVALID_ARTIFACT")
        return ResolvedRecipe(bundle, war, database, repository, war_path, baseline_path)

    def list_available_contrack_versions(self) -> dict:
        versions = []
        for bundle in self.bundles.values():
            error = None
            try:
                self.resolve(PrepareRequest(bundle_id=bundle.bundle_id))
            except EnvironmentError as exc:
                error = str(exc)
            versions.append({
                "bundleId": bundle.bundle_id, "displayName": bundle.display_name,
                "databaseSchema": bundle.database.schema_version,
                "status": "invalid" if error else "available", "error": error,
                "defaultDatabaseId": bundle.database.default_database_id,
                "defaultRepositoryId": bundle.repository.default_repository_id,
            })
        return {
            "versions": versions,
            "databases": [{"id": db.database_id, "schema": db.schema_version, "profile": db.profile_type}
                          for db in self.databases.values() if db.status == "available"],
            "repositories": [{"id": repo.repository_id, "type": repo.repository_type,
                              "name": repo.display_name or repo.repository_id}
                             for repo in self.repositories.values() if repo.status == "available"],
        }


def repository_address(repository: RepositoryProfile) -> tuple[str, int]:
    try:
        url = urlsplit(repository.url)
        ports = {"http": 80, "https": 443, "svn": 3690, "git": 9418, "ssh": 22, "svn+ssh": 22}
        if url.scheme not in ports or not url.hostname or url.username or url.password or "{{" in repository.url or \
                any(ord(char) < 32 for char in repository.url) or "\\" in repository.url:
            raise ValueError("Invalid repository URL")
        return url.hostname, url.port or ports[url.scheme]
    except ValueError as exc:
        raise EnvironmentError("Repository profile needs a valid URL without embedded credentials", "REPOSITORY_CONFIG") from exc
