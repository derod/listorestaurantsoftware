from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import Product, AudioSettings, Ingredient

# Real master inventory data (loaded once). name, category, base unit, purchase
# presentation, pack content (base units per presentation), purchase price,
# yield, stock, notes. Cost per base unit is auto = price / pack_content.
MASTER_INVENTORY = [
    # Proteínas
    {"name": "Bistec", "category": "Proteínas", "unit": "kg", "purchase_unit": "kg", "pack_content": 1, "purchase_price": 5500, "yield_qty": 7, "yield_unit": "porción", "stock": 0, "notes": "Existencia según compra"},
    {"name": "Pollo", "category": "Proteínas", "unit": "kg", "purchase_unit": "kg", "pack_content": 1, "purchase_price": 3400, "yield_qty": 6, "yield_unit": "porción", "stock": 0, "notes": "Existencia: 9 paquetes"},
    {"name": "Chuleta", "category": "Proteínas", "unit": "kg", "purchase_unit": "kg", "pack_content": 1, "purchase_price": 3500, "yield_qty": 6, "yield_unit": "porción", "stock": 0, "notes": "Existencia según compra"},
    {"name": "Pescado", "category": "Proteínas", "unit": "pieza", "purchase_unit": "5 cajas", "pack_content": 105, "purchase_price": 40000, "stock": 105, "notes": "7 paquetes × 15 piezas = 105"},
    {"name": "Jamón", "category": "Embutidos", "unit": "g", "purchase_unit": "bolsa", "pack_content": 454, "purchase_price": 3100, "stock": 3632, "notes": "8 bolsas × 454 g. Receta usa ~10 láminas."},
    {"name": "Gordon", "category": "Proteínas", "unit": "unidad", "stock": 11, "notes": "Pollo + Jamón. Precio pendiente."},
    # Granos
    {"name": "Arroz", "category": "Granos", "unit": "g", "purchase_unit": "bolsa", "purchase_price": 1000, "stock": 0, "notes": "17 bolsas. Definir peso de la bolsa para costo/g. Porción estándar: 215 g."},
    {"name": "Frijoles", "category": "Granos", "unit": "g", "purchase_unit": "bolsa", "purchase_price": 1000, "stock": 0, "notes": "44 bolsas. Definir peso. Porción estándar: 135 g."},
    {"name": "Azúcar", "category": "Granos", "unit": "g", "purchase_unit": "bolsa 3 kg", "pack_content": 3000, "stock": 0, "notes": "4 bolsas de 3 kg. Precio pendiente."},
    {"name": "Sal", "category": "Granos", "unit": "g", "purchase_unit": "bolsa", "purchase_price": 375, "stock": 0, "notes": "8 bolsas. Definir peso de la bolsa."},
    # Conservas
    {"name": "Maíz", "category": "Conservas", "unit": "lata", "purchase_unit": "lata", "pack_content": 1, "purchase_price": 800, "stock": 9},
    {"name": "Atún", "category": "Conservas", "unit": "lata", "purchase_unit": "lata", "pack_content": 1, "purchase_price": 650, "stock": 8, "notes": "180 g por lata (Corriente Azul)"},
    {"name": "Hongos", "category": "Conservas", "unit": "g", "purchase_unit": "lata", "pack_content": 2040, "purchase_price": 4500, "stock": 2040},
    # Condimentos y Salsas
    {"name": "Kim Ve Wong", "category": "Condimentos y Salsas", "unit": "ml", "purchase_unit": "botella", "purchase_price": 1500, "stock": 0, "notes": "2 botellas. Dura ~10 días. Definir ml por botella."},
    {"name": "Salsa Lizano", "category": "Condimentos y Salsas", "unit": "ml", "purchase_unit": "botella grande", "purchase_price": 10000, "stock": 0, "notes": "3 botellas grandes. Definir ml."},
    {"name": "Salsa de tomate", "category": "Condimentos y Salsas", "unit": "unidad", "purchase_unit": "unidad", "pack_content": 1, "purchase_price": 2000, "stock": 4},
    {"name": "Saxon Completo", "category": "Condimentos y Salsas", "unit": "g", "purchase_unit": "envase 2.72 kg", "pack_content": 2720, "purchase_price": 12800, "stock": 2720, "notes": "Dura 45 días (Badia)"},
    {"name": "Cúrcuma", "category": "Condimentos y Salsas", "unit": "g", "purchase_unit": "envase", "pack_content": 460, "purchase_price": 2000, "stock": 920, "notes": "Badia Turmeric. 2 envases."},
    {"name": "Pimienta Negra", "category": "Condimentos y Salsas", "unit": "g", "purchase_unit": "envase", "pack_content": 153, "purchase_price": 2700, "stock": 306, "notes": "Dura 1 mes. 2 envases."},
    # Bebidas
    {"name": "Té frío", "category": "Bebidas", "unit": "paquete", "purchase_unit": "paquete", "pack_content": 1, "purchase_price": 4000, "stock": 1},
    {"name": "Cas", "category": "Bebidas", "unit": "paquete", "purchase_unit": "paquete", "pack_content": 1, "stock": 2, "notes": "Precio pendiente."},
    {"name": "Mora", "category": "Bebidas", "unit": "paquete", "purchase_unit": "paquete", "pack_content": 1, "stock": 3, "notes": "Precio pendiente."},
    {"name": "Swiss Miss", "category": "Bebidas", "unit": "sobre", "purchase_unit": "caja", "pack_content": 60, "purchase_price": 6500, "stock": 55, "notes": "Caja de 60 sobres."},
    # Empaques
    {"name": "Envases 8x8 con división", "category": "Empaques", "unit": "paquete", "stock": 10},
    {"name": "Envases 6x9", "category": "Empaques", "unit": "paquete", "stock": 0, "notes": "Existencia pendiente."},
    {"name": "Papel encerado", "category": "Empaques", "unit": "caja", "stock": 1},
    {"name": "Papel aluminio", "category": "Empaques", "unit": "caja", "stock": 1},
    # Limpieza
    {"name": "Jabón para trastos", "category": "Limpieza", "unit": "unidad", "stock": 5},
    {"name": "Esponjas verdes", "category": "Limpieza", "unit": "unidad", "stock": 5},
    # Acompañamientos (porciones estándar; precio pendiente)
    {"name": "Arroz cantonés", "category": "Acompañamientos", "unit": "g", "stock": 0, "notes": "Porción estándar: 300 g. Precio pendiente."},
    {"name": "Chop Suey", "category": "Acompañamientos", "unit": "g", "stock": 0, "notes": "Porción estándar: 330 g. Precio pendiente."},
    {"name": "Yuca", "category": "Acompañamientos", "unit": "g", "stock": 0, "notes": "Porción estándar: 53 g. Precio pendiente."},
    {"name": "Plátano maduro", "category": "Acompañamientos", "unit": "g", "stock": 0, "notes": "Porción estándar: 70 g. Precio pendiente."},
]

