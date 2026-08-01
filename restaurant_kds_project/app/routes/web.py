import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse
import io as _io
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from pathlib import Path
import shutil

from ..database import get_db, DATA_DIR
from ..models import Product, Order, OrderItem, AudioSettings, Waiter, Inventory, InventoryLog, Sale, SaleItem, ContactMessage, AccessLog, WorkSession, Ingredient, Recipe, RecipeItem, InventoryMovement, Expense, FixedExpense, Purchase, PurchaseItem, Table, cr_now
from ..inventory_service import create_inventory_movement
from pydantic import BaseModel
from ..utils import duration_seconds
from ..order_history import (
    OrderHistoryFilters, get_order_history, get_all_for_export,
    export_csv, export_excel, export_pdf,
)

router = APIRouter()
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = DATA_DIR / "uploads" / "audio"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PRODUCT_IMG_DIR = DATA_DIR / "uploads" / "products"
PRODUCT_IMG_DIR.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "rodgabriel12@gmail.com")
ADMIN_PASSCODE = os.getenv("ADMIN_PASSCODE")
if not ADMIN_PASSCODE:
    raise RuntimeError("ADMIN_PASSCODE environment variable must be set")


# ─── helpers ────────────────────────────────────────────────────────────────

def require_waiter(request: Request):
    """Return (waiter_id, waiter_name) if session valid, else None."""
    wid = request.session.get("waiter_id")
    wname = request.session.get("waiter_name")
    if wid and wname:
        return wid, wname
    return None


def require_admin(request: Request):
    return request.session.get("admin_logged_in") is True


def record_access(db: Session, request: Request, role: str, actor_name=None, waiter_id=None):
    """Log a successful login/entry. Best-effort — never breaks the login."""
    try:
        db.add(AccessLog(
            role=role,
            actor_name=actor_name,
            waiter_id=waiter_id,
            ip=(request.client.host if request.client else None),
        ))
        db.commit()
    except Exception:
        db.rollback()


# ─── time clock (clock in / clock out) ────────────────────────────────────────

CLOCK_ROLES = ["station", "kitchen", "inventory", "pos"]
CLOCK_ROLE_LABELS = {
    "station": "Salón", "kitchen": "Cocina", "inventory": "Inventario", "pos": "Punto de Venta",
}


def auto_close_stale_sessions(db: Session):
    """Auto clock-out shifts left open from previous days (midnight close)."""
    try:
        today = cr_now().replace(hour=0, minute=0, second=0, microsecond=0)
        stale = db.query(WorkSession).filter(
            WorkSession.clock_out == None,  # noqa: E711
            WorkSession.clock_in < today,
        ).all()
        for s in stale:
            s.clock_out = s.clock_in.replace(hour=23, minute=59, second=59, microsecond=0)
            s.auto_closed = True
        if stale:
            db.commit()
    except Exception:
        db.rollback()


def clock_in(db: Session, role: str, actor_name, waiter_id):
    """Open a shift. Idempotent per (waiter, module): reuses an open one."""
    try:
        auto_close_stale_sessions(db)
        existing = db.query(WorkSession).filter(
            WorkSession.clock_out == None,  # noqa: E711
            WorkSession.role == role,
            WorkSession.waiter_id == waiter_id,
        ).first()
        if existing:
            return
        db.add(WorkSession(role=role, actor_name=actor_name, waiter_id=waiter_id))
        db.commit()
    except Exception:
        db.rollback()


def clock_out(db: Session, role: str, waiter_id):
    """Close the open shift for this (waiter, module), if any."""
    try:
        s = (
            db.query(WorkSession)
            .filter(
                WorkSession.clock_out == None,  # noqa: E711
                WorkSession.role == role,
                WorkSession.waiter_id == waiter_id,
            )
            .order_by(WorkSession.clock_in.desc())
            .first()
        )
        if s:
            s.clock_out = cr_now()
            db.commit()
    except Exception:
        db.rollback()


# ─── root ────────────────────────────────────────────────────────────────────

@router.get("/")
def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})


@router.get("/home")
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "page_title": "Listo Restaurant Software"})


# ─── admin login ─────────────────────────────────────────────────────────────

@router.get("/admin/login")
def admin_login_page(request: Request):
    if require_admin(request):
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse("admin_login.html", {"request": request, "page_title": "Admin Login"})


@router.post("/admin/login")
def admin_login_submit(request: Request, email: str = Form(...), passcode: str = Form(...), db: Session = Depends(get_db)):
    if email.strip() == ADMIN_EMAIL and passcode == ADMIN_PASSCODE:
        request.session["admin_logged_in"] = True
        record_access(db, request, "admin", "Admin")
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "page_title": "Admin Login", "error": "Credenciales incorrectas"},
        status_code=401,
    )


@router.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login")


# ─── station-a login ──────────────────────────────────────────────────────────

@router.get("/station-a/login")
def station_login_page(request: Request):
    w = require_waiter(request)
    if w:
        return RedirectResponse(url="/station-a/dashboard")
    return templates.TemplateResponse("station_login.html", {"request": request, "page_title": "Salon – Login"})


@router.post("/station-a/login")
def station_login_submit(request: Request, pin: str = Form(...), db: Session = Depends(get_db)):
    waiter = db.query(Waiter).filter(Waiter.pin == pin.strip(), Waiter.active == True).first()
    if not waiter:
        return templates.TemplateResponse(
            "station_login.html",
            {"request": request, "page_title": "Salon – Login", "error": "PIN incorrecto"},
            status_code=401,
        )
    request.session["waiter_id"] = waiter.id
    request.session["waiter_name"] = waiter.name
    record_access(db, request, "station", waiter.name, waiter.id)
    clock_in(db, "station", waiter.name, waiter.id)
    return RedirectResponse(url="/station-a/dashboard", status_code=303)


@router.get("/station-a/logout")
def station_logout(request: Request, db: Session = Depends(get_db)):
    wid = request.session.get("waiter_id")
    if wid:
        clock_out(db, "station", wid)
    request.session.pop("waiter_id", None)
    request.session.pop("waiter_name", None)
    return RedirectResponse(url="/station-a/login")


# ─── station-a dashboard ─────────────────────────────────────────────────────

@router.get("/station-a")
def station_a_root(request: Request):
    w = require_waiter(request)
    if not w:
        return RedirectResponse(url="/station-a/login")
    return RedirectResponse(url="/station-a/dashboard")


