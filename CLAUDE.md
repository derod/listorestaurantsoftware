# CLAUDE.md — LISTO Restaurant Software

Guía para trabajar este repo con Claude Code u otra IA/dev. Para el detalle completo
ver **`BLUEPRINT.md`** (arquitectura + modelo de datos), **`DEPLOY.md`** (despliegue) y
**`REBUILD_PROMPTS.md`** (reconstrucción).

## Qué es
App web **single-tenant** de gestión de restaurante (un restaurante por instalación).
FastAPI + SQLAlchemy 2.0 + SQLite + Jinja2 + JS vanilla + WebSocket (KDS). Sin build de
front. ~9.5k líneas Python, 39 tablas, 60 templates. Español (i18n ES/PT/FR).

## Dónde está el código
El repo anida el proyecto una vez: **`restaurant_kds_project/app/`**.
- `app/main.py` — arranque (middlewares, mounts, `create_all`, `_ensure_schema`, seed, routers, WS).
- `app/models.py` — 39 modelos. `app/database.py` — engine/SessionLocal/`DATA_DIR`.
- `app/routes/` — `web.py` (páginas+admin+logins, el más grande), `api.py` (`/api`), `admin_inventory.py`, `sanitario.py`, `menu.py`, `backup.py`.
- `app/templates/` (Jinja, casi todos extienden `base.html`), `app/static/{css,js}`.
- `app/seed.py`, `i18n.py`, `utils.py`, `websockets.py`, `factura.py`, `order_history.py`, `sanitario_data.py`.

## Convenciones (respetarlas siempre)
- **Auth por sesión, 2 roles**: admin (`ADMIN_PASSCODE`/`ADMIN_EMAIL` → `require_admin`) y agente por PIN (`Waiter` → `require_waiter`). Reutiliza `templates`, `require_admin/waiter`, `record_access`, `clock_in/out` de `routes/web.py`.
- **Timestamps**: siempre `cr_now()` (UTC‑6) / `cr_today()` desde `models.py`.
- **Migraciones**: tablas nuevas → `create_all`. Columnas nuevas en tablas existentes → añadir un `ALTER TABLE ADD COLUMN` idempotente en `_ensure_schema()` de `main.py`. Nunca romper tablas.
- **Persistencia**: todo bajo `DATA_DIR` (BD `restaurant_kds.db` + `uploads/**` servido en `/uploads`).
- **Rutas**: HTML → `templates.TemplateResponse`; acciones POST → `RedirectResponse(303)`; JSON → dict. Si un literal choca con `{id}`, usa convertidor `{id:int}` (p. ej. `/admin/menu/pedidos` vs `/admin/menu/{page_id:int}`).
- **i18n**: `i18n.py` `STRINGS[clave]={"es","pt","fr"}`; en templates `{{ t('clave') }}`.
- **KDS**: `OrderItem.items` usa `order_by="OrderItem.id"` (preserva secuencia de comanda). La Cocina sondea `/api/orders/active` y escucha `/ws/kitchen`.
- **QR**: PNG server-side con `qrcode`. **PDF**: `reportlab`. **Excel**: `openpyxl`.
- **Auditable**: no borrar registros históricos desde la UI (desactivar en su lugar).

## Correr y probar
```bash
# correr
cd restaurant_kds_project && pip install -r requirements.txt
ADMIN_PASSCODE=dev uvicorn app.main:app --reload

# probar (TestClient) — SIEMPRE con PYTHONPATH al dir del proyecto y DATA_DIR temporal
export PYTHONPATH="<repo>/restaurant_kds_project"
export PYTHONIOENCODING=utf-8    # la consola Windows (cp1252) revienta con ₡/acentos
python - <<'PY'
import os, tempfile
os.environ.update(ADMIN_PASSCODE="test", ADMIN_EMAIL="rodgabriel12@gmail.com",
                  DATA_DIR=tempfile.mkdtemp())
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
c.post("/admin/login", data={"email":"rodgabriel12@gmail.com","passcode":"test"}, follow_redirects=False)
print(c.get("/admin").status_code)
PY
```
- Cada test usa un `DATA_DIR` temporal → seed fresco de SODA SILVIA (datos demo deterministas).
- **httpx/TestClient**: para forms con claves repetidas usa `data={"campo":["a","b"]}` (el formato lista‑de‑tuplas `[("campo","a")]` NO se envía bien).

## Gotchas
- El repo versiona `restaurant_kds.db` y `uploads/**` a propósito (deploy basado en git). En producción real, usa un volumen y `DATA_DIR=/data` (ver `DEPLOY.md`).
- `git push` puede fallar por red intermitente → reintentar. Warnings LF→CRLF son inocuos.
- Commits: mensajes en español; terminar con `Co-Authored-By: Claude ...` (ya es el estilo del repo).
