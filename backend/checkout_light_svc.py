"""结账灯（BUGFIX-06 甲路径）。

口径钉死：甲路径——厘级门禁灭灯。
- 金额按厘（分）比较：abs(差额) >= 0.01 强制灭灯，同事务写差额审计，
  正式结论 conclusion 固定为 0（不得为真）。
- 点灯占灯锁 light:{wid}，后到只记争用、不写业务。
- 口径写入结账灯册 light_policy_ledger，当天冻结，偏离拒写并记「灯偏了」。
禁止只改灯色；禁止无审计差额却亮灯。
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from db import connect, write_audit
from locks import release, try_acquire

router = APIRouter(tags=["checkout-light"])

# 甲路径唯一口径，禁止与乙路径混用
LIGHT_POLICY = "甲"


def to_cents(amount: float) -> int:
    """金额折成整数厘（分），消除浮点尾数。"""
    return round(float(amount) * 100)


def amount_diff(window_amount: float, materialized_amount: float) -> float:
    """以厘级整数口径回算的差额（元）。"""
    return abs(to_cents(window_amount) - to_cents(materialized_amount)) / 100


def evaluate_alignment(window_amount: float, materialized_amount: float) -> tuple[bool, float]:
    """厘级门禁：返回 (是否对齐, 差额)。差额 >= 0.01 即不对齐。"""
    diff_cents = abs(to_cents(window_amount) - to_cents(materialized_amount))
    return diff_cents < 1, diff_cents / 100


def _freeze_policy(conn, user: str) -> None:
    """口径写册并当天冻结；偏离甲路径拒写并记灯偏了。"""
    today = date.today().isoformat()
    row = conn.execute("SELECT * FROM light_policy_ledger WHERE id=1").fetchone()
    if row is None:
        now = datetime.now().isoformat(timespec="seconds")
        conn.execute(
            """INSERT INTO light_policy_ledger(id,policy,frozen_date,frozen_by,created_at)
               VALUES (1,?,?,?,?)""",
            (LIGHT_POLICY, today, user, now),
        )
        write_audit(
            conn,
            user,
            "light_policy_freeze",
            LIGHT_POLICY,
            {"policy": LIGHT_POLICY, "frozen_date": today, "path": "厘级门禁灭灯"},
        )
        return
    if row["policy"] != LIGHT_POLICY:
        # 册内口径与甲路径不符即视为改口：拒写并记灯偏了
        write_audit(
            conn,
            user,
            "灯偏了",
            LIGHT_POLICY,
            {"ledger_policy": row["policy"], "rejected": LIGHT_POLICY},
        )
        raise _policy_deviation()
    # 同口径延续：跨天重新冻结当天，禁止出现第二种口径
    if row["frozen_date"] != today:
        conn.execute(
            "UPDATE light_policy_ledger SET frozen_date=? WHERE id=1", (today,)
        )


def _policy_deviation() -> Exception:
    return HTTPException(409, "结账灯册口径已冻结，禁止改口（灯偏了）")


@router.post("/api/windows/{wid}/checkout-light")
def checkout_light(wid: int, authorization: AuthHeader = None):
    user = require_user(authorization)
    lock_key = f"light:{wid}"
    with connect() as conn:
        # 争用只记争用：try_acquire 已写入 contention_log，先提交再 409，
        # 保证后到不写任何灯态业务、争用登记不丢。
        if not try_acquire(conn, lock_key, user):
            conn.commit()
            raise HTTPException(409, "争用：后到只记争用，不写业务")
        conn.commit()
        try:
            _freeze_policy(conn, user)
            w = conn.execute(
                "SELECT * FROM windows WHERE id=?", (wid,)
            ).fetchone()
            if not w:
                conn.commit()
                raise HTTPException(404, "窗口不存在")

            ev = conn.execute(
                """SELECT COUNT(*) c, COALESCE(SUM(amount),0) s
                   FROM events WHERE window_id=? AND disposition='窗内'""",
                (wid,),
            ).fetchone()
            mat = conn.execute(
                """SELECT * FROM materializations WHERE window_id=?
                   ORDER BY id DESC LIMIT 1""",
                (wid,),
            ).fetchone()

            now = datetime.now().isoformat(timespec="seconds")
            if not mat:
                # 无物化台账：灯灭，无差额可审（零差额不算差额审计）
                lit, diff = False, 0.0
                mat_amount = 0.0
            else:
                mat_amount = float(mat["total_amount"])
                lit, diff = evaluate_alignment(float(ev["s"]), mat_amount)
            row_count_ok = bool(mat) and mat["row_count"] == ev["c"]
            lit = bool(lit and row_count_ok)

            # 灯册一窗一行：重复点灯覆盖灯态（审计/差额表保留每次历史）
            existing = conn.execute(
                "SELECT id FROM checkout_lights WHERE window_id=?", (wid,)
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    """INSERT INTO checkout_lights(window_id,lit,diff_amount,policy,actor,created_at)
                       VALUES (?,?,?,?,?,?)""",
                    (wid, 1 if lit else 0, diff, LIGHT_POLICY, user, now),
                )
                light_id = cur.lastrowid
            else:
                light_id = existing["id"]
                conn.execute(
                    """UPDATE checkout_lights
                       SET lit=?,diff_amount=?,policy=?,actor=?,created_at=?
                       WHERE id=?""",
                    (1 if lit else 0, diff, LIGHT_POLICY, user, now, light_id),
                )

            conclusion = 1 if lit else 0
            diff_cents = abs(to_cents(float(ev["s"])) - to_cents(mat_amount))
            if diff_cents >= 1 and not lit:
                # 厘级门禁强制灭灯：同事务写差额审计，正式结论不得为真
                conn.execute(
                    """INSERT INTO difference_audits(
                           window_id,light_id,materialized_amount,window_amount,
                           diff_amount,conclusion,actor,created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        wid,
                        light_id,
                        mat_amount,
                        float(ev["s"]),
                        diff,
                        0,
                        user,
                        now,
                    ),
                )
                write_audit(
                    conn,
                    user,
                    "light_force_off_diff",
                    str(wid),
                    {
                        "diff_amount": diff,
                        "window_amount": float(ev["s"]),
                        "materialized_amount": mat_amount,
                        "conclusion": False,
                    },
                )
            else:
                write_audit(
                    conn,
                    user,
                    "light_lit" if lit else "light_off",
                    str(wid),
                    {"diff_amount": diff, "lit": lit},
                )
            conn.commit()
            return {
                "window_id": wid,
                "lit": lit,
                "diff_amount": diff,
                "policy": LIGHT_POLICY,
                "conclusion": bool(conclusion),
                "actor": user,
                "created_at": now,
            }
        finally:
            release(conn, lock_key, user)
            conn.commit()


@router.get("/api/checkout-lights")
def list_lights(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT l.*, w.name AS window_name
               FROM checkout_lights l JOIN windows w ON w.id=l.window_id
               ORDER BY l.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/light-policy")
def light_policy(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM light_policy_ledger WHERE id=1"
        ).fetchone()
        return {"policy": LIGHT_POLICY, "ledger": dict(row) if row else None}
