"""记账本的测试：登录要求、账目增删查、金额校验、用户之间互相隔离、从文字里找金额。"""
import secrets
from datetime import date, timedelta

import pytest

from projects.bookkeeping.server import amount_to_cents, extract_amounts

BASE = "/apps/bookkeeping"


def guest(client, key=None):
    """用游客身份登录（每个游客一个随机密钥，就是一个独立用户）。"""
    client.cookies.clear()
    r = client.post("/api/auth/guest", json={"guest_key": key or secrets.token_urlsafe(32)})
    assert r.status_code == 200
    return r.json()


def add(client, amount="12.5", kind="expense", category="餐饮", note="", on=None, source="manual"):
    return client.post(f"{BASE}/api/entries", json={
        "kind": kind, "category": category, "amount": amount, "note": note,
        "occurredOn": (on or date.today()).isoformat(), "source": source,
    })


# ------------------------------------------------------------ 登录要求

def test_page_redirects_to_login_when_logged_out(client):
    r = client.get(f"{BASE}/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/?login=1&next=/apps/bookkeeping/"


def test_api_requires_login(client):
    assert client.get(f"{BASE}/api/entries").status_code == 401
    assert add(client).status_code == 401
    assert client.post(f"{BASE}/api/parse-numbers", json={"text": "1"}).status_code == 401


def test_page_loads_when_logged_in(client):
    guest(client)
    r = client.get(f"{BASE}/")
    assert r.status_code == 200
    assert "记账本" in r.text
    assert "static/app.js" in r.text


# ------------------------------------------------------------ 增删查

def test_create_list_delete(client):
    guest(client)
    r = add(client, amount="35.5", category="交通", note="地铁")
    assert r.status_code == 201
    entry = r.json()
    assert entry["amount"] == "35.50" and entry["kind"] == "expense" and entry["note"] == "地铁"

    data = client.get(f"{BASE}/api/entries").json()
    assert [e["id"] for e in data["entries"]] == [entry["id"]]
    assert data["totals"] == {"expense": "35.50", "income": "0.00"}
    assert data["categories"]["income"] == ["工资", "奖金", "理财", "其他"]

    assert client.delete(f"{BASE}/api/entries/{entry['id']}").status_code == 200
    assert client.get(f"{BASE}/api/entries").json()["entries"] == []


def test_totals_split_income_and_expense(client):
    guest(client)
    add(client, amount="100")
    add(client, amount="0.1")
    add(client, amount="0.2", kind="expense")
    add(client, amount="3000", kind="income", category="工资")
    data = client.get(f"{BASE}/api/entries").json()
    assert data["totals"] == {"expense": "100.30", "income": "3000.00"}   # 按分相加，没有小数误差


def test_month_filter(client):
    guest(client)
    this_month = date.today().replace(day=1)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    add(client, amount="1", on=this_month)
    add(client, amount="2", on=last_month)
    month = last_month.strftime("%Y-%m")
    data = client.get(f"{BASE}/api/entries", params={"month": month}).json()
    assert data["month"] == month
    assert [e["amount"] for e in data["entries"]] == ["2.00"]
    assert client.get(f"{BASE}/api/entries", params={"month": "2024-13"}).status_code == 400


def test_source_screenshot_is_kept(client):
    guest(client)
    add(client, amount="9.9", source="screenshot")
    assert client.get(f"{BASE}/api/entries").json()["entries"][0]["source"] == "screenshot"


# ------------------------------------------------------------ 输入校验

@pytest.mark.parametrize("amount", ["0", "-3", "abc", "", "1.234", "1000001", "NaN", "inf"])
def test_bad_amounts_rejected(client, amount):
    guest(client)
    assert add(client, amount=amount).status_code == 400


def test_bad_kind_category_source_date_rejected(client):
    guest(client)
    assert add(client, kind="transfer").status_code == 400
    assert add(client, category="工资").status_code == 400                 # 支出里没有「工资」
    assert add(client, kind="income", category="餐饮").status_code == 400  # 收入里没有「餐饮」
    assert add(client, source="hack").status_code == 400
    assert add(client, on=date.today() + timedelta(days=5)).status_code == 400
    assert add(client, on=date(1999, 1, 1)).status_code == 400
    assert add(client, note="x" * 101).status_code == 422


def test_amount_to_cents():
    assert amount_to_cents("35.5") == 3550
    assert amount_to_cents("1,280.00") == 128000
    assert amount_to_cents(" 0.01 ") == 1
    assert amount_to_cents("1000000") == 100000000
    for bad in ("0", "0.001", "-1", "x", "1e400"):
        with pytest.raises(Exception):
            amount_to_cents(bad)


# ------------------------------------------------------------ 用户隔离

def test_users_cannot_see_or_delete_each_other(client):
    guest(client, key="alice-" + secrets.token_urlsafe(24))
    mine = add(client, amount="8").json()

    guest(client, key="bob-" + secrets.token_urlsafe(24))
    assert client.get(f"{BASE}/api/entries").json()["entries"] == []
    assert client.delete(f"{BASE}/api/entries/{mine['id']}").status_code == 404

    guest(client, key="alice-" + secrets.token_urlsafe(24))   # 换个游客密钥，看不到 alice 的账目
    assert client.get(f"{BASE}/api/entries").json()["entries"] == []


# ------------------------------------------------------------ 截图识别：从文字里找金额

def test_extract_amounts():
    # 订单号 20241124 超过金额上限（100 万），被过滤掉；12.345 不会被拆成 12.34 和 5
    text = "午餐 ¥ 35.5\n合计 1,280.00\n订单号 20241124\n12.345 元"
    assert extract_amounts(text) == ["35.50", "1280.00", "12.00"]


def test_extract_amounts_dedup_and_limit():
    # 0 不算金额；-3 里的 3 会被提取出来（符号忽略），由用户自己挑
    assert extract_amounts("5 5 5.0 0 -3") == ["5.00", "3.00"]
    assert len(extract_amounts(" ".join(str(i) for i in range(1, 60)))) == 20


def test_parse_numbers_api(client):
    guest(client)
    r = client.post(f"{BASE}/api/parse-numbers", json={"text": "金额 42.8 元"})
    assert r.status_code == 200
    assert r.json() == {"numbers": ["42.80"]}
