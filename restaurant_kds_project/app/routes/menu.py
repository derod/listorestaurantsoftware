"""
Menú Online / QR — Fase 1: menú digital público accesible por QR.

Single-tenant: el admin arma páginas de menú (cada una con su slug/URL y QR).
Dentro de una página hay varios menús por horario (Desayuno/Almuerzo) que en la
página pública se muestran como pestañas con auto-selección según la hora.

La configuración va detrás del login de admin; la página /m/<slug> es pública
(solo lectura en esta fase; el auto-pedido del cliente es la Fase 2).
"""
from __future__ import annotations

import io as _io
import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db, DATA_DIR
from ..models import (
    MenuPage, Menu, MenuItem, MenuItemVariant, MenuOptionGroup, MenuOption, Product, Table,
    OnlineOrder, OnlineOrderItem, ONLINE_ORDER_STATES,
    Order, OrderItem, OrderEvent, cr_now,
)
from .web import templates, require_admin

router = APIRouter()

MENU_IMG_DIR = DATA_DIR / "uploads" / "menu"
MENU_IMG_DIR.mkdir(parents=True, exist_ok=True)
_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


# ─── helpers ──────────────────────────────────────────────────────────────────

def _admin(request: Request):
    return require_admin(request)


def _slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "menu"


def _unique_slug(db: Session, base: str, exclude_id: int | None = None) -> str:
    slug = base
    n = 1
    while True:
        q = db.query(MenuPage.id).filter(MenuPage.slug == slug)
        if exclude_id:
            q = q.filter(MenuPage.id != exclude_id)
        if not q.first():
            return slug
        n += 1
        slug = f"{base}-{n}"


def _hm_to_min(hm: str | None):
    if not hm:
        return None
    try:
        h, m = hm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _menu_active_now(m: Menu, now_min: int) -> bool:
    if m.all_day:
        return True
    a, b = _hm_to_min(m.start_hm), _hm_to_min(m.end_hm)
    if a is None or b is None:
        return False
    if a <= b:
        return a <= now_min < b
    return now_min >= a or now_min < b  # ventana que cruza medianoche


def _save_image(upload: UploadFile, prefix: str) -> str | None:
    if not upload or not getattr(upload, "filename", ""):
        return None
    ext = Path(upload.filename).suffix.lower()
    if ext not in _IMG_EXT:
        return None
    safe = f"{prefix}{ext}"
    dest = MENU_IMG_DIR / safe
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return f"/uploads/menu/{safe}"


def _sections(items: list[MenuItem]):
    """Agrupa ítems por sección preservando el orden de aparición."""
    order = []
    by_sec = {}
    for it in sorted(items, key=lambda x: (x.display_order, x.id)):
        sec = (it.section or "General").strip() or "General"
        if sec not in by_sec:
            by_sec[sec] = []
            order.append(sec)
        by_sec[sec].append(it)
    return [(s, by_sec[s]) for s in order]


# ══════════════════════════════════════════════════════════════════════════════
#  PÚBLICO
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/m/{slug}")
def public_menu(slug: str, request: Request, mesa: str = "", pickup: str = "", db: Session = Depends(get_db)):
    page = (
        db.query(MenuPage)
        .options(
            joinedload(MenuPage.menus).joinedload(Menu.items).joinedload(MenuItem.variants),
            joinedload(MenuPage.menus).joinedload(Menu.items).joinedload(MenuItem.option_groups).joinedload(MenuOptionGroup.options),
        )
        .filter(MenuPage.slug == slug, MenuPage.active == True).first()  # noqa: E712
    )
    if not page:
        return templates.TemplateResponse(
            "menu_public.html",
            {"request": request, "page": None, "page_title": "Menú no encontrado"},
            status_code=404,
        )
    # Contexto de mesa (QR) o modo "recoger" (cliente logueado desde /cliente).
    table = None
    if mesa.isdigit():
        table = db.query(Table).filter(Table.id == int(mesa)).first()
    is_pickup = pickup in ("1", "true", "si", "yes")
    menus = sorted([m for m in page.menus if m.active], key=lambda m: (m.display_order, m.id))
    now = cr_now()
    now_min = now.hour * 60 + now.minute
    active_index = next((i for i, m in enumerate(menus) if _menu_active_now(m, now_min)), 0)
    menus_view = []
    for m in menus:
        items = [it for it in m.items if it.available]
        menus_view.append({
            "id": m.id, "name": m.name,
            "schedule": ("Todo el día" if m.all_day else (f"{m.start_hm}–{m.end_hm}" if m.start_hm and m.end_hm else "")),
            "sections": _sections(items),
        })
    return templates.TemplateResponse(
        "menu_public.html",
        {
            "request": request, "page": page, "menus": menus_view,
            "active_index": active_index, "currency": page.currency or "₡",
            "theme": page.theme_color or "#ff8c42",
            "ordering": (table is not None) or is_pickup,
            "pickup": is_pickup,
            "table_id": table.id if table else None,
            "table_label": (("Mesa " + str(table.number)) + ((" · " + table.name) if table.name else "")) if table else None,
            "page_title": page.name,
        },
    )


