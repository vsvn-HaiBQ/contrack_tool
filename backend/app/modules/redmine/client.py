from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import re
from threading import Lock
from typing import Any

import httpx
from app.core.config import settings
from app.core.session_store import session_store


class RedmineClientError(Exception):
    pass


@dataclass
class RedmineIssue:
    issue_id: int
    subject: str
    tracker: str
    tracker_id: int | None
    status: str
    allowed_statuses: list[str]
    assignee: str | None
    url: str
    parent_issue_id: int | None = None


_HTTP_CLIENTS: dict[tuple[str, bool], httpx.Client] = {}
_HTTP_CLIENTS_LOCK = Lock()
# Keep workflow/allowed_statuses cache aligned with status cache TTL.
_ISSUE_PAYLOAD_CACHE_TTL_SECONDS = 24 * 60 * 60


def _get_http_client(host: str) -> httpx.Client:
    """Return a shared httpx.Client per (host, verify) pair to enable connection pooling."""
    key = (host, settings.http_verify_ssl)
    client = _HTTP_CLIENTS.get(key)
    if client is not None:
        return client
    with _HTTP_CLIENTS_LOCK:
        client = _HTTP_CLIENTS.get(key)
        if client is None:
            client = httpx.Client(
                base_url=host,
                timeout=20.0,
                verify=settings.http_verify_ssl,
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            )
            _HTTP_CLIENTS[key] = client
        return client


