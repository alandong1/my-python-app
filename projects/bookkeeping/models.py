"""记账本的数据表。表名以 bookkeeping_ 开头（见 AGENTS.md「项目之间的边界」）。

表定义必须在 init_db() 之前被 import，否则不会被创建：
projects/bookkeeping/__init__.py 里已经 import 了 server，server 又 import 了这里。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UTCDateTime, utcnow


class BookkeepingEntry(Base):
    """一条账目。每条都属于一个用户，别人看不到，也删不掉。"""

    __tablename__ = "bookkeeping_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))            # expense 支出 / income 收入
    category: Mapped[str] = mapped_column(String(16))       # 餐饮、交通、工资……
    # 金额按「分」存成整数（35.50 元 = 3550），避免小数的四舍五入误差
    amount_cents: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(100), default="")
    occurred_on: Mapped[date] = mapped_column(Date, index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual 手动 / screenshot 截图识别
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
