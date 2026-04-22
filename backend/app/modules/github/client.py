from __future__ import annotations

import base64
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx
from app.core.config import settings


class GitHubClientError(Exception):
    pass


_GITHUB_HTTP_CLIENT: httpx.Client | None = None
_GITHUB_HTTP_LOCK = Lock()


def _http() -> httpx.Client:
    global _GITHUB_HTTP_CLIENT
    if _GITHUB_HTTP_CLIENT is not None:
        return _GITHUB_HTTP_CLIENT
    with _GITHUB_HTTP_LOCK:
        if _GITHUB_HTTP_CLIENT is None:
            _GITHUB_HTTP_CLIENT = httpx.Client(
                base_url="https://api.github.com",
                timeout=20.0,
                verify=settings.http_verify_ssl,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                headers={"Accept": "application/vnd.github+json"},
            )
        return _GITHUB_HTTP_CLIENT


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = _http().request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise GitHubClientError(str(exc)) from exc

    def get_pull_request_template(self, repo: str) -> str | None:
        candidates = [
            ".github/pull_request_template.md",
            "docs/pull_request_template.md",
            "pull_request_template.md",
        ]
        for path in candidates:
            try:
                payload = self._request("GET", f"/repos/{repo}/contents/{path}")
            except GitHubClientError:
                continue
            if payload.get("encoding") == "base64" and payload.get("content"):
                return base64.b64decode(payload["content"]).decode("utf-8")
        return None

    def get_current_user(self) -> dict[str, Any]:
        return self._request("GET", "/user")

    def get_repo(self, repo: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{repo}")

    def branch_exists(self, repo: str, branch: str) -> bool:
        encoded_branch = quote(branch.strip(), safe="")
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            response = _http().request("GET", f"/repos/{repo}/branches/{encoded_branch}", headers=headers)
        except httpx.HTTPError as exc:
            raise GitHubClientError(str(exc)) from exc
        if response.status_code == 404:
            return False
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GitHubClientError(str(exc)) from exc
        return True

    def create_pull_request(self, repo: str, *, title: str, body: str, base: str, head: str) -> dict[str, Any]:
        payload = self._request("POST", f"/repos/{repo}/pulls", json={"title": title, "body": body, "base": base, "head": head})
        return {"url": payload["html_url"], "title": payload["title"]}
