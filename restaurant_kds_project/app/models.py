from datetime import datetime, timedelta
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Float
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
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="unit")
    cost_per_unit: Mapped[float] = mapped_column(Float, default=0)
    stock: Mapped[float] = mapped_column(Float, default=0)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
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
