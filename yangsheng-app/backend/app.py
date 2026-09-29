#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
养生馆预约管理 - 后端 (FastAPI + SQLite)
顾客端: 服务列表 / 预约 / 我的预约(手机号查询+取消)
店员端: 密码登录 / 预约管理 / 快速开单 / 营收统计 / 项目管理
"""
import hashlib
import json
import os
import random
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---------------- 配置 ----------------
BASE_DIR = Path(__file__).resolve().parent.parent          # 项目根目录
DB_PATH = Path(os.environ.get("DB_PATH", BASE_DIR / "data" / "app.db"))
FRONTEND_DIR = BASE_DIR / "frontend"
STAFF_PASSWORD = os.environ.get("STAFF_PASSWORD", "888888")  # 默认店员密码,上线务必修改
TOKEN_TTL = 24 * 3600  # 登录有效期 24 小时

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
TIME_SLOTS = [f"{h:02d}:00" for h in range(10, 22)]  # 10:00 - 21:00 整点

STATUS_LABEL = {
    "pending": "待到店",
    "arrived": "已到店",
    "done": "已完成",
    "cancelled": "已取消",
}

SEED_SERVICES = [
    ("面部护肤", 58, "面部护理", 1),
    ("经典头疗", 58, "头部", 2),
    ("肾部保养", 68, "身体调理", 3),
    ("清肠排毒", 68, "身体调理", 4),
    ("背部疏通", 78, "身体调理", 5),
    ("腿部疏通", 88, "身体调理", 6),
    ("调理腰腿", 118, "身体调理", 7),
    ("背+胃+腿", 198, "优惠套餐", 8),
]

# ---------------- 数据库 ----------------
def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            category TEXT NOT NULL DEFAULT '身体调理',
            description TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            service_id INTEGER NOT NULL,
            service_name TEXT NOT NULL,
            price REAL NOT NULL,
            date TEXT NOT NULL,
            time_slot TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            items TEXT NOT NULL,
            total REAL NOT NULL,
            payment_method TEXT NOT NULL,
            customer_name TEXT NOT NULL DEFAULT '',
            customer_phone TEXT NOT NULL DEFAULT '',
            remark TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_phone ON bookings(phone)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")

    # 初始项目数据: 只在 services 为空时写入
    cur.execute("SELECT COUNT(*) AS c FROM services")
    if cur.fetchone()["c"] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for name, price, category, sort_order in SEED_SERVICES:
            cur.execute(
                """INSERT INTO services
                   (name, price, category, description, active, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, '', 1, ?, ?, ?)""",
                (name, price, category, sort_order, now, now),
            )
    conn.commit()
    conn.close()


def row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


# ---------------- 认证(店员) ----------------
_tokens: dict[str, float] = {}  # token -> 过期时间戳


def check_staff(x_token: str = Header(default="", alias="X-Token")) -> None:
    exp = _tokens.get(x_token)
    if not exp or exp < time.time():
        _tokens.pop(x_token, None)
        raise HTTPException(status_code=401, detail="未登录或登录已过期")


# ---------------- 请求模型 ----------------
class BookingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    phone: str = Field(min_length=11, max_length=11)
    service_id: int
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time_slot: str


class StaffLogin(BaseModel):
    password: str


class BookingStatusUpdate(BaseModel):
    status: str  # pending / arrived / done / cancelled


class OrderItem(BaseModel):
    service_id: int
    qty: int = Field(default=1, ge=1, le=20)


class OrderCreate(BaseModel):
    items: list[OrderItem] = Field(min_length=1)
    payment_method: str  # 现金 / 微信 / 支付宝
    customer_name: str = ""
    customer_phone: str = ""
    remark: str = ""


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    price: float = Field(gt=0, le=100000)
    category: str = Field(default="身体调理", max_length=20)
    description: str = ""
    sort_order: int = 0


class ServiceUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=30)
    price: float | None = Field(default=None, gt=0, le=100000)
    category: str | None = Field(default=None, max_length=20)
    description: str | None = None
    active: int | None = Field(default=None, ge=0, le=1)
    sort_order: int | None = None


# ---------------- 应用 ----------------
app = FastAPI(title="养生馆预约管理", version="1.0.0")


@app.on_event("startup")
def _startup():
    init_db()


# ============ 顾客端 ============
@app.get("/api/services")
def list_services():
    """服务列表(仅上架)"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, price, category, description, sort_order FROM services "
        "WHERE active=1 ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return {"services": [row_to_dict(r) for r in rows]}


@app.get("/api/meta")
def meta():
    """预约页元信息: 可约日期(未来7天)与时间段"""
    days = []
    today = date.today()
    week = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for i in range(7):
        d = today + timedelta(days=i)
        label = "今天" if i == 0 else ("明天" if i == 1 else week[d.weekday()])
        days.append({"date": d.strftime("%Y-%m-%d"), "label": f"{d.month}月{d.day}日 {label}"})
    return {"days": days, "time_slots": TIME_SLOTS}