@router.get("/station-a/dashboard")
def station_a(request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return RedirectResponse(url="/station-a/login")
    waiter_id, waiter_name = w
    products = db.query(Product).filter(Product.active == True).order_by(Product.display_order.asc(), Product.name.asc()).all()
    settings = db.query(AudioSettings).first()
    tables = db.query(Table).order_by(Table.number.asc()).all()
    return templates.TemplateResponse(
        "station.html",
        {
            "request": request,
            "products": products,
            "categories": PRODUCT_CATEGORIES,
            "tables": tables,
            "source_role": "station_a",
            "page_title": "Salon",
            "waiter_name": waiter_name,
            "waiter_id": waiter_id,
            "settings": settings,
        },
    )


# ─── mesas (vista de piso, accesible por todos) ───────────────────────────────

@router.get("/mesas")
def mesas_page(request: Request):
    return templates.TemplateResponse("mesas.html", {"request": request, "page_title": "Mesas"})


@router.get("/admin/mesas")
def admin_mesas(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    tables = db.query(Table).order_by(Table.number.asc()).all()
    return templates.TemplateResponse("admin_mesas.html", {"request": request, "tables": tables, "page_title": "Editar plano"})


@router.post("/admin/mesas/layout")
async def save_mesas_layout(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return JSONResponse(status_code=403, content={"detail": "No autorizado"})
    data = await request.json()
    positions = data.get("positions", [])
    by_id = {t.id: t for t in db.query(Table).all()}
    for p in positions:
        t = by_id.get(p.get("id"))
        if not t:
            continue
        try:
            t.pos_x = max(0.0, min(100.0, float(p["pos_x"])))
            t.pos_y = max(0.0, min(100.0, float(p["pos_y"])))
        except (KeyError, TypeError, ValueError):
            continue
    db.commit()
    return {"ok": True}


# ─── kitchen login ────────────────────────────────────────────────────────────

@router.get("/kitchen/login")
def kitchen_login_page(request: Request):
    w = require_waiter(request)
    if w:
        return RedirectResponse(url="/kitchen/dashboard")
    return templates.TemplateResponse("kitchen_login.html", {"request": request, "page_title": "Kitchen – Login"})


@router.post("/kitchen/login")
def kitchen_login_submit(request: Request, pin: str = Form(...), db: Session = Depends(get_db)):
    waiter = db.query(Waiter).filter(Waiter.pin == pin.strip(), Waiter.active == True).first()
    if not waiter:
        return templates.TemplateResponse(
            "kitchen_login.html",
            {"request": request, "page_title": "Kitchen – Login", "error": "PIN incorrecto"},
            status_code=401,
        )
    request.session["waiter_id"] = waiter.id
    request.session["waiter_name"] = waiter.name
    record_access(db, request, "kitchen", waiter.name, waiter.id)
    clock_in(db, "kitchen", waiter.name, waiter.id)
    return RedirectResponse(url="/kitchen/dashboard", status_code=303)


@router.get("/kitchen/logout")
def kitchen_logout(request: Request, db: Session = Depends(get_db)):
    wid = request.session.get("waiter_id")
    if wid:
        clock_out(db, "kitchen", wid)
    request.session.pop("waiter_id", None)
    request.session.pop("waiter_name", None)
    return RedirectResponse(url="/kitchen/login")


# ─── kitchen dashboard ────────────────────────────────────────────────────────

@router.get("/kitchen")
def kitchen_root(request: Request):
    w = require_waiter(request)
    if not w:
        return RedirectResponse(url="/kitchen/login")
    return RedirectResponse(url="/kitchen/dashboard")


@router.get("/kitchen/dashboard")
def kitchen(request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return RedirectResponse(url="/kitchen/login")
    waiter_id, waiter_name = w
    products = db.query(Product).filter(Product.active == True).order_by(Product.display_order.asc(), Product.name.asc()).all()
    settings = db.query(AudioSettings).first()
    active_orders = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .filter(Order.status.in_(["nuevo", "aceptado", "preparando", "listo"]))
        .filter(Order.source_role != "kitchen")
        .order_by(Order.created_at.asc())
        .all()
    )
    import json
    orders_json = json.dumps([
        {
            "id": o.id,
            "source_role": o.source_role,
            "status": o.status,
            "requires_acceptance": o.requires_acceptance,
            "created_at": o.created_at.isoformat() + "Z",
            "was_edited": o.was_edited,
            "was_cancelled": o.was_cancelled,
            "waiter_name": o.waiter_name,
            "accepted_at": (o.accepted_at.isoformat() + "Z") if o.accepted_at else None,
            "preparing_at": (o.preparing_at.isoformat() + "Z") if o.preparing_at else None,
            "items": [{"product_name": i.product.name, "quantity": i.quantity, "product_id": i.product_id} for i in o.items],
        }
        for o in active_orders
    ])
    return templates.TemplateResponse(
        "kitchen.html",
        {
            "request": request,
            "products": products,
            "settings": settings,
            "active_orders": active_orders,
            "orders_json": orders_json,
            "page_title": "Kitchen",
            "waiter_name": waiter_name,
            "waiter_id": waiter_id,
        },
    )


# ─── admin ────────────────────────────────────────────────────────────────────

@router.get("/admin")
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    from sqlalchemy import func

    today_start = cr_now().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # Single-pass stats via SQL COUNT — no longer loads all orders into memory
    orders_today_count = db.query(func.count(Order.id)).filter(Order.created_at >= today_start).scalar() or 0
    orders_yesterday_count = db.query(func.count(Order.id)).filter(Order.created_at >= yesterday_start, Order.created_at < today_start).scalar() or 0
    cancelled_today = db.query(func.count(Order.id)).filter(Order.created_at >= today_start, Order.was_cancelled == True).scalar() or 0
    active_now = db.query(func.count(Order.id)).filter(
        Order.created_at >= today_start,
        Order.status.in_(["nuevo", "aceptado", "preparando", "listo"]),
    ).scalar() or 0

    # Averages — only load dispatched/cancelled orders (those with a duration)
    def avg_for_range(start, end=None):
        q = db.query(Order).filter(Order.created_at >= start)
        if end:
            q = q.filter(Order.created_at < end)
        q = q.filter((Order.dispatched_at != None) | (Order.cancelled_at != None))
        rows = q.all()
        values = [duration_seconds(o) for o in rows if duration_seconds(o) is not None]
        return round(sum(values) / len(values) / 60, 1) if values else 0

    stats = {
        "orders_today": orders_today_count,
        "orders_yesterday": orders_yesterday_count,
        "avg_today": avg_for_range(today_start),
        "avg_yesterday": avg_for_range(yesterday_start, today_start),
        "cancelled_today": cancelled_today,
        "active_now": active_now,
    }
    recent_orders = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .order_by(Order.created_at.desc())
        .limit(25)
        .all()
    )
    leads_unread = db.query(func.count(ContactMessage.id)).filter(ContactMessage.status == "nuevo").scalar() or 0
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "stats": stats, "orders": recent_orders, "duration_seconds": duration_seconds,
         "leads_unread": leads_unread, "page_title": "Admin"},
    )


