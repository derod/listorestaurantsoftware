# LISTO Restaurant Software — Blueprint (cómo está hecho)

Documento maestro de arquitectura. Sirve para **entender** el sistema, **clonarlo**
para una copia nueva, o **reconstruirlo** desde cero (ver `REBUILD_PROMPTS.md`).

> Tamaño real: ~9.500 líneas de Python (6 routers), **39 tablas**, **60 templates**,
> ~1.750 líneas de JS. Un solo proceso, single-tenant (un restaurante por instalación).

---

## 1. Stack

| Capa | Tecnología |
|---|---|
| Web framework | **FastAPI** 0.115 (rutas sync sobre threadpool) |
| Servidor | **uvicorn** (`Procfile`: `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2`) |
| ORM / DB | **SQLAlchemy 2.0** (Mapped/mapped_column) + **SQLite** por defecto (`DATABASE_URL` permite Postgres) |
| Templates | **Jinja2** (server-rendered) |
| Front | HTML + CSS propio (`static/css/styles.css`, touch-first) + **JS vanilla** (sin build) |
| Tiempo real | **WebSocket** nativo (`/ws/kitchen`) para el KDS |
| Sesiones | `SessionMiddleware` (itsdangerous), cookie `kds_session` |
| PDF | **reportlab** · Excel: **openpyxl** · QR: **qrcode**+PIL |
| Cripto | **cryptography** (secretos de factura electrónica) |
| i18n | Diccionario propio ES/PT/FR por cookie `lang` |

Dependencias exactas: `requirements.txt`.

---

## 2. Estructura

```
restaurant_kds_project/            # (dir del proyecto; el repo lo anida una vez)
  Procfile  requirements.txt  README.md
  app/
    main.py            # arranque: middlewares, mounts, create_all, _ensure_schema, seed, routers, WS
    database.py        # engine, SessionLocal, Base, get_db, DATA_DIR
    models.py          # 39 modelos SQLAlchemy (todas las tablas)
    schemas.py         # Pydantic (payloads de la API)
    seed.py            # datos iniciales idempotentes (SODA SILVIA)
    i18n.py            # STRINGS ES/PT/FR + t()
    utils.py           # create_order, change_order_status, inventario al despachar
    websockets.py      # ConnectionManager + broadcasts del KDS
    order_history.py   # export CSV/Excel/PDF del historial de órdenes
    inventory_service.py, notifications.py, factura.py, sanitario_data.py
    routes/
      web.py           # páginas HTML + admin + logins (el más grande)
      api.py           # /api/* JSON (órdenes, productos, POS, leads)
      admin_inventory.py  # /admin/inv/* (insumos, recetas, movimientos)
      sanitario.py     # Control Sanitario
      menu.py          # Menú Online + público /m/{slug}
      backup.py        # respaldo/export/import
    templates/         # 60 .html (base.html + módulos)
    static/            # css/styles.css, js/{station,kitchen,ui}.js, favicons, videos
```

Persistencia (fuera del código): `DATA_DIR/restaurant_kds.db` + `DATA_DIR/uploads/**`
(servido en `/uploads`). Por defecto `DATA_DIR="."`.

---

## 3. Convenciones clave (imprescindibles para reconstruir)

- **Auth por sesión, dos roles**:
  - **Admin**: `ADMIN_EMAIL` + `ADMIN_PASSCODE` (env) → `session["admin_logged_in"]=True`. Gate: `require_admin(request)`.
  - **Agente** (mesero/cocinero/etc.): login por **PIN** contra la tabla `Waiter` → `session["waiter_id"]`, `session["waiter_name"]`. Gate: `require_waiter(request)`. Un mismo PIN sirve para Salón/Cocina/Inventario/POS/Sanitario.
  - `AccessLog` registra cada login; `WorkSession` maneja clock in/out por (agente, módulo).
