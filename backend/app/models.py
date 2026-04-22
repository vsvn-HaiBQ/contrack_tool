from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Enum("admin", "user", name="user_role"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    settings: Mapped["UserSettings | None"] = relationship(back_populates="user", cascade="all, delete-orphan")
    managed_ticket_follows: Mapped[list["UserManagedTicketFollow"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    redmine_jp_api_key_enc: Mapped[str | None] = mapped_column(Text)
    redmine_vn_api_key_enc: Mapped[str | None] = mapped_column(Text)
    github_token_enc: Mapped[str | None] = mapped_column(Text)
    default_assignee_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="settings")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[str | None] = mapped_column(String(100))


class ManagedTicket(Base):
    __tablename__ = "managed_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jp_issue_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    vn_issue_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    links: Mapped[list["TicketLink"]] = relationship(back_populates="managed_ticket", cascade="all, delete-orphan")
    followers: Mapped[list["UserManagedTicketFollow"]] = relationship(
        back_populates="managed_ticket", cascade="all, delete-orphan"
    )


class UserManagedTicketFollow(Base):
    __tablename__ = "user_managed_ticket_follows"
    __table_args__ = (
        UniqueConstraint("user_id", "managed_ticket_id", name="uq_user_managed_ticket_follows_user_ticket"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    managed_ticket_id: Mapped[int] = mapped_column(ForeignKey("managed_tickets.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped["User"] = relationship(back_populates="managed_ticket_follows")
    managed_ticket: Mapped["ManagedTicket"] = relationship(back_populates="followers")


class TicketLink(Base):
    __tablename__ = "ticket_links"
    __table_args__ = (
        UniqueConstraint("url", name="uq_ticket_links_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    managed_ticket_id: Mapped[int] = mapped_column(ForeignKey("managed_tickets.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(Enum("spec", "thread", "build", "pr", name="ticket_link_type"), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    managed_ticket: Mapped["ManagedTicket"] = relationship(back_populates="links")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer)
    actor_username: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(100))
    payload_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload_after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