DEFAULT_PRODUCTS = [
    "Pescado",
    "Pollo a la plancha",
    "Sopa",
    "Café",
    "Jugo",
    "Arroz",
]

# Base inventory catalog (insumos) grouped by category. Seeded once; existing
# ingredients (matched by name) are never touched — only missing ones are added.
INGREDIENT_CATALOG = [
    # Abarrotes
    ("Arroz", "Abarrotes"),
    ("Frijoles", "Abarrotes"),
    ("Azúcar", "Abarrotes"),
    ("Splenda", "Abarrotes"),
    ("Sal (bolsitas)", "Abarrotes"),
    ("Aceite", "Abarrotes"),
    ("Caracoles", "Abarrotes"),
    ("Pasta seca", "Abarrotes"),
    ("Dulce (bolsa)", "Abarrotes"),
    ("Café", "Abarrotes"),
    ("Chocolate (bolsita)", "Abarrotes"),
    ("Filtros", "Abarrotes"),
    ("Té de manzanilla", "Abarrotes"),
    ("Té negro", "Abarrotes"),
    ("Maicena", "Abarrotes"),
    ("Harina", "Abarrotes"),
    ("Mantequilla", "Abarrotes"),
    ("Arroz precocido", "Abarrotes"),
    ("Atún", "Abarrotes"),
    ("Petit Pois", "Abarrotes"),
    ("Maíz dulce", "Abarrotes"),
    # Salsas y condimentos
    ("Mayonesa", "Salsas y condimentos"),
    ("Salsa de tomate", "Salsas y condimentos"),
    ("Natilla", "Salsas y condimentos"),
    ("Hongos de lata", "Salsas y condimentos"),
    ("Vinagre", "Salsas y condimentos"),
    ("Salsa inglesa", "Salsas y condimentos"),
    ("Salsa soya", "Salsas y condimentos"),
    # Limpieza e higiene
    ("Cloro", "Limpieza e higiene"),
    ("Desinfectante", "Limpieza e higiene"),
    ("Alcohol en gel", "Limpieza e higiene"),
    ("Papel higiénico", "Limpieza e higiene"),
    ("Papel para manos", "Limpieza e higiene"),
    ("Toallas de cocina", "Limpieza e higiene"),
    ("Tefrío", "Limpieza e higiene"),
    ("Plástico (caja)", "Limpieza e higiene"),
    ("Papel aluminio", "Limpieza e higiene"),
    ("Jabón líquido", "Limpieza e higiene"),
    ("Jabón de trastes", "Limpieza e higiene"),
    ("Jabón en polvo", "Limpieza e higiene"),
    # Otros
    ("Confites", "Otros"),
    ("Vasos para café", "Otros"),
    ("Vasos para Coca-Cola", "Otros"),
]


