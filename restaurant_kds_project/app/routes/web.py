import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from pathlib import Path
import shutil

from ..database import get_db, DATA_DIR
from ..models import Product, Order, OrderItem, AudioSettings, Waiter, Inventory, InventoryLog, Sale, SaleItem
from ..utils import duration_seconds

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


# ─── root ────────────────────────────────────────────────────────────────────

@router.get("/")
def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "page_title": "Listo Restaurant Software"})


# ─── admin login ─────────────────────────────────────────────────────────────

@router.get("/admin/login")
def admin_login_page(request: Request):
    if require_admin(request):
        return RedirectResponse(url="/admin")
    return templates.TemplateResponse("admin_login.html", {"request": request, "page_title": "Admin Login"})


@router.post("/admin/login")
def admin_login_submit(request: Request, email: str = Form(...), passcode: str = Form(...)):
    if email.strip() == ADMIN_EMAIL and passcode == ADMIN_PASSCODE:
        request.session["admin_logged_in"] = True
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
    return RedirectResponse(url="/station-a/dashboard", status_code=303)


@router.get("/station-a/logout")
def station_logout(request: Request):
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
    return templates.TemplateResponse(
        "station.html",
        {
            "request": request,
            "products": products,
            "source_role": "station_a",
            "page_title": "Salon",
            "waiter_name": waiter_name,
            "waiter_id": waiter_id,
            "settings": settings,
        },
    )


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
    return RedirectResponse(url="/kitchen/dashboard", status_code=303)


@router.get("/kitchen/logout")
def kitchen_logout(request: Request):
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
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    orders_today = db.query(Order).filter(Order.created_at >= today_start).all()
    orders_yesterday = db.query(Order).filter(Order.created_at >= yesterday_start, Order.created_at < today_start).all()

    def avg_duration(orders):
        values = [duration_seconds(o) for o in orders if duration_seconds(o) is not None]
        return round(sum(values) / len(values) / 60, 1) if values else 0

    stats = {
        "orders_today": len(orders_today),
        "orders_yesterday": len(orders_yesterday),
        "avg_today": avg_duration(orders_today),
        "avg_yesterday": avg_duration(orders_yesterday),
        "cancelled_today": len([o for o in orders_today if o.was_cancelled]),
        "active_now": len([o for o in orders_today if o.status in ["nuevo", "aceptado", "preparando", "listo"]]),
    }
    recent_orders = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .order_by(Order.created_at.desc())
        .limit(25)
        .all()
    )
    return templates.TemplateResponse(
        "admin.html",
        {"request": request, "stats": stats, "orders": recent_orders, "duration_seconds": duration_seconds, "page_title": "Admin"},
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


@router.get("/admin/products")
def admin_products(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    products = db.query(Product).order_by(Product.display_order.asc(), Product.name.asc()).all()
    return templates.TemplateResponse("admin_products.html", {"request": request, "products": products, "page_title": "Admin Products"})


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


@router.get("/admin/audio")
def admin_audio(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    settings = db.query(AudioSettings).first()
    return templates.TemplateResponse("admin_audio.html", {"request": request, "settings": settings, "page_title": "Admin Audio"})


@router.post("/admin/audio")
def update_audio(
    request: Request,
    station_sound: UploadFile | None = File(None),
    kitchen_sound: UploadFile | None = File(None),
    ready_sound: UploadFile | None = File(None),
    cancel_sound: UploadFile | None = File(None),
    master_volume: float = Form(1.0),
    voice_enabled_for_station_orders: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    settings = db.query(AudioSettings).first()

    def save_upload(upload: UploadFile | None, current_value: str | None):
        if not upload or not upload.filename:
            return current_value
        safe_name = Path(upload.filename).name
        ext = Path(safe_name).suffix.lower()
        if ext not in {".mp3", ".wav", ".m4a"}:
            return current_value
        dest = UPLOAD_DIR / safe_name
        with dest.open("wb") as f:
            shutil.copyfileobj(upload.file, f)
        return f"/uploads/audio/{safe_name}"

    settings.station_order_sound_path = save_upload(station_sound, settings.station_order_sound_path)
    settings.kitchen_order_sound_path = save_upload(kitchen_sound, settings.kitchen_order_sound_path)
    settings.ready_sound_path = save_upload(ready_sound, settings.ready_sound_path)
    settings.cancel_sound_path = save_upload(cancel_sound, settings.cancel_sound_path)
    settings.master_volume = max(0, min(master_volume, 1))
    settings.voice_enabled_for_station_orders = voice_enabled_for_station_orders == "on"
    db.commit()
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
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=6)

    def consumption(since: datetime):
        rows = (
            db.query(Product.id, Product.name, OrderItem.quantity)
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(Order.dispatched_at != None)
            .filter(Order.dispatched_at >= since)
            .all()
        )
        agg = {}
        for pid, pname, qty in rows:
            if pid not in agg:
                agg[pid] = {"product_id": pid, "name": pname, "total": 0}
            agg[pid]["total"] += qty
        return sorted(agg.values(), key=lambda x: x["total"], reverse=True)

    daily = consumption(today_start)
    weekly = consumption(week_start)

    inv_map = {inv.product_id: inv.quantity for inv in db.query(Inventory).all()}
    products = db.query(Product).filter(Product.active == True).order_by(Product.name.asc()).all()
    stock = [{"name": p.name, "quantity": inv_map.get(p.id, 0)} for p in products]

    return templates.TemplateResponse(
        "admin_reports.html",
        {
            "request": request,
            "daily": daily,
            "weekly": weekly,
            "stock": stock,
            "today_label": today_start.strftime("%Y-%m-%d"),
            "week_label": f"{week_start.strftime('%Y-%m-%d')} → {today_start.strftime('%Y-%m-%d')}",
            "page_title": "Reportes",
        },
    )


# ─── admin inventory ──────────────────────────────────────────────────────────

@router.get("/admin/inventory")
def admin_inventory(request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
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
        "admin_inventory.html",
        {"request": request, "items": items, "logs": logs, "page_title": "Inventario"},
    )


@router.post("/admin/inventory/{product_id}")
def update_inventory(product_id: int, request: Request, quantity: float = Form(...), db: Session = Depends(get_db)):
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse(url="/admin/inventory", status_code=303)
    inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    old_qty = inv.quantity if inv else 0
    new_qty = max(0, quantity)
    if inv:
        inv.quantity = new_qty
    else:
        inv = Inventory(product_id=product_id, quantity=new_qty)
        db.add(inv)
    actor = request.session.get("admin_email") or "admin"
    db.add(InventoryLog(product_id=product_id, old_quantity=old_qty, new_quantity=new_qty, actor_name=actor))
    db.commit()
    return RedirectResponse(url="/admin/inventory", status_code=303)


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
    return RedirectResponse(url="/inventory", status_code=303)


@router.get("/inventory/logout")
def inventory_logout(request: Request):
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
    return RedirectResponse(url="/pos", status_code=303)


@router.get("/pos/logout")
def pos_logout(request: Request):
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

