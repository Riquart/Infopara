from __future__ import annotations

import enum
import json
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class SourceKind(str, enum.Enum):
    rss = "rss"
    html = "html"


class SourceCategory(str, enum.Enum):
    officiel = "officiel"
    syndicat = "syndicat"
    ordre = "ordre"
    presse = "presse"
    editeur = "editeur"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind), nullable=False)
    selector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title_sel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    link_sel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_sel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    summary_sel: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[SourceCategory] = mapped_column(Enum(SourceCategory), nullable=False)
    _default_tags: Mapped[str] = mapped_column("default_tags", Text, default="[]")
    _default_profession_tags: Mapped[str] = mapped_column(
        "default_profession_tags", Text, default="[]"
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    articles: Mapped[List[Article]] = relationship("Article", back_populates="source")

    @property
    def default_tags(self) -> List[str]:
        return json.loads(self._default_tags)

    @default_tags.setter
    def default_tags(self, value: List[str]) -> None:
        self._default_tags = json.dumps(value, ensure_ascii=False)

    @property
    def default_profession_tags(self) -> List[str]:
        return json.loads(self._default_profession_tags)

    @default_profession_tags.setter
    def default_profession_tags(self, value: List[str]) -> None:
        self._default_profession_tags = json.dumps(value, ensure_ascii=False)

    @property
    def article_count(self) -> int:
        return len(self.articles)


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("sources.id"), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    url_hash: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    summary_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    _tags: Mapped[str] = mapped_column("tags", Text, default="[]")
    _profession_tags: Mapped[str] = mapped_column("profession_tags", Text, default="[]")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    source: Mapped[Source] = relationship("Source", back_populates="articles")

    __table_args__ = (
        Index("ix_articles_url_hash", "url_hash"),
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_source_id", "source_id"),
    )

    @property
    def tags(self) -> List[str]:
        return json.loads(self._tags)

    @tags.setter
    def tags(self, value: List[str]) -> None:
        self._tags = json.dumps(value, ensure_ascii=False)

    @property
    def profession_tags(self) -> List[str]:
        return json.loads(self._profession_tags)

    @profession_tags.setter
    def profession_tags(self, value: List[str]) -> None:
        self._profession_tags = json.dumps(value, ensure_ascii=False)


class UserPref(Base):
    """Per-user article preferences, keyed by cookie session UUID."""
    __tablename__ = "user_prefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False)
    article_id: Mapped[int] = mapped_column(Integer, ForeignKey("articles.id", ondelete="CASCADE"), nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)

    article: Mapped[Article] = relationship("Article")

    __table_args__ = (
        Index("ix_user_prefs_session", "session_id"),
        Index("ix_user_prefs_session_article", "session_id", "article_id", unique=True),
    )
