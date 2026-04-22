from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.core.security import decrypt_secret
from app.modules.redmine.client import RedmineClient, RedmineClientError


class IntegrationConfigError(Exception):
    pass


def _default_activity_name(client: RedmineClient) -> str:
    activities = client.list_time_entry_activities()
    if not activities:
        raise IntegrationConfigError("No Redmine time entry activities found")
    return activities[0]


def _find_tracker_id(trackers: list[dict], *names: str) -> int | None:
    normalized_names = {name.strip().lower() for name in names if name.strip()}
    for tracker in trackers:
        tracker_name = str(tracker.get("name") or "").strip().lower()
        if tracker_name in normalized_names:
            return int(tracker["id"])
    return None


def _render_description(template: str | None, *, jp_issue_id: int, jp_issue_url: str, jp_subject: str) -> str:
    if not template:
        return f"JP issue: {jp_issue_url}\n\nSubject: {jp_subject}"
    return (
        template.replace("{jp_issue_id}", str(jp_issue_id))
        .replace("{jp_issue_url}", jp_issue_url)
        .replace("{jp_subject}", jp_subject)
    )


def get_client(host: str | None, encrypted_api_key: str | None) -> RedmineClient:
    if not host:
        raise IntegrationConfigError("Redmine host is not configured")
    if not encrypted_api_key:
        raise IntegrationConfigError("Redmine API key is not configured")
    api_key = decrypt_secret(encrypted_api_key)
    if not api_key:
        raise IntegrationConfigError("Redmine API key is invalid")
    return RedmineClient(host, api_key)


def verify_jp_issue_resolved(jp_issue_id: int, host: str | None, encrypted_api_key: str | None):
    return get_client(host, encrypted_api_key).get_issue(jp_issue_id)


def list_assignees_resolved(host: str | None, encrypted_api_key: str | None, project_id: int | str | None):
    if not project_id:
        raise IntegrationConfigError("Redmine VN project id is not configured")
    return get_client(host, encrypted_api_key).list_project_members(project_id)


def list_activities_resolved(host: str | None, encrypted_api_key: str | None):
    return get_client(host, encrypted_api_key).list_time_entry_activities()


def list_issue_statuses_resolved(host: str | None, encrypted_api_key: str | None):
    return get_client(host, encrypted_api_key).list_issue_statuses()


def list_trackers_resolved(host: str | None, encrypted_api_key: str | None, project_id: int | str | None):
    client = get_client(host, encrypted_api_key)
    if project_id:
        return client.list_project_trackers(project_id)
    return client.list_trackers()


def search_reference_tickets_resolved(host: str | None, encrypted_api_key: str | None, project_id: int | str | None, jp_issue_id: int):
    return get_client(host, encrypted_api_key).search_reference_tickets(project_id, jp_issue_id)


def get_issue_resolved(host: str | None, encrypted_api_key: str | None, issue_id: int):
    return get_client(host, encrypted_api_key).get_issue(issue_id)


def update_vn_issue_resolved(
    host: str | None,
    encrypted_api_key: str | None,
    issue_id: int,
    *,
    status: str | None,
    assignee: str | None,
    project_id: int | str | None = None,
    set_status: bool = False,
    set_assignee: bool = False,
):
    get_client(host, encrypted_api_key).update_issue(
        issue_id,
        status_name=status,
        assignee_name=assignee,
        project_id=project_id,
        set_status=set_status,
        set_assignee=set_assignee,
    )


def get_logtime_source_resolved(
    host: str | None,
    encrypted_api_key: str | None,
    day: str,
    *,
    project_id: int | str | None = None,
):
    client = get_client(host, encrypted_api_key)
    current_user = client.current_user()
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_assigned = executor.submit(
            client.list_assigned_issues,
            current_user["id"],
            project_id=project_id,
            open_only=True,
        )
        future_entries = executor.submit(client.get_time_entries, day, user_id=current_user["id"])
        future_default = executor.submit(_default_activity_name, client)
        assigned_issues = future_assigned.result()
        time_entries = future_entries.result()
        default_activity = future_default.result()

        row_map: dict[int, dict] = {
        issue.issue_id: {
            "issue_id": issue.issue_id,
            "subject": issue.subject,
            "status": issue.status,
            "allowed_statuses": issue.allowed_statuses,
            "url": issue.url,
            "assignee": issue.assignee,
            "tracker": issue.tracker,
            "parent_issue_id": issue.parent_issue_id,
            "activity": default_activity,
            "hours": 0.0,
        }
        for issue in assigned_issues
    }

    missing_ids: list[int] = []
    seen_missing: set[int] = set()
    for entry in time_entries:
        issue_info = entry.get("issue") or {}
        issue_id = issue_info.get("id")
        if not issue_id or issue_id in row_map or issue_id in seen_missing:
            continue
        missing_ids.append(issue_id)
        seen_missing.add(issue_id)
    if missing_ids:
        try:
            fetched = client.get_issues_by_ids(missing_ids)
        except RedmineClientError:
            fetched = []
        for issue in fetched:
            row_map[issue.issue_id] = {
                "issue_id": issue.issue_id,
                "subject": issue.subject,
                "status": issue.status,
                "allowed_statuses": issue.allowed_statuses,
                "url": issue.url,
                "assignee": issue.assignee,
                "tracker": issue.tracker,
                "parent_issue_id": issue.parent_issue_id,
                "activity": default_activity,
                "hours": 0.0,
            }

    for entry in time_entries:
        issue_info = entry.get("issue") or {}
        issue_id = issue_info.get("id")
        if not issue_id or issue_id not in row_map:
            continue
        row = row_map[issue_id]
        row["activity"] = entry.get("activity", {}).get("name") or row["activity"]
        row["hours"] += float(entry.get("hours") or 0)
    return list(row_map.values())