# ─── público: enviar pedido (carrito → cola de aceptación) ────────────────────

class OnlineOrderLine(BaseModel):
    menu_item_id: int
    variant_id: int | None = None
    quantity: int = 1
    note: str | None = None
    option_ids: list[int] | None = None


class OnlineOrderIn(BaseModel):
    table_id: int | None = None
    pickup: bool = False
    pickup_time: str | None = None
    customer_name: str | None = None
    phone: str | None = None
    note: str | None = None
    items: list[OnlineOrderLine]


@router.post("/m/{slug}/pedido")
def public_place_order(slug: str, payload: OnlineOrderIn, request: Request, db: Session = Depends(get_db)):
    """Crea un pedido online. Página pública: valida todo contra la BD y
    RECALCULA los precios en el servidor (no confía en el cliente)."""
    page = db.query(MenuPage).filter(MenuPage.slug == slug, MenuPage.active == True).first()  # noqa: E712
    if not page:
        raise HTTPException(404, "Menú no encontrado")
    is_pickup = bool(payload.pickup)
    table = None
    if not is_pickup:
        table = db.query(Table).filter(Table.id == payload.table_id).first()
        if not table:
            raise HTTPException(400, "Mesa inválida")
    if not payload.items or len(payload.items) > 40:
        raise HTTPException(400, "Pedido vacío o demasiado grande")

    # IDs de menús activos de esta página (para no aceptar ítems ajenos).
    menu_ids = {m.id for m in page.menus if m.active}
    order = OnlineOrder(
        page_id=page.id,
        table_id=(table.id if table else None),
        table_label=(("Mesa " + str(table.number)) if table else None),
        customer_name=(payload.customer_name or "").strip()[:120] or None,
        phone=(payload.phone or "").strip()[:40] or None,
        pickup_time=(payload.pickup_time or "").strip()[:20] or None,
        note=(payload.note or "").strip()[:500] or None,
        status="pendiente", total=0,
    )
    db.add(order)
    db.flush()

    total = 0.0
    line_count = 0
    for line in payload.items:
        it = db.query(MenuItem).filter(MenuItem.id == line.menu_item_id).first()
        if not it or it.menu_id not in menu_ids or not it.available:
            continue
        qty = max(1, min(int(line.quantity or 1), 20))
        variant_label = None
        unit = float(it.price or 0)
        if line.variant_id:
            v = db.query(MenuItemVariant).filter(
                MenuItemVariant.id == line.variant_id, MenuItemVariant.item_id == it.id
            ).first()
            if v:
                variant_label = v.label
                unit = float(v.price or 0)
        elif it.variants:
            # el ítem exige variante y no se eligió → se omite la línea
            continue
        # Modifiers (option groups): recompute price on the server from the
        # chosen option ids that actually belong to this item.
        modifiers_text = None
        if line.option_ids:
            opts = (
                db.query(MenuOption)
                .join(MenuOptionGroup, MenuOption.group_id == MenuOptionGroup.id)
                .filter(MenuOption.id.in_(line.option_ids), MenuOptionGroup.item_id == it.id)
                .order_by(MenuOptionGroup.display_order, MenuOption.display_order)
                .all()
            )
            if opts:
                unit += sum(float(o.price_delta or 0) for o in opts)
                modifiers_text = " · ".join(o.label for o in opts)[:500]
        line_total = round(unit * qty, 2)
        total += line_total
        db.add(OnlineOrderItem(
            online_order_id=order.id, menu_item_id=it.id, name=it.name,
            variant_label=variant_label, unit_price=unit, quantity=qty,
            line_total=line_total, note=(line.note or "").strip()[:200] or None,
            modifiers=modifiers_text,
        ))
        line_count += 1

    if line_count == 0:
        db.delete(order)
        db.commit()
        raise HTTPException(400, "No se pudo registrar ninguna línea del pedido")
    order.total = round(total, 2)
    db.commit()

    result = {"ok": True, "order_id": order.id, "total": order.total}
    # Loyalty: an online order with a phone earns one star per day.
    if payload.phone:
        from .loyalty import award_star_for_phone
        star = award_star_for_phone(db, payload.phone, source="pedido_online", name=order.customer_name)
        result["star_awarded"] = bool(star.get("awarded"))
        result["stars_total"] = star.get("total_stars")
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/admin/menu")
def admin_menu_list(request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    pages = db.query(MenuPage).order_by(MenuPage.created_at.desc()).all()
    view = []
    for p in pages:
        view.append({"p": p, "menus": len(p.menus),
                     "items": sum(len(m.items) for m in p.menus)})
    return templates.TemplateResponse(
        "admin_menu_list.html",
        {"request": request, "pages": view, "pending": pending_online_count(db), "page_title": "Menú Online"},
    )


@router.post("/admin/menu")
def admin_menu_create(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    name = name.strip()
    if name:
        page = MenuPage(name=name[:120], slug=_unique_slug(db, _slugify(name)))
        db.add(page)
        db.commit()
        return RedirectResponse(url=f"/admin/menu/{page.id}", status_code=303)
    return RedirectResponse(url="/admin/menu", status_code=303)


@router.get("/admin/menu/{page_id:int}")
def admin_menu_builder(page_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    page = (
        db.query(MenuPage)
        .options(
            joinedload(MenuPage.menus).joinedload(Menu.items).joinedload(MenuItem.variants),
            joinedload(MenuPage.menus).joinedload(Menu.items).joinedload(MenuItem.option_groups).joinedload(MenuOptionGroup.options),
        )
        .filter(MenuPage.id == page_id).first()
    )
    if not page:
        return RedirectResponse(url="/admin/menu")
    menus = sorted(page.menus, key=lambda m: (m.display_order, m.id))
    products = db.query(Product).filter(Product.active == True).order_by(Product.name).all()  # noqa: E712
    return templates.TemplateResponse(
        "admin_menu_builder.html",
        {"request": request, "page": page, "menus": menus, "products": products,
         "sections_fn": _sections, "page_title": f"Menú · {page.name}"},
    )


@router.post("/admin/menu/{page_id}/edit")
async def admin_menu_edit(page_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    page = db.query(MenuPage).filter(MenuPage.id == page_id).first()
    if not page:
        return RedirectResponse(url="/admin/menu")
    form = await request.form()

    def g(k):
        return (form.get(k) or "").strip()

    if g("name"):
        page.name = g("name")[:120]
    if g("slug"):
        page.slug = _unique_slug(db, _slugify(g("slug")), exclude_id=page.id)
    page.description = g("description") or None
    tc = g("theme_color")
    if re.match(r"^#[0-9A-Fa-f]{6}$", tc):
        page.theme_color = tc
    page.currency = (g("currency") or "₡")[:4]
    page.active = form.get("active") == "on"
    cover = form.get("cover")
    if cover is not None and getattr(cover, "filename", ""):
        saved = _save_image(cover, f"page_{page.id}_cover")
        if saved:
            page.cover_image_path = saved
    db.commit()
    return RedirectResponse(url=f"/admin/menu/{page.id}", status_code=303)


@router.post("/admin/menu/{page_id}/delete")
def admin_menu_delete(page_id: int, request: Request, confirm: str = Form(""), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    if confirm == "CONFIRMAR":
        page = db.query(MenuPage).filter(MenuPage.id == page_id).first()
        if page:
            db.delete(page)
            db.commit()
    return RedirectResponse(url="/admin/menu", status_code=303)


# ─── menús (horarios) ─────────────────────────────────────────────────────────

@router.post("/admin/menu/{page_id}/menus")
def admin_menu_add(page_id: int, request: Request,
                   name: str = Form(...), all_day: str = Form(""),
                   start_hm: str = Form(""), end_hm: str = Form(""),
                   db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    if name.strip():
        last = db.query(func.max(Menu.display_order)).filter(Menu.page_id == page_id).scalar() or 0
        db.add(Menu(
            page_id=page_id, name=name.strip()[:120],
            all_day=(all_day == "on"),
            start_hm=(start_hm.strip() or None), end_hm=(end_hm.strip() or None),
            display_order=last + 1,
        ))
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{page_id}", status_code=303)


@router.post("/admin/menu/menus/{menu_id}/edit")
def admin_submenu_edit(menu_id: int, request: Request,
                       name: str = Form(...), all_day: str = Form(""),
                       start_hm: str = Form(""), end_hm: str = Form(""),
                       active: str = Form(""), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    if m and name.strip():
        m.name = name.strip()[:120]
        m.all_day = (all_day == "on")
        m.start_hm = (start_hm.strip() or None)
        m.end_hm = (end_hm.strip() or None)
        m.active = (active == "on")
        db.commit()
    pid = m.page_id if m else 0
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


@router.post("/admin/menu/menus/{menu_id}/delete")
def admin_submenu_delete(menu_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    pid = m.page_id if m else 0
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


# ─── ítems ────────────────────────────────────────────────────────────────────

@router.post("/admin/menu/menus/{menu_id}/items")
def admin_item_add(menu_id: int, request: Request,
                   name: str = Form(...), section: str = Form("General"),
                   price: str = Form("0"), description: str = Form(""),
                   product_id: str = Form(""), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    m = db.query(Menu).filter(Menu.id == menu_id).first()
    if not m:
        return RedirectResponse(url="/admin/menu", status_code=303)
    pid = None
    nm = name.strip()
    pr = _to_float(price)
    if product_id.isdigit():
        prod = db.query(Product).filter(Product.id == int(product_id)).first()
        if prod:
            pid = prod.id
            if not nm:
                nm = prod.name
            if pr == 0:
                pr = float(prod.price or 0)
    if nm:
        last = db.query(func.max(MenuItem.display_order)).filter(MenuItem.menu_id == menu_id).scalar() or 0
        db.add(MenuItem(
            menu_id=menu_id, product_id=pid, name=nm[:200],
            section=(section.strip()[:80] or "General"),
            price=pr, description=(description.strip() or None),
            display_order=last + 1,
        ))
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{m.page_id}", status_code=303)


@router.post("/admin/menu/items/{item_id}/edit")
def admin_item_edit(item_id: int, request: Request,
                    name: str = Form(...), section: str = Form("General"),
                    price: str = Form("0"), description: str = Form(""),
                    db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    it = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if it and name.strip():
        it.name = name.strip()[:200]
        it.section = (section.strip()[:80] or "General")
        it.price = _to_float(price)
        it.description = (description.strip() or None)
        db.commit()
    pid = _item_page_id(db, it)
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


@router.post("/admin/menu/items/{item_id}/photo")
def admin_item_photo(item_id: int, request: Request, photo: UploadFile = File(...), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    it = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if it:
        saved = _save_image(photo, f"item_{item_id}")
        if saved:
            it.image_path = saved
            db.commit()
    pid = _item_page_id(db, it)
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


@router.post("/admin/menu/items/{item_id}/toggle")
def admin_item_toggle(item_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    it = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if it:
        it.available = not it.available
        db.commit()
    pid = _item_page_id(db, it)
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


@router.post("/admin/menu/items/{item_id}/delete")
def admin_item_delete(item_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    it = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    pid = _item_page_id(db, it)
    if it:
        db.delete(it)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


# ─── variantes de precio ──────────────────────────────────────────────────────

@router.post("/admin/menu/items/{item_id}/variants")
def admin_variant_add(item_id: int, request: Request, label: str = Form(...), price: str = Form("0"), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    it = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if it and label.strip():
        last = db.query(func.max(MenuItemVariant.display_order)).filter(MenuItemVariant.item_id == item_id).scalar() or 0
        db.add(MenuItemVariant(item_id=item_id, label=label.strip()[:120], price=_to_float(price), display_order=last + 1))
        db.commit()
    pid = _item_page_id(db, it)
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


@router.post("/admin/menu/variants/{variant_id}/delete")
def admin_variant_delete(variant_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    v = db.query(MenuItemVariant).filter(MenuItemVariant.id == variant_id).first()
    pid = 0
    if v:
        it = db.query(MenuItem).filter(MenuItem.id == v.item_id).first()
        pid = _item_page_id(db, it)
        db.delete(v)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


# ─── Grupos de opciones (modificadores) ──────────────────────────────────────
def _int(v, default=0):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def _group_page_id(db, group):
    if not group:
        return 0
    it = db.query(MenuItem).filter(MenuItem.id == group.item_id).first()
    return _item_page_id(db, it)


@router.post("/admin/menu/items/{item_id}/optgroups")
def admin_optgroup_add(item_id: int, request: Request, title: str = Form(...),
                       min_select: str = Form("0"), max_select: str = Form("1"),
                       required: str = Form(None), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    it = db.query(MenuItem).filter(MenuItem.id == item_id).first()
    if it and title.strip():
        last = db.query(func.max(MenuOptionGroup.display_order)).filter(MenuOptionGroup.item_id == item_id).scalar() or 0
        db.add(MenuOptionGroup(item_id=item_id, title=title.strip()[:160],
                               min_select=max(0, _int(min_select, 0)), max_select=max(1, _int(max_select, 1)),
                               required=bool(required), display_order=last + 1))
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{_item_page_id(db, it)}", status_code=303)


@router.post("/admin/menu/optgroups/{group_id}/edit")
def admin_optgroup_edit(group_id: int, request: Request, title: str = Form(...),
                        min_select: str = Form("0"), max_select: str = Form("1"),
                        required: str = Form(None), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    g = db.query(MenuOptionGroup).filter(MenuOptionGroup.id == group_id).first()
    if g and title.strip():
        g.title = title.strip()[:160]
        g.min_select = max(0, _int(min_select, 0))
        g.max_select = max(1, _int(max_select, 1))
        g.required = bool(required)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{_group_page_id(db, g)}", status_code=303)


@router.post("/admin/menu/optgroups/{group_id}/delete")
def admin_optgroup_delete(group_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    g = db.query(MenuOptionGroup).filter(MenuOptionGroup.id == group_id).first()
    pid = _group_page_id(db, g)
    if g:
        db.delete(g)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


@router.post("/admin/menu/optgroups/{group_id}/options")
def admin_option_add(group_id: int, request: Request, label: str = Form(...),
                     price: str = Form("0"), popular: str = Form(None), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    g = db.query(MenuOptionGroup).filter(MenuOptionGroup.id == group_id).first()
    if g and label.strip():
        last = db.query(func.max(MenuOption.display_order)).filter(MenuOption.group_id == group_id).scalar() or 0
        db.add(MenuOption(group_id=group_id, label=label.strip()[:160],
                          price_delta=_to_float(price), popular=bool(popular), display_order=last + 1))
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{_group_page_id(db, g)}", status_code=303)


@router.post("/admin/menu/options/{option_id}/edit")
def admin_option_edit(option_id: int, request: Request, label: str = Form(...),
                      price: str = Form("0"), popular: str = Form(None), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    o = db.query(MenuOption).filter(MenuOption.id == option_id).first()
    g = db.query(MenuOptionGroup).filter(MenuOptionGroup.id == o.group_id).first() if o else None
    if o and label.strip():
        o.label = label.strip()[:160]
        o.price_delta = _to_float(price)
        o.popular = bool(popular)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{_group_page_id(db, g)}", status_code=303)


@router.post("/admin/menu/options/{option_id}/delete")
def admin_option_delete(option_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    o = db.query(MenuOption).filter(MenuOption.id == option_id).first()
    g = db.query(MenuOptionGroup).filter(MenuOptionGroup.id == o.group_id).first() if o else None
    pid = _group_page_id(db, g)
    if o:
        db.delete(o)
        db.commit()
    return RedirectResponse(url=f"/admin/menu/{pid}", status_code=303)


# ─── QR de la página pública ──────────────────────────────────────────────────

@router.get("/admin/menu/{page_id}/qr.png")
def admin_menu_qr(page_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    page = db.query(MenuPage).filter(MenuPage.id == page_id).first()
    if not page:
        return RedirectResponse(url="/admin/menu")
    import qrcode
    base = str(request.base_url).rstrip("/")
    url = f"{base}/m/{page.slug}"
    img = qrcode.make(url)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})


# ─── QR por mesa (para pedidos) ───────────────────────────────────────────────

@router.get("/admin/menu/{page_id}/mesas")
def admin_menu_tables(page_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    page = db.query(MenuPage).filter(MenuPage.id == page_id).first()
    if not page:
        return RedirectResponse(url="/admin/menu")
    tables = db.query(Table).order_by(Table.number.asc()).all()
    return templates.TemplateResponse(
        "admin_menu_tables.html",
        {"request": request, "page": page, "tables": tables, "page_title": f"QR de mesas · {page.name}"},
    )


@router.get("/admin/menu/{page_id}/mesa/{table_id}/qr.png")
def admin_menu_table_qr(page_id: int, table_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    page = db.query(MenuPage).filter(MenuPage.id == page_id).first()
    if not page:
        return RedirectResponse(url="/admin/menu")
    import qrcode
    base = str(request.base_url).rstrip("/")
    url = f"{base}/m/{page.slug}?mesa={table_id}"
    img = qrcode.make(url)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})


# ─── tablero de pedidos online (staff) ────────────────────────────────────────

def pending_online_count(db: Session) -> int:
    return db.query(func.count(OnlineOrder.id)).filter(OnlineOrder.status == "pendiente").scalar() or 0


@router.get("/admin/menu/pedidos")
def admin_online_orders(request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    active = (
        db.query(OnlineOrder).options(joinedload(OnlineOrder.items))
        .filter(OnlineOrder.status.in_(["pendiente", "aceptado", "preparando", "listo"]))
        .order_by(OnlineOrder.created_at.asc()).all()
    )
    recent = (
        db.query(OnlineOrder).options(joinedload(OnlineOrder.items))
        .filter(OnlineOrder.status.in_(["entregado", "rechazado"]))
        .order_by(OnlineOrder.updated_at.desc()).limit(20).all()
    )
    latest_pending = db.query(func.max(OnlineOrder.id)).filter(OnlineOrder.status == "pendiente").scalar() or 0
    return templates.TemplateResponse(
        "admin_menu_pedidos.html",
        {"request": request, "active": active, "recent": recent,
         "latest_pending_id": latest_pending, "page_title": "Pedidos Online"},
    )


@router.get("/admin/menu/pedidos/count")
def admin_online_orders_count(request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        raise HTTPException(401, "Admin session required")
    latest = db.query(func.max(OnlineOrder.id)).filter(OnlineOrder.status == "pendiente").scalar() or 0
    return {"pending": pending_online_count(db), "latest": latest}


_ONLINE_TRANSITIONS = {
    "pendiente": {"aceptado", "rechazado"},
    "aceptado": {"preparando", "listo", "rechazado"},
    "preparando": {"listo", "rechazado"},
    "listo": {"entregado"},
}

# Tablero → KDS: al mover el pedido en el tablero, reflejarlo en la comanda de
# cocina (si ya existe). "aceptado" no se mapea: crea la comanda vía el puente.
_BOARD_TO_KDS_STATUS = {
    "preparando": "preparando", "listo": "listo",
    "entregado": "despachado", "rechazado": "cancelado",
}


@router.post("/admin/menu/pedidos/{order_id}/estado")
def admin_online_order_state(order_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    o = (
        db.query(OnlineOrder).options(joinedload(OnlineOrder.items))
        .filter(OnlineOrder.id == order_id).first()
    )
    if o and status in ONLINE_ORDER_STATES and status in _ONLINE_TRANSITIONS.get(o.status, set()):
        o.status = status
        if status == "aceptado" and not o.accepted_at:
            o.accepted_at = cr_now()
            o.accepted_by = "Admin"
        db.commit()
        if status == "aceptado":
            _bridge_to_kds(db, o)  # crea la orden nativa para la pantalla de cocina
        elif o.kds_order_id and status in _BOARD_TO_KDS_STATUS:
            # tablero → KDS: refleja el cambio en la comanda de cocina
            from ..utils import change_order_status
            kds = db.query(Order).filter(Order.id == o.kds_order_id).first()
            if kds and kds.status != _BOARD_TO_KDS_STATUS[status]:
                try:
                    change_order_status(db, kds, _BOARD_TO_KDS_STATUS[status], "online")
                except Exception:
                    db.rollback()
    return RedirectResponse(url="/admin/menu/pedidos", status_code=303)


# ─── puente al KDS (Cocina) ───────────────────────────────────────────────────

def _placeholder_product(db: Session) -> Product:
    """Producto oculto (inactivo) usado como FK para líneas de pedidos online que
    no están vinculadas a un producto real. No aparece en menús ni POS (filtran
    active==True); el nombre real se muestra vía OrderItem.item_name."""
    p = db.query(Product).filter(Product.name == "Pedido online").first()
    if not p:
        p = Product(name="Pedido online", active=False, price=0, category="General")
        db.add(p)
        db.flush()
    return p


def _bridge_to_kds(db: Session, o: OnlineOrder) -> None:
    """Crea una orden nativa (source_role='online') a partir del pedido online
    aceptado, para que aparezca en la pantalla de Cocina. Idempotente: si ya se
    creó (kds_order_id) no hace nada. Nunca rompe el flujo de aceptación."""
    if o.kds_order_id:
        return
    try:
        if o.table_id:
            src = "🌐 " + (o.table_label or "Online")
            olabel = None
        else:
            src = "🥤 Pedido de Cliente: " + (o.customer_name or "Cliente")
            bits = []
            if o.pickup_time:
                bits.append("Recoger " + o.pickup_time)
            if o.phone:
                bits.append("Tel " + o.phone)
            olabel = " · ".join(bits) or None
        kds = Order(
            source_role="online", requires_acceptance=True, status="nuevo",
            waiter_name=src, order_label=olabel, table_id=o.table_id,
        )
        db.add(kds)
        db.flush()
        ph = None
        for it in o.items:
            pid = None
            if it.menu_item_id:
                mi = db.query(MenuItem.product_id).filter(MenuItem.id == it.menu_item_id).first()
                if mi and mi[0]:
                    pid = mi[0]
            if pid is None:
                ph = ph or _placeholder_product(db)
                pid = ph.id
            label = it.name + (f" ({it.variant_label})" if it.variant_label else "")
            if it.modifiers:
                label += f" — {it.modifiers}"
            if it.note:
                label += f" – {it.note}"
            db.add(OrderItem(order_id=kds.id, product_id=pid, quantity=it.quantity, item_name=label[:200]))
        db.add(OrderEvent(order_id=kds.id, event_type="created", actor_role="online", new_value="online"))
        o.kds_order_id = kds.id
        db.commit()
    except Exception:
        db.rollback()
        return
    # Aviso en vivo a la pantalla de cocina (best-effort).
    try:
        from ..utils import get_order
        from ..websockets import schedule_broadcast, broadcast_new_order
        schedule_broadcast(broadcast_new_order(get_order(db, o.kds_order_id)))
    except Exception:
        pass


# ─── utilidades ───────────────────────────────────────────────────────────────

def _to_float(s):
    try:
        return max(0.0, float(str(s).replace(",", "").strip() or 0))
    except (TypeError, ValueError):
        return 0.0


def _item_page_id(db: Session, it: MenuItem | None) -> int:
    if not it:
        return 0
    m = db.query(Menu.page_id).filter(Menu.id == it.menu_id).first()
    return m[0] if m else 0
