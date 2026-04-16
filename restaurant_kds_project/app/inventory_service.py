"""
Ingredient-level inventory service.

Design rules (enforced):
- Consumption happens ONLY at POS order confirmation.
- Idempotent by `reference` (e.g. "sale:123"): repeat calls are no-ops.
- Products without a Recipe are silently skipped (backward compatible).
- Negative stock is allowed (logged), never blocks the caller.
- All public functions are non-raising where noted.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from .models import Ingredient, Recipe, RecipeItem, InventoryMovement

logger = logging.getLogger("inventory")

VALID_TYPES = {"in", "out", "adjustment", "waste"}


def create_inventory_movement(
    db: Session,
    ingredient_id: int,
    mtype: str,
    quantity: float,
    reference: Optional[str] = None,
    commit: bool = True,
) -> Optional[InventoryMovement]:
    """
    Apply a stock delta and log the movement.
    - 'in' / positive 'adjustment' → stock += quantity
    - 'out' / 'waste' → stock -= quantity
    - 'adjustment' with negative quantity → decreases stock
    Returns the movement row, or None on invalid input.
    """
    if mtype not in VALID_TYPES:
        logger.warning("Rejected movement: invalid type %r", mtype)
        return None
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        logger.warning("Rejected movement: ingredient %s not found", ingredient_id)
        return None

    qty = float(quantity or 0)
    if mtype in ("out", "waste"):
        ing.stock = (ing.stock or 0) - abs(qty)
    else:  # in | adjustment
        ing.stock = (ing.stock or 0) + qty

    if ing.stock < 0:
        logger.warning(
            "Ingredient #%s (%s) stock is negative: %.4f (ref=%s)",
            ing.id, ing.name, ing.stock, reference,
        )

    mv = InventoryMovement(
        ingredient_id=ing.id,
        type=mtype,
        quantity=qty,
        reference=reference,
    )
    db.add(mv)
    if commit:
        db.commit()
        db.refresh(mv)
    else:
        db.flush()
    return mv


def _reference_exists(db: Session, reference: str) -> bool:
    if not reference:
        return False
    return db.query(InventoryMovement.id).filter(
        InventoryMovement.reference == reference
    ).first() is not None


def consume_recipe(
    db: Session,
    product_id: int,
    quantity: float = 1,
    reference: Optional[str] = None,
) -> bool:
    """
    Consume ingredient stock for `quantity` units of a product.
    Returns True if consumption happened, False if skipped (no recipe, duplicate, etc.).
    Never raises — callers wrap in try/except anyway, but this is defensive.
    """
    try:
        if reference and _reference_exists(db, reference):
            # Idempotency guard: already consumed for this reference.
            return False

        recipe = db.query(Recipe).filter(Recipe.product_id == product_id).first()
        if not recipe:
            return False  # no recipe → silently skip (backward compatible)

        items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
        if not items:
            return False

        for ri in items:
            total_needed = float(ri.quantity or 0) * float(quantity or 0)
            if total_needed <= 0:
                continue
            create_inventory_movement(
                db,
                ingredient_id=ri.ingredient_id,
                mtype="out",
                quantity=total_needed,
                reference=reference,
                commit=False,
            )
        return True
    except Exception:
        logger.exception("consume_recipe failed (product_id=%s ref=%s)", product_id, reference)
        return False
