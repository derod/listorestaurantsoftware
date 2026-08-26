from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import (
    Product, AudioSettings, Ingredient, Table, Order,
    CleaningArea, CleaningTask, TemperatureEquipment,
    MenuPage, Menu, MenuItem, MenuItemVariant, MenuOptionGroup, MenuOption,
)

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


def seed_tables(db: Session, n: int = 12):
    """Crea las mesas 1..n solo en una base nueva (sin mesas). No rellena huecos
    para no recrear mesas eliminadas a propósito."""
    if db.query(Table.id).first():
        return
    for i in range(1, n + 1):
        db.add(Table(number=i, status="libre"))
    db.commit()


def reconfigure_tables_v2(db: Session):
    """Ajuste puntual del salón (una sola vez, guardado por: existe la 9 y no
    existe la 13): elimina la Mesa 9, renumera 11→14, 12→11, 10→12, agrega la
    Mesa 13 y fija posiciones del pie. Los pedidos de la mesa borrada se
    desligan (table_id → NULL); referencian por id, no por número."""
    t9 = db.query(Table).filter(Table.number == 9).first()
    if not t9 or db.query(Table).filter(Table.number == 13).first():
        return

    def renum(old, new):
        t = db.query(Table).filter(Table.number == old).first()
        if t:
            t.number = new
            db.flush()

    # Orden seguro para no chocar con el índice único de number.
    renum(11, 14)
    renum(12, 11)
    renum(10, 12)
    # Eliminar Mesa 9 (desligar sus pedidos primero).
    db.query(Order).filter(Order.table_id == t9.id).update({"table_id": None})
    db.delete(t9)
    db.flush()
    # Agregar Mesa 13.
    db.add(Table(number=13, status="libre"))
    db.flush()
    # Posiciones del pie (dos pares con la divisoria en el medio).
    foot = {8: (15, 74), 12: (45, 74), 11: (75, 74), 14: (45, 88), 13: (75, 88)}
    for num, (x, y) in foot.items():
        t = db.query(Table).filter(Table.number == num).first()
        if t:
            t.pos_x, t.pos_y = float(x), float(y)
    db.commit()


def seed_table_capacities(db: Session):
    """Asigna capacidades iniciales una sola vez (brazo 1-7 = 2 personas / redonda;
    el resto = 4 / rectangular). Guarda: se aplica si todas están en el default 4."""
    caps = [c for (c,) in db.query(Table.capacity).all()]
    if not caps or any((c or 4) != 4 for c in caps):
        return  # ya configurado a mano
    for t in db.query(Table).all():
        t.capacity = 2 if t.number in (1, 2, 3, 4, 5, 6, 7) else 4
    db.commit()


# ─── Control Sanitario: datos demo de SODA SILVIA ────────────────────────────
# Áreas del establecimiento. El orden define su presentación.
SANITARIO_AREAS = [
    "Cocina", "Baño María", "Baños", "Mesas", "Utensilios", "Refrigeradores",
    "Pisos", "Desagües", "Campana", "Área de atención", "Recipientes de residuos",
]

# Procedimiento estándar de limpieza y desinfección (recomendación operativa).
_PROC_LD = (
    "Retirar residuos\n"
    "Lavar con agua y jabón\n"
    "Enjuagar\n"
    "Aplicar desinfectante\n"
    "Respetar el tiempo de contacto según la ficha técnica del producto\n"
    "Secar\n"
    "Verificar"
)

