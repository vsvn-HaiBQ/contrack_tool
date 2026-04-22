import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def write_audit_log(
    db: Session,
    *,
    actor: User,
    action: str,
    target_type: str,
    target_id: str | None,
    payload_before: dict[str, Any] | None = None,
    payload_after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id,
            actor_username=actor.username,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload_before=json.dumps(payload_before, ensure_ascii=True) if payload_before is not None else None,
            payload_after=json.dumps(payload_after, ensure_ascii=True) if payload_after is not None else None,
            ip=ip,
            user_agent=user_agent,
        )
    )
