from datetime import datetime, timedelta, date
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

# Costa Rica timezone (UTC-6)
def cr_now():
    """Return current UTC time adjusted to Costa Rica timezone (UTC-6)."""
    return datetime.utcnow() - timedelta(hours=6)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    image_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    price: Mapped[float] = mapped_column(Float, default=0)
    category: Mapped[str] = mapped_column(String(40), default="General")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


class Waiter(Base):
    __tablename__ = "waiters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    pin: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_role: Mapped[str] = mapped_column(String(50), nullable=False)  # station_a / kitchen
    status: Mapped[str] = mapped_column(String(50), default="nuevo", index=True)
    requires_acceptance: Mapped[bool] = mapped_column(Boolean, default=True)
    waiter_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("waiters.id"), nullable=True)
    waiter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    order_label: Mapped[str | None] = mapped_column(String(120), nullable=True)  # nombre de la orden (ej. Uber)
    table_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("tables.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    preparing_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)
    was_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    was_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    events = relationship("OrderEvent", back_populates="order", cascade="all, delete-orphan")
    table = relationship("Table")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    order = relationship("Order", back_populates="events")


class Inventory(Base):
    __tablename__ = "inventory"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)

    product = relationship("Product")


class InventoryLog(Base):
    __tablename__ = "inventory_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    old_quantity: Mapped[float] = mapped_column(Float, default=0)
    new_quantity: Mapped[float] = mapped_column(Float, default=0)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    product = relationship("Product")


class AudioSettings(Base):
    __tablename__ = "audio_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_order_sound_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kitchen_order_sound_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ready_sound_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cancel_sound_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    voice_enabled_for_station_orders: Mapped[bool] = mapped_column(Boolean, default=True)
    master_volume: Mapped[float] = mapped_column(Float, default=1.0)
    tax_rate: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    subtotal: Mapped[float] = mapped_column(Float, default=0)
    tax: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float, default=0)
    payment_method: Mapped[str] = mapped_column(String(50), default="efectivo")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")


class SaleItem(Base):
    __tablename__ = "sale_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    line_total: Mapped[float] = mapped_column(Float, default=0)

    sale = relationship("Sale", back_populates="items")
    product = relationship("Product")


# ─── Ingredient-level inventory (additive, optional) ─────────────────────────

class Ingredient(Base):
    """Master item: any ingredient, packaging, drink or supply. Single source
    of truth referenced by recipes, purchases, production and inventory."""
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="unit")   # base unit (g, kg, ml, L, unidad, pieza…)
    cost_per_unit: Mapped[float] = mapped_column(Float, default=0)   # cost per BASE unit (auto when purchase info set)
    stock: Mapped[float] = mapped_column(Float, default=0)           # in base unit
    category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    # ── purchase presentation & costing ──────────────────────────────────
    purchase_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)   # bolsa, caja, botella…
    pack_content: Mapped[float | None] = mapped_column(Float, nullable=True)        # base units per purchase unit (ej. 454 g)
    purchase_price: Mapped[float | None] = mapped_column(Float, nullable=True)      # price of one purchase presentation
    # ── yield / rendimiento (informational in phase 1) ───────────────────
    yield_qty: Mapped[float | None] = mapped_column(Float, nullable=True)           # porciones/piezas por presentación
    yield_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)       # porción, pieza…
    # ── stock control ────────────────────────────────────────────────────
    min_stock: Mapped[float] = mapped_column(Float, default=0)
    supplier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_purchase_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="activo")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    product = relationship("Product")
    items = relationship("RecipeItem", back_populates="recipe", cascade="all, delete-orphan")


class RecipeItem(Base):
    __tablename__ = "recipe_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0)

    recipe = relationship("Recipe", back_populates="items")
    ingredient = relationship("Ingredient")


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # in|out|adjustment|waste
    quantity: Mapped[float] = mapped_column(Float, default=0)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    ingredient = relationship("Ingredient")


class Purchase(Base):
    """A received purchase from a supplier (recepción de mercadería)."""
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    supplier: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    notes: Mapped[str | None] = mapped_column(String(300), nullable=True)
    total: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    items = relationship("PurchaseItem", back_populates="purchase", cascade="all, delete-orphan")


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id"), nullable=False)
    ingredient_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ingredient_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # snapshot
    qty: Mapped[float] = mapped_column(Float, default=0)             # presentations bought
    unit_price: Mapped[float] = mapped_column(Float, default=0)      # price per presentation
    pack_content: Mapped[float | None] = mapped_column(Float, nullable=True)  # base units per presentation (snapshot)
    base_units: Mapped[float] = mapped_column(Float, default=0)      # total base units received
    line_total: Mapped[float] = mapped_column(Float, default=0)

    purchase = relationship("Purchase", back_populates="items")


