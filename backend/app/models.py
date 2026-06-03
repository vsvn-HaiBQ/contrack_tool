from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Enum("admin", "dev", "qa", name="user_role"), nullable=False)
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
    team_automate_url_enc: Mapped[str | None] = mapped_column(Text)
    box_access_token_enc: Mapped[str | None] = mapped_column(Text)
    box_refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    box_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    default_assignee_id: Mapped[int | None] = mapped_column(Integer)
    build_source_folder: Mapped[str | None] = mapped_column(Text)
    build_output_folder: Mapped[str | None] = mapped_column(Text)
    git_eol_source_folder: Mapped[str | None] = mapped_column(Text)
    document_translation_output_directory: Mapped[str | None] = mapped_column(Text)
    document_translation_direction: Mapped[str | None] = mapped_column(String(20))
    document_translation_model: Mapped[str | None] = mapped_column(String(100))
    document_translation_reasoning_effort: Mapped[str | None] = mapped_column(String(20))
    document_translation_timeout_seconds: Mapped[int | None] = mapped_column(Integer)
    document_translation_batch_size: Mapped[int | None] = mapped_column(Integer)
    document_translation_context_window: Mapped[int | None] = mapped_column(Integer)
    document_translation_fast_mode: Mapped[bool | None] = mapped_column(Boolean)
    document_translation_glossary: Mapped[str | None] = mapped_column(Text)
    document_translation_instructions: Mapped[str | None] = mapped_column(Text)
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


class BoxIntegrationSetting(Base):
    __tablename__ = "box_integration_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    client_id: Mapped[str | None] = mapped_column(Text)
    client_secret_enc: Mapped[str | None] = mapped_column(Text)
    server_folder_id: Mapped[str | None] = mapped_column(String(100))
    client_folder_id: Mapped[str | None] = mapped_column(String(100))
    shared_link_access: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
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
    type: Mapped[str] = mapped_column(Enum("spec", "thread", "build", "client", "server", "pr", name="ticket_link_type"), nullable=False)
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


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