# Tareas razonables por área (basadas en un Programa de Higiene y Desinfección).
# No se imponen concentraciones ni tiempos de contacto: se configuran según la
# ficha técnica del producto que use el negocio.
# (área, nombre, frecuencia, momento, veces/día, procedimiento)
SANITARIO_TASKS = [
    ("Cocina", "Limpieza y desinfección de superficies", "diaria", "cierre", 1, _PROC_LD),
    ("Baño María", "Limpieza y desinfección", "diaria", "cierre", 1, _PROC_LD),
    ("Baños", "Limpieza y desinfección", "varias_dia", "durante", 3, _PROC_LD),
    ("Mesas", "Limpieza y desinfección", "varias_dia", "durante", 4, _PROC_LD),
    ("Utensilios", "Lavado y desinfección de utensilios", "diaria", "cierre", 1, _PROC_LD),
    ("Refrigeradores", "Limpieza interna", "semanal", "apertura", 1, _PROC_LD),
    ("Pisos", "Barrido y trapeado", "diaria", "cierre", 1, "Barrer\nTrapear con solución de limpieza\nDesinfectar\nDejar secar"),
    ("Desagües", "Limpieza de desagües", "diaria", "cierre", 1, "Retirar rejilla\nRetirar residuos sólidos\nLavar\nDesinfectar\nColocar rejilla"),
    ("Campana", "Limpieza de campana y filtros", "segun_programacion", None, 1, "Retirar filtros\nDesengrasar\nLavar\nEnjuagar\nSecar\nColocar filtros"),
    ("Área de atención", "Limpieza y desinfección", "diaria", "apertura", 1, _PROC_LD),
    ("Recipientes de residuos", "Vaciado y desinfección", "diaria", "cierre", 1, "Vaciar\nLavar\nDesinfectar\nColocar bolsa nueva"),
]

# Equipos de temperatura de ejemplo con rangos EDITABLES (recomendación
# operativa, no requisito legal). El negocio ajusta los valores.
SANITARIO_TEMP_EQUIPMENT = [
    ("Refrigerador principal", "refrigerador", 0.0, 5.0),
    ("Congelador", "congelador", -18.0, -12.0),
]


def seed_sanitario_soda_silvia(db: Session):
    """Crea áreas, tareas y equipos de temperatura demo una sola vez.
    Guardado por: no existen áreas de limpieza. No toca datos existentes."""
    if db.query(CleaningArea.id).first():
        return
    areas = {}
    for idx, name in enumerate(SANITARIO_AREAS):
        a = CleaningArea(name=name, active=True, display_order=idx)
        db.add(a)
        areas[name] = a
    db.flush()  # asigna ids
    for area_name, tname, freq, moment, tpd, proc in SANITARIO_TASKS:
        a = areas.get(area_name)
        if not a:
            continue
        db.add(CleaningTask(
            area_id=a.id, name=tname, frequency=freq, moment=moment,
            times_per_day=tpd, procedure=proc, active=True,
        ))
    if db.query(TemperatureEquipment.id).first() is None:
        for name, kind, mn, mx in SANITARIO_TEMP_EQUIPMENT:
            db.add(TemperatureEquipment(name=name, kind=kind, min_temp=mn, max_temp=mx, active=True))
    db.commit()


def seed_menu_demo(db: Session):
    """Crea una página de menú demo (Soda Silvia) una sola vez, con Desayuno y
    Almuerzo por horario y un Casado con variantes de precio. Guardado por: no
    existe ninguna página de menú."""
    if db.query(MenuPage.id).first():
        return
    page = MenuPage(
        name="Soda Silvia", slug="soda-silvia", active=True,
        description="Comida casera costarricense. ¡Bienvenidos!",
        theme_color="#ff8c42", currency="₡",
    )
    db.add(page)
    db.flush()

    desayuno = Menu(page_id=page.id, name="Desayuno", start_hm="06:00", end_hm="11:00", display_order=1)
    almuerzo = Menu(page_id=page.id, name="Almuerzo", start_hm="11:00", end_hm="16:00", display_order=2)
    db.add_all([desayuno, almuerzo])
    db.flush()

    # Desayuno: los productos reales se cargan en seed_breakfast_combos (sin demos).

    # Almuerzo: Casado con variantes + otros
    casado = MenuItem(menu_id=almuerzo.id, name="Casado", section="Platos fuertes",
                      price=0, description="Arroz, frijoles, ensalada, plátano y su proteína.", display_order=1)
    db.add(casado)
    db.flush()
    for i, (label, pr) in enumerate([("Pollo", 3500), ("Res", 4000), ("Pescado", 4500)]):
        db.add(MenuItemVariant(item_id=casado.id, label=label, price=pr, display_order=i))
    for i, (n, sec, pr, desc) in enumerate([
        ("Arroz con pollo", "Platos fuertes", 3200, "Acompañado de ensalada."),
        ("Sopa de mariscos", "Platos fuertes", 4200, None),
        ("Fresco natural", "Bebidas", 1200, "Cas, mora o tamarindo."),
    ], start=2):
        db.add(MenuItem(menu_id=almuerzo.id, name=n, section=sec, price=pr, description=desc, display_order=i))
    db.commit()


