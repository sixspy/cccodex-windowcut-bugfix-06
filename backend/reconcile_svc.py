"""窗内事件与物化结果互证。

BUGFIX-06：金额对齐走结账灯同一厘级门禁（甲路径），
abs(差额) >= 0.01 即不对齐（灭灯），禁止任何容差放宽。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user
from checkout_light_svc import amount_diff, evaluate_alignment
from db import connect

router = APIRouter(tags=["reconcile"])


def _light_state(conn, wid: int) -> dict:
    row = conn.execute(
        "SELECT lit,diff_amount,policy FROM checkout_lights WHERE window_id=?",
        (wid,),
    ).fetchone()
    if row is None:
        return {"lit": None, "light_diff_amount": None, "light_policy": None}
    return {
        "lit": bool(row["lit"]),
        "light_diff_amount": row["diff_amount"],
        "light_policy": row["policy"],
    }


@router.get("/api/reconcile/{wid}")
def reconcile(wid: int, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        w = conn.execute("SELECT * FROM windows WHERE id=?", (wid,)).fetchone()
        if not w:
            raise HTTPException(404, "窗口不存在")
        ev = conn.execute(
            """SELECT COUNT(*) c, COALESCE(SUM(amount),0) s
               FROM events WHERE window_id=? AND disposition='窗内'""",
            (wid,),
        ).fetchone()
        mat = conn.execute(
            "SELECT * FROM materializations WHERE window_id=? ORDER BY id DESC LIMIT 1",
            (wid,),
        ).fetchone()
        late = conn.execute(
            "SELECT COUNT(*) c FROM late_bucket WHERE window_name=?",
            (w["name"],),
        ).fetchone()["c"]
        rejects = conn.execute(
            "SELECT COUNT(*) c FROM reject_slips WHERE window_name=?",
            (w["name"],),
        ).fetchone()["c"]
        # 厘级门禁：与结账灯同一口径，差 0.01 即灭（aligned=False）
        if mat:
            amount_ok, diff = evaluate_alignment(float(ev["s"]), float(mat["total_amount"]))
            aligned = bool(amount_ok and mat["row_count"] == ev["c"])
        else:
            diff = 0.0
            aligned = False
        light = _light_state(conn, wid)
        return {
            "window": dict(w),
            "window_events": ev["c"],
            "window_amount": ev["s"],
            "materialized": dict(mat) if mat else None,
            "late_bucket": late,
            "rejects": rejects,
            "aligned": aligned,
            "diff_amount": amount_diff(float(ev["s"]), float(mat["total_amount"])) if mat else 0.0,
            "lit": light["lit"],
            "light_diff_amount": light["light_diff_amount"],
            "light_policy": light["light_policy"],
        }


@router.get("/api/reconcile")
def reconcile_all(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        windows = conn.execute("SELECT id,name,status FROM windows ORDER BY id").fetchall()
        items = []
        for w in windows:
            ev = conn.execute(
                """SELECT COUNT(*) c, COALESCE(SUM(amount),0) s
                   FROM events WHERE window_id=? AND disposition='窗内'""",
                (w["id"],),
            ).fetchone()
            mat = conn.execute(
                "SELECT * FROM materializations WHERE window_id=? ORDER BY id DESC LIMIT 1",
                (w["id"],),
            ).fetchone()
            late = conn.execute(
                "SELECT COUNT(*) c FROM late_bucket WHERE window_name=?",
                (w["name"],),
            ).fetchone()["c"]
            # 厘级门禁：与结账灯、单窗对账完全同态
            if mat:
                amount_ok, _ = evaluate_alignment(float(ev["s"]), float(mat["total_amount"]))
                aligned = bool(amount_ok and mat["row_count"] == ev["c"])
            else:
                aligned = False
            light = _light_state(conn, w["id"])
            items.append(
                {
                    "window_id": w["id"],
                    "name": w["name"],
                    "status": w["status"],
                    "aligned": aligned,
                    "lit": light["lit"],
                    "window_events": ev["c"],
                    "window_amount": ev["s"],
                    "late_bucket": late,
                }
            )
        return {"items": items}
