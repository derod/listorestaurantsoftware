import asyncio
from datetime import datetime
from sqlalchemy.orm import Session, joinedload
from .models import Order, OrderItem, OrderEvent, Inventory, InventoryLog, OnlineOrder, cr_now

ALLOWED_STATUSES = ["nuevo", "aceptado", "preparando", "listo", "despachado", "cancelado"]

# Mapa de estado KDS → estado del tablero de Pedidos Online (para sincronizar
# cuando la cocina mueve una comanda que vino de un pedido online).
KDS_TO_BOARD_STATUS = {
    "aceptado": "aceptado", "preparando": "preparando", "listo": "listo",
    "despachado": "entregado", "cancelado": "rechazado",
}


def _sync_online_board_from_kds(db: Session, order: Order) -> None:
    """Si esta orden nació de un pedido online, refleja su estado en el tablero.
    Set directo (no vuelve a llamar al KDS) → sin bucles."""
    if order.source_role != "online":
        return
    mapped = KDS_TO_BOARD_STATUS.get(order.status)
    if not mapped:
        return
    oo = db.query(OnlineOrder).filter(OnlineOrder.kds_order_id == order.id).first()
    if oo and oo.status != mapped:
        oo.status = mapped
        db.commit()


def create_order(db: Session, source_role: str, items: list[dict], waiter_id: int | None = None, waiter_name: str | None = None, order_label: str | None = None, table_id: int | None = None):
    requires_acceptance = source_role == "station_a"
    order = Order(source_role=source_role, requires_acceptance=requires_acceptance, waiter_id=waiter_id, waiter_name=waiter_name, order_label=order_label, table_id=table_id)
    db.add(order)
    db.flush()
    for item in items:
        db.add(OrderItem(order_id=order.id, product_id=item["product_id"], quantity=item["quantity"]))
    db.add(OrderEvent(order_id=order.id, event_type="created", actor_role=source_role, new_value=source_role))
    db.commit()
    full_order = get_order(db, order.id)
    # Fire-and-forget: push to connected clients (Cocina y Salón) via WebSocket.
    try:
        from .websockets import schedule_broadcast, broadcast_new_order
        schedule_broadcast(broadcast_new_order(full_order))
    except Exception:
        pass  # Never let WS failure affect order creation
    return full_order


def get_order(db: Session, order_id: int):
    return db.query(Order).options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.events), joinedload(Order.table)).filter(Order.id == order_id).first()


def list_active_orders(db: Session):
    return (
        db.query(Order)
        .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.table))
        .filter(Order.status.in_(["nuevo", "aceptado", "preparando", "listo"]))
        .order_by(Order.created_at.asc())
        .all()
    )


def update_order_items(db: Session, order: Order, items: list[dict], actor_role: str):
    order.items.clear()
    db.flush()
    for item in items:
        db.add(OrderItem(order_id=order.id, product_id=item["product_id"], quantity=item["quantity"]))
    order.was_edited = True
    db.add(OrderEvent(order_id=order.id, event_type="items_updated", actor_role=actor_role))
    db.commit()
    return get_order(db, order.id)


def change_order_status(db: Session, order: Order, status: str, actor_role: str):
    if status not in ALLOWED_STATUSES:
        raise ValueError("Invalid status")
    old = order.status
    order.status = status
    now = cr_now()
    if status == "aceptado":
        order.accepted_at = now
    elif status == "preparando":
        order.preparing_at = now
    elif status == "listo":
        order.ready_at = now
    elif status == "despachado":
        order.dispatched_at = now
        if old != "despachado":
            _decrement_inventory_for_order(db, order, actor_role)
    elif status == "cancelado":
        order.cancelled_at = now
        order.was_cancelled = True
    db.add(OrderEvent(order_id=order.id, event_type="status_changed", actor_role=actor_role, old_value=old, new_value=status))
    db.commit()
    # KDS → tablero de Pedidos Online (si la comanda vino de un pedido online).
    if order.source_role == "online" and old != status:
        try:
            _sync_online_board_from_kds(db, order)
        except Exception:
            db.rollback()
    full = get_order(db, order.id)
    # Fire-and-forget: avisar al Salón al instante cuando un pedido de salón
    # queda listo/despachado (mismo criterio que /orders/ready-recent).
    if order.source_role == "station_a" and status in ("listo", "despachado") and old != status:
        try:
            from .websockets import schedule_broadcast, broadcast_order_ready
            schedule_broadcast(broadcast_order_ready(full))
        except Exception:
            pass  # Never let WS failure affect status changes
    return full


def _decrement_inventory_for_order(db: Session, order: Order, actor_role: str):
    # Agregar por producto: una comanda secuencial (Desayuno/Uber) puede tener el
    # mismo producto en varias líneas. Sin agregar, se intentaría crear dos filas
    # Inventory con el mismo product_id (unique) -> IntegrityError al despachar.
    totals: dict[int, int] = {}
    for item in order.items:
        totals[item.product_id] = totals.get(item.product_id, 0) + item.quantity
    for product_id, qty in totals.items():
        inv = db.query(Inventory).filter(Inventory.product_id == product_id).first()
        old_qty = inv.quantity if inv else 0
        new_qty = max(0, old_qty - qty)
        if inv:
            inv.quantity = new_qty
        else:
            db.add(Inventory(product_id=product_id, quantity=new_qty))
        db.add(InventoryLog(
            product_id=product_id,
            old_quantity=old_qty,
            new_quantity=new_qty,
            actor_name=f"auto:{actor_role}:order#{order.id}",
        ))


def duration_seconds(order: Order):
    end = order.dispatched_at or order.cancelled_at
    if not end:
        return None
    return int((end - order.created_at).total_seconds())
