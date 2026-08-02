import logging
import re
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..schemas import OrderCreate, OrderUpdate, StatusUpdate, ProductCreate
from ..models import Product, Order, OrderItem, AudioSettings, Waiter, Inventory, InventoryLog, Sale, SaleItem, ContactMessage, Table, cr_now
from datetime import timedelta
from ..utils import create_order, get_order, update_order_items, change_order_status, duration_seconds
from ..notifications import send_lead_notification
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()
logger = logging.getLogger("leads")


def serialize_order(order: Order):
    return {
        "id": order.id,
        "source_role": order.source_role,
        "status": order.status,
        "order_label": order.order_label,
        "table_id": order.table_id,
        "table_number": order.table.number if order.table else None,
        "requires_acceptance": order.requires_acceptance,
        "created_at": order.created_at.isoformat() + "Z",
        "accepted_at": (order.accepted_at.isoformat() + "Z") if order.accepted_at else None,
        "preparing_at": (order.preparing_at.isoformat() + "Z") if order.preparing_at else None,
        "ready_at": (order.ready_at.isoformat() + "Z") if order.ready_at else None,
        "dispatched_at": (order.dispatched_at.isoformat() + "Z") if order.dispatched_at else None,
        "cancelled_at": (order.cancelled_at.isoformat() + "Z") if order.cancelled_at else None,
        "updated_at": (order.updated_at.isoformat() + "Z") if order.updated_at else None,
        "was_edited": order.was_edited,
        "was_cancelled": order.was_cancelled,
        "duration_seconds": duration_seconds(order),
        "waiter_id": order.waiter_id,
        "waiter_name": order.waiter_name,
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product.name,
                "quantity": item.quantity,
            }
            for item in order.items
        ],
    }


@router.get("/products")
def products(db: Session = Depends(get_db)):
    rows = db.query(Product).filter(Product.active == True).order_by(Product.display_order.asc()).all()
    return [{"id": p.id, "name": p.name, "active": p.active, "image_path": p.image_path, "price": p.price or 0, "category": p.category or "General"} for p in rows]


class MoveDir(BaseModel):
    direction: str  # up | down


class ReorderIds(BaseModel):
    ids: list[int]


@router.post("/products/reorder")
def reorder_products(payload: ReorderIds, db: Session = Depends(get_db)):
    order = {pid: i for i, pid in enumerate(payload.ids)}
    prods = db.query(Product).filter(Product.id.in_(payload.ids)).all()
    for p in prods:
        if p.id in order:
            p.display_order = order[p.id]
    db.commit()
    return {"ok": True}


@router.post("/products/{product_id}/move")
def move_product_api(product_id: int, payload: MoveDir, db: Session = Depends(get_db)):
    if payload.direction not in ("up", "down"):
        raise HTTPException(400, "direction inválida")
    products = (
        db.query(Product)
        .filter(Product.active == True)
        .order_by(Product.display_order.asc(), Product.name.asc())
        .all()
    )
    # Normalize to sequential order so swaps are always well-defined.
    for i, p in enumerate(products):
        p.display_order = i
    idx = next((i for i, p in enumerate(products) if p.id == product_id), None)
    if idx is None:
        raise HTTPException(404, "Producto no encontrado")
    new_idx = idx - 1 if payload.direction == "up" else idx + 1
    if 0 <= new_idx < len(products):
        products[idx].display_order, products[new_idx].display_order = (
            products[new_idx].display_order,
            products[idx].display_order,
        )
    db.commit()
    return {"ok": True}


@router.post("/products")
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "Nombre vacío")
    existing = db.query(Product).filter(Product.name == name).first()
    if existing:
        raise HTTPException(400, "Ya existe un producto con ese nombre")
    last = db.query(Product).order_by(Product.display_order.desc()).first()
    display_order = (last.display_order + 1) if last else 1
    product = Product(name=name, display_order=display_order)
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id, "name": product.name, "active": product.active, "image_path": product.image_path}