# ── Desayunos con grupos de opciones (modificadores) ─────────────────────────
# Cada opción es (label, price_delta[, "pop"]). Grupo: (title, min, max, required, options).
_PREP = [("Huevo frito", 0), ("Huevo revuelto", 0), ("Huevo revuelto con cebolla", 0), ("Huevo revuelto con cebollin", 0)]
_PROT = [("Jamón", 0), ("Salchicha", 0), ("Salchichón", 0)]
_TEA = [("Té frío de limón", 0)]
_COFFEE = [("Cafe", 1100), ("Cafe con Leche", 1200), ("Te de Manzanilla", 950, "pop")]
_SODA = [("Coca-Cola Zero 600ml", 1600), ("Ginger Ale Light 600ml", 1600)]


def _extras(salchichon, queso_blanco, huevito):
    return [("Dos porciones de jamón", 900), ("Salchicha", 900),
            ("Cuatro porciones de salchichón", salchichon), ("Queso blanco", queso_blanco),
            ("Queso frito", 900), ("Huevito Extra", huevito, "pop")]


BREAKFAST_COMBOS = [
    {
        "name": "Gallo Pinto Típico Especial", "price": 2850,
        "description": "Huevo al gusto, delicioso gallo pinto, pan, natilla y platanitos maduros. Te incluye una bebida té frío.",
        "groups": [
            ("Elige el tipo de preparación", 1, 1, True, _PREP),
            ("¿Deseas unos deliciosos extras?", 0, 5, False, _extras(950, 900, 900)),
            ("Elige el que prefieras (gratis)", 0, 1, False, _TEA),
            ("Un Cafecito?", 0, 5, False, _COFFEE),
            ("Agrega una gaseosa grande a tu pedido", 0, 2, False, _SODA),
        ],
    },
    {
        "name": "Two Pack de Gallo Pinto", "price": 5500,
        "description": "Dos platos deliciosos: huevos al gusto, puede incluir jamón, salchicha o salchichón de gratis. Gallo pinto, pan, natilla y platanitos maduros.",
        "groups": [
            ("Elige el tipo de preparación", 1, 1, True, _PREP),
            ("Elige el tipo de preparación del segundo plato", 1, 1, True, _PREP),
            ("Elige tu proteína favorita", 0, 1, False, _PROT),
            ("Elige tu proteína favorita — segundo plato", 0, 1, False, _PROT),
            ("Elige lo que prefieras (Gratis)", 0, 1, False, _TEA),
            ("¿Deseas unos deliciosos extras?", 0, 5, False, _extras(950, 900, 900)),
            ("Elige lo que prefieras (Gratis) — segundo plato", 0, 1, False, _TEA),
            ("¿Deseas unos deliciosos extras? Platillo 2", 0, 5, False, _extras(750, 750, 750)),
            ("Un Cafecito?", 0, 5, False, _COFFEE),
            ("Agrega una gaseosa grande a tu pedido", 0, 2, False, _SODA),
        ],
    },
    {
        "name": "Three Pack de Gallo Pinto (Special Promo)", "price": 7500,
        "description": "Tres deliciosos platillos completos: huevos al gusto (fritos o revueltos), con jamón, salchicha o salchichón, gallo pinto, pan, natilla y platanitos maduros.",
        "groups": [
            ("Elige el tipo de preparación del primer plato", 1, 1, True, _PREP),
            ("Elige el tipo de preparación del segundo plato", 1, 1, True, _PREP),
            ("Elige el tipo de preparación del tercer plato", 1, 1, True, _PREP),
            ("Elige tu proteína preferida del primer plato", 0, 1, False, _PROT),
            ("Elige tu proteína preferida del segundo plato", 0, 1, False, _PROT),
            ("Elige el tipo de proteína del tercer plato", 0, 1, False, _PROT),
            ("Elige lo que prefieras del primer plato (Gratis)", 0, 1, False, _TEA),
            ("Elige lo que prefieras del segundo plato (Gratis)", 0, 1, False, _TEA),
            ("Elige lo que prefieras del tercer plato (Gratis)", 0, 1, False, _TEA),
            ("¿Deseas unos deliciosos extras? Platillo 1", 0, 5, False, _extras(750, 750, 900)),
            ("¿Deseas unos deliciosos extras? Platillo 2", 0, 5, False, _extras(750, 900, 750)),
            ("¿Deseas unos deliciosos extras? Platillo 3", 0, 5, False, _extras(750, 750, 750)),
        ],
    },
]


