# LISTO — Prompts de reconstrucción

Prompts numerados para **reconstruir el sistema desde cero** con una IA de código
(Claude Code / Cursor / etc.) sobre un repo vacío. Ejecútalos **en orden**; cada uno
asume que los anteriores ya corrieron. El resultado será *parecido*, no idéntico al
original (ver `BLUEPRINT.md` para la referencia exacta).

**Cómo usarlos:** pega un prompt, deja que la IA lo implemente y lo pruebe, verifica
que arranca, y pasa al siguiente. Empieza siempre por el 0.

---

## Prompt 0 — Scaffold (base del proyecto)

```
Crea el esqueleto de "LISTO Restaurant Software": una app web single-tenant
(un restaurante por instalación) para gestión de restaurante.

Stack OBLIGATORIO (sin build de front): FastAPI + uvicorn, SQLAlchemy 2.0
(Mapped/mapped_column) con SQLite por defecto (DATABASE_URL para override),
Jinja2 para HTML server-rendered, JS vanilla, SessionMiddleware (itsdangerous).

Estructura:
  app/main.py, app/database.py, app/models.py, app/schemas.py, app/seed.py,
  app/i18n.py, app/routes/{web,api}.py, app/templates/, app/static/{css,js}
  requirements.txt, Procfile (web: uvicorn app.main:app --host 0.0.0.0 --port $PORT)

Convenciones que debes respetar en TODO el proyecto:
- Persistencia bajo DATA_DIR (env, default "."): la BD en DATA_DIR/restaurant_kds.db
  y los archivos subidos en DATA_DIR/uploads/** servidos en /uploads.
- Zona horaria Costa Rica: define cr_now() = datetime.utcnow() - timedelta(hours=6)
  y cr_today(); ÚSALAS en todos los timestamps (default=cr_now).
- Migraciones aditivas: en main.py, tras Base.metadata.create_all, una función
  _ensure_schema() que inspecciona columnas y hace "ALTER TABLE ADD COLUMN"
  idempotente para columnas nuevas. Nunca rompas tablas existentes.
- Autenticación por sesión con DOS roles:
  * Admin: variables de entorno ADMIN_EMAIL y ADMIN_PASSCODE (ADMIN_PASSCODE es
    obligatorio, la app falla si falta). Login en /admin/login → session
    ["admin_logged_in"]=True. Helper require_admin(request).
  * Agente: login por PIN contra tabla Waiter → session["waiter_id"/"waiter_name"].
    Helper require_waiter(request) que devuelve (id, name) o None.
- i18n: app/i18n.py con STRINGS = { "clave": {"es":..,"pt":..,"fr":..} }, LANGS=
  ["es","pt","fr"], función t(lang,key). Regístrala como global de Jinja t() usando
  la cookie "lang" (default es). Ruta GET /idioma/{lang} que setea la cookie.
- base.html: topbar con marca "LISTO Restaurant Software", nav de admin (solo en
  rutas /admin), selector de idioma, y un modal de confirmación reutilizable
  (window.askConfirm) + toast (window.toast). CSS touch-first en static/css/styles.css
  con variables --bg/--card/--border/--text/--accent/--blue/--green/--yellow/--red.
- Rutas: web.py sin prefijo (páginas HTML → TemplateResponse; acciones POST →
  RedirectResponse 303). api.py con prefijo /api (JSON).

Modelos iniciales: Product(name unique, active, display_order, image_path, price,
category, created_at) y Waiter(name, pin unique, active, created_at).
Seed idempotente: unos productos demo si la tabla está vacía.

Endpoints mínimos: landing "/", "/home" (hub de módulos), /admin/login (GET/POST),
/admin (dashboard protegido), /health. Deja todo corriendo con uvicorn.
```

---

## Prompt 1 — Productos + KDS (Salón, Cocina, tiempo real)

```
Agrega el núcleo operativo (KDS - Kitchen Display System).

Modelos: Order(source_role, status[nuevo,aceptado,preparando,listo,despachado,
cancelado], requires_acceptance, waiter_id/name, order_label, table_id nullable,
timestamps por estado con cr_now, was_edited, was_cancelled), OrderItem(order_id,
product_id, quantity, item_name nullable), OrderEvent(auditoría: event_type,
old/new_value, actor_role). Order.items con relationship order_by="OrderItem.id"
para PRESERVAR la secuencia de agregado.

utils.py: create_order(...), change_order_status(...) (setea timestamps; al
"despachado" descuenta inventario), get_order, list_active_orders.

WebSocket: app/websockets.py con un ConnectionManager y broadcasts; endpoint
/ws/kitchen. Al crear/cambiar órdenes, dispara broadcast_new_order/order_ready
(fire-and-forget, nunca rompe la operación si no hay clientes).

Rutas:
- Salón (/station-a/*): login por PIN, dashboard con grid de productos por
  CATEGORÍAS (pestañas General/Desayuno/Sandwiches + "Uber"). El carrito es una
  lista de LÍNEAS: en General agrupa por producto; en Desayuno/Uber es COMANDA
  SECUENCIAL (agrupa solo toques consecutivos; volver a un producto anterior crea
  línea nueva). Enviar → POST /api/orders.
- Cocina (/kitchen/*): login por PIN, pantalla que sondea /api/orders/active cada
  ~1-2s y escucha el WebSocket, con sonido/voz al llegar pedidos. Estados con
  botones (aceptar→preparando→listo→despachado, cancelar). Los pedidos de
  categoría Desayuno se muestran en estilo COMANDA (lista vertical en secuencia),
  el resto en grid de tiles con cantidad grande. Detecta desayuno por la categoría
  de los ítems (incluye 'category' en el JSON del KDS).
- api.py: /api/products, /api/orders (crear), /api/orders/{id}/status,
  /api/orders/active, /api/orders/cancelled-recent.

Admin: /admin/products (crear, foto, precio, categoría, activar, reordenar, borrar).
JS en static/js/{station,kitchen}.js.
```