@router.get("/admin/logs")
def admin_logs(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    logs = (
        db.query(InventoryLog)
        .options(joinedload(InventoryLog.product))
        .order_by(InventoryLog.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        "admin_logs.html",
        {"request": request, "logs": logs, "page_title": "Logs de usuarios"},
    )


# Categorías de producto (menús) mostradas como pestañas en el Salón.
PRODUCT_CATEGORIES = ["General", "Desayuno"]


@router.get("/admin/products")
def admin_products(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    products = db.query(Product).order_by(Product.display_order.asc(), Product.name.asc()).all()
    return templates.TemplateResponse("admin_products.html", {"request": request, "products": products, "categories": PRODUCT_CATEGORIES, "page_title": "Admin Products"})


@router.post("/admin/products")
def create_product(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    last = db.query(Product).order_by(Product.display_order.desc()).first()
    display_order = (last.display_order + 1) if last else 0
    db.add(Product(name=name.strip(), display_order=display_order))
    db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/photo")
def upload_product_photo(product_id: int, request: Request, photo: UploadFile = File(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or not photo.filename:
        return RedirectResponse(url="/admin/products", status_code=303)
    ext = Path(photo.filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return RedirectResponse(url="/admin/products", status_code=303)
    safe_name = f"product_{product_id}{ext}"
    dest = PRODUCT_IMG_DIR / safe_name
    with dest.open("wb") as f:
        shutil.copyfileobj(photo.file, f)
    product.image_path = f"/uploads/products/{safe_name}"
    db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/price")
def update_product_price(product_id: int, request: Request, price: float = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.price = max(0, price)
        db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/toggle")
def toggle_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.active = not product.active
        db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/move")
def move_product(product_id: int, request: Request, direction: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    products = db.query(Product).order_by(Product.display_order.asc()).all()
    idx = next((i for i, p in enumerate(products) if p.id == product_id), None)
    if idx is not None:
        new_idx = idx - 1 if direction == "up" else idx + 1
        if 0 <= new_idx < len(products):
            products[idx].display_order, products[new_idx].display_order = products[new_idx].display_order, products[idx].display_order
            db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/rename")
def rename_product(product_id: int, request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        name = name.strip()
        if name:
            product.name = name
            db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/category")
def set_product_category(product_id: int, request: Request, category: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    if product and category in PRODUCT_CATEGORIES:
        product.category = category
        db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/admin/products/{product_id}/delete")
def delete_product(product_id: int, request: Request, confirm: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    if confirm != "CONFIRMAR":
        return RedirectResponse(url="/admin/products", status_code=303)
    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        # Delete all child rows that reference this product to avoid FK integrity errors
        db.query(InventoryLog).filter(InventoryLog.product_id == product_id).delete()
        db.query(Inventory).filter(Inventory.product_id == product_id).delete()
        db.query(OrderItem).filter(OrderItem.product_id == product_id).delete()
        db.query(SaleItem).filter(SaleItem.product_id == product_id).delete()
        db.flush()
        db.delete(product)
        db.commit()
    return RedirectResponse(url="/admin/products", status_code=303)


@router.get("/admin/audio")
def admin_audio(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    settings = db.query(AudioSettings).first()

    def _file_exists(url_path):
        if not url_path or not url_path.startswith("/uploads/audio/"):
            return False
        fname = url_path.replace("/uploads/audio/", "", 1)
        return (UPLOAD_DIR / fname).exists()

    file_status = {
        "station": _file_exists(settings.station_order_sound_path) if settings else False,
        "kitchen": _file_exists(settings.kitchen_order_sound_path) if settings else False,
        "ready": _file_exists(settings.ready_sound_path) if settings else False,
        "cancel": _file_exists(settings.cancel_sound_path) if settings else False,
    }
    return templates.TemplateResponse(
        "admin_audio.html",
        {"request": request, "settings": settings, "file_status": file_status,
         "upload_dir": str(UPLOAD_DIR), "page_title": "Admin Audio"},
    )


@router.post("/admin/audio")
async def update_audio(
    request: Request,
    db: Session = Depends(get_db),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    settings = db.query(AudioSettings).first()
    if not settings:
        settings = AudioSettings()
        db.add(settings)
        db.flush()

    try:
        form = await request.form()

        def save_upload(field_name: str, current_value):
            upload = form.get(field_name)
            if not upload or not hasattr(upload, "filename") or not upload.filename:
                return current_value
            raw_name = Path(upload.filename).name
            ext = Path(raw_name).suffix.lower()
            if ext not in {".mp3", ".wav", ".m4a"}:
                return current_value
            # Sanitize: replace spaces/unsafe chars with underscore, keep extension
            import re
            stem = Path(raw_name).stem
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-") or "audio"
            safe_name = f"{safe_stem}{ext}"
            dest = UPLOAD_DIR / safe_name
            with dest.open("wb") as f:
                shutil.copyfileobj(upload.file, f)
            return f"/uploads/audio/{safe_name}"

        settings.station_order_sound_path = save_upload("station_sound", settings.station_order_sound_path)
        settings.kitchen_order_sound_path = save_upload("kitchen_sound", settings.kitchen_order_sound_path)
        settings.ready_sound_path = save_upload("ready_sound", settings.ready_sound_path)
        settings.cancel_sound_path = save_upload("cancel_sound", settings.cancel_sound_path)

        vol = form.get("master_volume", "1.0")
        settings.master_volume = max(0.0, min(float(vol), 1.0))
        settings.voice_enabled_for_station_orders = form.get("voice_enabled_for_station_orders") == "on"
        db.commit()
    except Exception as exc:
        import logging
        logging.getLogger("audio").exception("Audio settings update failed")
        db.rollback()
        return templates.TemplateResponse(
            "admin_audio.html",
            {"request": request, "settings": settings, "page_title": "Admin Audio",
             "error_msg": f"Error al guardar: {exc}"},
        )

    return RedirectResponse(url="/admin/audio", status_code=303)


# ─── admin waiters ────────────────────────────────────────────────────────────

@router.get("/admin/waiters")
def admin_waiters(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    waiters = db.query(Waiter).order_by(Waiter.created_at.asc()).all()
    return templates.TemplateResponse("admin_waiters.html", {"request": request, "waiters": waiters, "page_title": "Agentes"})


@router.post("/admin/waiters")
def create_waiter(request: Request, name: str = Form(...), pin: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    pin = pin.strip()
    name = name.strip()
    existing = db.query(Waiter).filter(Waiter.pin == pin).first()
    if existing:
        waiters = db.query(Waiter).order_by(Waiter.created_at.asc()).all()
        return templates.TemplateResponse(
            "admin_waiters.html",
            {"request": request, "waiters": waiters, "page_title": "Agentes", "error": "PIN ya existe"},
            status_code=400,
        )
    db.add(Waiter(name=name, pin=pin))
    db.commit()
    return RedirectResponse(url="/admin/waiters", status_code=303)


@router.get("/admin/waiters/{waiter_id}/edit")
def edit_waiter_page(waiter_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    waiter = db.query(Waiter).filter(Waiter.id == waiter_id).first()
    if not waiter:
        return RedirectResponse(url="/admin/waiters")
    return templates.TemplateResponse("admin_waiter_edit.html", {"request": request, "waiter": waiter, "page_title": "Editar Agente"})


@router.post("/admin/waiters/{waiter_id}/edit")
def edit_waiter_submit(waiter_id: int, request: Request, name: str = Form(...), pin: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    waiter = db.query(Waiter).filter(Waiter.id == waiter_id).first()
    if not waiter:
        return RedirectResponse(url="/admin/waiters")
    pin = pin.strip()
    name = name.strip()
    conflict = db.query(Waiter).filter(Waiter.pin == pin, Waiter.id != waiter_id).first()
    if conflict:
        return templates.TemplateResponse(
            "admin_waiter_edit.html",
            {"request": request, "waiter": waiter, "page_title": "Editar Agente", "error": "PIN ya en uso"},
            status_code=400,
        )
    waiter.name = name
    waiter.pin = pin
    db.commit()
    return RedirectResponse(url="/admin/waiters", status_code=303)


@router.post("/admin/waiters/{waiter_id}/toggle")
def toggle_waiter(waiter_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    waiter = db.query(Waiter).filter(Waiter.id == waiter_id).first()
    if waiter:
        waiter.active = not waiter.active
        db.commit()
    return RedirectResponse(url="/admin/waiters", status_code=303)


# ─── admin reports ────────────────────────────────────────────────────────────

@router.get("/admin/reports")
def admin_reports(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    now = cr_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)

    # ── B) Consumo de platos = pedidos despachados (KDS) + ventas POS ──────────
    def consumption(since: datetime):
        agg = {}
        # KDS: pedidos marcados como despachados
        kds = (
            db.query(Product.id, Product.name, OrderItem.quantity)
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.dispatched_at != None)
            .filter(Order.dispatched_at >= since)
            .all()
        )
        for pid, pname, qty in kds:
            a = agg.setdefault(pid, {"product_id": pid, "name": pname, "total": 0})
            a["total"] += qty or 0
        # POS: ventas registradas
        pos = (
            db.query(Product.id, Product.name, SaleItem.quantity)
            .join(SaleItem, SaleItem.product_id == Product.id)
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(Sale.created_at >= since)
            .all()
        )
        for pid, pname, qty in pos:
            a = agg.setdefault(pid, {"product_id": pid, "name": pname, "total": 0})
            a["total"] += qty or 0
        return sorted(agg.values(), key=lambda x: x["total"], reverse=True)

    daily = consumption(today_start)
    weekly = consumption(week_start)

    # ── C) Consumo de insumos = movimientos de salida/merma en el período ──────
    def ing_consumption(since: datetime):
        rows = (
            db.query(
                Ingredient.id, Ingredient.name, Ingredient.unit,
                InventoryMovement.type, InventoryMovement.quantity,
            )
            .join(InventoryMovement, InventoryMovement.ingredient_id == Ingredient.id)
            .filter(InventoryMovement.type.in_(["out", "waste"]))
            .filter(InventoryMovement.created_at >= since)
            .all()
        )
        agg = {}
        for iid, iname, unit, mtype, qty in rows:
            a = agg.setdefault(iid, {"name": iname, "unit": unit or "", "out": 0.0, "waste": 0.0})
            if mtype == "waste":
                a["waste"] += qty or 0
            else:
                a["out"] += qty or 0
        for a in agg.values():
            a["total"] = a["out"] + a["waste"]
        return sorted(agg.values(), key=lambda x: x["total"], reverse=True)

    ing_daily = ing_consumption(today_start)
    ing_weekly = ing_consumption(week_start)

    # ── A) Stock actual = inventario de insumos (mismo que /admin/inventario) ──
    ings = db.query(Ingredient).order_by(Ingredient.name.asc()).all()
    stock = [
        {
            "name": ing.name,
            "stock": ing.stock,
            "unit": ing.unit or "",
            "low": bool(ing.min_stock and ing.stock <= ing.min_stock),
        }
        for ing in ings
    ]

    return templates.TemplateResponse(
        "admin_reports.html",
        {
            "request": request,
            "daily": daily,
            "weekly": weekly,
            "ing_daily": ing_daily,
            "ing_weekly": ing_weekly,
            "stock": stock,
            "today_label": today_start.strftime("%Y-%m-%d"),
            "week_label": f"{week_start.strftime('%Y-%m-%d')} → {today_start.strftime('%Y-%m-%d')}",
            "page_title": "Reportes",
        },
    )


# ─── admin rentabilidad (profit report) ───────────────────────────────────────

def _period_start(rng: str):
    now = cr_now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if rng == "today":
        return today
    if rng == "week":
        return today - timedelta(days=today.weekday())
    if rng == "month":
        return today.replace(day=1)
    return None  # all


def _colon(x) -> str:
    return "₡" + f"{round(x):,}"


@router.get("/admin/rentabilidad")
def admin_rentabilidad(request: Request, range: str = "month", db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    from sqlalchemy import func

    rng = range if range in ("today", "week", "month", "all") else "month"
    start = _period_start(rng)

    ingredients = db.query(Ingredient).all()
    ing_cost = {i.id: float(i.cost_per_unit or 0) for i in ingredients}

    # Vendido (POS revenue)
    sq = db.query(Sale)
    if start is not None:
        sq = sq.filter(Sale.created_at >= start)
    sales = sq.all()
    vendido = sum(float(s.total or 0) for s in sales)
    num_sales = len(sales)

    # Comprado (ingredient purchases) & Merma (waste), valued at cost_per_unit
    mq = db.query(InventoryMovement)
    if start is not None:
        mq = mq.filter(InventoryMovement.created_at >= start)
    movs = mq.all()
    comprado = sum(float(m.quantity or 0) * ing_cost.get(m.ingredient_id, 0) for m in movs if m.type == "in")
    merma = sum(float(m.quantity or 0) * ing_cost.get(m.ingredient_id, 0) for m in movs if m.type == "waste")

    # Valor de inventario actual (snapshot de insumos)
    inv_value = sum(float(i.stock or 0) * float(i.cost_per_unit or 0) for i in ingredients)

    # COGS vía recetas (parcial: solo productos con receta)
    recipe_pid = {r.id: r.product_id for r in db.query(Recipe).all()}
    recipe_cost = {}
    for ri in db.query(RecipeItem).all():
        recipe_cost[ri.recipe_id] = recipe_cost.get(ri.recipe_id, 0) + float(ri.quantity or 0) * ing_cost.get(ri.ingredient_id, 0)
    product_unit_cost = {pid: recipe_cost.get(rid, 0) for rid, pid in recipe_pid.items()}

    iq = db.query(SaleItem).join(Sale, SaleItem.sale_id == Sale.id)
    if start is not None:
        iq = iq.filter(Sale.created_at >= start)
    cogs = 0.0
    covered_rev = 0.0
    for it in iq.all():
        if it.product_id in product_unit_cost:
            cogs += product_unit_cost[it.product_id] * float(it.quantity or 0)
            covered_rev += float(it.line_total or 0)
    gross = covered_rev - cogs
    margin = (gross / covered_rev * 100) if covered_rev > 0 else 0
    coverage = (covered_rev / vendido * 100) if vendido > 0 else 0
    products_total = db.query(func.count(Product.id)).filter(Product.active == True).scalar() or 0
    products_recipe = len(set(recipe_pid.values()))

    # Gastos operativos del período (salarios, alquiler, servicios, comisiones…)
    gq = db.query(Expense)
    if start is not None:
        gq = gq.filter(Expense.date >= start)
    gastos = sum(float(e.amount or 0) for e in gq.all())

    balance = vendido - comprado
    neta = vendido - comprado - gastos
    bar_max = max(vendido, comprado, merma, gastos, 1)

    return templates.TemplateResponse(
        "admin_rentabilidad.html",
        {
            "request": request,
            "active_range": rng,
            "vendido": _colon(vendido), "num_sales": num_sales,
            "comprado": _colon(comprado), "merma": _colon(merma),
            "inv_value": _colon(inv_value),
            "balance": _colon(balance), "balance_pos": balance >= 0,
            "gastos": _colon(gastos),
            "neta": _colon(neta), "neta_pos": neta >= 0,
            "cogs": _colon(cogs), "gross": _colon(gross),
            "margin": round(margin), "coverage": round(coverage),
            "has_cost": covered_rev > 0,
            "products_total": products_total, "products_recipe": products_recipe,
            "bar_vendido": round(vendido / bar_max * 100),
            "bar_comprado": round(comprado / bar_max * 100),
            "bar_merma": round(merma / bar_max * 100),
            "bar_gastos": round(gastos / bar_max * 100),
            "page_title": "Rentabilidad",
        },
    )


# ─── admin gastos del negocio (expenses) ──────────────────────────────────────

EXPENSE_CATEGORIES = [
    "Salarios", "Caja Costarricense", "Electricidad", "Agua", "Gas", "Internet",
    "Alquiler", "Limpieza", "Empaques", "SINPE", "Comisión tarjeta", "Banco",
    "Contador", "Otros",
]
EXPENSE_METHODS = ["efectivo", "tarjeta", "sinpe", "transferencia"]


def _month_bounds(month_str: str):
    now = cr_now()
    try:
        y, m = [int(x) for x in month_str.split("-")]
        start = datetime(y, m, 1)
    except Exception:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = datetime(start.year + 1, 1, 1) if start.month == 12 else datetime(start.year, start.month + 1, 1)
    return start, nxt


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except Exception:
        return cr_now().replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/admin/gastos")
def admin_gastos(request: Request, month: str = "", db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    start, nxt = _month_bounds(month)
    rows = (
        db.query(Expense)
        .filter(Expense.date >= start, Expense.date < nxt)
        .order_by(Expense.date.desc(), Expense.id.desc())
        .all()
    )
    by_cat = {}
    total = 0.0
    expenses = []
    for e in rows:
        by_cat[e.category] = by_cat.get(e.category, 0) + float(e.amount or 0)
        total += float(e.amount or 0)
        expenses.append({
            "id": e.id,
            "category": e.category,
            "description": e.description or "",
            "method": e.payment_method or "",
            "amount": float(e.amount or 0),
            "amount_fmt": _colon(e.amount or 0),
            "date": e.date.strftime("%d/%m/%Y") if e.date else "",
            "date_iso": e.date.strftime("%Y-%m-%d") if e.date else "",
        })
    cat_totals = [(c, _colon(v)) for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])]
    fixed = db.query(FixedExpense).order_by(FixedExpense.category.asc()).all()
    fixed_view = [{"id": f.id, "category": f.category, "description": f.description or "",
                   "amount_fmt": _colon(f.amount or 0), "active": f.active} for f in fixed]
    fixed_total = sum(float(f.amount or 0) for f in fixed if f.active)

    prev_m = (start - timedelta(days=1)).strftime("%Y-%m")
    next_m = nxt.strftime("%Y-%m")
    return templates.TemplateResponse(
        "admin_gastos.html",
        {
            "request": request,
            "expenses": expenses,
            "cat_totals": cat_totals,
            "total": _colon(total),
            "fixed": fixed_view,
            "fixed_total": _colon(fixed_total),
            "categories": EXPENSE_CATEGORIES,
            "methods": EXPENSE_METHODS,
            "month": start.strftime("%Y-%m"),
            "month_label": start.strftime("%m/%Y"),
            "prev_month": prev_m,
            "next_month": next_m,
            "page_title": "Gastos del negocio",
        },
    )


@router.post("/admin/gastos")
def create_expense(request: Request, category: str = Form(...), amount: str = Form(...),
                   date: str = Form(""), description: str = Form(""),
                   payment_method: str = Form(""), month: str = Form(""),
                   db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    if category in EXPENSE_CATEGORIES:
        try:
            amt = float(amount)
        except Exception:
            amt = 0
        db.add(Expense(
            category=category,
            description=(description.strip() or None),
            amount=amt,
            date=_parse_date(date),
            payment_method=(payment_method if payment_method in EXPENSE_METHODS else None),
        ))
        db.commit()
    return RedirectResponse(url=f"/admin/gastos?month={month or ''}", status_code=303)


@router.post("/admin/gastos/{expense_id}/edit")
def edit_expense(expense_id: int, request: Request, category: str = Form(...), amount: str = Form(...),
                 date: str = Form(""), description: str = Form(""), payment_method: str = Form(""),
                 month: str = Form(""), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    e = db.query(Expense).filter(Expense.id == expense_id).first()
    if e and category in EXPENSE_CATEGORIES:
        try:
            e.amount = float(amount)
        except Exception:
            pass
        e.category = category
        e.description = description.strip() or None
        e.date = _parse_date(date)
        e.payment_method = payment_method if payment_method in EXPENSE_METHODS else None
        db.commit()
    return RedirectResponse(url=f"/admin/gastos?month={month or ''}", status_code=303)


@router.post("/admin/gastos/{expense_id}/delete")
def delete_expense(expense_id: int, request: Request, month: str = Form(""), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    e = db.query(Expense).filter(Expense.id == expense_id).first()
    if e:
        db.delete(e)
        db.commit()
    return RedirectResponse(url=f"/admin/gastos?month={month or ''}", status_code=303)


@router.post("/admin/gastos/fijos")
def create_fixed(request: Request, category: str = Form(...), amount: str = Form(...),
                 description: str = Form(""), month: str = Form(""), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    if category in EXPENSE_CATEGORIES:
        try:
            amt = float(amount)
        except Exception:
            amt = 0
        db.add(FixedExpense(category=category, description=(description.strip() or None), amount=amt, active=True))
        db.commit()
    return RedirectResponse(url=f"/admin/gastos?month={month or ''}", status_code=303)


@router.post("/admin/gastos/fijos/{fixed_id}/delete")
def delete_fixed(fixed_id: int, request: Request, month: str = Form(""), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    f = db.query(FixedExpense).filter(FixedExpense.id == fixed_id).first()
    if f:
        db.delete(f)
        db.commit()
    return RedirectResponse(url=f"/admin/gastos?month={month or ''}", status_code=303)


@router.post("/admin/gastos/generar")
def generar_gastos_mes(request: Request, month: str = Form(""), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    start, nxt = _month_bounds(month)
    now = cr_now()
    # date for generated rows: today if generating current month, else 1st of month
    gen_date = now.replace(hour=0, minute=0, second=0, microsecond=0) if (start <= now < nxt) else start
    templates_active = db.query(FixedExpense).filter(FixedExpense.active == True).all()
    for f in templates_active:
        exists = (
            db.query(Expense.id)
            .filter(Expense.fixed_id == f.id, Expense.date >= start, Expense.date < nxt)
            .first()
        )
        if exists:
            continue
        db.add(Expense(category=f.category, description=f.description, amount=f.amount,
                       date=gen_date, payment_method=None, fixed_id=f.id))
    db.commit()
    return RedirectResponse(url=f"/admin/gastos?month={start.strftime('%Y-%m')}", status_code=303)


@router.get("/admin/gastos/export.csv")
def export_gastos(request: Request, month: str = "", db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    import csv
    start, nxt = _month_bounds(month)
    rows = db.query(Expense).filter(Expense.date >= start, Expense.date < nxt).order_by(Expense.date.asc()).all()
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fecha", "categoria", "descripcion", "metodo", "monto"])
    for e in rows:
        w.writerow([
            e.date.strftime("%Y-%m-%d") if e.date else "",
            e.category, e.description or "", e.payment_method or "", round(e.amount or 0),
        ])
    buf.seek(0)
    return StreamingResponse(
        _io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=gastos-{start.strftime('%Y-%m')}.csv"},
    )


# ─── admin compras (purchases / recepción) ────────────────────────────────────

@router.get("/admin/compras")
def admin_compras(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    ings = db.query(Ingredient).order_by(Ingredient.category.asc(), Ingredient.name.asc()).all()
    ingredients = [{
        "id": i.id, "name": i.name, "unit": i.unit or "unid",
        "pack_content": i.pack_content, "purchase_price": i.purchase_price,
        "purchase_unit": i.purchase_unit or "", "category": i.category or "",
    } for i in ings]
    purchases = db.query(Purchase).order_by(Purchase.date.desc(), Purchase.id.desc()).limit(50).all()
    pv = []
    for p in purchases:
        pv.append({
            "id": p.id,
            "date": p.date.strftime("%d/%m/%Y") if p.date else "",
            "supplier": p.supplier or "—",
            "total": _colon(p.total or 0),
            "lines": [{
                "name": it.ingredient_name or "",
                "qty": (int(it.qty) if it.qty == int(it.qty) else it.qty),
                "unit_price": _colon(it.unit_price or 0),
                "line_total": _colon(it.line_total or 0),
            } for it in p.items],
        })
    return templates.TemplateResponse(
        "admin_compras.html",
        {"request": request, "ingredients": ingredients, "purchases": pv,
         "today": cr_now().strftime("%Y-%m-%d"), "page_title": "Compras"},
    )


class PurchaseItemIn(BaseModel):
    ingredient_id: int
    qty: float
    unit_price: float


class PurchaseIn(BaseModel):
    supplier: str | None = None
    date: str | None = None
    notes: str | None = None
    items: list[PurchaseItemIn]


@router.post("/admin/compras")
def create_purchase(payload: PurchaseIn, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    valid = [it for it in payload.items if it.qty and it.qty > 0]
    if not valid:
        raise HTTPException(400, "Agrega al menos una línea con cantidad")
    pdate = _parse_date(payload.date) if payload.date else cr_now()
    supplier = (payload.supplier.strip() if payload.supplier else None) or None

    purchase = Purchase(supplier=supplier, date=pdate,
                        notes=(payload.notes.strip() if payload.notes else None), total=0)
    db.add(purchase)
    db.flush()  # get purchase.id

    total = 0.0
    for it in valid:
        ing = db.query(Ingredient).filter(Ingredient.id == it.ingredient_id).first()
        if not ing:
            continue
        qty = float(it.qty or 0)
        unit_price = float(it.unit_price or 0)
        pc = float(ing.pack_content) if ing.pack_content else 1.0
        base_units = qty * pc
        receipt_unit_cost = (unit_price / pc) if pc > 0 else unit_price
        line_total = qty * unit_price
        total += line_total

        # Weighted-average cost BEFORE adding the received stock.
        old_stock = float(ing.stock or 0)
        old_cost = float(ing.cost_per_unit or 0)
        denom = old_stock + base_units
        new_cost = ((old_stock * old_cost + base_units * receipt_unit_cost) / denom) if denom > 0 else receipt_unit_cost

        create_inventory_movement(db, ing.id, "in", base_units, reference=f"compra:{purchase.id}", commit=False)
        ing.cost_per_unit = round(new_cost, 4)
        ing.purchase_price = unit_price
        ing.last_purchase_date = pdate
        if supplier:
            ing.supplier = supplier

        db.add(PurchaseItem(
            purchase_id=purchase.id, ingredient_id=ing.id, ingredient_name=ing.name,
            qty=qty, unit_price=unit_price, pack_content=ing.pack_content,
            base_units=base_units, line_total=line_total,
        ))

    purchase.total = total
    db.commit()
    return {"ok": True, "id": purchase.id}


# ─── admin leads / contact inbox ──────────────────────────────────────────────

_LEAD_STATUSES = ["nuevo", "leido", "contactado", "archivado"]


@router.get("/admin/leads")
def admin_leads(request: Request, status: str = "", db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    from sqlalchemy import func

    q = db.query(ContactMessage)
    if status in _LEAD_STATUSES:
        q = q.filter(ContactMessage.status == status)
    leads = q.order_by(ContactMessage.created_at.desc()).limit(500).all()

    counts = dict(
        db.query(ContactMessage.status, func.count(ContactMessage.id))
        .group_by(ContactMessage.status)
        .all()
    )
    counts["all"] = sum(counts.get(s, 0) for s in _LEAD_STATUSES)
    return templates.TemplateResponse(
        "admin_leads.html",
        {
            "request": request,
            "leads": leads,
            "counts": counts,
            "active_status": status if status in _LEAD_STATUSES else "",
            "statuses": _LEAD_STATUSES,
            "page_title": "Contactos",
        },
    )


@router.post("/admin/leads/{lead_id}/status")
def admin_lead_status(lead_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    if status not in _LEAD_STATUSES:
        raise HTTPException(400, "Estado inválido")
    lead = db.query(ContactMessage).filter(ContactMessage.id == lead_id).first()
    if not lead:
        raise HTTPException(404, "Lead no encontrado")
    lead.status = status
    db.commit()
    return {"ok": True, "id": lead_id, "status": status}


@router.post("/admin/leads/{lead_id}/delete")
def admin_lead_delete(lead_id: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    lead = db.query(ContactMessage).filter(ContactMessage.id == lead_id).first()
    if lead:
        db.delete(lead)
        db.commit()
    return {"ok": True, "id": lead_id}


@router.get("/admin/leads/export.csv")
def admin_leads_export(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    import csv
    leads = db.query(ContactMessage).order_by(ContactMessage.created_at.desc()).all()
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "fecha", "nombre", "restaurante", "email", "telefono",
                "sucursales", "usa_hoy", "estado", "idioma", "mensaje"])
    for l in leads:
        w.writerow([
            l.id,
            l.created_at.strftime("%Y-%m-%d %H:%M") if l.created_at else "",
            l.name, l.restaurant or "", l.email, l.phone or "",
            l.locations or "", l.current_system or "", l.status, l.lang or "",
            (l.message or "").replace("\n", " "),
        ])
    buf.seek(0)
    return StreamingResponse(
        _io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contactos.csv"},
    )


# ─── admin access log ─────────────────────────────────────────────────────────

_ACCESS_ROLES = ["admin", "station", "kitchen", "inventory", "pos"]
_ACCESS_ROLE_LABELS = {
    "admin": "Admin", "station": "Salón", "kitchen": "Cocina",
    "inventory": "Inventario", "pos": "Punto de Venta",
}


@router.get("/admin/access-log")
def admin_access_log(request: Request, role: str = "", db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    from sqlalchemy import func

    q = db.query(AccessLog)
    if role in _ACCESS_ROLES:
        q = q.filter(AccessLog.role == role)
    rows = q.order_by(AccessLog.created_at.desc()).limit(500).all()

    counts = dict(
        db.query(AccessLog.role, func.count(AccessLog.id)).group_by(AccessLog.role).all()
    )
    counts["all"] = sum(counts.get(r, 0) for r in _ACCESS_ROLES)
    return templates.TemplateResponse(
        "admin_access_log.html",
        {
            "request": request,
            "rows": rows,
            "counts": counts,
            "active_role": role if role in _ACCESS_ROLES else "",
            "roles": _ACCESS_ROLES,
            "role_labels": _ACCESS_ROLE_LABELS,
            "page_title": "Accesos",
        },
    )


@router.get("/admin/access-log/export.csv")
def admin_access_log_export(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    import csv
    rows = db.query(AccessLog).order_by(AccessLog.created_at.desc()).all()
    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "fecha", "modulo", "usuario", "ip"])
    for r in rows:
        w.writerow([
            r.id,
            r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
            _ACCESS_ROLE_LABELS.get(r.role, r.role),
            r.actor_name or "",
            r.ip or "",
        ])
    buf.seek(0)
    return StreamingResponse(
        _io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=accesos.csv"},
    )


# ─── admin time clock ─────────────────────────────────────────────────────────

def _fmt_hm(seconds: float) -> str:
    m = int(max(0, seconds) // 60)
    return f"{m // 60}h {m % 60:02d}m"


def _payroll_hours(seconds: float) -> float:
    """Decimal hours rounded to the nearest quarter hour (payroll standard)."""
    return round((max(0, seconds) / 3600.0) * 4) / 4


def _clock_range_start(rng: str):
    now = cr_now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if rng == "week":
        return today - timedelta(days=today.weekday())  # Monday of this week
    if rng == "biweekly":
        # Payroll fortnight: 1st–15th, then 16th–end of month.
        return today.replace(day=1) if today.day <= 15 else today.replace(day=16)
    if rng == "all":
        return None
    return today  # default: today


def _parse_clock_dt(date_str: str, time_str: str):
    return datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y-%m-%d %H:%M")


_CLOCK_RANGES = ("today", "week", "biweekly", "all")


@router.get("/admin/clock")
def admin_clock(request: Request, range: str = "biweekly", waiter: int = 0, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    auto_close_stale_sessions(db)

    rng = range if range in _CLOCK_RANGES else "biweekly"
    start = _clock_range_start(rng)
    now = cr_now()

    q = db.query(WorkSession)
    if start is not None:
        q = q.filter(WorkSession.clock_in >= start)
    if waiter:
        q = q.filter(WorkSession.waiter_id == waiter)
    sessions = q.order_by(WorkSession.clock_in.desc()).all()

    users = {}
    working_now = 0
    for s in sessions:
        name = s.actor_name or "—"
        u = users.setdefault(name, {"name": name, "rows": [], "total_seconds": 0, "working": False})
        end = s.clock_out or now
        secs = max(0, (end - s.clock_in).total_seconds())
        is_open = s.clock_out is None
        u["rows"].append({
            "id": s.id,
            "role_label": CLOCK_ROLE_LABELS.get(s.role, s.role),
            "role": s.role,
            "date": s.clock_in.strftime("%d/%m/%Y"),
            "date_iso": s.clock_in.strftime("%Y-%m-%d"),
            "in": s.clock_in.strftime("%H:%M"),
            "out": ("—" if is_open else s.clock_out.strftime("%H:%M")),
            "out_hhmm": ("" if is_open else s.clock_out.strftime("%H:%M")),
            "hours": _fmt_hm(secs),
            "open": is_open,
            "auto": s.auto_closed,
            "edited": s.edited,
        })
        u["total_seconds"] += secs
        if is_open:
            u["working"] = True
    for u in users.values():
        u["total"] = _fmt_hm(u["total_seconds"])
        u["payroll"] = f"{_payroll_hours(u['total_seconds']):.2f}"
        if u["working"]:
            working_now += 1

    users_list = sorted(users.values(), key=lambda x: x["name"].lower())
    grand_seconds = sum(u["total_seconds"] for u in users_list)
    waiters = db.query(Waiter).order_by(Waiter.name.asc()).all()
    return templates.TemplateResponse(
        "admin_clock.html",
        {
            "request": request,
            "users": users_list,
            "active_range": rng,
            "active_waiter": waiter,
            "waiters": waiters,
            "roles": CLOCK_ROLES,
            "role_labels": CLOCK_ROLE_LABELS,
            "working_now": working_now,
            "grand_total": _fmt_hm(grand_seconds),
            "grand_payroll": f"{_payroll_hours(grand_seconds):.2f}",
            "page_title": "Reloj",
        },
    )


# ─── time clock manual corrections ────────────────────────────────────────────

@router.post("/admin/clock/session")
def admin_clock_create(
    request: Request,
    waiter_id: int = Form(...),
    role: str = Form(...),
    date: str = Form(...),
    in_time: str = Form(...),
    out_time: str = Form(""),
    db: Session = Depends(get_db),
):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    if role not in CLOCK_ROLES:
        raise HTTPException(400, "Módulo inválido")
    w = db.query(Waiter).filter(Waiter.id == waiter_id).first()
    if not w:
        raise HTTPException(400, "Empleado no encontrado")
    try:
        ci = _parse_clock_dt(date, in_time)
        co = _parse_clock_dt(date, out_time) if out_time.strip() else None
    except ValueError:
        raise HTTPException(400, "Fecha u hora inválida")
    if co and co < ci:
        raise HTTPException(400, "La salida no puede ser antes de la entrada")
    db.add(WorkSession(waiter_id=w.id, actor_name=w.name, role=role, clock_in=ci, clock_out=co, edited=True))
    db.commit()
    return {"ok": True}


@router.post("/admin/clock/session/{sid}")
def admin_clock_update(
    sid: int,
    request: Request,
    date: str = Form(...),
    in_time: str = Form(...),
    out_time: str = Form(""),
    db: Session = Depends(get_db),
):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    s = db.query(WorkSession).filter(WorkSession.id == sid).first()
    if not s:
        raise HTTPException(404, "Turno no encontrado")
    try:
        ci = _parse_clock_dt(date, in_time)
        co = _parse_clock_dt(date, out_time) if out_time.strip() else None
    except ValueError:
        raise HTTPException(400, "Fecha u hora inválida")
    if co and co < ci:
        raise HTTPException(400, "La salida no puede ser antes de la entrada")
    s.clock_in = ci
    s.clock_out = co
    s.auto_closed = False
    s.edited = True
    db.commit()
    return {"ok": True}


@router.post("/admin/clock/session/{sid}/close")
def admin_clock_close(sid: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    s = db.query(WorkSession).filter(WorkSession.id == sid).first()
    if not s:
        raise HTTPException(404, "Turno no encontrado")
    if s.clock_out is None:
        s.clock_out = cr_now()
        s.edited = True
        db.commit()
    return {"ok": True}


@router.post("/admin/clock/session/{sid}/delete")
def admin_clock_delete(sid: int, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    s = db.query(WorkSession).filter(WorkSession.id == sid).first()
    if s:
        db.delete(s)
        db.commit()
    return {"ok": True}


@router.get("/admin/clock/export.csv")
def admin_clock_export(request: Request, range: str = "all", waiter: int = 0, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    import csv
    auto_close_stale_sessions(db)
    rng = range if range in _CLOCK_RANGES else "all"
    start = _clock_range_start(rng)
    now = cr_now()
    q = db.query(WorkSession)
    if start is not None:
        q = q.filter(WorkSession.clock_in >= start)
    if waiter:
        q = q.filter(WorkSession.waiter_id == waiter)
    sessions = q.order_by(WorkSession.actor_name.asc(), WorkSession.clock_in.asc()).all()

    buf = _io.StringIO()
    w = csv.writer(buf)
    w.writerow(["usuario", "modulo", "fecha", "entrada", "salida", "horas", "horas_nomina", "estado"])
    for s in sessions:
        end = s.clock_out or now
        secs = max(0, (end - s.clock_in).total_seconds())
        w.writerow([
            s.actor_name or "",
            CLOCK_ROLE_LABELS.get(s.role, s.role),
            s.clock_in.strftime("%Y-%m-%d"),
            s.clock_in.strftime("%H:%M"),
            (s.clock_out.strftime("%H:%M") if s.clock_out else "ABIERTO"),
            _fmt_hm(secs),
            f"{_payroll_hours(secs):.2f}",
            (("auto-cerrado" if s.auto_closed else ("abierto" if s.clock_out is None else "cerrado"))
             + (" · manual" if s.edited else "")),
        ])
    buf.seek(0)
    return StreamingResponse(
        _io.BytesIO(buf.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reloj.csv"},
    )


# ─── cuestionario fácil (full-screen slide inventory) ─────────────────────────

@router.get("/cuestionario")
def cuestionario_page(request: Request, gmonth: str = "", db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    ingredients = db.query(Ingredient).order_by(Ingredient.name.asc()).all()
    insumos = [
        {"id": i.id, "name": i.name, "unit": i.unit or "unid", "stock": round(i.stock or 0, 2)}
        for i in ingredients
    ]
    products = db.query(Product).filter(Product.active == True).order_by(
        Product.display_order.asc(), Product.name.asc()
    ).all()
    inv_map = {inv.product_id: inv for inv in db.query(Inventory).all()}
    productos = [
        {"id": p.id, "name": p.name, "unit": "unid",
         "stock": round((inv_map.get(p.id).quantity if inv_map.get(p.id) else 0), 2)}
        for p in products
    ]
    # Gastos flow: current questionnaire amount per category for the month
    gm_start, gm_nxt = _month_bounds(gmonth)
    gcur = {}
    for e in db.query(Expense).filter(
        Expense.source == "cuestionario", Expense.date >= gm_start, Expense.date < gm_nxt
    ).all():
        gcur[e.category] = float(e.amount or 0)
    gastos = [{"category": c, "current": round(gcur.get(c, 0))} for c in EXPENSE_CATEGORIES]
    return templates.TemplateResponse(
        "cuestionario.html",
        {
            "request": request, "insumos": insumos, "productos": productos,
            "gastos": gastos, "gmonth": gm_start.strftime("%Y-%m"),
            "gmonth_label": gm_start.strftime("%m/%Y"),
            "page_title": "Cuestionario Fácil",
        },
    )


class GastoQuizIn(BaseModel):
    category: str
    month: str
    amount: float


@router.post("/admin/gastos/quiz/apply")
def gastos_quiz_apply(payload: GastoQuizIn, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    if payload.category not in EXPENSE_CATEGORIES:
        raise HTTPException(400, "Categoría inválida")
    start, nxt = _month_bounds(payload.month)
    now = cr_now()
    gen_date = now.replace(hour=0, minute=0, second=0, microsecond=0) if (start <= now < nxt) else start
    e = (
        db.query(Expense)
        .filter(Expense.category == payload.category, Expense.source == "cuestionario",
                Expense.date >= start, Expense.date < nxt)
        .first()
    )
    amt = float(payload.amount or 0)
    if amt <= 0:
        if e:
            db.delete(e)
            db.commit()
        return {"ok": True, "amount": 0}
    if e:
        e.amount = amt
    else:
        db.add(Expense(category=payload.category, amount=amt, date=gen_date, source="cuestionario"))
    db.commit()
    return {"ok": True, "amount": round(amt)}


class QuizApply(BaseModel):
    target: str   # insumo | producto
    id: int
    mode: str     # conteo | compra | merma
    value: float
    reference: str | None = None


@router.post("/admin/inv/quiz/apply")
def cuestionario_apply(payload: QuizApply, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    if payload.target not in ("insumo", "producto"):
        raise HTTPException(400, "Objetivo inválido")
    if payload.mode not in ("conteo", "compra", "merma"):
        raise HTTPException(400, "Modo inválido")
    value = float(payload.value or 0)
    ref = payload.reference or f"cuestionario:{cr_now().strftime('%Y-%m-%d')}"

    if payload.target == "insumo":
        ing = db.query(Ingredient).filter(Ingredient.id == payload.id).first()
        if not ing:
            raise HTTPException(404, "Insumo no encontrado")
        if payload.mode == "conteo":
            delta = value - float(ing.stock or 0)
            if delta != 0:
                create_inventory_movement(db, ing.id, "adjustment", delta, reference=ref)
        elif payload.mode == "compra":
            if value > 0:
                create_inventory_movement(db, ing.id, "in", value, reference=ref)
        else:  # merma
            if value > 0:
                create_inventory_movement(db, ing.id, "waste", value, reference=ref)
        db.refresh(ing)
        return {"ok": True, "new_stock": round(ing.stock or 0, 2)}

    # producto — product-level Inventory + InventoryLog
    product = db.query(Product).filter(Product.id == payload.id).first()
    if not product:
        raise HTTPException(404, "Producto no encontrado")
    inv = db.query(Inventory).filter(Inventory.product_id == product.id).first()
    if not inv:
        inv = Inventory(product_id=product.id, quantity=0)
        db.add(inv)
        db.flush()
    old = float(inv.quantity or 0)
    if payload.mode == "conteo":
        new = value
    elif payload.mode == "compra":
        new = old + value
    else:  # merma
        new = old - value
    inv.quantity = new
    db.add(InventoryLog(product_id=product.id, old_quantity=old, new_quantity=new, actor_name="Cuestionario"))
    db.commit()
    return {"ok": True, "new_stock": round(new, 2)}


# ─── general inventory (shared login) ─────────────────────────────────────────

def require_inventory_user(request: Request):
    uid = request.session.get("inv_user_id")
    uname = request.session.get("inv_user_name")
    if uid and uname:
        return uid, uname
    return None


@router.get("/inventory/login")
def inventory_login_page(request: Request):
    if require_inventory_user(request):
        return RedirectResponse(url="/inventory")
    return templates.TemplateResponse(
        "inventory_login.html",
        {"request": request, "page_title": "Inventario – Login"},
    )


@router.post("/inventory/login")
def inventory_login_submit(request: Request, pin: str = Form(...), db: Session = Depends(get_db)):
    waiter = db.query(Waiter).filter(Waiter.pin == pin.strip(), Waiter.active == True).first()
    if not waiter:
        return templates.TemplateResponse(
            "inventory_login.html",
            {"request": request, "page_title": "Inventario – Login", "error": "Código incorrecto"},
            status_code=401,
        )
    request.session["inv_user_id"] = waiter.id
    request.session["inv_user_name"] = waiter.name
    record_access(db, request, "inventory", waiter.name, waiter.id)
    clock_in(db, "inventory", waiter.name, waiter.id)
    return RedirectResponse(url="/inventory", status_code=303)


@router.get("/inventory/logout")
def inventory_logout(request: Request, db: Session = Depends(get_db)):
    wid = request.session.get("inv_user_id")
    if wid:
        clock_out(db, "inventory", wid)
    request.session.pop("inv_user_id", None)
    request.session.pop("inv_user_name", None)
    return RedirectResponse(url="/inventory/login")


@router.get("/inventory")
def inventory_dashboard(request: Request, db: Session = Depends(get_db)):
    u = require_inventory_user(request)
    if not u:
        return RedirectResponse(url="/inventory/login")
    _, uname = u
    products = db.query(Product).filter(Product.active == True).order_by(Product.display_order.asc(), Product.name.asc()).all()
    inv_map = {inv.product_id: inv for inv in db.query(Inventory).all()}
    items = []
    for p in products:
        inv = inv_map.get(p.id)
        items.append({
            "product_id": p.id,
            "name": p.name,
            "quantity": inv.quantity if inv else 0,
            "updated_at": inv.updated_at if inv else None,
        })
    logs = (
        db.query(InventoryLog)
        .options(joinedload(InventoryLog.product))
        .order_by(InventoryLog.created_at.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse(
        "inventory.html",
        {"request": request, "items": items, "logs": logs, "user_name": uname, "page_title": "Inventario"},
    )


@router.post("/inventory/{product_id}")
def inventory_update(product_id: int, request: Request, quantity: float = Form(...), db: Session = Depends(get_db)):
    u = require_inventory_user(request)
    if not u:
        return RedirectResponse(url="/inventory/login")
    _, uname = u
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse(url="/inventory", status_code=303)
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    old_qty = inv.quantity if inv else 0
    new_qty = max(0, quantity)
    if inv:
        inv.quantity = new_qty
    else:
        inv = Inventory(product_id=product_id, quantity=new_qty)
        db.add(inv)
    db.add(InventoryLog(product_id=product_id, old_quantity=old_qty, new_quantity=new_qty, actor_name=uname))
    db.commit()
    return RedirectResponse(url="/inventory", status_code=303)


# ─── admin POS settings ───────────────────────────────────────────────────────

@router.get("/admin/pos-settings")
def admin_pos_settings(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    settings = db.query(AudioSettings).first()
    return templates.TemplateResponse(
        "admin_pos_settings.html",
        {"request": request, "settings": settings, "page_title": "POS – Configuración"},
    )


@router.post("/admin/pos-settings")
def update_pos_settings(request: Request, tax_rate: float = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    settings = db.query(AudioSettings).first()
    settings.tax_rate = max(0, min(tax_rate, 100))
    db.commit()
    return RedirectResponse(url="/admin/pos-settings", status_code=303)


# ─── POS (Punto de Venta) ─────────────────────────────────────────────────────

def require_pos_user(request: Request):
    uid = request.session.get("pos_user_id")
    uname = request.session.get("pos_user_name")
    if uid and uname:
        return uid, uname
    return None


@router.get("/pos/login")
def pos_login_page(request: Request):
    if require_pos_user(request):
        return RedirectResponse(url="/pos")
    return templates.TemplateResponse(
        "pos_login.html",
        {"request": request, "page_title": "Punto de Venta – Login"},
    )


@router.post("/pos/login")
def pos_login_submit(request: Request, pin: str = Form(...), db: Session = Depends(get_db)):
    waiter = db.query(Waiter).filter(Waiter.pin == pin.strip(), Waiter.active == True).first()
    if not waiter:
        return templates.TemplateResponse(
            "pos_login.html",
            {"request": request, "page_title": "Punto de Venta – Login", "error": "Código incorrecto"},
            status_code=401,
        )
    request.session["pos_user_id"] = waiter.id
    request.session["pos_user_name"] = waiter.name
    record_access(db, request, "pos", waiter.name, waiter.id)
    clock_in(db, "pos", waiter.name, waiter.id)
    return RedirectResponse(url="/pos", status_code=303)


@router.get("/pos/logout")
def pos_logout(request: Request, db: Session = Depends(get_db)):
    wid = request.session.get("pos_user_id")
    if wid:
        clock_out(db, "pos", wid)
    request.session.pop("pos_user_id", None)
    request.session.pop("pos_user_name", None)
    return RedirectResponse(url="/pos/login")


@router.get("/pos")
def pos_dashboard(request: Request, db: Session = Depends(get_db)):
    u = require_pos_user(request)
    if not u:
        return RedirectResponse(url="/pos/login")
    _, uname = u
    products = db.query(Product).filter(Product.active == True).order_by(Product.display_order.asc(), Product.name.asc()).all()
    settings = db.query(AudioSettings).first()
    tax_rate = settings.tax_rate if settings and settings.tax_rate is not None else 0
    return templates.TemplateResponse(
        "pos.html",
        {"request": request, "products": products, "user_name": uname, "tax_rate": tax_rate, "page_title": "Punto de Venta"},
    )


# ─── admin reset endpoints ────────────────────────────────────────────────────


@router.post("/admin/reset/products")
def reset_products(request: Request, confirm: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return JSONResponse(status_code=403, content={"detail": "No autorizado"})
    if confirm != "RESET":
        return JSONResponse(status_code=400, content={"detail": "Confirmación inválida"})
    try:
        inv_count = db.query(Inventory).count()
        db.query(Inventory).delete()
        prod_count = db.query(Product).count()
        db.query(Product).delete()
        db.commit()
        return {"status": "ok", "deleted": prod_count + inv_count}
    except Exception:
        db.rollback()
        raise


@router.post("/admin/reset/orders")
def reset_orders(request: Request, confirm: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return JSONResponse(status_code=403, content={"detail": "No autorizado"})
    if confirm != "RESET":
        return JSONResponse(status_code=400, content={"detail": "Confirmación inválida"})
    try:
        db.query(OrderItem).delete()
        from ..models import OrderEvent
        db.query(OrderEvent).delete()
        count = db.query(Order).count()
        db.query(Order).delete()
        db.commit()
        return {"status": "ok", "deleted": count}
    except Exception:
        db.rollback()
        raise


@router.post("/admin/reset/logs")
def reset_logs(request: Request, confirm: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return JSONResponse(status_code=403, content={"detail": "No autorizado"})
    if confirm != "RESET":
        return JSONResponse(status_code=400, content={"detail": "Confirmación inválida"})
    try:
        count = db.query(InventoryLog).count()
        db.query(InventoryLog).delete()
        db.commit()
        return {"status": "ok", "deleted": count}
    except Exception:
        db.rollback()
        raise


@router.post("/admin/reset/inventory")
def reset_inventory(request: Request, confirm: str = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return JSONResponse(status_code=403, content={"detail": "No autorizado"})
    if confirm != "RESET":
        return JSONResponse(status_code=400, content={"detail": "Confirmación inválida"})
    try:
        count = db.query(Inventory).filter(Inventory.quantity != 0).count()
        db.query(Inventory).update({"quantity": 0})
        db.commit()
        return {"status": "ok", "deleted": count}
    except Exception:
        db.rollback()
        raise


# ─── admin order history ──────────────────────────────────────────────────────

def _parse_int(val):
    try:
        return int(val) if val else None
    except (ValueError, TypeError):
        return None


def _parse_float(val):
    try:
        return float(val) if val else None
    except (ValueError, TypeError):
        return None


def _build_filters(request: Request) -> OrderHistoryFilters:
    p = request.query_params
    return OrderHistoryFilters(
        date_from=p.get("date_from"),
        date_to=p.get("date_to"),
        status=p.get("status"),
        source_role=p.get("source_role"),
        waiter_name=p.get("waiter_name"),
        product_id=_parse_int(p.get("product_id")),
        payment_method=p.get("payment_method"),
        min_total=_parse_float(p.get("min_total")),
        max_total=_parse_float(p.get("max_total")),
    )


@router.get("/admin/orders/history")
def orders_history(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    page = max(1, _parse_int(request.query_params.get("page")) or 1)
    per_page = 50
    filters = _build_filters(request)
    orders, total, tax_rate = get_order_history(db, filters, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()

    # Build query string without page for helpers
    base_params = {k: v for k, v in request.query_params.items() if k != "page"}

    def _qs(extra: dict) -> str:
        merged = {**base_params, **extra}
        return "&".join(f"{k}={v}" for k, v in merged.items() if v)

    def page_url(p: int) -> str:
        return f"/admin/orders/history?{_qs({'page': p})}"

    def export_url(fmt: str) -> str:
        return f"/admin/orders/history/export/{fmt}?{_qs({})}"

    return templates.TemplateResponse("admin_orders_history.html", {
        "request": request,
        "orders": orders,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "tax_rate": tax_rate * 100,
        "products": products,
        "filters": filters,
        "params": dict(request.query_params),
        "page_url": page_url,
        "export_url": export_url,
        "page_title": "Historial de Órdenes",
    })


@router.get("/admin/orders/history/export/csv")
def orders_export_csv(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    filters = _build_filters(request)
    orders, _ = get_all_for_export(db, filters)
    data = export_csv(orders)
    return StreamingResponse(
        _io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ordenes.csv"},
    )


@router.get("/admin/orders/history/export/excel")
def orders_export_excel(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    filters = _build_filters(request)
    orders, _ = get_all_for_export(db, filters)
    data = export_excel(orders)
    return StreamingResponse(
        _io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ordenes.xlsx"},
    )


@router.get("/admin/orders/history/export/pdf")
def orders_export_pdf(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    filters = _build_filters(request)
    orders, tax_rate = get_all_for_export(db, filters)
    data = export_pdf(orders, filters, tax_rate)
    return StreamingResponse(
        _io.BytesIO(data),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ordenes.pdf"},
    )


# ─── admin inventario (ingredient-level UI, senior-friendly) ─────────────────

@router.get("/admin/inventario")
def admin_inventario_page(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()
    return templates.TemplateResponse(
        "admin_inventario.html",
        {
            "request": request,
            "page_title": "Inventario (Insumos)",
            "products": products,
        },
    )

