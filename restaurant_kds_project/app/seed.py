from sqlalchemy.orm import Session
from .models import Product, AudioSettings, Ingredient

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


def seed_initial_data(db: Session):
    if db.query(Product).count() == 0:
        for idx, name in enumerate(DEFAULT_PRODUCTS):
            db.add(Product(name=name, display_order=idx))
    if db.query(AudioSettings).count() == 0:
        db.add(AudioSettings())
    db.commit()
    seed_ingredient_catalog(db)
