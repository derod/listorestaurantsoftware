"""Loyalty module — customer accounts, QR check-in (one star/day), rewards.

Ported from the standalone Soda Silvia rewards app and namespaced under
/cliente/* so it lives alongside the KDS without route collisions. Uses the
KDS Costa Rica clock (cr_now) and the Customer/Loyalty* models.
"""
import io
import os
import re
import random
from pathlib import Path

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context as _pass_context
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..i18n import t as _i18n_t, dict_for as _i18n_dict, LANGS as _I18N_LANGS, LANG_LABELS as _I18N_LABELS
from ..models import (
    Customer, LoyaltyVisit, LoyaltyReward, LoyaltyCycle, LoyaltyManualNumber, cr_now,
)

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# i18n globals so base.html-extending admin templates render (same as web.py).
def _cur_lang(request):
    try:
        lang = request.cookies.get("lang")
    except Exception:
        lang = None
    return lang if lang in _I18N_LANGS else "es"


@_pass_context
def _jinja_t(context, key):
    req = context.get("request")
    return _i18n_t(_cur_lang(req) if req else "es", key)


templates.env.globals.update({
    "t": _jinja_t, "cur_lang": _cur_lang, "i18n_dict": _i18n_dict,
    "i18n_langs": _I18N_LANGS, "i18n_labels": _I18N_LABELS,
})


def _require_admin(request: Request) -> bool:
    return request.session.get("admin_logged_in") is True

# Restaurant QR token the in-app scanner validates. Rotatable later from admin.
LOYALTY_QR_TOKEN = os.getenv("LOYALTY_QR_TOKEN", os.getenv("RESTAURANT_TOKEN", "soda-silvia-loyalty"))

STARS_PER_CYCLE = 12


# ── helpers ──────────────────────────────────────────────────────────────────
def cr_today() -> str:
    """Today's date (YYYY-MM-DD) in Costa Rica time."""
    return cr_now().strftime("%Y-%m-%d")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\d+$")


def normalize_identifier(login_type: str, login_identifier: str) -> str:
    if login_type == "email":
        return login_identifier.strip().lower()
    if login_type == "phone":
        return re.sub(r"[\s\-\(\)]", "", login_identifier).strip()
    return login_identifier.strip().lower()


def validate_identifier(login_type: str, login_identifier: str) -> None:
    if login_type == "email" and not _EMAIL_RE.match(login_identifier):
        raise HTTPException(status_code=400, detail="Ingresa un correo válido (ej: nombre@dominio.com)")
    if login_type == "phone" and not _PHONE_RE.match(login_identifier):
        raise HTTPException(status_code=400, detail="El teléfono solo puede contener números")


def get_customer_by_identifier(db: Session, login_type: str, login_identifier: str):
    return db.query(Customer).filter(
        Customer.login_type == login_type,
        Customer.login_identifier == login_identifier,
    ).first()


def get_visits_count(db: Session, customer_id: int) -> int:
    return sum(v.stars_earned for v in db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == customer_id).all())


def get_tier_info(stars_count: int):
    if stars_count < 4:
        return {"tier": "bronze", "name": "Bronce", "emoji": "🥉"}
    if stars_count < 8:
        return {"tier": "silver", "name": "Plata", "emoji": "🥈"}
    return {"tier": "gold", "name": "Oro", "emoji": "🥇"}


def calculate_stars_to_add() -> int:
    return 1


def create_rewards_if_needed(db: Session, customer_id: int, total_stars: int):
    """Milestones at 3/6/9/12 stars per cycle → raffle number; 12 → surprise."""
    created = []
    if total_stars <= 0:
        return created
    cycle_progress = total_stars % STARS_PER_CYCLE
    milestone = STARS_PER_CYCLE if cycle_progress == 0 else cycle_progress
    if milestone not in {3, 6, 9, 12}:
        return created
    cycle_number = total_stars // STARS_PER_CYCLE if milestone == 12 else (total_stars // STARS_PER_CYCLE) + 1

    rifa_key = f"RIFA3_C{cycle_number}_M{milestone}"
    if not db.query(LoyaltyReward).filter(LoyaltyReward.customer_id == customer_id, LoyaltyReward.unique_key == rifa_key).first():
        number = str(random.randint(0, 99)).zfill(2)
        db.add(LoyaltyReward(customer_id=customer_id, type="RIFA_3", number=number, status="available", unique_key=rifa_key))
        db.commit()
        created.append({"type": "RIFA_3", "number": number})

    if milestone == 12:
        surprise_key = f"CYCLE12_C{cycle_number}"
        if not db.query(LoyaltyReward).filter(LoyaltyReward.customer_id == customer_id, LoyaltyReward.unique_key == surprise_key).first():
            db.add(LoyaltyReward(customer_id=customer_id, type="SURPRISE_12", number=None, status="available", unique_key=surprise_key))
            db.commit()
            created.append({"type": "SURPRISE_12"})
        if not db.query(LoyaltyCycle).filter(LoyaltyCycle.customer_id == customer_id, LoyaltyCycle.cycle_number == cycle_number).first():
            db.add(LoyaltyCycle(customer_id=customer_id, completed_at=cr_now(), cycle_number=cycle_number))
            db.commit()
            created.append({"type": "COMPLETION_12", "is_big_moment": True})
    return created


