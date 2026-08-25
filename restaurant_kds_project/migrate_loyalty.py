"""Migrate loyalty data from the old Soda Silvia rewards SQLite DB into the KDS.

Maps:  users -> customers, visits -> loyalty_visits, rewards -> loyalty_rewards,
completion_cycles -> loyalty_cycles, manual_numbers -> loyalty_manual_numbers.

Idempotent: customers deduped by (login_type, login_identifier); visits by
(customer, date_key); rewards by (customer, unique_key); cycles by
(customer, cycle_number); manual numbers by (customer, number, assigned_date).
Existing password hashes (bcrypt) are preserved.

Usage (run from inside restaurant_kds_project, with the same DATA_DIR/DATABASE_URL
env the app uses so it writes to the SAME database):

    python migrate_loyalty.py /path/to/soda_silvia.db
    # or set LOYALTY_SOURCE_DB=/path/to/soda_silvia.db and run without args
"""
import os
import sys
import sqlite3
from datetime import datetime

from app.database import SessionLocal, engine, Base
from app import models  # ensure models are registered
from app.models import (
    Customer, LoyaltyVisit, LoyaltyReward, LoyaltyCycle, LoyaltyManualNumber, cr_now,
)


def _dt(value):
    """Parse a datetime stored by the old app; fall back to cr_now()."""
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
    cur.execute(f"SELECT * FROM {table}")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main():
    src = (sys.argv[1] if len(sys.argv) > 1 else os.getenv("LOYALTY_SOURCE_DB", "")).strip()
    if not src or not os.path.isfile(src):
        print(f"ERROR: source DB not found: {src!r}")
        print("Pass the old soda_silvia.db path as an argument or set LOYALTY_SOURCE_DB.")
        sys.exit(1)

    # Make sure destination tables exist.
    Base.metadata.create_all(bind=engine)

    sc = sqlite3.connect(src)
    sc.row_factory = None
    cur = sc.cursor()
    users = _rows(cur, "users")
    visits = _rows(cur, "visits")
    rewards = _rows(cur, "rewards")
    cycles = _rows(cur, "completion_cycles")
    manuals = _rows(cur, "manual_numbers")
    sc.close()

    added = {"customers": 0, "visits": 0, "rewards": 0, "cycles": 0, "manual": 0}
    skipped = {"customers": 0, "visits": 0, "rewards": 0, "cycles": 0, "manual": 0}
    id_map = {}  # old user_id -> new customer_id

    db = SessionLocal()
    try:
        # Customers
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
                name=u.get("name"),
                phone=u.get("phone"),
                login_type=u["login_type"],
                login_identifier=u["login_identifier"],
                hashed_password=u.get("hashed_password"),
                created_at=_dt(u.get("created_at")),
            )
            db.add(c)
            db.flush()  # get c.id
            id_map[u["id"]] = c.id
            added["customers"] += 1

        # Visits
        for v in visits:
            cid = id_map.get(v["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == cid, LoyaltyVisit.date_key == v["date_key"]).first():
                skipped["visits"] += 1
                continue
            db.add(LoyaltyVisit(
                customer_id=cid, date_key=v["date_key"],
                source=v.get("source") or "qr_scan",
                stars_earned=v.get("stars_earned") or 1,
                created_at=_dt(v.get("created_at")),
            ))
            added["visits"] += 1

        # Rewards
        for r in rewards:
            cid = id_map.get(r["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyReward).filter(LoyaltyReward.customer_id == cid, LoyaltyReward.unique_key == r["unique_key"]).first():
                skipped["rewards"] += 1
                continue
            db.add(LoyaltyReward(
                customer_id=cid, type=r["type"], number=r.get("number"),
                status=r.get("status") or "available", unique_key=r["unique_key"],
                earned_at=_dt(r.get("earned_at")),
            ))
            added["rewards"] += 1

        # Completion cycles
        for cy in cycles:
            cid = id_map.get(cy["user_id"])
            if not cid:
                continue
            if db.query(LoyaltyCycle).filter(LoyaltyCycle.customer_id == cid, LoyaltyCycle.cycle_number == cy["cycle_number"]).first():
                skipped["cycles"] += 1
                continue
            db.add(LoyaltyCycle(customer_id=cid, cycle_number=cy["cycle_number"], completed_at=_dt(cy.get("completed_at"))))
            added["cycles"] += 1

        # Manual numbers
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
            db.add(LoyaltyManualNumber(
                customer_id=cid, number=m["number"], assigned_date=m["assigned_date"],
                created_at=_dt(m.get("created_at")),
            ))
            added["manual"] += 1

        db.commit()
    finally:
        db.close()

    print("Migration complete.")
    for k in added:
        print(f"  {k:10} added={added[k]:4}  skipped(existing)={skipped[k]}")


if __name__ == "__main__":
    main()