class RedmineClient:
    def __init__(self, host: str, api_key: str) -> None:
        self.host = host.rstrip("/")
        self.api_key = api_key
        self._http = _get_http_client(self.host)
        # Per-request memoisation caches.
        self._activities_cache: list[str] | None = None
        self._activity_lookup_cache: list[dict[str, Any]] | None = None
        self._statuses_cache: list[dict[str, Any]] | None = None
        self._users_cache: list[dict[str, Any]] | None = None
        self._issue_payload_cache: dict[int, dict[str, Any]] = {}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = kwargs.pop("headers", {})
        headers["X-Redmine-API-Key"] = self.api_key
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPStatusError as exc:
            detail = ""
            try:
                payload = exc.response.json()
                errors = payload.get("errors") if isinstance(payload, dict) else None
                if errors:
                    detail = f" ({'; '.join(str(item) for item in errors)})"
            except ValueError:
                body = exc.response.text.strip()
                if body:
                    detail = f" ({body[:200]})"
            raise RedmineClientError(f"{exc}{detail}") from exc
        except httpx.HTTPError as exc:
            raise RedmineClientError(str(exc)) from exc

    def _collect_pages(
        self,
        path: str,
        key: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        limit = 100
        offset = 0
        base_params = list(params or []) if isinstance(params, list) else dict(params or {})
        while True:
            if isinstance(base_params, list):
                page_params: dict[str, Any] | list[tuple[str, Any]] = [*base_params, ("limit", limit), ("offset", offset)]
            else:
                page_params = {**base_params, "limit": limit, "offset": offset}
            payload = self._request("GET", path, params=page_params)
            items = payload.get(key, [])
            merged.extend(items)
            total_count = int(payload.get("total_count") or len(merged))
            if offset + len(items) >= total_count or not items:
                return merged
            offset += limit

    def get_issue(self, issue_id: int) -> RedmineIssue:
        payload = self.get_issue_payload(issue_id)
        issue = payload["issue"]
        return self._map_issue(issue)

    def _issue_payload_cache_key(self, issue_id: int) -> str:
        digest = hashlib.sha256(f"{self.host}:{self.api_key}:{issue_id}:issue_payload".encode("utf-8")).hexdigest()
        return f"cache:redmine_issue_payload:{digest}"

    def _get_cached_issue_payload(self, issue_id: int) -> dict[str, Any] | None:
        cached = self._issue_payload_cache.get(issue_id)
        if cached is not None:
            return cached
        try:
            payload = session_store._client().get(self._issue_payload_cache_key(issue_id))
        except RuntimeError:
            payload = None
        if payload:
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                self._issue_payload_cache[issue_id] = parsed
                return parsed
        return None

    def _set_cached_issue_payload(self, issue_id: int, payload: dict[str, Any]) -> None:
        self._issue_payload_cache[issue_id] = payload
        try:
            session_store._client().setex(
                self._issue_payload_cache_key(issue_id),
                _ISSUE_PAYLOAD_CACHE_TTL_SECONDS,
                json.dumps(payload),
            )
        except RuntimeError:
            return

    def _delete_cached_issue_payload(self, issue_id: int) -> None:
        self._issue_payload_cache.pop(issue_id, None)
        try:
            session_store._client().delete(self._issue_payload_cache_key(issue_id))
        except RuntimeError:
            return

    def get_issue_payload(self, issue_id: int) -> dict[str, Any]:
        cached = self._get_cached_issue_payload(issue_id)
        if cached is not None:
            return cached
        payload = self._request("GET", f"/issues/{issue_id}.json", params={"include": "children,relations,allowed_statuses"})
        self._set_cached_issue_payload(issue_id, payload)
        return payload

    def get_issues_by_ids(self, issue_ids: list[int]) -> list[RedmineIssue]:
        if not issue_ids:
            return []
        if len(issue_ids) == 1:
            return [self.get_issue(issue_ids[0])]
        # Parallel fan-out; preserve input order.
        with ThreadPoolExecutor(max_workers=min(8, len(issue_ids))) as executor:
            return list(executor.map(self.get_issue, issue_ids))

    def current_user(self) -> dict[str, Any]:
        payload = self._request("GET", "/users/current.json")
        user = payload.get("user")
        if not user:
            raise RedmineClientError("Unable to resolve current Redmine user")
        return {"id": user["id"], "name": user["login"]}

    def list_assignees(self) -> list[dict[str, Any]]:
        return [{"id": user["id"], "name": user["name"]} for user in self._raw_users()]

    def list_project_members(self, project_id: int | str) -> list[dict[str, Any]]:
        memberships = self._collect_pages(f"/projects/{project_id}/memberships.json", "memberships")
        users: dict[int, dict[str, Any]] = {}
        for membership in memberships:
            user = membership.get("user") or {}
            user_id = user.get("id")
            if not user_id:
                continue
            users[user_id] = {"id": user_id, "name": user.get("name") or user.get("login") or f"User {user_id}"}
        return list(users.values())

    def list_time_entry_activities(self) -> list[str]:
        if self._activities_cache is None:
            self._activity_lookup_cache = self._request(
                "GET", "/enumerations/time_entry_activities.json"
            ).get("time_entry_activities", [])
            self._activities_cache = [item["name"] for item in self._activity_lookup_cache]
        return self._activities_cache

    def list_issue_statuses(self) -> list[dict[str, Any]]:
        if self._statuses_cache is None:
            payload = self._request("GET", "/issue_statuses.json")
            self._statuses_cache = [{"id": item["id"], "name": item["name"]} for item in payload.get("issue_statuses", [])]
        return self._statuses_cache

    def list_trackers(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/trackers.json")
        return [{"id": item["id"], "name": item["name"]} for item in payload.get("trackers", [])]

    def list_project_trackers(self, project_id: int | str) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/projects/{project_id}.json", params={"include": "trackers"})
        project = payload.get("project") or {}
        return [{"id": item["id"], "name": item["name"]} for item in project.get("trackers", [])]

    def _raw_users(self) -> list[dict[str, Any]]:
        if self._users_cache is None:
            payload = self._request("GET", "/users.json", params={"status": 1, "limit": 100})
            self._users_cache = payload.get("users", [])
        return self._users_cache

    def search_reference_tickets(self, project_id: int | str | None, jp_issue_id: int) -> list[RedmineIssue]:
        needle = str(jp_issue_id)
        pattern = re.compile(rf"(?<!\d){re.escape(needle)}(?!\d)")
        params: list[tuple[str, Any]] = [
            ("sort", "updated_on:desc"),
            ("status_id", "*"),
            ("set_filter", "1"),
            ("f[]", "subject"),
            ("op[subject]", "~"),
            ("v[subject][]", needle),
        ]
        if project_id:
            params.append(("project_id", project_id))
        issues = self._collect_pages("/issues.json", "issues", params=params)
        matched = []
        for issue in issues:
            subject = issue.get("subject", "")
            if pattern.search(subject):
                matched.append(self._map_issue(issue))
        return matched

    def update_issue(
        self,
        issue_id: int,
        *,
        status_name: str | None = None,
        assignee_name: str | None = None,
        project_id: int | str | None = None,
        set_status: bool = False,
        set_assignee: bool = False,
    ) -> None:
        update_payload: dict[str, Any] = {}
        if set_status:
            if not status_name:
                raise RedmineClientError("Status cannot be empty")
            issue_payload = self.get_issue_payload(issue_id).get("issue", {})
            current_status = (issue_payload.get("status") or {}).get("name")
            if status_name == current_status:
                set_status = False
            else:
                allowed_statuses = issue_payload.get("allowed_statuses") or []
                matched = next((item for item in allowed_statuses if item.get("name") == status_name), None)
                if not matched:
                    allowed_names = [str(item.get("name")) for item in allowed_statuses if item.get("name")]
                    if not allowed_names:
                        raise RedmineClientError(
                            f"Status '{status_name}' is not allowed by the current Redmine workflow for issue #{issue_id}"
                        )
                    raise RedmineClientError(
                        f"Status '{status_name}' is not allowed for issue #{issue_id}. Allowed: {', '.join(allowed_names)}"
                    )
                update_payload["status_id"] = matched["id"]
        if set_assignee:
            normalized_assignee = (assignee_name or "").strip()
            if not normalized_assignee:
                update_payload["assigned_to_id"] = None
            else:
                resolved_project_id = project_id
                if resolved_project_id is None:
                    issue_payload = self.get_issue_payload(issue_id).get("issue", {})
                    resolved_project_id = (issue_payload.get("project") or {}).get("id")
                if not resolved_project_id:
                    raise RedmineClientError("Cannot resolve project members for assignee update")
                members = self.list_project_members(resolved_project_id)
                matched_user = next((user for user in members if user["name"] == normalized_assignee), None)
                if not matched_user:
                    raise RedmineClientError(f"Unknown assignee in project: {normalized_assignee}")
                update_payload["assigned_to_id"] = matched_user["id"]
        if not update_payload:
            return
        self._request("PUT", f"/issues/{issue_id}.json", json={"issue": update_payload})
        self._delete_cached_issue_payload(issue_id)

    def get_time_entries(self, spent_on: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"spent_on": spent_on}
        if user_id is not None:
            params["user_id"] = user_id
        return self._collect_pages("/time_entries.json", "time_entries", params=params)

    def list_assigned_issues(
        self,
        user_id: int,
        *,
        project_id: int | str | None = None,
        open_only: bool = False,
    ) -> list[RedmineIssue]:
        params: dict[str, Any] = {"assigned_to_id": user_id, "sort": "updated_on:desc"}
        if project_id is not None:
            params["project_id"] = project_id
        if open_only:
            params["status_id"] = "open"
        issues = self._collect_pages("/issues.json", "issues", params=params)
        issue_ids = [int(issue["id"]) for issue in issues if issue.get("id")]
        return self.get_issues_by_ids(issue_ids)

    def create_issue(
        self,
        *,
        project_id: int | str,
        subject: str,
        description: str,
        tracker_id: int | None = None,
        assigned_to_id: int | None = None,
        parent_issue_id: int | None = None,
    ) -> RedmineIssue:
        issue_payload: dict[str, Any] = {
            "project_id": project_id,
            "subject": subject,
            "description": description,
        }
        if tracker_id is not None:
            issue_payload["tracker_id"] = tracker_id
        if assigned_to_id is not None:
            issue_payload["assigned_to_id"] = assigned_to_id
        if parent_issue_id is not None:
            issue_payload["parent_issue_id"] = parent_issue_id
        payload = self._request("POST", "/issues.json", json={"issue": issue_payload})
        issue = payload.get("issue")
        if issue:
            return self._map_issue(issue)
        if "id" not in payload:
            raise RedmineClientError("Redmine did not return created issue id")
        return self.get_issue(payload["id"])

    def create_relation(self, issue_id: int, related_issue_id: int) -> None:
        self._request(
            "POST",
            f"/issues/{issue_id}/relations.json",
            json={"relation": {"issue_to_id": related_issue_id, "relation_type": "relates"}},
        )

    def save_time_entry(self, *, issue_id: int, hours: float, activity_name: str, spent_on: str) -> None:
        self.list_time_entry_activities()  # populate _activity_lookup_cache
        activities = self._activity_lookup_cache or []
        activity = next((item for item in activities if item["name"] == activity_name), None)
        if not activity:
            raise RedmineClientError(f"Unknown activity: {activity_name}")
        current_user = self.current_user()
        existing_entries = self.get_time_entries(spent_on, user_id=current_user["id"])
        matched = next(
            (
                entry
                for entry in existing_entries
                if entry.get("issue", {}).get("id") == issue_id and entry.get("activity", {}).get("name") == activity_name
            ),
            None,
        )
        payload = {"time_entry": {"issue_id": issue_id, "hours": hours, "activity_id": activity["id"], "spent_on": spent_on}}
        if matched:
            self._request("PUT", f"/time_entries/{matched['id']}.json", json=payload)
            return
        self._request("POST", "/time_entries.json", json=payload)

    def _map_issue(self, issue: dict[str, Any]) -> RedmineIssue:
        assignee = issue.get("assigned_to", {})
        tracker = issue.get("tracker", {})
        status = issue.get("status", {})
        return RedmineIssue(
            issue_id=issue["id"],
            subject=issue.get("subject", ""),
            tracker=tracker.get("name", "Unknown"),
            tracker_id=tracker.get("id"),
            status=status.get("name", "Unknown"),
            allowed_statuses=[str(item.get("name")) for item in issue.get("allowed_statuses", []) if item.get("name")],
            assignee=assignee.get("name"),
            url=f"{self.host}/issues/{issue['id']}",
            parent_issue_id=(issue.get("parent") or {}).get("id"),
        )