class ContactMessage(Base):
    """A lead submitted from the public landing 'Contact Us' form."""
    __tablename__ = "contact_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    restaurant: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(60), nullable=True)
    locations: Mapped[str | None] = mapped_column(String(20), nullable=True)   # 1 | 2-5 | 5+
    current_system: Mapped[str | None] = mapped_column(String(40), nullable=True)  # papel | otro-pos | nada
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="nuevo", index=True)  # nuevo|leido|contactado|archivado
    lang: Mapped[str | None] = mapped_column(String(5), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)


class AccessLog(Base):
    """Records each successful login/entry to any module."""
    __tablename__ = "access_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # admin|station|kitchen|inventory|pos
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    waiter_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)


class Expense(Base):
    """A registered business expense (gasto del negocio)."""
    __tablename__ = "expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    date: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    payment_method: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fixed_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # from a FixedExpense template
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)  # e.g. 'cuestionario'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


class FixedExpense(Base):
    """A recurring monthly expense template (gasto fijo)."""
    __tablename__ = "fixed_expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


class WorkSession(Base):
    """A clock-in / clock-out shift for a staff member on a given module."""
    __tablename__ = "work_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    waiter_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # station|kitchen|inventory|pos
    clock_in: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    clock_out: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)  # manually added/edited by admin


class InvoiceClient(Base):
    """Cliente (receptor) para factura electrónica de Hacienda (v4.4)."""
    __tablename__ = "invoice_clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    id_tipo: Mapped[str] = mapped_column(String(2), default="01")  # 01 Física, 02 Jurídica, 03 DIMEX, 04 NITE, 05 Extranjero, 06 No Contribuyente
    id_numero: Mapped[str] = mapped_column(String(20), nullable=False)
    correo: Mapped[str | None] = mapped_column(String(160), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


class FacturaConfig(Base):
    """Configuración del emisor + credenciales de Hacienda (fila única).
    Los secretos (clave ATV, PIN del certificado) se guardan cifrados."""
    __tablename__ = "factura_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ambiente: Mapped[str] = mapped_column(String(20), default="sandbox")  # sandbox | produccion
    emisor_nombre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    emisor_id_tipo: Mapped[str] = mapped_column(String(2), default="02")
    emisor_id_numero: Mapped[str | None] = mapped_column(String(20), nullable=True)
    emisor_actividad: Mapped[str | None] = mapped_column(String(6), nullable=True)  # código actividad económica
    emisor_provincia: Mapped[str | None] = mapped_column(String(1), nullable=True)
    emisor_canton: Mapped[str | None] = mapped_column(String(2), nullable=True)
    emisor_distrito: Mapped[str | None] = mapped_column(String(2), nullable=True)
    emisor_otras_senas: Mapped[str | None] = mapped_column(String(160), nullable=True)
    emisor_telefono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    emisor_correo: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sucursal: Mapped[str] = mapped_column(String(3), default="001")
    terminal: Mapped[str] = mapped_column(String(5), default="00001")
    consecutivo_num: Mapped[int] = mapped_column(Integer, default=0)  # último consecutivo de factura usado
    atv_usuario: Mapped[str | None] = mapped_column(String(160), nullable=True)
    atv_clave_enc: Mapped[str | None] = mapped_column(Text, nullable=True)      # cifrado
    cert_filename: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cert_pin_enc: Mapped[str | None] = mapped_column(Text, nullable=True)       # cifrado
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)


class Table(Base):
    """Mesa del salón para la vista de piso. Estado libre/ocupada (cierre manual)."""
    __tablename__ = "tables"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="libre")  # libre | ocupada
    capacity: Mapped[int] = mapped_column(Integer, default=4)  # sillas: forma redonda (<=2) o rect (>=3)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # inicio de la sesión actual
    pos_x: Mapped[float | None] = mapped_column(Float, nullable=True)  # posición en el plano (0-100 %)
    pos_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)


# ─── Control Sanitario / Higiene y Limpieza ──────────────────────────────────
# Programa de Higiene y Desinfección (concepto operativo Reglamento 37308-S CR).
# Módulo single-tenant, coherente con el resto de LISTO (un solo negocio).

def cr_today() -> date:
    """Fecha actual en zona de Costa Rica (UTC-6)."""
    return cr_now().date()