def award_star_for_phone(db: Session, phone: str, source: str = "pedido", name: str | None = None) -> dict:
    """Tie ordering to loyalty: upsert a customer by phone and award one star
    per day (creating the account on first order). Safe with empty/invalid phone.
    """
    normalized = normalize_identifier("phone", phone or "")
    if not normalized or not _PHONE_RE.match(normalized):
        return {"awarded": False, "reason": "no_phone"}
    customer = get_customer_by_identifier(db, "phone", normalized)
    if not customer:
        customer = Customer(name=(name or None), login_type="phone",
                            login_identifier=normalized, phone=normalized)
        db.add(customer)
        db.commit()
        db.refresh(customer)
    today = cr_today()
    if db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == customer.id, LoyaltyVisit.date_key == today).first():
        return {"awarded": False, "reason": "already_today",
                "customer_id": customer.id, "total_stars": get_visits_count(db, customer.id)}
    db.add(LoyaltyVisit(customer_id=customer.id, date_key=today, source=source, stars_earned=calculate_stars_to_add()))
    db.commit()
    total = get_visits_count(db, customer.id)
    return {"awarded": True, "stars_earned": 1, "total_stars": total,
            "current_cycle_stars": total % STARS_PER_CYCLE,
            "new_rewards": create_rewards_if_needed(db, customer.id, total),
            "customer_id": customer.id}


