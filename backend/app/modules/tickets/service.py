from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import ManagedTicket, UserManagedTicketFollow


def ensure_ticket_follow_schema(db: Session) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS user_managed_ticket_follows (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            managed_ticket_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_user_managed_ticket_follows_user
                FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE,
            CONSTRAINT fk_user_managed_ticket_follows_managed_ticket
                FOREIGN KEY (managed_ticket_id)
                REFERENCES managed_tickets(id)
                ON DELETE CASCADE,
            CONSTRAINT uq_user_managed_ticket_follows_user_ticket UNIQUE (user_id, managed_ticket_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_user_managed_ticket_follows_user_id ON user_managed_ticket_follows (user_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_managed_ticket_follows_managed_ticket_id ON user_managed_ticket_follows (managed_ticket_id)",
    ]
    for statement in statements:
        db.execute(text(statement))
    db.flush()


def ensure_managed_ticket(db: Session, *, jp_issue_id: int, vn_issue_id: int, actor_username: str) -> ManagedTicket:
    ticket = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if ticket:
        ticket.vn_issue_id = vn_issue_id
        return ticket
    ticket = ManagedTicket(jp_issue_id=jp_issue_id, vn_issue_id=vn_issue_id, created_by=actor_username)
    db.add(ticket)
    db.flush()
    return ticket


def ensure_ticket_follow(db: Session, *, user_id: int, managed_ticket_id: int) -> UserManagedTicketFollow:
    ensure_ticket_follow_schema(db)
    follow = (
        db.query(UserManagedTicketFollow)
        .filter(
            UserManagedTicketFollow.user_id == user_id,
            UserManagedTicketFollow.managed_ticket_id == managed_ticket_id,
        )
        .first()
    )
    if follow:
        return follow
    follow = UserManagedTicketFollow(user_id=user_id, managed_ticket_id=managed_ticket_id)
    db.add(follow)
    db.flush()
    return follow


def remove_ticket_follow(db: Session, *, user_id: int, managed_ticket_id: int) -> bool:
    ensure_ticket_follow_schema(db)
    follow = (
        db.query(UserManagedTicketFollow)
        .filter(
            UserManagedTicketFollow.user_id == user_id,
            UserManagedTicketFollow.managed_ticket_id == managed_ticket_id,
        )
        .first()
    )
    if not follow:
        return False
    db.delete(follow)
    db.flush()
    return True
