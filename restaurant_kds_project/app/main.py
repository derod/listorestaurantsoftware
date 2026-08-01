import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware
from .database import Base, engine, SessionLocal, DATA_DIR
from .seed import seed_initial_data
from .routes import web, api, admin_inventory
from .websockets import manager

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = DATA_DIR / "uploads"
(UPLOADS_DIR / "audio").mkdir(parents=True, exist_ok=True)

SESSION_SECRET = os.getenv("SESSION_SECRET", "kds-dev-secret-change-me")
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "0") == "1"

app = FastAPI(title="LISTO Restaurant Software")
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="kds_session",
    https_only=SECURE_COOKIES,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


@app.middleware("http")
async def add_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    elif path.startswith("/uploads/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}

Base.metadata.create_all(bind=engine)

def _ensure_schema():
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    prod_cols = {c["name"] for c in insp.get_columns("products")}
    if "image_path" not in prod_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN image_path VARCHAR(300)"))
    if "price" not in prod_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN price FLOAT DEFAULT 0"))
    if "category" not in prod_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN category VARCHAR(40) DEFAULT 'General'"))
    if "audio_settings" in insp.get_table_names():
        audio_cols = {c["name"] for c in insp.get_columns("audio_settings")}
        if "tax_rate" not in audio_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE audio_settings ADD COLUMN tax_rate FLOAT DEFAULT 0"))
    if "work_sessions" in insp.get_table_names():
        ws_cols = {c["name"] for c in insp.get_columns("work_sessions")}
        if "edited" not in ws_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE work_sessions ADD COLUMN edited BOOLEAN DEFAULT 0"))
    if "ingredients" in insp.get_table_names():
        ing_cols = {c["name"] for c in insp.get_columns("ingredients")}
        if "category" not in ing_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE ingredients ADD COLUMN category VARCHAR(80)"))
        # Master-item fields (phase 1 inventory redesign)
        _ing_new = {
            "purchase_unit": "VARCHAR(40)",
            "pack_content": "FLOAT",
            "purchase_price": "FLOAT",
            "yield_qty": "FLOAT",
            "yield_unit": "VARCHAR(40)",
            "min_stock": "FLOAT DEFAULT 0",
            "supplier": "VARCHAR(200)",
            "last_purchase_date": "DATETIME",
            "expiry_date": "DATETIME",
            "status": "VARCHAR(20)",
            "notes": "TEXT",
        }
        for col, ddl in _ing_new.items():
            if col not in ing_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE ingredients ADD COLUMN {col} {ddl}"))
    if "expenses" in insp.get_table_names():
        exp_cols = {c["name"] for c in insp.get_columns("expenses")}
        if "source" not in exp_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE expenses ADD COLUMN source VARCHAR(40)"))
    if "orders" in insp.get_table_names():
        ord_cols = {c["name"] for c in insp.get_columns("orders")}
        if "order_label" not in ord_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN order_label VARCHAR(120)"))
        if "table_id" not in ord_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN table_id INTEGER"))
    # Performance indexes for orders table
    existing_indexes = {idx["name"] for idx in insp.get_indexes("orders")} if "orders" in insp.get_table_names() else set()
    with engine.begin() as conn:
        if "ix_orders_created_at" not in existing_indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders (created_at)"))
        if "ix_orders_status" not in existing_indexes:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_orders_status ON orders (status)"))

_ensure_schema()

with SessionLocal() as db:
    seed_initial_data(db)

app.include_router(web.router)
app.include_router(api.router, prefix="/api")
app.include_router(admin_inventory.router)


@app.websocket("/ws/kitchen")
async def websocket_kitchen(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive; we only push from server → client.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
