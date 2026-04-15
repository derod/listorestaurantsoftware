from sqlalchemy.orm import Session
from .models import Product, AudioSettings

DEFAULT_PRODUCTS = [
    "Pescado",
    "Pollo a la plancha",
    "Sopa",
    "Café",
    "Jugo",
    "Arroz",
]


def seed_initial_data(db: Session):
    if db.query(Product).count() == 0:
        for idx, name in enumerate(DEFAULT_PRODUCTS):
            db.add(Product(name=name, display_order=idx))
    if db.query(AudioSettings).count() == 0:
        db.add(AudioSettings())
    db.commit()