def save_logtime_resolved(host: str | None, encrypted_api_key: str | None, day: str, rows: list[dict]):
    client = get_client(host, encrypted_api_key)
    # Pre-warm activity cache once so concurrent saves don't all fetch it.
    client.list_time_entry_activities()

    def _save(row: dict) -> dict:
        try:
            client.save_time_entry(issue_id=row["issue_id"], hours=row["hours"], activity_name=row["activity"], spent_on=day)
            return {"issue_id": row["issue_id"], "success": True, "message": "Saved"}
        except RedmineClientError as exc:
            return {"issue_id": row["issue_id"], "success": False, "message": str(exc)}

    if not rows:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(rows))) as executor:
        return list(executor.map(_save, rows))


def create_vn_ticket_resolved(
    *,
    vn_host: str | None,
    vn_api_key_enc: str | None,
    project_id: int | str | None,
    jp_issue_id: int,
    jp_issue_url: str,
    jp_subject: str,
    subject: str | None,
    description: str | None,
    assignee_id: int | None,
    parent_issue_id: int | None,
    related_ticket_id: int | None,
    create_subtasks: list[str],
    description_template: str | None,
    main_tracker: str | None = None,
):
    if not project_id:
        raise IntegrationConfigError("Redmine VN project id is not configured")
    client = get_client(vn_host, vn_api_key_enc)
    available_trackers = client.list_project_trackers(project_id) if project_id else client.list_trackers()
    desired_tracker = (main_tracker or "Story").strip()
    desired_tracker_key = desired_tracker.lower()
    main_tracker_id = _find_tracker_id(available_trackers, desired_tracker, desired_tracker_key)
    if main_tracker_id is None:
        raise IntegrationConfigError(f"Unknown tracker: {desired_tracker}")
    story = client.create_issue(
        project_id=project_id,
        subject=subject or f"#{jp_issue_id}: {jp_subject}",
        description=description or _render_description(description_template, jp_issue_id=jp_issue_id, jp_issue_url=jp_issue_url, jp_subject=jp_subject),
        tracker_id=main_tracker_id,
        assigned_to_id=assignee_id,
        parent_issue_id=parent_issue_id,
    )
    subtasks = []
    subtask_tracker_id = _find_tracker_id(available_trackers, "Sub-task", "Subtask")
    if create_subtasks and subtask_tracker_id is None:
        raise IntegrationConfigError("Project tracker 'Sub-task' is not available")
    for subtask_name in create_subtasks:
        # Frontend now sends the full subject; only prefix if missing.
        prefix = f"#{jp_issue_id}: "
        full_subject = subtask_name if subtask_name.lstrip().startswith(prefix) else f"{prefix}{subtask_name}"
        subtask = client.create_issue(
            project_id=project_id,
            subject=full_subject,
            description=f"Subtask for JP {jp_issue_id}",
            tracker_id=subtask_tracker_id,
            assigned_to_id=assignee_id,
            parent_issue_id=story.issue_id,
        )
        subtasks.append(subtask)
    if related_ticket_id:
        client.create_relation(story.issue_id, related_ticket_id)
    return {"story": story, "subtasks": subtasks}


def build_ticket_detail(
    *,
    jp_issue_id: int,
    vn_issue_id: int,
    jp_host: str | None,
    jp_api_key_enc: str | None,
    vn_host: str | None,
    vn_api_key_enc: str | None,
):
    jp_client = get_client(jp_host, jp_api_key_enc)
    vn_client = get_client(vn_host, vn_api_key_enc)

    # Fetch JP issue and VN story payload in parallel.
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_jp = executor.submit(jp_client.get_issue, jp_issue_id)
        future_story_payload = executor.submit(vn_client.get_issue_payload, vn_issue_id)
        future_story = executor.submit(vn_client.get_issue, vn_issue_id)
        jp = future_jp.result()
        story_payload = future_story_payload.result().get("issue", {})
        story = future_story.result()

    parent_info = story_payload.get("parent") or {}
    parent_id = parent_info.get("id")
    child_ids = [child["id"] for child in story_payload.get("children", []) if child.get("id")]
    related_ids: list[int] = []
    for relation in story_payload.get("relations", []):
        rid = relation.get("issue_id")
        rid_to = relation.get("issue_to_id")
        counterpart = rid_to if rid == vn_issue_id else rid
        if counterpart:
            related_ids.append(counterpart)

    # Parallelize parent + children + related fetches.
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_parent = executor.submit(vn_client.get_issue, parent_id) if parent_id else None
        future_children = executor.submit(vn_client.get_issues_by_ids, child_ids)
        future_related = executor.submit(vn_client.get_issues_by_ids, related_ids)
        parent = future_parent.result() if future_parent else None
        children = future_children.result()
        related = future_related.result()

    return {"jp": jp, "story": story, "parent": parent, "children": children, "related": related}


def test_connection(host: str | None, encrypted_api_key: str | None) -> str:
    client = get_client(host, encrypted_api_key)
    current_user = client.current_user()
    return f"Connected as {current_user['name']}"