@router.post("/orders")
def create_order_endpoint(payload: OrderCreate, db: Session = Depends(get_db)):
    if payload.source_role not in {"station_a", "kitchen"}:
        raise HTTPException(400, "Invalid source_role")
    valid_ids = {p.id for p in db.query(Product.id).all()}
    for item in payload.items:
        if item.product_id not in valid_ids:
            raise HTTPException(400, f"Invalid product {item.product_id}")
    label = (payload.order_label or "").strip() or None
    table_id = payload.table_id
    if table_id is not None and not db.query(Table.id).filter(Table.id == table_id).first():
        raise HTTPException(400, "Mesa inválida")
    order = create_order(db, payload.source_role, [item.model_dump() for item in payload.items if item.quantity > 0], waiter_id=payload.waiter_id, waiter_name=payload.waiter_name, order_label=label, table_id=table_id)
    # Marcar la mesa como ocupada (inicia sesión si estaba libre). Usa el
    # created_at de la orden como inicio para que quede incluida en la sesión.
    if table_id is not None:
        t = db.query(Table).filter(Table.id == table_id).first()
        if t and t.status != "ocupada":
            t.status = "ocupada"
            t.opened_at = order.created_at
            db.commit()
    return serialize_order(order)


@router.get("/orders/active")
def active_orders(db: Session = Depends(get_db)):
    rows = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .filter(Order.status.in_(["nuevo", "aceptado", "preparando", "listo"]))
        .order_by(Order.created_at.asc())
        .all()
    )
    return [serialize_order(o) for o in rows]


@router.get("/orders/recent")
def recent_orders(
    source_role: Optional[str] = None,
    waiter_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(Order).options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.table))
    if source_role:
        q = q.filter(Order.source_role == source_role)
    if waiter_id:
        q = q.filter(Order.waiter_id == waiter_id)
    rows = q.order_by(Order.created_at.desc()).limit(max(1, min(limit, 50))).all()
    return [serialize_order(o) for o in rows]


@router.get("/orders/ready-recent")
def ready_recent(minutes: int = 5, db: Session = Depends(get_db)):
    from sqlalchemy import or_
    cutoff = cr_now() - timedelta(minutes=max(1, min(minutes, 120)))
    rows = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .filter(
            Order.source_role == "station_a",
            Order.status.in_(["listo", "despachado"]),
            or_(Order.dispatched_at >= cutoff, Order.ready_at >= cutoff),
        )
        .order_by(Order.updated_at.desc())
        .all()
    )
    return [serialize_order(o) for o in rows]


@router.get("/orders/cancelled-recent")
def cancelled_recent(minutes: int = 5, db: Session = Depends(get_db)):
    cutoff = cr_now() - timedelta(minutes=max(1, min(minutes, 120)))
    rows = (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product))
        .filter(
            Order.status == "cancelado",
            Order.cancelled_at != None,  # noqa: E711
            Order.cancelled_at >= cutoff,
        )
        .order_by(Order.cancelled_at.desc())
        .all()
    )
    return [serialize_order(o) for o in rows]


# ─── Mesas (vista de piso) ────────────────────────────────────────────────────

@router.get("/tables")
def list_tables(db: Session = Depends(get_db)):
    """Estado de todas las mesas + los pedidos de la sesión actual de cada una."""
    tables = db.query(Table).order_by(Table.number.asc()).all()
    result = []
    for t in tables:
        orders = []
        if t.status == "ocupada" and t.opened_at is not None:
            rows = (
                db.query(Order)
                .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.table))
                .filter(Order.table_id == t.id, Order.created_at >= t.opened_at, Order.status != "cancelado")
                .order_by(Order.created_at.asc())
                .all()
            )
            orders = [serialize_order(o) for o in rows]
        total_items = sum(sum(i["quantity"] for i in o["items"]) for o in orders)
        result.append({
            "id": t.id,
            "number": t.number,
            "name": t.name,
            "status": t.status,
            "capacity": t.capacity or 4,
            "pos_x": t.pos_x,
            "pos_y": t.pos_y,
            "opened_at": (t.opened_at.isoformat() + "Z") if t.opened_at else None,
            "order_count": len(orders),
            "total_items": total_items,
            "orders": orders,
        })
    return result


