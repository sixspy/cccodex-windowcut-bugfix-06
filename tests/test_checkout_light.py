"""BUGFIX-06 结账灯：先落失败测（红），再改写路径（绿）。

口径：甲路径（厘级门禁灭灯）。
- 金额差 >= 0.01 强制灭灯，同事务写差额审计，正式结论 conclusion 不得为真。
- 两人同窗点灯占灯锁 light:{wid}，后到只记争用、不写业务。
"""
import pytest
from fastapi.testclient import TestClient

from app import app, init_db
import db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "light.db")
    init_db()
    yield


def _auth(c, username="admin", password="123456"):
    tok = c.post(
        "/api/login", json={"username": username, "password": password}
    ).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _close_and_materialize(c, h, amount=10.0):
    assert c.post(
        "/api/events",
        headers=h,
        json={
            "window_name": "W-1102",
            "biz_key": "K1",
            "event_ts": "2026-11-02T10:00:00",
            "amount": amount,
        },
    ).status_code == 200
    assert c.post("/api/windows/2/close", headers=h).status_code == 200
    assert c.post("/api/windows/2/materialize", headers=h).status_code == 200


def test_one_cent_diff_forces_light_off_and_writes_diff_audit():
    """假亮失败测：台账少一厘（差 0.01），点灯必须强制灭并同事务落差额审计。"""
    c = TestClient(app)
    h = _auth(c)
    _close_and_materialize(c, h, 10.0)
    # 制造 0.01 差额：物化台账 9.99 vs 窗内合计 10.00
    with db.connect() as conn:
        conn.execute(
            "UPDATE materializations SET total_amount=9.99 WHERE window_id=2"
        )
        conn.commit()

    r = c.post("/api/windows/2/checkout-light", headers=h)
    assert r.status_code == 200
    body = r.json()
    # 厘级门禁：差 0.01 灯不得亮
    assert body["lit"] is False
    assert abs(body["diff_amount"] - 0.01) < 1e-9

    # 对账页同态：同一厘级口径，aligned 必须为 False
    recon = c.get("/api/reconcile/2", headers=h).json()
    assert recon["aligned"] is False
    assert recon["lit"] is False

    with db.connect() as conn:
        light = conn.execute(
            "SELECT * FROM checkout_lights WHERE window_id=2"
        ).fetchone()
        assert light is not None
        assert light["lit"] == 0  # 灯册钉死为灭
        da = conn.execute(
            "SELECT * FROM difference_audits WHERE window_id=2"
        ).fetchone()
        # 同事务差额审计必须存在，且正式结论不得为真
        assert da is not None
        assert abs(da["diff_amount"] - 0.01) < 1e-9
        assert da["conclusion"] == 0

    # 差额审计旁路可见
    items = c.get("/api/difference-audits", headers=h).json()["items"]
    assert any(
        x["window_id"] == 2 and x["conclusion"] is False for x in items
    )
    # 禁止无审计差额却亮灯：亮态灯不得对应任何差额审计
    with db.connect() as conn:
        lit_with_diff = conn.execute(
            """SELECT COUNT(*) c FROM checkout_lights l
               JOIN difference_audits d ON d.window_id=l.window_id
               WHERE l.lit=1 AND d.conclusion=0"""
        ).fetchone()["c"]
        assert lit_with_diff == 0


def test_two_users_contend_for_same_window_light():
    """双人抢点灯争用失败测：后到 409 只记争用，不写灯态/差额审计。"""
    c = TestClient(app)
    h1 = _auth(c)
    h2 = _auth(c, "closer", "close123")
    _close_and_materialize(c, h1, 10.0)

    # 第一人占住灯锁
    assert c.post(
        "/api/locks/acquire", headers=h1, json={"lock_key": "light:2"}
    ).status_code == 200

    # 后到者点灯
    r = c.post("/api/windows/2/checkout-light", headers=h2)
    assert r.status_code == 409

    # 争用只登记
    cont = c.get("/api/contention", headers=h1).json()["items"]
    assert any(
        x["lock_key"] == "light:2" and x["actor"] == "closer" for x in cont
    )
    # 后到不写任何业务
    with db.connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM checkout_lights"
        ).fetchone()["c"] == 0
        assert conn.execute(
            "SELECT COUNT(*) c FROM difference_audits"
        ).fetchone()["c"] == 0

    # 释放后第一人点灯成功（金额一致，灯亮）
    assert c.post(
        "/api/locks/release", headers=h1, json={"lock_key": "light:2"}
    ).status_code == 200
    ok = c.post("/api/windows/2/checkout-light", headers=h1)
    assert ok.status_code == 200
    assert ok.json()["lit"] is True