def seed_ingredient_catalog(db: Session):
    """Add missing catalog ingredients once. Never modifies existing ones.

    Runs a single time: guarded by whether any ingredient already has a
    category. Skips names that already exist (case-insensitive)."""
    already_seeded = db.query(Ingredient).filter(Ingredient.category != None).count() > 0  # noqa: E711
    if already_seeded:
        return
    existing = {i.name.strip().lower() for i in db.query(Ingredient).all()}
    added = 0
    for name, category in INGREDIENT_CATALOG:
        key = name.strip().lower()
        if key in existing:
            continue  # already in inventory → leave it untouched
        db.add(Ingredient(name=name, unit="unid", category=category))
        existing.add(key)
        added += 1
    if added:
        db.commit()


def seed_master_inventory(db: Session):
    """Load the real master inventory once. Upserts by name and computes the
    cost per base unit (price / pack_content). Runs a single time: guarded by
    whether any ingredient already has a purchase_price (data loaded)."""
    if db.query(Ingredient).filter(Ingredient.purchase_price != None).count() > 0:  # noqa: E711
        return
    for r in MASTER_INVENTORY:
        ing = db.query(Ingredient).filter(func.lower(Ingredient.name) == r["name"].lower()).first()
        if not ing:
            ing = Ingredient(name=r["name"])
            db.add(ing)
        ing.category = r["category"]
        ing.unit = r["unit"]
        ing.purchase_unit = r.get("purchase_unit")
        ing.pack_content = r.get("pack_content")
        ing.purchase_price = r.get("purchase_price")
        ing.yield_qty = r.get("yield_qty")
        ing.yield_unit = r.get("yield_unit")
        ing.stock = r.get("stock", 0) or 0
        ing.min_stock = r.get("min_stock", 0) or 0
        ing.notes = r.get("notes")
        ing.status = "activo"
        pp, pc = r.get("purchase_price"), r.get("pack_content")
        ing.cost_per_unit = round(pp / pc, 4) if (pp and pc) else 0
    db.commit()


# Productos del menú de Desayuno. Se crean con categoría "Desayuno" y precio 0
# (ajustable en Admin). Los huevos usan solo el código como nombre.
BREAKFAST_PRODUCTS = [
    "Pinto Pequeño", "Pinto Mediano", "Pinto Grande",
    "Tortilla", "Pan", "Natilla", "Tostadas",
    "HpC", "HpS", "HpCeb", "HF", "HFC", "HpCC",
    "Salchicha", "Salchichón", "Jamón", "Queso", "Queso frito", "Queso blanco",
    "Bistec sin cebolla", "Bistec con cebolla",
    "Pollo a la plancha sin cebolla", "Pollo a la plancha con cebolla",
    "Agua dulce", "Café negro", "Café con leche", "Jugo natural",
]


def seed_breakfast_products(db: Session):
    """Crea los productos de Desayuno que falten (idempotente, por nombre).
    Precio 0 (ajustable en Admin). No reclasifica productos ya existentes."""
    existing = {n.lower() for (n,) in db.query(Product.name).all()}
    max_order = db.query(func.max(Product.display_order)).scalar() or 0
    added = False
    for name in BREAKFAST_PRODUCTS:
        if name.lower() in existing:
            continue
        max_order += 1
        db.add(Product(name=name, category="Desayuno", price=0, display_order=max_order, active=True))
        added = True
    if added:
        db.commit()


def seed_initial_data(db: Session):
    if db.query(Product).count() == 0:
        for idx, name in enumerate(DEFAULT_PRODUCTS):
            db.add(Product(name=name, display_order=idx))
    if db.query(AudioSettings).count() == 0:
        db.add(AudioSettings())
    db.commit()
    seed_ingredient_catalog(db)
    seed_master_inventory(db)
    seed_breakfast_products(db)