# ── pydantic payloads ────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str | None = None
    login_type: str
    login_identifier: str
    password: str | None = None

    @field_validator("password", "name", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        return None if v == "" or v is None else v


class LoginRequest(BaseModel):
    login_type: str
    login_identifier: str
    password: str | None = None

    @field_validator("password", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        return None if v == "" or v is None else v


class ScanCheckinRequest(BaseModel):
    restaurant_token: str


# ── HTML pages ───────────────────────────────────────────────────────────────
@router.get("/cliente", response_class=HTMLResponse)
def customer_home(request: Request):
    return RedirectResponse(url="/cliente/login", status_code=303)


# Compatibility redirects: the old loyalty app served these at the root. Keep
# old bookmarks / printed-QR links working after the cutover to /cliente/*.
def _redirect(to):
    def _r(request: Request):
        return RedirectResponse(url=to, status_code=301)
    return _r


for _old, _new in [
    ("/login", "/cliente/login"),
    ("/register", "/cliente/register"),
    ("/dashboard", "/cliente/dashboard"),
    ("/historial", "/cliente/historial"),
    ("/terminos", "/cliente/terminos"),
    ("/checkin", "/cliente/dashboard"),  # old QR native-camera scans land here
]:
    router.add_api_route(_old, _redirect(_new), methods=["GET"], include_in_schema=False)


@router.get("/cliente/register", response_class=HTMLResponse)
def customer_register_page(request: Request):
    return templates.TemplateResponse("customer_register.html", {"request": request})


@router.get("/cliente/login", response_class=HTMLResponse)
def customer_login_page(request: Request):
    return templates.TemplateResponse("customer_login.html", {"request": request})


@router.get("/cliente/dashboard", response_class=HTMLResponse)
def customer_dashboard_page(request: Request):
    return templates.TemplateResponse("customer_dashboard.html", {"request": request})


@router.get("/cliente/historial", response_class=HTMLResponse)
def customer_history_page(request: Request):
    return templates.TemplateResponse("customer_history.html", {"request": request})


@router.get("/cliente/terminos", response_class=HTMLResponse)
def customer_terminos_page(request: Request):
    return templates.TemplateResponse("customer_terminos.html", {"request": request})


# ── JSON API ─────────────────────────────────────────────────────────────────
@router.post("/cliente/api/register")
def api_register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if payload.login_type not in ("phone", "email", "username"):
        raise HTTPException(status_code=400, detail="Invalid login type")
    normalized = normalize_identifier(payload.login_type, payload.login_identifier or "")
    if not normalized:
        raise HTTPException(status_code=400, detail="El identificador no puede estar vacío")
    validate_identifier(payload.login_type, normalized)
    if get_customer_by_identifier(db, payload.login_type, normalized):
        raise HTTPException(status_code=400, detail=f"{payload.login_type.capitalize()} already registered")
    customer = Customer(
        name=payload.name,
        login_type=payload.login_type,
        login_identifier=normalized,
        hashed_password=hash_password(payload.password) if payload.password else None,
        phone=normalized if payload.login_type == "phone" else None,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return {"success": True, "user": {
        "id": customer.id, "name": customer.name,
        "login_type": customer.login_type, "login_identifier": customer.login_identifier,
    }}


@router.post("/cliente/api/login")
def api_login(payload: LoginRequest, db: Session = Depends(get_db)):
    normalized = normalize_identifier(payload.login_type, payload.login_identifier or "")
    customer = get_customer_by_identifier(db, payload.login_type, normalized)
    if not customer:
        raise HTTPException(status_code=404, detail="User not found")
    if customer.hashed_password:
        if not payload.password:
            raise HTTPException(status_code=401, detail="Password required")
        if not verify_password(payload.password, customer.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid password")
    return {"success": True, "user": {
        "id": customer.id, "name": customer.name,
        "login_type": customer.login_type, "login_identifier": customer.login_identifier,
    }}


@router.get("/cliente/api/me")
def api_me(request: Request, login_type: str, login_identifier: str, db: Session = Depends(get_db)):
    customer = get_customer_by_identifier(db, login_type, login_identifier)
    if not customer:
        raise HTTPException(status_code=404, detail="User not found")
    total_stars = get_visits_count(db, customer.id)
    current_cycle_stars = total_stars % STARS_PER_CYCLE

    visits = db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == customer.id).order_by(LoyaltyVisit.created_at.desc()).limit(5).all()
    last_visits = [{"date": v.created_at.strftime("%d/%m/%Y"), "time": v.created_at.strftime("%H:%M"),
                    "source": v.source, "stars_earned": v.stars_earned} for v in visits]

    rewards = db.query(LoyaltyReward).filter(LoyaltyReward.customer_id == customer.id).order_by(LoyaltyReward.earned_at.desc()).all()
    raffles = [{"id": r.id, "number": r.number, "date": r.earned_at.strftime("%d/%m/%Y %H:%M"), "status": r.status}
               for r in rewards if r.type == "RIFA_3"]
    surprises = [{"id": r.id, "date": r.earned_at.strftime("%d/%m/%Y %H:%M"), "status": r.status}
                 for r in rewards if r.type == "SURPRISE_12"]

    completions = db.query(LoyaltyCycle).filter(LoyaltyCycle.customer_id == customer.id).order_by(LoyaltyCycle.completed_at.desc()).all()
    completion_history = [{"cycle_number": c.cycle_number, "completed_at": c.completed_at.strftime("%d/%m/%Y %H:%M")} for c in completions]

    manual_numbers = db.query(LoyaltyManualNumber).filter(LoyaltyManualNumber.customer_id == customer.id).order_by(LoyaltyManualNumber.assigned_date.desc()).all()
    manual_numbers_data = [{"id": m.id, "number": m.number, "assigned_date": m.assigned_date} for m in manual_numbers]

    base = str(request.base_url).rstrip("/")
    return {
        "user": {"id": customer.id, "name": customer.name or "Usuario",
                 "login_type": customer.login_type, "login_identifier": customer.login_identifier},
        "restaurant_qr_url": f"{base}/cliente/checkin?token={LOYALTY_QR_TOKEN}",
        "total_stars": total_stars,
        "current_cycle_stars": current_cycle_stars,
        "stars_until_reward": STARS_PER_CYCLE - current_cycle_stars,
        "tier": get_tier_info(current_cycle_stars),
        "last_visits": last_visits,
        "rewards": {"surprises": surprises, "raffles": raffles},
        "completion_history": completion_history,
        "manual_numbers": manual_numbers_data,
    }


@router.post("/cliente/api/scan-checkin")
def api_scan_checkin(request: ScanCheckinRequest, login_type: str, login_identifier: str, db: Session = Depends(get_db)):
    if request.restaurant_token != LOYALTY_QR_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid restaurant QR code")
    customer = get_customer_by_identifier(db, login_type, login_identifier)
    if not customer:
        raise HTTPException(status_code=404, detail="User not found")

    today = cr_today()
    if db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == customer.id, LoyaltyVisit.date_key == today).first():
        return {"success": False, "message": "already_checked_in_today",
                "display_message": "Ya sumaste tu estrella de hoy.\nSólo se suma una por día — ¡te esperamos mañana!"}

    stars_earned = calculate_stars_to_add()
    db.add(LoyaltyVisit(customer_id=customer.id, date_key=today, source="qr_scan", stars_earned=stars_earned))
    db.commit()

    total_stars = get_visits_count(db, customer.id)
    current_cycle_stars = total_stars % STARS_PER_CYCLE
    new_rewards = create_rewards_if_needed(db, customer.id, total_stars)
    new_raffle_number = next((r.get("number") for r in new_rewards if r.get("type") == "RIFA_3"), None)
    is_big_moment = current_cycle_stars == 0 and total_stars > 0

    return {
        "success": True, "message": "visit_registered",
        "display_message": f"¡Visita registrada! +{stars_earned} estrella{'s' if stars_earned > 1 else ''}",
        "stars_earned": stars_earned, "total_stars": total_stars,
        "current_cycle_stars": current_cycle_stars, "new_rewards": new_rewards,
        "new_raffle_number": new_raffle_number, "big_moment": is_big_moment,
    }


@router.get("/cliente/api/visits")
def api_visits(login_type: str, login_identifier: str, page: int = 1, per_page: int = 50, db: Session = Depends(get_db)):
    customer = get_customer_by_identifier(db, login_type, login_identifier)
    if not customer:
        raise HTTPException(status_code=404, detail="User not found")
    q = db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == customer.id)
    total = q.count()
    visits = q.order_by(LoyaltyVisit.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [{"id": v.id, "date": v.created_at.strftime("%d/%m/%Y"),
                   "time": v.created_at.strftime("%H:%M"), "source": v.source,
                   "stars_earned": v.stars_earned} for v in visits],
        "total": total, "page": page, "per_page": per_page,
    }


@router.get("/cliente/checkin")
def customer_checkin_redirect(request: Request, token: str = ""):
    """Landing for native-camera scans of the check-in QR: send them to the
    dashboard (the in-app scanner is what actually posts the check-in)."""
    return RedirectResponse(url="/cliente/dashboard", status_code=303)


# ── Admin: loyalty management (behind the KDS admin session) ──────────────────
def _customer_row(db: Session, c: Customer):
    total = get_visits_count(db, c.id)
    last = db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == c.id).order_by(LoyaltyVisit.created_at.desc()).first()
    return {
        "id": c.id,
        "name": c.name or "—",
        "identifier": c.login_identifier,
        "login_type": c.login_type,
        "stars": total,
        "cycle": total % STARS_PER_CYCLE,
        "last_visit": last.created_at.strftime("%d/%m/%Y") if last else "—",
    }


