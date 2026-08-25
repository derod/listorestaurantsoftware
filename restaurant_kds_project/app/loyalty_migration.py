"""Core loyalty data migration, importable from both the CLI (migrate_loyalty.py)
and the app startup hook (main.py). Reads the old Soda Silvia rewards SQLite DB
and imports it into the KDS. Idempotent (deduped on natural keys)."""
import os
import sqlite3
from datetime import datetime

from .database import SessionLocal, engine, Base
from .models import (
    Customer, LoyaltyVisit, LoyaltyReward, LoyaltyCycle, LoyaltyManualNumber, cr_now,
)


def _dt(value):
    if value is None:
        return cr_now()
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return cr_now()


def _rows(cur, table):
    try:
        cur.execute(f"SELECT * FROM {table}")
    except sqlite3.OperationalError:
        return []
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def migrate_from_sqlite(src_path: str) -> dict:
    """Import users/visits/rewards/cycles/manual_numbers from the old DB.
    Returns {"added": {...}, "skipped": {...}}."""
    if not src_path or not os.path.isfile(src_path):
        raise FileNotFoundError(f"source DB not found: {src_path!r}")

    Base.metadata.create_all(bind=engine)

    sc = sqlite3.connect(src_path)
    cur = sc.cursor()
    users = _rows(cur, "users")
    visits = _rows(cur, "visits")
    rewards = _rows(cur, "rewards")
    cycles = _rows(cur, "completion_cycles")
    manuals = _rows(cur, "manual_numbers")
    sc.close()

    added = {"customers": 0, "visits": 0, "rewards": 0, "cycles": 0, "manual": 0}
    skipped = {"customers": 0, "visits": 0, "rewards": 0, "cycles": 0, "manual": 0}
    id_map = {}

    db = SessionLocal()
    try:
        for u in users:
            existing = db.query(Customer).filter(
                Customer.login_type == u["login_type"],
                Customer.login_identifier == u["login_identifier"],
            ).first()
            if existing:
                id_map[u["id"]] = existing.id
                skipped["customers"] += 1
                continue
            c = Customer(
                name=u.get("name"), phone=u.get("phone"),
                login_type=u["login_type"], login_identifier=u["login_identifier"],
                hashed_password=u.get("hashed_password"), created_at=_dt(u.get("created_at")),
            )
            db.add(c)
            db.flush()
            id_map[u["id"]] = c.id
            added["customers"] += 1

        for v in visits:
            cid = id_map.get(v["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == cid, LoyaltyVisit.date_key == v["date_key"]).first():
                skipped["visits"] += 1
                continue
            db.add(LoyaltyVisit(customer_id=cid, date_key=v["date_key"],
                                source=v.get("source") or "qr_scan", stars_earned=v.get("stars_earned") or 1,
                                created_at=_dt(v.get("created_at"))))
            added["visits"] += 1

        for r in rewards:
            cid = id_map.get(r["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyReward).filter(LoyaltyReward.customer_id == cid, LoyaltyReward.unique_key == r["unique_key"]).first():
                skipped["rewards"] += 1
                continue
            db.add(LoyaltyReward(customer_id=cid, type=r["type"], number=r.get("number"),
                                 status=r.get("status") or "available", unique_key=r["unique_key"],
                                 earned_at=_dt(r.get("earned_at"))))
            added["rewards"] += 1

        for cy in cycles:
            cid = id_map.get(cy["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyCycle).filter(LoyaltyCycle.customer_id == cid, LoyaltyCycle.cycle_number == cy["cycle_number"]).first():
                skipped["cycles"] += 1
                continue
            db.add(LoyaltyCycle(customer_id=cid, cycle_number=cy["cycle_number"], completed_at=_dt(cy.get("completed_at"))))
            added["cycles"] += 1

        for m in manuals:
            cid = id_map.get(m["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyManualNumber).filter(
                LoyaltyManualNumber.customer_id == cid,
                LoyaltyManualNumber.number == m["number"],
                LoyaltyManualNumber.assigned_date == m["assigned_date"],
            ).first():
                skipped["manual"] += 1
                continue
            db.add(LoyaltyManualNumber(customer_id=cid, number=m["number"],
                                       assigned_date=m["assigned_date"], created_at=_dt(m.get("created_at"))))
            added["manual"] += 1

        db.commit()
    finally:
        db.close()

    return {"added": added, "skipped": skipped}
