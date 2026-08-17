import os
import shutil
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.gzip import GZipMiddleware
from .database import Base, engine, SessionLocal, DATA_DIR
from .seed import seed_initial_data
from .routes import web, api, admin_inventory, sanitario, menu, backup
from .websockets import manager

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = DATA_DIR / "uploads"
# Subcarpetas de uploads (funcionan igual en disco local o en un volumen /data).
for _sub in ("audio", "menu", "products", "documentation"):
    (UPLOADS_DIR / _sub).mkdir(parents=True, exist_ok=True)


def _bootstrap_persistent_volume():
    """Cuando DATA_DIR apunta a un volumen externo (ej. /data), el volumen puede
    arrancar vacío. Copia al volumen los archivos que vienen EN el repo (uploads:
    documentos oficiales, imágenes demo) si faltan, para que estén disponibles
    sin recommittearlos. No sobrescribe nada existente.

    La base de datos NO se copia por defecto (el seed crea una nueva en el
    volumen). Para migrar tus datos actuales al volumen, poné SEED_DB_FROM_BUNDLE=1
    (copia restaurant_kds.db del repo solo si el volumen aún no tiene una)."""
    src_uploads = BASE_DIR / "uploads"
    try:
        same_place = UPLOADS_DIR.resolve() == src_uploads.resolve()
    except OSError:
        same_place = False
    if not same_place and src_uploads.is_dir():
        for src in src_uploads.rglob("*"):
            rel = src.relative_to(src_uploads)
            dst = UPLOADS_DIR / rel
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            elif src.is_file() and not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    # DB opcional: sembrar desde el bundle solo si se pide y el volumen no la tiene.
    if os.getenv("SEED_DB_FROM_BUNDLE") == "1":
        src_db = BASE_DIR / "restaurant_kds.db"
        dst_db = DATA_DIR / "restaurant_kds.db"
        try:
            if src_db.exists() and src_db.resolve() != dst_db.resolve() and not dst_db.exists():
                shutil.copy2(src_db, dst_db)
        except OSError:
            pass


_bootstrap_persistent_volume()

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
    if "tables" in insp.get_table_names():
        tbl_cols = {c["name"] for c in insp.get_columns("tables")}
        for col in ("pos_x", "pos_y"):
            if col not in tbl_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE tables ADD COLUMN {col} FLOAT"))
        if "capacity" not in tbl_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tables ADD COLUMN capacity INTEGER DEFAULT 4"))
    if "factura_config" in insp.get_table_names():
        fc_cols = {c["name"] for c in insp.get_columns("factura_config")}
        for col, ddl in {"sucursal": "VARCHAR(3) DEFAULT '001'", "terminal": "VARCHAR(5) DEFAULT '00001'", "consecutivo_num": "INTEGER DEFAULT 0"}.items():
            if col not in fc_cols:
                with engine.begin() as conn:
                    conn.execute(text(f"ALTER TABLE factura_config ADD COLUMN {col} {ddl}"))
    if "orders" in insp.get_table_names():
        ord_cols = {c["name"] for c in insp.get_columns("orders")}
        if "order_label" not in ord_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN order_label VARCHAR(120)"))
        if "table_id" not in ord_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE orders ADD COLUMN table_id INTEGER"))
    if "order_items" in insp.get_table_names():
        oi_cols = {c["name"] for c in insp.get_columns("order_items")}
        if "item_name" not in oi_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE order_items ADD COLUMN item_name VARCHAR(200)"))
    if "online_orders" in insp.get_table_names():
        oo_cols = {c["name"] for c in insp.get_columns("online_orders")}
        if "kds_order_id" not in oo_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE online_orders ADD COLUMN kds_order_id INTEGER"))
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
app.include_router(sanitario.router)
app.include_router(menu.router)
app.include_router(backup.router)


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