@app.post("/api/bookings", status_code=201)
def create_booking(b: BookingCreate):
    """创建预约"""
    name = b.name.strip()
    if not name:
        raise HTTPException(400, "请填写姓名")
    if not PHONE_RE.match(b.phone):
        raise HTTPException(400, "手机号格式不正确")
    if b.time_slot not in TIME_SLOTS:
        raise HTTPException(400, "时间段无效")
    try:
        d = datetime.strptime(b.date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "日期无效")
    if d < date.today() or d > date.today() + timedelta(days=6):
        raise HTTPException(400, "只能预约未来7天内")

    conn = get_conn()
    svc = conn.execute(
        "SELECT id, name, price FROM services WHERE id=? AND active=1", (b.service_id,)
    ).fetchone()
    if not svc:
        raise HTTPException(400, "该项目不存在或已下架")
    # 防重复: 同一手机号同一日期同一时段只允许一条有效预约
    dup = conn.execute(
        "SELECT id FROM bookings WHERE phone=? AND date=? AND time_slot=? AND status IN ('pending','arrived')",
        (b.phone, b.date, b.time_slot),
    ).fetchone()
    if dup:
        conn.close()
        raise HTTPException(400, "该时段您已有一条预约,无需重复提交")

    booking_no = "BK" + datetime.now().strftime("%Y%m%d") + f"{random.randint(1000, 9999)}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO bookings
           (booking_no, name, phone, service_id, service_name, price, date, time_slot, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (booking_no, name, b.phone, svc["id"], svc["name"], svc["price"],
         b.date, b.time_slot, now),
    )
    conn.commit()
    bid = cur.lastrowid
    conn.close()
    return {
        "id": bid,
        "booking_no": booking_no,
        "service_name": svc["name"],
        "price": svc["price"],
        "date": b.date,
        "time_slot": b.time_slot,
        "status": "pending",
        "status_label": STATUS_LABEL["pending"],
    }