@router.get("/admin/lealtad", response_class=HTMLResponse)
def admin_loyalty(request: Request, db: Session = Depends(get_db)):
    if not _require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    customers = db.query(Customer).order_by(Customer.created_at.desc()).all()
    rows = [_customer_row(db, c) for c in customers]
    rows.sort(key=lambda r: r["stars"], reverse=True)
    totals = {
        "customers": len(rows),
        "stars": sum(r["stars"] for r in rows),
        "rewards": db.query(LoyaltyReward).count(),
    }
    return templates.TemplateResponse("admin_loyalty.html", {
        "request": request, "page_title": "Lealtad", "rows": rows, "totals": totals,
    })


@router.get("/admin/lealtad/qr", response_class=HTMLResponse)
def admin_loyalty_qr(request: Request):
    if not _require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    base = str(request.base_url).rstrip("/")
    return templates.TemplateResponse("admin_loyalty_qr.html", {
        "request": request, "page_title": "QR de Lealtad",
        "token": LOYALTY_QR_TOKEN,
        "qr_url": f"{base}/cliente/checkin?token={LOYALTY_QR_TOKEN}",
    })


@router.get("/admin/lealtad/qr.png")
def admin_loyalty_qr_png(request: Request):
    if not _require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    import qrcode
    base = str(request.base_url).rstrip("/")
    img = qrcode.make(f"{base}/cliente/checkin?token={LOYALTY_QR_TOKEN}")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/admin/lealtad/{customer_id:int}", response_class=HTMLResponse)
def admin_loyalty_detail(customer_id: int, request: Request, db: Session = Depends(get_db)):
    if not _require_admin(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    total = get_visits_count(db, customer.id)
    visits = db.query(LoyaltyVisit).filter(LoyaltyVisit.customer_id == customer.id).order_by(LoyaltyVisit.created_at.desc()).limit(50).all()
    rewards = db.query(LoyaltyReward).filter(LoyaltyReward.customer_id == customer.id).order_by(LoyaltyReward.earned_at.desc()).all()
    manual = db.query(LoyaltyManualNumber).filter(LoyaltyManualNumber.customer_id == customer.id).order_by(LoyaltyManualNumber.assigned_date.desc()).all()
    return templates.TemplateResponse("admin_loyalty_detail.html", {
        "request": request, "page_title": customer.name or customer.login_identifier,
        "customer": customer, "total_stars": total, "cycle": total % STARS_PER_CYCLE,
        "tier": get_tier_info(total % STARS_PER_CYCLE),
        "visits": visits, "rewards": rewards, "manual": manual,
    })