---

## Prompt 2 — POS (punto de venta)

```
Agrega un POS. Modelos Sale(user_name, subtotal, tax, total, payment_method,
created_at) y SaleItem(sale_id, product_id, quantity, unit_price, line_total).
AudioSettings ya puede llevar tax_rate configurable. Pantalla /pos con login por
PIN: grid de productos, carrito, método de pago, impuesto configurable, y registro
de la venta vía /api. Admin /admin/pos-settings para el impuesto y sonidos.
```

---

## Prompt 3 — Inventario (insumos, recetas, compras)

```
Agrega inventario a nivel de insumos. Modelos: Ingredient (item maestro: name
unique, unit, cost_per_unit, stock, category, purchase_unit, pack_content,
purchase_price, yield_qty/unit, min_stock, supplier, expiry_date, status, notes),
Recipe + RecipeItem (producto → insumos y cantidades), InventoryMovement
(in/out/adjustment/waste), Purchase + PurchaseItem (recepción de mercadería, calcula
base_units y actualiza costo por unidad = precio/pack_content).

Router admin_inventory.py bajo /admin/inv/* (JSON, gate admin): CRUD de insumos,
movimientos, upsert de recetas. Páginas admin: /admin/inventario (gestión),
/admin/compras (recepción). Al despachar una orden (KDS) descuenta stock de
producto; con recetas se puede calcular COGS. Servicio inventory_service.py con
create_inventory_movement.
```

---

## Prompt 4 — Mesas, Gastos, Rentabilidad, Reloj, Reportes

```
Agrega:
- Mesas: modelo Table(number unique, name, status, capacity, pos_x, pos_y). Vista
  de piso /mesas y editor /admin/mesas (posiciones y capacidad). Las órdenes se
  pueden asociar a una mesa (table_id).
- Gastos: Expense y FixedExpense; página /admin/gastos (registrar, categorías,
  generar gastos fijos del mes, export CSV).
- Rentabilidad: /admin/rentabilidad (vendido POS, comprado, merma, gastos, margen,
  COGS vía recetas) por rango (hoy/semana/mes).
- Reloj: WorkSession (clock in/out por agente y módulo, auto-cierre a medianoche);
  /admin/clock. AccessLog de cada login; /admin/access-log.
- Historial de órdenes: order_history.py con export CSV/Excel(openpyxl)/PDF(reportlab);
  /admin/orders/history con filtros.
- Reportes: /admin/reports (consumo de platos e insumos, stock).
```

---

## Prompt 5 — Factura electrónica (Hacienda Costa Rica v4.4)

```
Agrega gestión de factura electrónica de Costa Rica (Comprobantes v4.4). Modelos:
InvoiceClient (receptores: nombre, id_tipo/numero, correo) y FacturaConfig (fila
única: datos del emisor + credenciales del IdP de Hacienda). Los SECRETOS (clave
ATV y PIN del certificado .p12) se guardan CIFRADOS con la librería cryptography
(módulo app/factura.py con encrypt/decrypt, carpeta privada para el certificado).
Páginas /admin/factura (clientes) y /admin/factura/config (emisor + credenciales,
subida del .p12, prueba de autenticación con el IdP). NO subas los secretos si el
campo viene vacío (write-only).
```

---

## Prompt 6 — Control Sanitario (Programa de Higiene y Desinfección)