# Enums (whitelists validadas también en el backend).
CLEANING_FREQUENCIES = ["diaria", "varias_dia", "semanal", "segun_programacion"]
CLEANING_MOMENTS = ["apertura", "durante", "cierre", "otro"]
CLEANING_RECORD_STATES = ["pendiente", "en_proceso", "completada", "vencida", "verificada"]
INCIDENT_PRIORITIES = ["baja", "media", "alta", "critica"]
INCIDENT_STATES = ["abierta", "en_proceso", "resuelta"]
TEMP_EQUIPMENT_KINDS = ["refrigerador", "congelador", "equipo", "bano_maria"]
PEST_STATES = ["sin_evidencia", "activo", "controlado", "resuelto"]


class CleaningArea(Base):
    """Área física del establecimiento (Cocina, Baños, Campana…)."""
    __tablename__ = "cleaning_areas"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    tasks = relationship("CleaningTask", back_populates="area")


class CleaningTask(Base):
    """Definición del protocolo: una tarea de limpieza/desinfección de un área.
    La concentración y el tiempo de contacto se configuran según la ficha técnica
    del producto (no se inventan)."""
    __tablename__ = "cleaning_tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("cleaning_areas.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    procedure: Mapped[str | None] = mapped_column(Text, nullable=True)  # pasos, uno por línea
    frequency: Mapped[str] = mapped_column(String(30), default="diaria")  # ver CLEANING_FREQUENCIES
    times_per_day: Mapped[int] = mapped_column(Integer, default=1)  # para "varias_dia"
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=Lun … 6=Dom (para "semanal")
    moment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ver CLEANING_MOMENTS
    responsible: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product: Mapped[str | None] = mapped_column(String(200), nullable=True)      # producto de limpieza
    concentration: Mapped[str | None] = mapped_column(String(120), nullable=True)  # según ficha técnica
    contact_time: Mapped[str | None] = mapped_column(String(120), nullable=True)   # según ficha técnica
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)

    area = relationship("CleaningArea", back_populates="tasks")
    records = relationship("CleaningRecord", back_populates="task")


class CleaningRecord(Base):
    """Ejecución (o programación) de una tarea en un día. Auditable: los tiempos
    originales (created_at, started_at, completed_at, verified_at) no se editan."""
    __tablename__ = "cleaning_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("cleaning_tasks.id"), nullable=False, index=True)
    scheduled_date: Mapped[date] = mapped_column(Date, default=cr_today, index=True)
    slot: Mapped[int] = mapped_column(Integer, default=0)  # turno del día (0..times_per_day-1)
    status: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # confirmó el procedimiento
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)  # snapshot del nombre
    # Verificación (solo Admin) — fusiona el concepto CleaningVerification.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)

    task = relationship("CleaningTask", back_populates="records")


class CleaningIncident(Base):
    """Incidencia sanitaria y su acción correctiva."""
    __tablename__ = "cleaning_incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("cleaning_areas.id"), nullable=True, index=True)
    problem: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="media", index=True)  # ver INCIDENT_PRIORITIES
    reported_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reported_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="abierta", index=True)  # ver INCIDENT_STATES
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)

    area = relationship("CleaningArea")


class TemperatureEquipment(Base):
    """Equipo con control de temperatura y su rango configurable (no hardcodeado)."""
    __tablename__ = "temperature_equipments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="refrigerador")  # ver TEMP_EQUIPMENT_KINDS
    min_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_temp: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    records = relationship("TemperatureRecord", back_populates="equipment")


class TemperatureRecord(Base):
    """Lectura de temperatura de un equipo. out_of_range se calcula al guardar."""
    __tablename__ = "temperature_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("temperature_equipments.id"), nullable=False, index=True)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    out_of_range: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    equipment = relationship("TemperatureEquipment", back_populates="records")


class PestControlRecord(Base):
    """Registro de inspección/control de plagas."""
    __tablename__ = "pest_control_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    inspection_date: Mapped[date] = mapped_column(Date, default=cr_today, index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("cleaning_areas.id"), nullable=True, index=True)
    pest_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_taken: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="sin_evidencia", index=True)  # ver PEST_STATES
    observations: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)

    area = relationship("CleaningArea")


