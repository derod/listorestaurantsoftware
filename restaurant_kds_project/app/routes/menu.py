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

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db, DATA_DIR
from ..models import MenuPage, Menu, MenuItem, MenuItemVariant, Product, cr_now
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
def public_menu(slug: str, request: Request, db: Session = Depends(get_db)):
    page = (
        db.query(MenuPage)
        .options(joinedload(MenuPage.menus).joinedload(Menu.items).joinedload(MenuItem.variants))
        .filter(MenuPage.slug == slug, MenuPage.active == True).first()  # noqa: E712
    )
    if not page:
        return templates.TemplateResponse(
            "menu_public.html",
            {"request": request, "page": None, "page_title": "Menú no encontrado"},
            status_code=404,
        )
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
            "page_title": page.name,
        },
    )


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
        {"request": request, "pages": view, "page_title": "Menú Online"},
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


@router.get("/admin/menu/{page_id}")
def admin_menu_builder(page_id: int, request: Request, db: Session = Depends(get_db)):
    if not _admin(request):
        return RedirectResponse(url="/admin/login")
    page = (
        db.query(MenuPage)
        .options(joinedload(MenuPage.menus).joinedload(Menu.items).joinedload(MenuItem.variants))
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
