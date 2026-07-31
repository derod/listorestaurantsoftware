"""
WebSocket connection manager and broadcast utilities.

Additive layer — no existing functionality is modified.
"""
import asyncio
import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)
        # Capture the running event loop so sync (threadpool) endpoints can
        # schedule broadcasts onto it via run_coroutine_threadsafe.
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        logger.info("WS client connected. Total: %d", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        try:
            self._connections.remove(websocket)
        except ValueError:
            pass
        logger.info("WS client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, message: str) -> None:
        """Send a text message to every connected client.

        Dead connections are removed silently so a single bad socket
        cannot block or crash the broadcast loop.
        """
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


# Module-level singleton shared across the whole application.
manager = ConnectionManager()


def schedule_broadcast(coro) -> None:
    """Run a broadcast coroutine from any context.

    Los endpoints son funciones sync que corren en un threadpool (sin loop
    asyncio corriendo en ese hilo), así que create_task no sirve. Programamos
    la corrutina en el loop principal capturado al conectar un cliente WS.
    """
    loop = manager.loop
    if loop is None or not manager._connections:
        # Sin clientes conectados no hay a quién avisar; descartar la corrutina.
        try:
            coro.close()
        except Exception:
            pass
        return
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
    except Exception as exc:
        logger.exception("schedule_broadcast failed: %s", exc)
        try:
            coro.close()
        except Exception:
            pass


def _serialize_order(order) -> dict:
    """Convert a SQLAlchemy Order instance to a JSON-safe dict."""
    return {
        "id": order.id,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "status": order.status,
        "source_role": order.source_role,
        "waiter_name": order.waiter_name,
        "items": [
            {
                "name": item.product.name if item.product else str(item.product_id),
                "quantity": item.quantity,
            }
            for item in (order.items or [])
        ],
    }


async def broadcast_new_order(order) -> None:
    """Serialize an Order and push it to all connected kitchen clients."""
    if not manager._connections:
        return
    try:
        payload = json.dumps({"event": "new_order", "order": _serialize_order(order)})
        await manager.broadcast(payload)
    except Exception as exc:
        # Never let a broadcast failure propagate into order-creation logic.
        logger.exception("broadcast_new_order failed: %s", exc)


async def broadcast_order_ready(order) -> None:
    """Push an 'order_ready' event (order marcado listo/despachado) to clients.

    Lo escucha el Salón para avisar al instante que un pedido está listo,
    en vez de esperar al sondeo de ready-recent.
    """
    if not manager._connections:
        return
    try:
        payload = json.dumps({"event": "order_ready", "order": _serialize_order(order)})
        await manager.broadcast(payload)
    except Exception as exc:
        logger.exception("broadcast_order_ready failed: %s", exc)