@router.post("/tables/{table_id}/close")
def close_table(table_id: int, db: Session = Depends(get_db)):
    t = db.query(Table).filter(Table.id == table_id).first()
    if not t:
        raise HTTPException(404, "Mesa no encontrada")
    t.status = "libre"
    t.opened_at = None
    db.commit()
    return {"ok": True, "id": t.id, "status": t.status}


@router.put("/orders/{order_id}")
def edit_order(order_id: int, payload: OrderUpdate, db: Session = Depends(get_db)):
    order = get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    if order.status != "nuevo":
        raise HTTPException(400, "Only new orders can be edited")
    order = update_order_items(db, order, [item.model_dump() for item in payload.items if item.quantity > 0], actor_role=order.source_role)
    return serialize_order(order)


@router.post("/orders/{order_id}/status")
def update_status(order_id: int, payload: StatusUpdate, db: Session = Depends(get_db)):
    order = get_order(db, order_id)
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        order = change_order_status(db, order, payload.status, payload.actor_role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return serialize_order(order)


class PosSaleItem(BaseModel):
    product_id: int
    quantity: int


class PosSaleCreate(BaseModel):
    items: list[PosSaleItem]
    payment_method: str = "efectivo"


@router.post("/pos/sale")
def pos_create_sale(payload: PosSaleCreate, request: Request, db: Session = Depends(get_db)):
    uid = request.session.get("pos_user_id")
    uname = request.session.get("pos_user_name")
    if not uid or not uname:
        raise HTTPException(401, "No autenticado en POS")
    method = payload.payment_method.lower()
    if method not in {"efectivo", "tarjeta", "otros"}:
        raise HTTPException(400, "Método de pago inválido")
    valid_items = [i for i in payload.items if i.quantity > 0]
    if not valid_items:
        raise HTTPException(400, "Carrito vacío")

    products = {p.id: p for p in db.query(Product).filter(Product.id.in_([i.product_id for i in valid_items])).all()}
    for i in valid_items:
        if i.product_id not in products:
            raise HTTPException(400, f"Producto inválido {i.product_id}")

    settings = db.query(AudioSettings).first()
    rate = (settings.tax_rate if settings and settings.tax_rate is not None else 0) / 100.0

    subtotal = 0.0
    line_rows = []
    for i in valid_items:
        p = products[i.product_id]
        unit = float(p.price or 0)
        line = unit * i.quantity
        subtotal += line
        line_rows.append((p, i.quantity, unit, line))

    tax = round(subtotal * rate, 2)
    total = round(subtotal + tax, 2)

    sale = Sale(user_name=uname, subtotal=round(subtotal, 2), tax=tax, total=total, payment_method=method)
    db.add(sale)
    db.flush()
    for p, qty, unit, line in line_rows:
        db.add(SaleItem(sale_id=sale.id, product_id=p.id, quantity=qty, unit_price=unit, line_total=round(line, 2)))
        inv = db.query(Inventory).filter(Inventory.product_id == p.id).first()
        old_qty = inv.quantity if inv else 0
        new_qty = max(0, old_qty - qty)
        if inv:
            inv.quantity = new_qty
        else:
            db.add(Inventory(product_id=p.id, quantity=new_qty))
        db.add(InventoryLog(
            product_id=p.id,
            old_quantity=old_qty,
            new_quantity=new_qty,
            actor_name=f"pos:{uname}:sale#{sale.id}",
        ))

    # Ingredient-level consumption (additive, non-breaking, idempotent).
    # Only runs when a Recipe exists for the product; errors never break sales.
    try:
        from ..inventory_service import consume_recipe
        for p, qty, _unit, _line in line_rows:
            consume_recipe(db, product_id=p.id, quantity=qty, reference=f"sale:{sale.id}")
    except Exception:
        import logging
        logging.getLogger("inventory").exception("POS recipe consumption failed for sale#%s", sale.id)

    db.commit()
    db.refresh(sale)
    return {
        "id": sale.id,
        "subtotal": sale.subtotal,
        "tax": sale.tax,
        "total": sale.total,
        "payment_method": sale.payment_method,
        "user_name": sale.user_name,
    }


class PosProductCreate(BaseModel):
    name: str
    price: float = 0


@router.post("/pos/products")
def pos_create_product(payload: PosProductCreate, request: Request, db: Session = Depends(get_db)):
    """Crear un producto (con precio) desde el POS. Requiere sesión de POS."""
    uid = request.session.get("pos_user_id")
    uname = request.session.get("pos_user_name")
    if not uid or not uname:
        raise HTTPException(401, "No autenticado en POS")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Escribe el nombre del producto")
    name = name[:200]
    price = float(payload.price or 0)
    if price < 0:
        raise HTTPException(400, "Precio inválido")
    if db.query(Product.id).filter(func.lower(Product.name) == name.lower()).first():
        raise HTTPException(400, "Ya existe un producto con ese nombre")
    max_order = db.query(func.max(Product.display_order)).scalar() or 0
    product = Product(name=name, price=round(price, 2), active=True, display_order=max_order + 1)
    db.add(product)
    db.commit()
    db.refresh(product)
    return {"id": product.id, "name": product.name, "price": product.price, "image_path": product.image_path}


@router.get("/audio-settings")
def audio_settings(db: Session = Depends(get_db)):
    settings = db.query(AudioSettings).first()
    return {
        "station_order_sound_path": settings.station_order_sound_path,
        "kitchen_order_sound_path": settings.kitchen_order_sound_path,
        "ready_sound_path": settings.ready_sound_path,
        "cancel_sound_path": settings.cancel_sound_path,
        "voice_enabled_for_station_orders": settings.voice_enabled_for_station_orders,
        "master_volume": settings.master_volume,
    }


# ─── public contact / lead form ──────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VALID_LOCATIONS = {"1", "2-5", "5+"}
_VALID_SYSTEMS = {"papel", "otro-pos", "nada"}


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=200)
    restaurant: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=60)
    locations: Optional[str] = None
    current_system: Optional[str] = None
    message: Optional[str] = Field(default=None, max_length=4000)
    company: Optional[str] = None  # honeypot — must stay empty


@router.post("/contact")
def submit_contact(
    payload: ContactIn,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Honeypot: real users never fill a hidden field. Pretend success for bots.
    if payload.company:
        logger.info("Contact honeypot triggered; dropping submission")
        return {"ok": True}

    name = payload.name.strip()
    email = payload.email.strip()
    if not name or not _EMAIL_RE.match(email):
        raise HTTPException(400, "Nombre o email inválido")

    lead = ContactMessage(
        name=name[:200],
        email=email[:200],
        restaurant=(payload.restaurant or "").strip()[:200] or None,
        phone=(payload.phone or "").strip()[:60] or None,
        locations=payload.locations if payload.locations in _VALID_LOCATIONS else None,
        current_system=payload.current_system if payload.current_system in _VALID_SYSTEMS else None,
        message=(payload.message or "").strip()[:4000] or None,
        lang=(request.headers.get("x-lang") or "")[:5] or None,
        source_ip=(request.client.host if request.client else None),
        status="nuevo",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    # Fire the email alert after responding (never blocks or breaks the form).
    background.add_task(send_lead_notification, lead)
    return {"ok": True}