```
Agrega el módulo "Control Sanitario" (Reglamento 37308-S de Costa Rica). Router
app/routes/sanitario.py.

Modelos: CleaningArea, CleaningTask (protocolo: área, nombre, procedimiento por
pasos, frecuencia[diaria/varias_dia/semanal/segun_programacion], momento, producto,
concentración y tiempo de contacto -según ficha técnica, no inventar-, activo),
CleaningRecord (ejecución del día: estado[pendiente/en_proceso/completada/vencida/
verificada], started/completed_at, created_by_id/name, confirmed, verified_at/by/
notes; timestamps inmutables), CleaningAssignment (área↔agente, reparto),
CleaningIncident, TemperatureEquipment (rangos configurables) + TemperatureRecord
(out_of_range calculado), PestControlRecord, SanitaryInspection (autoinspección).
Waiter gana un flag 'supervisor' (encargado).

Lógica:
- ensure_today_records(db): genera de forma perezosa e idempotente los registros
  del día según frecuencia (no hay scheduler). Marca vencidas del pasado.
- Acceso worker por el mismo PIN de agente (/sanitario/login). "Limpiezas de hoy"
  con pestañas "Mis tareas" (áreas asignadas) / "Todas".
- Registrar limpieza: iniciar → completar con checkbox de confirmación (no editar
  tiempos). Verificación: la hace el Admin O un agente con supervisor=True desde
  /sanitario/verificaciones, con SEGREGACIÓN (no puede verificar lo que él mismo
  hizo: created_by_id != waiter).
- Admin: protocolo (CRUD áreas/tareas), "Repartir" (matriz área×agente + designar
  encargados), tareas con QR por tarea (PNG server-side con qrcode, apunta a URL
  que exige login), historial con filtros, incidencias, temperaturas, plagas.
- Autoinspección: checklist oficial (guárdalo como datos en app/sanitario_data.py)
  puntuado, con rangos (≤69 inaceptable / 70-80 deficiente / 81-100 buenas) y
  snapshots (SanitaryInspection). Guías + calculadora de cloro (diluciones).
- Reportes PDF (reportlab): diario (formato profesional para el Ministerio, con
  responsable asignado, quién realizó, quién verificó, firmas) y por período.
Todo en español; registros no borrables desde la UI.
```

---

## Prompt 7 — Menú Online / QR + pedidos del cliente

```
Agrega "Menú Online / QR". Router app/routes/menu.py.

Modelos: MenuPage (name, slug único, active, branding, currency), Menu (por horario:
name, all_day o start_hm/end_hm), MenuItem (enlazable a Product, section texto,
price, image, available), MenuItemVariant (variaciones de precio). Para pedidos:
OnlineOrder (page_id, table_id, table_label, customer_name, note, status[pendiente/
aceptado/preparando/listo/entregado/rechazado], total, kds_order_id) y
OnlineOrderItem (snapshot de nombre/variante/precio/cantidad).

- Página pública /m/{slug} (standalone, móvil): pestañas por menú con AUTO-SELECCIÓN
  según la hora, secciones, fotos, variantes. Si entra por el QR de una mesa
  (?mesa=ID) habilita CARRITO y envío. El servidor RECALCULA precios y valida
  contra la BD (no confía en el cliente); exige variante cuando el ítem la tiene.
- Admin: lista de páginas + builder (branding, menús con horario, ítems con foto/
  variantes) + QR general y QR POR MESA (imprimible). "Pedidos Online": cola de
  aceptación (aceptar/rechazar/preparando/listo/entregado, transiciones validadas),
  auto-actualización y AVISO CON SONIDO (beep WebAudio) al llegar uno nuevo.
- Puente al KDS: al aceptar, crea una Order nativa (source_role="online") que
  aparece en la pantalla de Cocina; líneas sin producto usan un Product placeholder
  "Pedido online" (inactivo) como FK y el nombre real va en OrderItem.item_name.
  Sincroniza estados board↔KDS en ambos sentidos (sin bucles).
Cuidado con colisiones de ruta: usa {page_id:int} para que /admin/menu/pedidos no
choque con /admin/menu/{page_id}.
```

---

## Prompt 8 — Respaldo y Datos + despliegue con volumen

```
Agrega:
- Página Admin /admin/backup: (1) "Respaldo completo" que descarga un .zip con un
  SNAPSHOT consistente de la BD (API de backup de SQLite) + volcado .sql + la
  carpeta uploads/; (2) exportar Productos e Insumos a Excel(openpyxl) y CSV;
  (3) importar Productos/Insumos desde Excel/CSV con UPSERT por nombre (crea/
  actualiza, no borra) y VISTA PREVIA (crear/actualizar/omitir) antes de aplicar.
  Precios y validación recalculados en el servidor.
- Bootstrap de volumen persistente: si DATA_DIR apunta a un volumen externo (ej.
  /data), al arrancar copia los assets del repo (uploads/**) al volumen si faltan
  (sin sobrescribir). SEED_DB_FROM_BUNDLE=1 copia la BD del repo al volumen solo si
  aún no existe. Documenta el despliegue en DEPLOY.md.
```

---

### Notas para quien reconstruye
- Respeta **siempre** las convenciones del Prompt 0 (auth, cr_now, _ensure_schema,
  DATA_DIR, i18n, RedirectResponse 303). Son el pegamento del sistema.
- Prueba cada módulo con el `TestClient` de FastAPI antes de pasar al siguiente.
- Es **single-tenant**: no metas `business_id` a menos que rehagas la plataforma.
