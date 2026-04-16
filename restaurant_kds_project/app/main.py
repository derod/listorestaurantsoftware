import os
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
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
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="kds_session",
    https_only=SECURE_COOKIES,
    same_site="lax",
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


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
    if "audio_settings" in insp.get_table_names():
        audio_cols = {c["name"] for c in insp.get_columns("audio_settings")}
        if "tax_rate" not in audio_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE audio_settings ADD COLUMN tax_rate FLOAT DEFAULT 0"))

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
