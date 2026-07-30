"""
Admin-only ingredient inventory routes.

All endpoints require an authenticated admin session (same gate as /admin/*).
Mounted under /admin/inventory/* to keep the surface protected.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Ingredient, Recipe, RecipeItem, InventoryMovement, Product
from ..inventory_service import create_inventory_movement, VALID_TYPES

router = APIRouter(prefix="/admin/inv", tags=["admin-inventory"])


def _require_admin(request: Request):
    if request.session.get("admin_logged_in") is not True:
        raise HTTPException(401, "Admin session required")


# ─── schemas ─────────────────────────────────────────────────────────────────

class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="unit", max_length=20)
    cost_per_unit: float = 0          # manual fallback when no purchase info
    stock: float = 0
    category: Optional[str] = Field(default=None, max_length=80)
    # purchase presentation & costing
    purchase_unit: Optional[str] = Field(default=None, max_length=40)
    pack_content: Optional[float] = None
    purchase_price: Optional[float] = None
    # yield / rendimiento
    yield_qty: Optional[float] = None
    yield_unit: Optional[str] = Field(default=None, max_length=40)
    # control
    min_stock: float = 0
    supplier: Optional[str] = Field(default=None, max_length=200)
    expiry_date: Optional[str] = None   # YYYY-MM-DD
    status: Optional[str] = Field(default="activo", max_length=20)
    notes: Optional[str] = None


def _parse_date_opt(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def _cost_per_base_unit(purchase_price, pack_content):
    if purchase_price and pack_content and pack_content > 0:
        return round(purchase_price / pack_content, 4)
    return None


def _cost_per_portion(purchase_price, yield_qty):
    if purchase_price and yield_qty and yield_qty > 0:
        return round(purchase_price / yield_qty, 4)
    return None


def _apply_ingredient_fields(ing: Ingredient, p: IngredientIn):
    ing.unit = (p.unit or "unit").strip() or "unit"
    ing.stock = float(p.stock or 0)
    ing.category = (p.category.strip() if p.category else None) or None
    ing.purchase_unit = (p.purchase_unit.strip() if p.purchase_unit else None) or None
    ing.pack_content = float(p.pack_content) if p.pack_content else None
    ing.purchase_price = float(p.purchase_price) if p.purchase_price else None
    ing.yield_qty = float(p.yield_qty) if p.yield_qty else None
    ing.yield_unit = (p.yield_unit.strip() if p.yield_unit else None) or None
    ing.min_stock = float(p.min_stock or 0)
    ing.supplier = (p.supplier.strip() if p.supplier else None) or None
    ing.expiry_date = _parse_date_opt(p.expiry_date)
    ing.status = (p.status or "activo").strip() or "activo"
    ing.notes = (p.notes.strip() if p.notes else None) or None
    # Auto cost per base unit when purchase info is present; else manual value.
    cpb = _cost_per_base_unit(ing.purchase_price, ing.pack_content)
    ing.cost_per_unit = cpb if cpb is not None else float(p.cost_per_unit or 0)


def _serialize_ingredient(i: Ingredient):
    return {
        "id": i.id, "name": i.name, "unit": i.unit,
        "cost_per_unit": i.cost_per_unit, "stock": i.stock, "category": i.category,
        "purchase_unit": i.purchase_unit, "pack_content": i.pack_content,
        "purchase_price": i.purchase_price,
        "yield_qty": i.yield_qty, "yield_unit": i.yield_unit,
        "min_stock": i.min_stock or 0, "supplier": i.supplier,
        "expiry_date": i.expiry_date.strftime("%Y-%m-%d") if i.expiry_date else None,
        "status": i.status or "activo", "notes": i.notes,
        "cost_per_base_unit": _cost_per_base_unit(i.purchase_price, i.pack_content),
        "cost_per_portion": _cost_per_portion(i.purchase_price, i.yield_qty),
        "low": (i.min_stock or 0) > 0 and (i.stock or 0) <= (i.min_stock or 0),
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


class MovementIn(BaseModel):
    ingredient_id: int
    type: str  # in | out | adjustment | waste
    quantity: float
    reference: Optional[str] = None


class RecipeItemIn(BaseModel):
    ingredient_id: int
    quantity: float


class RecipeIn(BaseModel):
    product_id: int
    items: list[RecipeItemIn]


# ─── ingredients ─────────────────────────────────────────────────────────────

@router.get("/ingredients")
def list_ingredients(request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    rows = db.query(Ingredient).order_by(Ingredient.name.asc()).all()
    return [_serialize_ingredient(i) for i in rows]


@router.delete("/ingredients/{ingredient_id}")
def delete_ingredient(ingredient_id: int, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(404, "Insumo no encontrado")

    # Block deletion if the ingredient is used by any recipe — deleting it would
    # silently break a product's recipe. Ask the caller to unlink it first.
    used = (
        db.query(RecipeItem.id)
        .filter(RecipeItem.ingredient_id == ingredient_id)
        .first()
    )
    if used:
        product_ids = [
            r.product_id
            for r in db.query(Recipe.product_id)
            .join(RecipeItem, RecipeItem.recipe_id == Recipe.id)
            .filter(RecipeItem.ingredient_id == ingredient_id)
            .distinct()
            .all()
        ]
        names = [
            p.name
            for p in db.query(Product.name).filter(Product.id.in_(product_ids)).all()
        ]
        detail = ", ".join(names) if names else "una o más recetas"
        raise HTTPException(
            409,
            f"No se puede borrar: el insumo está en la receta de: {detail}. "
            "Quítalo de esas recetas antes de borrarlo.",
        )

    # No recipe references → safe to delete. Remove its movement history first
    # to satisfy the foreign key, then the ingredient itself.
    db.query(InventoryMovement).filter(
        InventoryMovement.ingredient_id == ingredient_id
    ).delete()
    db.delete(ing)
    db.commit()
    return {"deleted": ingredient_id}


@router.post("/ingredients")
def create_ingredient(payload: IngredientIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    exists = db.query(Ingredient).filter(Ingredient.name == payload.name).first()
    if exists:
        raise HTTPException(400, "Ingredient name already exists")
    ing = Ingredient(name=payload.name.strip())
    _apply_ingredient_fields(ing, payload)
    db.add(ing)
    db.commit()
    db.refresh(ing)
    return _serialize_ingredient(ing)


@router.put("/ingredients/{ingredient_id}")
def update_ingredient(ingredient_id: int, payload: IngredientIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(404, "Insumo no encontrado")
    new_name = payload.name.strip()
    if new_name and new_name != ing.name:
        clash = db.query(Ingredient).filter(Ingredient.name == new_name, Ingredient.id != ingredient_id).first()
        if clash:
            raise HTTPException(400, "Ya existe un insumo con ese nombre")
        ing.name = new_name
    _apply_ingredient_fields(ing, payload)
    db.commit()
    db.refresh(ing)
    return _serialize_ingredient(ing)


# ─── movements ───────────────────────────────────────────────────────────────

@router.post("/movements")
def create_movement(payload: MovementIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    if payload.type not in VALID_TYPES:
        raise HTTPException(400, f"Invalid type. Allowed: {sorted(VALID_TYPES)}")
    mv = create_inventory_movement(
        db,
        ingredient_id=payload.ingredient_id,
        mtype=payload.type,
        quantity=float(payload.quantity or 0),
        reference=payload.reference,
        commit=True,
    )
    if not mv:
        raise HTTPException(400, "Could not create movement (invalid ingredient or type)")
    return {"id": mv.id, "ingredient_id": mv.ingredient_id, "type": mv.type, "quantity": mv.quantity}


@router.get("/movements")
def list_movements(
    request: Request,
    ingredient_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    _require_admin(request)
    q = db.query(InventoryMovement)
    if ingredient_id:
        q = q.filter(InventoryMovement.ingredient_id == ingredient_id)
    rows = q.order_by(InventoryMovement.created_at.desc()).limit(max(1, min(limit, 500))).all()
    return [
        {
            "id": m.id,
            "ingredient_id": m.ingredient_id,
            "type": m.type,
            "quantity": m.quantity,
            "reference": m.reference,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


# ─── recipes ─────────────────────────────────────────────────────────────────

@router.post("/recipes")
def upsert_recipe(payload: RecipeIn, request: Request, db: Session = Depends(get_db)):
    _require_admin(request)
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(404, "Product not found")

    recipe = db.query(Recipe).filter(Recipe.product_id == payload.product_id).first()
    if not recipe:
        recipe = Recipe(product_id=payload.product_id)
        db.add(recipe)
        db.flush()
    else:
        # replace items atomically
        db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).delete()
        db.flush()

    for it in payload.items:
        if it.quantity is None or it.quantity <= 0:
            continue
        ing = db.query(Ingredient).filter(Ingredient.id == it.ingredient_id).first()
        if not ing:
            raise HTTPException(400, f"Ingredient {it.ingredient_id} not found")
        db.add(RecipeItem(recipe_id=recipe.id, ingredient_id=it.ingredient_id, quantity=float(it.quantity)))

    db.commit()
    db.refresh(recipe)
    return {"id": recipe.id, "product_id": recipe.product_id, "item_count": len(payload.items)}