class SanitaryInspection(Base):
    """Snapshot de una autoinspección (basada en la Guía de Inspección, DAC anexo
    9 del Decreto 37308-S). Guarda la calificación y las respuestas para dejar
    evidencia y ver la evolución. Auditable: no se edita ni borra desde la UI."""
    __tablename__ = "sanitary_inspections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)          # puntos obtenidos
    possible: Mapped[int] = mapped_column(Integer, default=0)       # puntos aplicables (excluye "no aplica")
    score_pct: Mapped[int] = mapped_column(Integer, default=0)      # 0..100
    rating: Mapped[str | None] = mapped_column(String(40), nullable=True)  # etiqueta del rango
    critical_fail: Mapped[bool] = mapped_column(Boolean, default=False)    # falló algún punto crítico
    answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # {"A#0":"cumple", ...}
    section_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # resumen por sección
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)


# ─── Menú Online / QR (Fase 1: menú digital público) ─────────────────────────
# Single-tenant: el admin del restaurante arma su(s) página(s) de menú. Cada
# página tiene un slug público y su QR; dentro, varios menús por horario
# (Desayuno/Almuerzo) que se muestran como pestañas con auto-selección por hora.

class MenuPage(Base):
    """Página pública de menú (la 'storefront' que el admin nombra). Su slug
    define la URL /m/<slug> y su QR."""
    __tablename__ = "menu_pages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(140), unique=True, nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_image_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    theme_color: Mapped[str] = mapped_column(String(9), default="#ff8c42")  # acento
    currency: Mapped[str] = mapped_column(String(4), default="₡")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)

    menus = relationship("Menu", back_populates="page", cascade="all, delete-orphan")


class Menu(Base):
    """Un menú por horario dentro de una página (ej. Desayuno, Almuerzo).
    Si all_day es True, aplica siempre; si no, entre start_hm y end_hm."""
    __tablename__ = "menus"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("menu_pages.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    start_hm: Mapped[str | None] = mapped_column(String(5), nullable=True)  # "06:00"
    end_hm: Mapped[str | None] = mapped_column(String(5), nullable=True)    # "11:00"
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    page = relationship("MenuPage", back_populates="menus")
    items = relationship("MenuItem", back_populates="menu", cascade="all, delete-orphan")


class MenuItem(Base):
    """Ítem del menú. Puede enlazar a un Producto (para reusar catálogo/cocina)
    o ser suelto. La sección es texto libre (Entradas, Fuertes, Bebidas…)."""
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    menu_id: Mapped[int] = mapped_column(ForeignKey("menus.id"), nullable=False, index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    section: Mapped[str] = mapped_column(String(80), default="General")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    price: Mapped[float] = mapped_column(Float, default=0)  # precio base (si no hay variantes)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now)

    menu = relationship("Menu", back_populates="items")
    product = relationship("Product")
    variants = relationship("MenuItemVariant", back_populates="item", cascade="all, delete-orphan")


class MenuItemVariant(Base):
    """Variación de precio de un ítem (ej. Casado: Pollo/Res/Pescado)."""
    __tablename__ = "menu_item_variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[float] = mapped_column(Float, default=0)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    item = relationship("MenuItem", back_populates="variants")


# ─── Pedidos Online (Fase 2) ─────────────────────────────────────────────────
# El cliente arma su pedido desde la página pública (accedida por el QR de su
# mesa) y entra a una cola de aceptación que modera el staff. Flujo propio, no
# toca el KDS existente. Los precios se recalculan en el servidor.

ONLINE_ORDER_STATES = ["pendiente", "aceptado", "preparando", "listo", "entregado", "rechazado"]


class OnlineOrder(Base):
    __tablename__ = "online_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    page_id: Mapped[int | None] = mapped_column(ForeignKey("menu_pages.id"), nullable=True, index=True)
    table_id: Mapped[int | None] = mapped_column(ForeignKey("tables.id"), nullable=True, index=True)
    table_label: Mapped[str | None] = mapped_column(String(60), nullable=True)  # snapshot ("Mesa 5")
    customer_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)
    total: Mapped[float] = mapped_column(Float, default=0)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accepted_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=cr_now, onupdate=cr_now)

    items = relationship("OnlineOrderItem", back_populates="order", cascade="all, delete-orphan")
    table = relationship("Table")


class OnlineOrderItem(Base):
    __tablename__ = "online_order_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    online_order_id: Mapped[int] = mapped_column(ForeignKey("online_orders.id"), nullable=False, index=True)
    menu_item_id: Mapped[int | None] = mapped_column(ForeignKey("menu_items.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)          # snapshot
    variant_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit_price: Mapped[float] = mapped_column(Float, default=0)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    line_total: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    order = relationship("OnlineOrder", back_populates="items")