def seed_breakfast_combos(db: Session):
    """Add the 3 breakfast combos with their option groups (idempotent by name)."""
    page = db.query(MenuPage).filter(MenuPage.slug == "soda-silvia").first()
    if not page:
        return
    desayuno = db.query(Menu).filter(Menu.page_id == page.id, Menu.name == "Desayuno").first()
    if not desayuno:
        return
    existing = {i.name for i in db.query(MenuItem).filter(MenuItem.menu_id == desayuno.id).all()}
    order0 = db.query(func.count(MenuItem.id)).filter(MenuItem.menu_id == desayuno.id).scalar() or 0
    changed = False
    for pdef in BREAKFAST_COMBOS:
        if pdef["name"] in existing:
            continue
        item = MenuItem(menu_id=desayuno.id, section="Desayuno", name=pdef["name"],
                        description=pdef["description"], price=pdef["price"], display_order=order0)
        db.add(item)
        db.flush()
        order0 += 1
        for gi, (title, mn, mx, req, opts) in enumerate(pdef["groups"]):
            g = MenuOptionGroup(item_id=item.id, title=title, min_select=mn, max_select=mx, required=req, display_order=gi)
            db.add(g)
            db.flush()
            for oi, opt in enumerate(opts):
                price = opt[1] if len(opt) > 1 else 0
                pop = len(opt) > 2 and opt[2] == "pop"
                db.add(MenuOption(group_id=g.id, label=opt[0], price_delta=price, popular=pop, display_order=oi))
        changed = True
    if changed:
        db.commit()


_DEMO_BREAKFAST = [("Gallo Pinto", 1800), ("Huevos al gusto", 1500), ("Café", 700), ("Jugo natural", 1200)]


def cleanup_demo_breakfast(db: Session):
    """Remove the old demo breakfast placeholders that duplicated the real
    combos. Exact name+price match and no option groups, so real items the
    owner built are never deleted. Idempotent."""
    page = db.query(MenuPage).filter(MenuPage.slug == "soda-silvia").first()
    if not page:
        return
    desayuno = db.query(Menu).filter(Menu.page_id == page.id, Menu.name == "Desayuno").first()
    if not desayuno:
        return
    changed = False
    for name, price in _DEMO_BREAKFAST:
        for it in db.query(MenuItem).filter(MenuItem.menu_id == desayuno.id, MenuItem.name == name).all():
            if abs(float(it.price or 0) - price) < 0.5 and not it.option_groups:
                db.delete(it)
                changed = True
    if changed:
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
    seed_tables(db)
    reconfigure_tables_v2(db)
    seed_table_capacities(db)
    seed_sanitario_soda_silvia(db)
    seed_menu_demo(db)
    seed_breakfast_combos(db)
    cleanup_demo_breakfast(db)
