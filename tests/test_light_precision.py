"""结账灯厘级门禁精度与五处同态补充测试。"""
import pytest
from fastapi.testclient import TestClient

from app import app, init_db
from checkout_light_svc import amount_diff, evaluate_alignment, to_cents
import db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "precision.db")
    init_db()
    yield


def _auth(c, username="admin", password="123456"):
    tok = c.post(
        "/api/login", json={"username": username, "password": password}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def test_cent_level_precision_helpers():
    # 浮点尾数不得制造假差额：0.1+0.2 与 0.3 在厘级口径下相等
    assert to_cents(0.1 + 0.2) == to_cents(0.3)
    assert evaluate_alignment(0.1 + 0.2, 0.3) == (True, 0.0)
    # 阈值钉死：差 0.01 即不对齐，0.009（折厘为 0）不算
    ok, diff = evaluate_alignment(10.00, 9.99)
    assert ok is False and abs(diff - 0.01) < 1e-9
    ok, diff = evaluate_alignment(10.00, 10.00)
    assert ok is True and diff == 0.0
    # 大额同样按厘比较
    ok, diff = evaluate_alignment(1_000_000.00, 999_999.99)
    assert ok is False and abs(diff - 0.01) < 1e-9
    assert abs(amount_diff(10.00, 9.99) - 0.01) < 1e-9


def test_row_count_mismatch_keeps_light_off():
    c = TestClient(app)
    h = _auth(c)
    c.post(
        "/api/events",
        headers=h,
        json={
            "window_name": "W-1102",
            "biz_key": "K1",
            "event_ts": "2026-11-02T10:00:00",
            "amount": 10.0,
        },
    )
    c.post("/api/windows/2/close", headers=h)
    c.post("/api/windows/2/materialize", headers=h)
    # 金额一致但笔数被改：灯仍灭
    with db.connect() as conn:
        conn.execute(
            "UPDATE materializations SET row_count=99 WHERE window_id=2"
        )
        conn.commit()
    r = c.post("/api/windows/2/checkout-light", headers=h).json()
    assert r["lit"] is False
    # 笔数不符但金额零差：不产生差额审计（差额审计只针对金额差）
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM difference_audits"
        ).fetchone()["c"] == 0
    recon = c.get("/api/reconcile/2", headers=h).json()
    assert recon["aligned"] is False and recon["lit"] is False


def test_no_lit_light_with_unconcluded_diff_anywhere():
    """禁止无审计差额却亮灯：凡灯册亮灯，库内不得存在同窗未核准差额。"""
    c = TestClient(app)
    h = _auth(c)
    c.post(
        "/api/events",
        headers=h,
        json={
            "window_name": "W-1102",
            "biz_key": "K1",
            "event_ts": "2026-11-02T10:00:00",
            "amount": 10.0,
        },
    )
    c.post("/api/windows/2/close", headers=h)
    c.post("/api/windows/2/materialize", headers=h)
    with db.connect() as conn:
        conn.execute(
            "UPDATE materializations SET total_amount=9.99 WHERE window_id=2"
        )
        conn.commit()
    r = c.post("/api/windows/2/checkout-light", headers=h).json()
    assert r["lit"] is False
    # 直接尝试把灯册篡改为亮：差额审计结论仍为假，同态查询必须报灭
    with db.connect() as conn:
        conn.execute("UPDATE checkout_lights SET lit=1 WHERE window_id=2")
        conn.commit()
    # 对账口径不依赖灯册自报，按厘级门禁独立判定
    recon = c.get("/api/reconcile/2", headers=h).json()
    assert recon["aligned"] is False
    items = c.get("/api/difference-audits", headers=h).json()["items"]
    assert all(x["conclusion"] is False for x in items)


def test_policy_ledger_rejects_deviation():
    """灯偏了：库层 CHECK 与应用层冻结双重拒写乙路径。"""
    import sqlite3

    import checkout_light_svc as svc
    from fastapi import HTTPException as FastHTTPException

    c = TestClient(app)
    h = _auth(c)
    c.post(
        "/api/events",
        headers=h,
        json={
            "window_name": "W-1102",
            "biz_key": "K1",
            "event_ts": "2026-11-02T10:00:00",
            "amount": 10.0,
        },
    )
    c.post("/api/windows/2/close", headers=h)
    c.post("/api/windows/2/materialize", headers=h)
    # 先正常点灯建立甲口径册
    assert c.post("/api/windows/2/checkout-light", headers=h).json()["lit"] is True
    # 库层硬约束：乙路径写不进灯册
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE light_policy_ledger SET policy='乙' WHERE id=1"
            )
        assert conn.execute(
            "SELECT policy FROM light_policy_ledger WHERE id=1"
        ).fetchone()["policy"] == "甲"

    # 应用层：假设册内被绕过约束改成乙，_freeze_policy 拒写并记灯偏了
    class _Row(dict):
        def __getitem__(self, k):
            return self.get(k)

    class _FakeConn:
        def __init__(self):
            self.actions = []

        def execute(self, sql, params=()):
            self.actions.append((sql, params))

            class _R:
                def fetchone(self_inner):
                    return _Row({"policy": "乙", "frozen_date": "2026-11-21"})

            return _R()

        def commit(self):
            pass

    fake = _FakeConn()
    with pytest.raises(FastHTTPException) as exc:
        svc._freeze_policy(fake, "admin")
    assert exc.value.status_code == 409
    # 灯偏了作为审计动作写在参数里
    assert any("灯偏了" in str(p) for _, p in fake.actions)
    # 对外只读口径始终报甲
    assert c.get("/api/light-policy", headers=h).json()["policy"] == "甲"
