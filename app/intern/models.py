"""
SQLAlchemy models for the Aixtraball member portal.
DB: SQLite (WAL mode) at app/data/intern.db
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine, event, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "intern.db"
DB_PATH.parent.mkdir(exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Member(Base):
    __tablename__ = "member"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    ical_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)

    def get_display_name(self) -> str:
        return self.display_name or self.email.split("@")[0]

    def get_or_create_ical_token(self, db_session) -> str:
        if not self.ical_token:
            self.ical_token = secrets.token_urlsafe(32)
            db_session.commit()
        return self.ical_token


class AuthToken(Base):
    __tablename__ = "auth_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    pin_code: Mapped[str | None] = mapped_column(String(6))   # 6-digit alternative login
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)  # failed pin attempts
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)

    member: Mapped[Member] = relationship("Member")


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_dt: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_dt: Mapped[datetime | None] = mapped_column(DateTime)
    location: Mapped[str | None] = mapped_column(String(200))
    min_members: Mapped[int | None] = mapped_column(Integer)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    creator: Mapped[Member] = relationship("Member", foreign_keys=[created_by])
    assignments: Mapped[list[EventAssignment]] = relationship(
        "EventAssignment", back_populates="event", cascade="all, delete-orphan"
    )


class EventAssignment(Base):
    __tablename__ = "event_assignment"
    __table_args__ = (UniqueConstraint("event_id", "member_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("event.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(String(200))

    event: Mapped[Event] = relationship("Event", back_populates="assignments")
    member: Mapped[Member] = relationship("Member")


class Machine(Base):
    __tablename__ = "machine"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    yaml_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    year: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    repairs: Mapped[list[Repair]] = relationship("Repair", back_populates="machine")


class Repair(Base):
    __tablename__ = "repair"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[int] = mapped_column(ForeignKey("machine.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="other")
    status: Mapped[str] = mapped_column(String(30), default="open")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    created_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    machine: Mapped[Machine] = relationship("Machine", back_populates="repairs")
    creator: Mapped[Member] = relationship("Member", foreign_keys=[created_by])
    assignee: Mapped[Member | None] = relationship("Member", foreign_keys=[assigned_to])
    media: Mapped[list[RepairMedia]] = relationship(
        "RepairMedia", back_populates="repair", cascade="all, delete-orphan"
    )
    comments: Mapped[list[RepairComment]] = relationship(
        "RepairComment", back_populates="repair", cascade="all, delete-orphan",
        order_by="RepairComment.created_at"
    )
    subscriptions: Mapped[list[RepairSubscription]] = relationship(
        "RepairSubscription", back_populates="repair", cascade="all, delete-orphan"
    )


class RepairMedia(Base):
    __tablename__ = "repair_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repair.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    repair: Mapped[Repair] = relationship("Repair", back_populates="media")
    uploader: Mapped[Member] = relationship("Member")


class RepairComment(Base):
    __tablename__ = "repair_comment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repair_id: Mapped[int] = mapped_column(ForeignKey("repair.id", ondelete="CASCADE"))
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    repair: Mapped[Repair] = relationship("Repair", back_populates="comments")
    author: Mapped[Member] = relationship("Member")


class RepairSubscription(Base):
    __tablename__ = "repair_subscription"
    __table_args__ = (UniqueConstraint("member_id", "repair_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("member.id", ondelete="CASCADE"))
    repair_id: Mapped[int] = mapped_column(ForeignKey("repair.id", ondelete="CASCADE"))
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    member: Mapped[Member] = relationship("Member")
    repair: Mapped[Repair] = relationship("Repair", back_populates="subscriptions")


class InfoPage(Base):
    __tablename__ = "info_page"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    section: Mapped[str | None] = mapped_column(String(100))
    content_html: Mapped[str] = mapped_column(Text, default="")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    creator: Mapped[Member] = relationship("Member", foreign_keys=[created_by])
    updater: Mapped[Member | None] = relationship("Member", foreign_keys=[updated_by])


class Contact(Base):
    __tablename__ = "contact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50))
    email: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)

    creator: Mapped[Member] = relationship("Member")


class TodoList(Base):
    __tablename__ = "todo_list"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("member.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)

    creator: Mapped[Member] = relationship("Member")
    sections: Mapped[list[TodoSection]] = relationship(
        "TodoSection", back_populates="todo_list", cascade="all, delete-orphan",
        order_by="TodoSection.sort_order"
    )


class TodoSection(Base):
    __tablename__ = "todo_section"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    list_id: Mapped[int] = mapped_column(ForeignKey("todo_list.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    todo_list: Mapped[TodoList] = relationship("TodoList", back_populates="sections")
    items: Mapped[list[TodoItem]] = relationship(
        "TodoItem", back_populates="section", cascade="all, delete-orphan",
        order_by="TodoItem.sort_order"
    )


class TodoItem(Base):
    __tablename__ = "todo_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("todo_section.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(String(500), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("member.id"))

    section: Mapped[TodoSection] = relationship("TodoSection", back_populates="items")
    completer: Mapped[Member | None] = relationship("Member")


# ── Ersatzteile ──────────────────────────────────────────────────────────────

class Part(Base):
    __tablename__ = "part"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    article_number: Mapped[str | None] = mapped_column(String(100))
    supplier: Mapped[str | None] = mapped_column(String(200))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    shelf: Mapped[str | None] = mapped_column(String(100))
    bin: Mapped[str | None] = mapped_column(String(100))

    synonyms: Mapped[list["PartSynonym"]] = relationship(
        "PartSynonym", back_populates="part", cascade="all, delete-orphan"
    )
    part_manufacturers: Mapped[list["PartManufacturer"]] = relationship(
        "PartManufacturer", back_populates="part", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "article_number": self.article_number,
            "supplier": self.supplier,
            "stock": self.stock,
            "shelf": self.shelf,
            "bin": self.bin,
            "synonyms": [s.synonym for s in self.synonyms],
            "manufacturers": [pm.manufacturer.name for pm in self.part_manufacturers],
        }


class PartSynonym(Base):
    __tablename__ = "part_synonym"
    __table_args__ = (UniqueConstraint("part_id", "synonym"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id", ondelete="CASCADE"))
    synonym: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    part: Mapped[Part] = relationship("Part", back_populates="synonyms")


class Manufacturer(Base):
    __tablename__ = "manufacturer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)

    part_manufacturers: Mapped[list["PartManufacturer"]] = relationship(
        "PartManufacturer", back_populates="manufacturer", cascade="all, delete-orphan"
    )


class PartManufacturer(Base):
    __tablename__ = "part_manufacturer"
    __table_args__ = (UniqueConstraint("part_id", "manufacturer_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("part.id", ondelete="CASCADE"))
    manufacturer_id: Mapped[int] = mapped_column(ForeignKey("manufacturer.id", ondelete="CASCADE"))

    part: Mapped[Part] = relationship("Part", back_populates="part_manufacturers")
    manufacturer: Mapped[Manufacturer] = relationship("Manufacturer", back_populates="part_manufacturers")