- **Zona horaria**: `cr_now()` = `datetime.utcnow() - 6h` (Costa Rica). **Todos** los timestamps la usan. `cr_today()` para fechas.
- **Migraciones aditivas**: tablas nuevas → `Base.metadata.create_all`. Columnas nuevas en tablas existentes → `_ensure_schema()` en `main.py` con `ALTER TABLE ... ADD COLUMN` idempotente (inspecciona columnas primero). **Nunca** se rompe una tabla existente.
- **`DATA_DIR` = raíz persistente** (BD + uploads). Un volumen `/data` en producción (ver `DEPLOY.md`). Bootstrap copia assets del repo al volumen vacío.
- **i18n**: `i18n.py` tiene `STRINGS[clave] = {"es","pt","fr"}`. En templates `{{ t('clave') }}`; en JS `window.I18N['clave']`. Idioma en cookie `lang`.
- **Rutas**: routers con `APIRouter`. `web.py` sin prefijo (páginas), `api.py` con prefijo `/api`. HTML → `templates.TemplateResponse`; acciones → `RedirectResponse(303)`; JSON → dict/`JSONResponse`. Colisión de rutas: usar convertidor `{id:int}` cuando haya literales que choquen (p. ej. `/admin/menu/{page_id:int}` vs `/admin/menu/pedidos`).
- **KDS en tiempo real**: al crear/cambiar órdenes, `utils.py` dispara `schedule_broadcast(broadcast_new_order/…)`; la Cocina también sondea `/api/orders/active` cada pocos segundos. `OrderItem` tiene `order_by="OrderItem.id"` para **preservar la secuencia** (comanda de Desayuno).
- **QR**: server-side PNG con `qrcode` (`.../qr.png`), apunta a URLs que **siempre pasan por login/permiso**.
- **PDF**: `reportlab` (SimpleDocTemplate + Table). **Excel**: `openpyxl`.
- **Templates**: casi todos `{% extends 'base.html' %}` (topbar + nav admin + modal de confirmación + audio unlock). Las pantallas de login y las públicas (`/m/{slug}`, cuestionario) son **standalone full-screen**.
- **Sin borrados destructivos** de registros históricos desde la UI (auditable). Se desactiva en vez de borrar cuando hay historial.

---

## 4. Modelo de datos (39 tablas, por módulo)

**Núcleo / KDS**: `Product`, `Order`, `OrderItem`, `OrderEvent`, `Waiter`, `Table`, `AudioSettings`, `AccessLog`, `WorkSession`.
- `Order(source_role, status[nuevo→aceptado→preparando→listo→despachado|cancelado], requires_acceptance, waiter_id/name, order_label, table_id, timestamps)`; `OrderItem(order_id, product_id, quantity, item_name?)`; `OrderEvent` (auditoría de cambios).
- `Waiter(name, pin unique, active, supervisor)` — `supervisor` = encargado que puede verificar en Sanitario.

**POS / Ventas**: `Sale`, `SaleItem`.

**Inventario**: `Ingredient` (item maestro: unidad, costo, stock, presentación de compra, min_stock…), `Recipe`, `RecipeItem`, `InventoryMovement`, `Purchase`, `PurchaseItem`, `Inventory`, `InventoryLog`.

**Gastos**: `Expense`, `FixedExpense`.

**Factura electrónica (Hacienda CR v4.4)**: `InvoiceClient`, `FacturaConfig` (emisor + credenciales **cifradas**: `atv_clave_enc`, `cert_pin_enc`).

**Leads (landing)**: `ContactMessage`.

**Control Sanitario** (Reglamento 37308-S): `CleaningArea`, `CleaningAssignment` (área↔agente), `CleaningTask` (protocolo), `CleaningRecord` (ejecución), `CleaningIncident`, `TemperatureEquipment`, `TemperatureRecord`, `PestControlRecord`, `SanitaryInspection` (autoinspección puntuada).

**Menú Online / QR**: `MenuPage` (slug público), `Menu` (por horario), `MenuItem` (enlazable a `Product`), `MenuItemVariant` (variaciones de precio), `OnlineOrder`, `OnlineOrderItem` (pedidos del cliente por QR de mesa).

---

