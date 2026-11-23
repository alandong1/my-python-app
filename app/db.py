"""数据库连接和表结构（SQLAlchemy）。

本地没配置 DATABASE_URL 时用 SQLite 文件 dev.db；线上用 Neon PostgreSQL。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import TypeDecorator

from . import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """统一按 UTC 存取时间。SQLite 不保存时区，读出来时补上。"""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 正式账号的用户名（唯一）；游客和第三方登录用户可以没有
    username: Mapped[Optional[str]] = mapped_column(String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(32))
    # 密码的 bcrypt 哈希，绝不存明文
    password_hash: Mapped[Optional[str]] = mapped_column(String(100))
    # 已验证的邮箱（唯一）
    email: Mapped[Optional[str]] = mapped_column(String(254), unique=True, index=True)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    # 游客凭证（浏览器 localStorage 里那串随机字符）的 SHA-256 哈希
    guest_key_hash: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime)


class OAuthAccount(Base):
    """一个用户可以绑定多个第三方账号（Google / Apple / 微信）。"""
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_user_id: Mapped[str] = mapped_column(String(255))
    email: Mapped[Optional[str]] = mapped_column(String(254))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LoginSession(Base):
    """登录会话。浏览器 cookie 里存原始 token，数据库只存它的哈希。"""
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class EmailVerification(Base):
    """待验证的邮箱。点了邮件里的链接后，才写进 users.email。"""
    __tablename__ = "email_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
engine = create_engine(
    settings.DATABASE_URL,
    # Neon 空闲时会断开连接，用之前先 ping 一下，断了就自动重连
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """启动时建表（表已存在就跳过）。"""
    Base.metadata.create_all(engine)


@contextmanager
def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def describe_db() -> str:
    """给日志用的数据库描述，隐藏密码。"""
    return engine.url.render_as_string(hide_password=True)