@app.get("/api/bookings")
def my_bookings(phone: str):
    """凭手机号查询自己的预约"""
    if not PHONE_RE.match(phone or ""):
        raise HTTPException(400, "手机号格式不正确")
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, booking_no, name, service_name, price, date, time_slot, status, created_at "
        "FROM bookings WHERE phone=? ORDER BY date DESC, time_slot DESC LIMIT 50",
        (phone,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["status_label"] = STATUS_LABEL.get(d["status"], d["status"])
        out.append(d)
    return {"bookings": out}


@app.post("/api/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: int, phone: str):
    """顾客取消自己的预约(仅限未到店)"""
    conn = get_conn()
    row = conn.execute("SELECT id, phone, status FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "预约不存在")
    if row["phone"] != phone:
        conn.close()
        raise HTTPException(403, "只能取消自己的预约")
    if row["status"] not in ("pending",):
        conn.close()
        raise HTTPException(400, "该预约当前状态不可取消")
    conn.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


# ============ 店员端 ============
@app.post("/api/staff/login")
def staff_login(body: StaffLogin):
    if not body.password or hashlib.sha256(body.password.encode()).hexdigest() != \
            hashlib.sha256(STAFF_PASSWORD.encode()).hexdigest():
        raise HTTPException(401, "密码错误")
    token = secrets.token_hex(24)
    _tokens[token] = time.time() + TOKEN_TTL
    return {"token": token, "expires_in": TOKEN_TTL}


@app.get("/api/staff/bookings")
def staff_bookings(d: str = "", _: None = Depends(check_staff)):
    """按日期查看预约"""
    if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise HTTPException(400, "日期格式错误")
    target = d or date.today().strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, booking_no, name, phone, service_name, price, date, time_slot, status, created_at "
        "FROM bookings WHERE date=? ORDER BY time_slot, id",
        (target,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        x = row_to_dict(r)
        x["status_label"] = STATUS_LABEL.get(x["status"], x["status"])
        out.append(x)
    return {"date": target, "bookings": out}


@app.post("/api/staff/bookings/{booking_id}/status")
def staff_booking_status(booking_id: int, body: BookingStatusUpdate, _: None = Depends(check_staff)):
    if body.status not in STATUS_LABEL:
        raise HTTPException(400, "状态值无效")
    conn = get_conn()
    row = conn.execute("SELECT id FROM bookings WHERE id=?", (booking_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "预约不存在")
    conn.execute("UPDATE bookings SET status=? WHERE id=?", (body.status, booking_id))
    conn.commit()
    conn.close()
    return {"ok": True, "status": body.status, "status_label": STATUS_LABEL[body.status]}


@app.post("/api/staff/orders", status_code=201)
def staff_create_order(o: OrderCreate, _: None = Depends(check_staff)):
    """快速开单"""
    if o.payment_method not in ("现金", "微信", "支付宝"):
        raise HTTPException(400, "支付方式无效")
    if o.customer_phone and not PHONE_RE.match(o.customer_phone):
        raise HTTPException(400, "顾客手机号格式不正确")
    conn = get_conn()
    items, total = [], 0.0
    for it in o.items:
        svc = conn.execute(
            "SELECT id, name, price FROM services WHERE id=? AND active=1", (it.service_id,)
        ).fetchone()
        if not svc:
            conn.close()
            raise HTTPException(400, f"项目 id={it.service_id} 不存在或已下架")
        subtotal = round(svc["price"] * it.qty, 2)
        total += subtotal
        items.append({
            "service_id": svc["id"], "name": svc["name"],
            "price": svc["price"], "qty": it.qty, "subtotal": subtotal,
        })
    total = round(total, 2)
    order_no = "OD" + datetime.now().strftime("%Y%m%d%H%M%S") + f"{random.randint(10, 99)}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO orders
           (order_no, items, total, payment_method, customer_name, customer_phone, remark, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (order_no, json.dumps(items, ensure_ascii=False), total, o.payment_method,
         o.customer_name.strip(), o.customer_phone, o.remark.strip(), now),
    )
    conn.commit()
    oid = cur.lastrowid
    conn.close()
    return {"id": oid, "order_no": order_no, "total": total,
            "payment_method": o.payment_method, "items": items}


@app.get("/api/staff/orders")
def staff_orders(d: str = "", _: None = Depends(check_staff)):
    """按日期查看订单"""
    if d and not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        raise HTTPException(400, "日期格式错误")
    target = d or date.today().strftime("%Y-%m-%d")
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, order_no, items, total, payment_method, customer_name, customer_phone, remark, created_at "
        "FROM orders WHERE substr(created_at, 1, 10)=? ORDER BY id DESC",
        (target,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        x = row_to_dict(r)
        x["items"] = json.loads(x["items"])
        out.append(x)
    return {"date": target, "orders": out}


@app.get("/api/staff/stats")
def staff_stats(_: None = Depends(check_staff)):
    """营收统计: 今日 / 本周(周一至今) / 本月 + 本月项目销量排行"""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    def period_stats(start: str, end: str):
        conn = get_conn()
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS s FROM orders "
            "WHERE substr(created_at, 1, 10) BETWEEN ? AND ?",
            (start, end),
        ).fetchone()
        conn.close()
        return {"orders": row["n"], "revenue": round(row["s"], 2)}

    t = today.strftime("%Y-%m-%d")
    stats = {
        "today": period_stats(t, t),
        "week": period_stats(monday.strftime("%Y-%m-%d"), t),
        "month": period_stats(month_start.strftime("%Y-%m-%d"), t),
    }
    # 本月项目销量排行
    conn = get_conn()
    rows = conn.execute(
        "SELECT items FROM orders WHERE substr(created_at, 1, 10) BETWEEN ? AND ?",
        (month_start.strftime("%Y-%m-%d"), t),
    ).fetchall()
    conn.close()
    agg: dict[str, dict] = {}
    for r in rows:
        for it in json.loads(r["items"]):
            name = it["name"]
            a = agg.setdefault(name, {"name": name, "qty": 0, "revenue": 0.0})
            a["qty"] += it["qty"]
            a["revenue"] = round(a["revenue"] + it["subtotal"], 2)
    ranking = sorted(agg.values(), key=lambda x: x["qty"], reverse=True)
    return {**stats, "ranking": ranking}


@app.get("/api/staff/services")
def staff_services(_: None = Depends(check_staff)):
    """全部项目(含已下架)"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name, price, category, description, active, sort_order FROM services "
        "ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return {"services": [row_to_dict(r) for r in rows]}


@app.post("/api/staff/services", status_code=201)
def staff_service_create(s: ServiceCreate, _: None = Depends(check_staff)):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO services (name, price, category, description, active, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
        (s.name.strip(), s.price, s.category.strip() or "身体调理", s.description.strip(),
         s.sort_order, now, now),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return {"id": sid}


@app.put("/api/staff/services/{service_id}")
def staff_service_update(service_id: int, s: ServiceUpdate, _: None = Depends(check_staff)):
    conn = get_conn()
    row = conn.execute("SELECT id FROM services WHERE id=?", (service_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "项目不存在")
    fields, vals = [], []
    for key in ("name", "price", "category", "description", "active", "sort_order"):
        v = getattr(s, key)
        if v is not None:
            if key in ("name", "category", "description"):
                v = v.strip()
            fields.append(f"{key}=?")
            vals.append(v)
    if fields:
        fields.append("updated_at=?")
        vals.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        vals.append(service_id)
        conn.execute(f"UPDATE services SET {', '.join(fields)} WHERE id=?", vals)
        conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# ============ 前端静态页 ============
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# 兜底: 前端路由刷新仍返回首页(单页应用)
@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    f = FRONTEND_DIR / path
    if f.is_file():
        return FileResponse(str(f))
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