## 5. Módulos funcionales

1. **Salón (Station A)** — toma de pedidos por mesero, categorías (General/Desayuno/Sandwiches/Uber), comanda secuencial para Desayuno, mesas.
2. **Cocina (KDS)** — pantalla en tiempo real (WebSocket + polling), estados, sonido/voz, estilo comanda para Desayuno.
3. **POS** — venta directa con impuesto configurable.
4. **Productos** — catálogo (foto, precio, categoría, orden, activo).
5. **Inventario** — insumos, recetas, compras/recepción, movimientos, costo por unidad, rentabilidad (COGS por receta).
6. **Gastos / Rentabilidad** — gastos fijos y variables, reportes.
7. **Mesas** — plano editable (posiciones, capacidad).
8. **Factura electrónica** — clientes, config emisor, credenciales Hacienda cifradas, prueba de conexión IdP.
9. **Reloj** — clock in/out del personal.
10. **Landing + Leads** — página pública comercial + formulario de contacto (email opcional).
11. **Cuestionario** — modo rápido full-screen para cargar inventario/gastos.
12. **Control Sanitario** — protocolo, reparto por área, ejecución worker por PIN, verificación por encargados (con segregación), incidencias, temperaturas, plagas, QR por tarea, autoinspección (checklist oficial), guías + calculadora de cloro, reporte diario y de período (PDF).
13. **Menú Online / QR** — páginas de menú públicas con horarios y variantes; pedidos del cliente por QR de mesa → cola de aceptación → puente al KDS; aviso con sonido.
14. **Respaldo y Datos** — backup completo (.zip: BD + uploads), export/import de Productos e Insumos (Excel/CSV, upsert con preview).

---

## 6. Variables de entorno

| Variable | Uso |
|---|---|
| `ADMIN_PASSCODE` | **Requerido**. Clave del admin. |
| `ADMIN_EMAIL` | Email del admin (default en código). |
| `SESSION_SECRET` | Firma de sesiones. |
| `SECURE_COOKIES` | `1` si HTTPS. |
| `DATA_DIR` | Raíz de BD + uploads (volumen `/data` en prod). |
| `DATABASE_URL` | Override de la BD (Postgres, etc.). |
| `SEED_DB_FROM_BUNDLE` | `1` en el primer deploy para migrar la BD del repo al volumen. |
| `EMAIL_PROVIDER`, `RESEND_API_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `LEAD_NOTIFY_TO/FROM` | Notificación de leads (opcional). |

---

## 7. Arrancar / desplegar

```bash
cd restaurant_kds_project
python -m venv .venv && . .venv/Scripts/activate   # (o source .venv/bin/activate)
pip install -r requirements.txt
export ADMIN_PASSCODE=tu-clave                       # requerido
uvicorn app.main:app --reload
```
Producción: ver **`DEPLOY.md`** (volumen `/data`, variables, bootstrap).

---

## 8. Copia nueva (clonar) — el camino recomendado para "otra soda"

Reconstruir con IA da un app *distinto*. Para una copia **funcional e idéntica**:

```bash
git clone https://github.com/derod/listorestaurantsoftware.git nueva-soda
cd nueva-soda/restaurant_kds_project
pip install -r requirements.txt
# BD nueva y limpia: NO copies restaurant_kds.db (deja que el seed cree una)
export ADMIN_PASSCODE=clave-del-nuevo-negocio
export DATA_DIR=/ruta/persistente        # su propio volumen/carpeta de datos
uvicorn app.main:app
```
- En el primer arranque, `seed.py` crea los datos demo (SODA SILVIA). Ajústalos o límpialos (Admin → Danger Zone / Respaldo).
- Cada copia = **su propio `DATA_DIR`** (BD + uploads separados). Es single-tenant: **una instalación por restaurante**.
- Para desplegar cada copia, sigue `DEPLOY.md` con su volumen y variables.

Si necesitas **muchos restaurantes en una sola instancia** (multi-tenant real), eso es un refactor mayor de toda la app (hoy no hay `business_id`).
