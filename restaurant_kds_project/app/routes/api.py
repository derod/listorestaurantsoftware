from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..schemas import OrderCreate, OrderUpdate, StatusUpdate, ProductCreate
from ..models import Product, Order, OrderItem, AudioSettings, Waiter, Inventory, InventoryLog, Sale, SaleItem
from ..utils import create_order, get_order, update_order_items, change_order_status, duration_seconds
from pydantic import BaseModel

router = APIRouter()


def serialize_order(order: Order):
    return {
        "id": order.id,
        "source_role": order.source_role,
        "status": order.status,
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
    return [{"id": p.id, "name": p.name, "active": p.active, "image_path": p.image_path, "price": p.price or 0} for p in rows]


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
    order = create_order(db, payload.source_role, [item.model_dump() for item in payload.items if item.quantity > 0], waiter_id=payload.waiter_id, waiter_name=payload.waiter_name)
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
