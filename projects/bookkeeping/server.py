"""记账本的服务器部分：页面、账目的增删查、从文字里找出金额。

挂载在 /apps/bookkeeping/ 下（见 projects/bookkeeping/__init__.py）。
截图和文字识别都在浏览器里完成（Tesseract.js），服务器只负责存账目、校验输入。
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth import SESSION_COOKIE, require_user, user_from_token
from app.db import get_db
from app.pages import html_page

from .models import BookkeepingEntry

router = APIRouter()
STATIC = Path(__file__).resolve().parent / "static"

MAX_AMOUNT = Decimal("1000000")
CATEGORIES = {
    "expense": ["餐饮", "交通", "购物", "居住", "娱乐", "医疗", "学习", "其他"],
    "income": ["工资", "奖金", "理财", "其他"],
}
SOURCES = ("manual", "screenshot")
_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
# 数字：支持千分位（1,280.00）和最多两位小数（35.5）。前后不能紧挨着别的数字或小数点，
# 这样 "12.345" 不会被错误地拆成 "12.34" 和 "5"
_NUMBER = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?(?!\d)")


# ------------------------------------------------------------------ 工具函数

def amount_to_cents(text: str) -> int:
    """把用户输入的金额（字符串）变成「分」。只接受 0.01 ~ 1000000，最多两位小数。"""
    raw = (text or "").strip().replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise HTTPException(400, "金额必须是数字，例如 35.5")
    if not value.is_finite() or value <= 0 or value > MAX_AMOUNT:
        raise HTTPException(400, "金额要大于 0，且不超过 1000000")
    if value != value.quantize(Decimal("0.01")):
        raise HTTPException(400, "金额最多两位小数")
    return int(value * 100)


def cents_to_str(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def extract_amounts(text: str) -> List[str]:
    """从识别出的文字里找出所有可能是金额的数字，按出现顺序去重，最多 20 个。"""
    found: List[str] = []
    for m in _NUMBER.finditer(text):
        whole = m.group(1).replace(",", "")
        value = Decimal(whole + (m.group(2) or ""))
        if value <= 0 or value > MAX_AMOUNT:
            continue
        shown = f"{value:.2f}"
        if shown not in found:
            found.append(shown)
    return found[:20]


def _entry_json(e: BookkeepingEntry) -> dict:
    return {
        "id": e.id,
        "kind": e.kind,
        "category": e.category,
        "amount": cents_to_str(e.amount_cents),
        "note": e.note,
        "occurredOn": e.occurred_on.isoformat(),
        "source": e.source,
    }


# ------------------------------------------------------------------ 请求格式

class EntryIn(BaseModel):
    kind: str
    category: str
    amount: str                 # 用字符串传输，避免浮点数误差
    note: str = Field("", max_length=100)
    occurredOn: date
    source: str = "manual"


class TextIn(BaseModel):
    text: str = Field(..., max_length=5000)


# ------------------------------------------------------------------ 路由

@router.get("/")
def page(request: Request):
    """记账页面。没登录就跳到平台的登录框，登录后回到这里。"""
    with get_db() as db:
        user = user_from_token(db, request.cookies.get(SESSION_COOKIE))
    if not user:
        return RedirectResponse("/?login=1&next=/apps/bookkeeping/", status_code=303)
    return html_page(STATIC / "index.html")


@router.get("/api/entries")
def list_entries(request: Request, month: Optional[str] = None):
    """某个月的全部账目，以及这个月的支出、收入合计。month 格式 YYYY-MM，默认本月。"""
    month = month or date.today().strftime("%Y-%m")
    if not _MONTH.fullmatch(month):
        raise HTTPException(400, "月份格式应为 YYYY-MM")
    year, mon = int(month[:4]), int(month[5:7])
    try:
        start = date(year, mon, 1)
        end = date(year + 1, 1, 1) if mon == 12 else date(year, mon + 1, 1)
    except ValueError:
        raise HTTPException(400, "月份不对")

    with get_db() as db:
        user = require_user(db, request)
        rows = db.scalars(
            select(BookkeepingEntry)
            .where(BookkeepingEntry.user_id == user.id,
                   BookkeepingEntry.occurred_on >= start,
                   BookkeepingEntry.occurred_on < end)
            .order_by(BookkeepingEntry.occurred_on.desc(), BookkeepingEntry.id.desc())
        ).all()
        entries = [_entry_json(r) for r in rows]

    totals = {"expense": 0, "income": 0}
    for r in rows:
        totals[r.kind] += r.amount_cents
    return {
        "month": month,
        "entries": entries,
        "totals": {k: cents_to_str(v) for k, v in totals.items()},
        "categories": CATEGORIES,
    }


@router.post("/api/entries", status_code=201)
def create_entry(body: EntryIn, request: Request):
    with get_db() as db:
        user = require_user(db, request)

        if body.kind not in CATEGORIES:
            raise HTTPException(400, "类型只能是支出或收入")
        if body.category not in CATEGORIES[body.kind]:
            raise HTTPException(400, "这个分类不能用于该类型")
        if body.source not in SOURCES:
            raise HTTPException(400, "来源不对")
        if body.occurredOn > date.today() + timedelta(days=1):
            raise HTTPException(400, "日期不能是未来")
        if body.occurredOn < date(2000, 1, 1):
            raise HTTPException(400, "日期太早了")

        entry = BookkeepingEntry(
            user_id=user.id,
            kind=body.kind,
            category=body.category,
            amount_cents=amount_to_cents(body.amount),
            note=body.note.strip(),
            occurred_on=body.occurredOn,
            source=body.source,
        )
        db.add(entry)
        db.flush()   # 先写入，拿到 id
        return _entry_json(entry)


@router.delete("/api/entries/{entry_id}")
def delete_entry(entry_id: int, request: Request):
    with get_db() as db:
        user = require_user(db, request)
        entry = db.get(BookkeepingEntry, entry_id)
        # 只能删自己的账目；别人的账目和不存在的一样，都返回 404
        if not entry or entry.user_id != user.id:
            raise HTTPException(404, "没有这条账目")
        db.delete(entry)
    return {"ok": True}


@router.post("/api/parse-numbers")
def parse_numbers(body: TextIn, request: Request):
    """截图识别出的文字 → 可能的金额列表。让用户从中挑，而不是自动决定。"""
    with get_db() as db:
        require_user(db, request)
    return {"numbers": extract_amounts(body.text)}
