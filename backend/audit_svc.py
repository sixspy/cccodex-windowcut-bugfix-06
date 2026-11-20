"""审计与互证只读旁路。"""
from __future__ import annotations

from fastapi import APIRouter

from auth import AuthHeader, require_user
from db import connect

router = APIRouter(tags=["audit"])


@router.get("/api/audit")
def list_audit(authorization: AuthHeader = None, limit: int = 100):
    require_user(authorization)
    limit = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_trail ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/audit/actions")
def audit_actions(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT action, COUNT(*) c FROM audit_trail
               GROUP BY action ORDER BY c DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/difference-audits")
def list_difference_audits(authorization: AuthHeader = None, limit: int = 100):
    """差额审计正式结论旁路：conclusion 为假表示差额未核准（灯必须灭）。"""
    require_user(authorization)
    limit = max(1, min(limit, 500))
    with connect() as conn:
        rows = conn.execute(
            """SELECT * FROM difference_audits ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            d["conclusion"] = bool(d["conclusion"])
            items.append(d)
        return {"items": items}


@router.get("/api/dashboard")
def dashboard(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        open_n = conn.execute(
            "SELECT COUNT(*) c FROM windows WHERE status='开启'"
        ).fetchone()["c"]
        closed_n = conn.execute(
            "SELECT COUNT(*) c FROM windows WHERE status='已关闭'"
        ).fetchone()["c"]
        late_n = conn.execute("SELECT COUNT(*) c FROM late_bucket").fetchone()["c"]
        reject_n = conn.execute("SELECT COUNT(*) c FROM reject_slips").fetchone()["c"]
        hold_n = conn.execute(
            "SELECT COUNT(*) c FROM hold_staging WHERE status='暂存'"
        ).fetchone()["c"]
        mats = conn.execute("SELECT COUNT(*) c FROM materializations").fetchone()["c"]
        contention = conn.execute("SELECT COUNT(*) c FROM contention_log").fetchone()["c"]
        diff_audit_n = conn.execute(
            "SELECT COUNT(*) c FROM difference_audits"
        ).fetchone()["c"]
        lit_n = conn.execute(
            "SELECT COUNT(*) c FROM checkout_lights WHERE lit=1"
        ).fetchone()["c"]
        return {
            "open_windows": open_n,
            "closed_windows": closed_n,
            "late_bucket": late_n,
            "rejects": reject_n,
            "holds": hold_n,
            "materializations": mats,
            "contention": contention,
            "difference_audits": diff_audit_n,
            "lights_lit": lit_n,
        }
