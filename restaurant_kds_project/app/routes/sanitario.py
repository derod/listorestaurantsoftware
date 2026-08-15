"""
Control Sanitario / Higiene y Limpieza.

Programa de Higiene y Desinfección (concepto operativo del Reglamento 37308-S de
Costa Rica). Módulo single-tenant, consistente con el resto de LISTO.

Autorización (reutiliza el sistema existente):
  - Configuración/verificación/reportes → sesión de Admin (`require_admin`).
  - Registro de limpiezas/incidencias/temperaturas → sesión de agente (PIN, `require_waiter`).

Los registros históricos son auditables: no hay borrado desde la UI y los tiempos
originales (created_at/started_at/completed_at/verified_at) no se editan.
"""
from __future__ import annotations

import io as _io
import json as _json
from datetime import datetime, date, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import (
    Waiter, FacturaConfig,
    CleaningArea, CleaningTask, CleaningRecord, CleaningIncident,
    TemperatureEquipment, TemperatureRecord, PestControlRecord, SanitaryInspection,
    cr_now, cr_today,
    CLEANING_FREQUENCIES, CLEANING_MOMENTS, CLEANING_RECORD_STATES,
    INCIDENT_PRIORITIES, INCIDENT_STATES, TEMP_EQUIPMENT_KINDS, PEST_STATES,
)
from ..sanitario_data import (
    INSPECTION_SECTIONS, INSPECTION_RANGES, CHLORINE_REFERENCE, PROCEDURE_TIPS, GUIDE_DOCS,
)
# Reutiliza plantillas (con globals i18n) y helpers de auth/auditoría existentes.
from .web import templates, require_admin, require_waiter, record_access, clock_in, clock_out

router = APIRouter()

WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

FREQUENCY_LABELS = {
    "diaria": "Diaria",
    "varias_dia": "Varias veces al día",
    "semanal": "Semanal",
    "segun_programacion": "Según programación",
}
MOMENT_LABELS = {"apertura": "Apertura", "durante": "Durante el día", "cierre": "Cierre", "otro": "Otro"}
STATE_LABELS = {
    "pendiente": "Pendiente", "en_proceso": "En proceso", "completada": "Completada",
    "vencida": "Vencida", "verificada": "Verificada",
}
PRIORITY_LABELS = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}
INCIDENT_STATE_LABELS = {"abierta": "Abierta", "en_proceso": "En proceso", "resuelta": "Resuelta"}
KIND_LABELS = {"refrigerador": "Refrigerador", "congelador": "Congelador", "equipo": "Equipo", "bano_maria": "Baño María"}
PEST_STATE_LABELS = {"sin_evidencia": "Sin evidencia", "activo": "Activo", "controlado": "Controlado", "resuelto": "Resuelto"}


# ─── gates (redirecciones consistentes con el resto de la app) ────────────────

def _admin_guard(request: Request):
    """Devuelve None si hay sesión admin, o un RedirectResponse al login."""
    if not require_admin(request):
        return RedirectResponse(url="/admin/login")
    return None


def _worker(request: Request):
    """Devuelve (id, nombre) del agente en sesión, o None."""
    return require_waiter(request)


def _login_redirect(next_url: str):
    return RedirectResponse(url=f"/sanitario/login?next={next_url}")


# ─── generación perezosa de tareas del día (sin scheduler) ────────────────────

def _freq_applies(task: CleaningTask, d: date) -> bool:
    f = task.frequency
    if f in ("diaria", "varias_dia"):
        return True
    if f == "semanal":
        return task.weekday is None or d.weekday() == (task.weekday % 7)
    return False  # segun_programacion → no autogenera


def ensure_today_records(db: Session, d: date | None = None) -> None:
    """Crea de forma idempotente los CleaningRecord del día `d` para cada tarea
    activa cuya frecuencia aplique, y marca como 'vencida' lo pendiente de días
    anteriores. Guardado por (task_id, scheduled_date, slot)."""
    d = d or cr_today()
    # Barrido: pendiente / en_proceso de días pasados → vencida.
    db.query(CleaningRecord).filter(
        CleaningRecord.scheduled_date < d,
        CleaningRecord.status.in_(["pendiente", "en_proceso"]),
    ).update({CleaningRecord.status: "vencida"}, synchronize_session=False)

    tasks = db.query(CleaningTask).filter(CleaningTask.active == True).all()  # noqa: E712
    existing = {
        (r.task_id, r.slot)
        for r in db.query(CleaningRecord.task_id, CleaningRecord.slot)
        .filter(CleaningRecord.scheduled_date == d).all()
    }
    created = False
    for task in tasks:
        if not _freq_applies(task, d):
            continue
        slots = max(1, task.times_per_day or 1) if task.frequency == "varias_dia" else 1
        for s in range(slots):
            if (task.id, s) in existing:
                continue
            db.add(CleaningRecord(task_id=task.id, scheduled_date=d, slot=s, status="pendiente"))
            created = True
    # Commit siempre: el barrido de vencidas pudo modificar filas aunque no se creen nuevas.
    db.commit()
    _ = created


def _effective_status(r: CleaningRecord, today: date) -> str:
    """Estado efectivo para mostrar (marca vencidas del pasado no completadas)."""
    if r.status in ("completada", "verificada"):
        return r.status
    if r.scheduled_date < today and r.status in ("pendiente", "en_proceso"):
        return "vencida"
    return r.status


# ─── worker login (reusa el PIN de agente) ────────────────────────────────────

@router.get("/sanitario/login")
def sanitario_login_page(request: Request, next: str = "/sanitario/hoy"):
    if require_waiter(request):
        return RedirectResponse(url=next if next.startswith("/") else "/sanitario/hoy")
    return templates.TemplateResponse(
        "sanitario_login.html",
        {"request": request, "page_title": "Control Sanitario", "next": next},
    )


@router.post("/sanitario/login")
def sanitario_login_submit(request: Request, pin: str = Form(...), next: str = Form("/sanitario/hoy"), db: Session = Depends(get_db)):
    waiter = db.query(Waiter).filter(Waiter.pin == pin.strip(), Waiter.active == True).first()  # noqa: E712
    if not waiter:
        return templates.TemplateResponse(
            "sanitario_login.html",
            {"request": request, "page_title": "Control Sanitario", "next": next, "error": "PIN incorrecto"},
            status_code=401,
        )
    request.session["waiter_id"] = waiter.id
    request.session["waiter_name"] = waiter.name
    record_access(db, request, "sanitario", waiter.name, waiter.id)
    clock_in(db, "sanitario", waiter.name, waiter.id)
    target = next if next.startswith("/") else "/sanitario/hoy"
    return RedirectResponse(url=target, status_code=303)


@router.get("/sanitario/logout")
def sanitario_logout(request: Request, db: Session = Depends(get_db)):
    wid = request.session.get("waiter_id")
    if wid:
        clock_out(db, "sanitario", wid)
    request.session.pop("waiter_id", None)
    request.session.pop("waiter_name", None)
    return RedirectResponse(url="/sanitario/login")


# ─── worker: limpiezas de hoy ─────────────────────────────────────────────────

@router.get("/sanitario")
def sanitario_root(request: Request):
    if not require_waiter(request):
        return _login_redirect("/sanitario/hoy")
    return RedirectResponse(url="/sanitario/hoy")


def _record_view(r: CleaningRecord, today: date) -> dict:
    st = _effective_status(r, today)
    return {
        "id": r.id,
        "area": r.task.area.name if r.task and r.task.area else "—",
        "task": r.task.name if r.task else "—",
        "moment": MOMENT_LABELS.get(r.task.moment or "", "") if r.task else "",
        "frequency": FREQUENCY_LABELS.get(r.task.frequency, r.task.frequency) if r.task else "",
        "slot": r.slot,
        "status": st,
        "status_label": STATE_LABELS.get(st, st),
        "created_by": r.created_by,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "verified_by": r.verified_by,
        "verified_at": r.verified_at,
    }


@router.get("/sanitario/hoy")
def sanitario_hoy(request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return _login_redirect("/sanitario/hoy")
    _, waiter_name = w
    ensure_today_records(db)
    today = cr_today()
    records = (
        db.query(CleaningRecord)
        .options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.scheduled_date == today)
        .all()
    )
    records.sort(key=lambda r: (r.task.area.display_order if r.task and r.task.area else 0,
                                r.task.name if r.task else "", r.slot))
    views = [_record_view(r, today) for r in records]
    total = len(views)
    done = sum(1 for v in views if v["status"] in ("completada", "verificada"))
    pct = round(done / total * 100) if total else 0
    pending = [v for v in views if v["status"] in ("pendiente", "en_proceso", "vencida")]
    completed = [v for v in views if v["status"] in ("completada", "verificada")]
    equipos = db.query(TemperatureEquipment).filter(TemperatureEquipment.active == True).order_by(TemperatureEquipment.name).all()  # noqa: E712
    return templates.TemplateResponse(
        "sanitario_hoy.html",
        {
            "request": request, "page_title": "Limpiezas de hoy",
            "waiter_name": waiter_name, "today": today,
            "pending": pending, "completed": completed,
            "total": total, "done": done, "pct": pct, "equipos": equipos,
        },
    )


@router.get("/sanitario/tarea/{record_id}")
def sanitario_tarea(record_id: int, request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return _login_redirect(f"/sanitario/tarea/{record_id}")
    r = (
        db.query(CleaningRecord)
        .options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.id == record_id).first()
    )
    if not r:
        return RedirectResponse(url="/sanitario/hoy")
    steps = [s.strip() for s in (r.task.procedure or "").splitlines() if s.strip()] if r.task else []
    today = cr_today()
    return templates.TemplateResponse(
        "sanitario_tarea.html",
        {
            "request": request, "page_title": "Registrar limpieza",
            "r": r, "task": r.task, "area": r.task.area if r.task else None,
            "steps": steps, "status": _effective_status(r, today),
            "waiter_name": w[1],
        },
    )


@router.post("/sanitario/registro/{record_id}/iniciar")
def sanitario_iniciar(record_id: int, request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return _login_redirect(f"/sanitario/tarea/{record_id}")
    wid, wname = w
    r = db.query(CleaningRecord).filter(CleaningRecord.id == record_id).first()
    if r and r.status in ("pendiente", "vencida"):
        r.status = "en_proceso"
        if not r.started_at:
            r.started_at = cr_now()
        if not r.created_by:
            r.created_by, r.created_by_id = wname, wid
        db.commit()
    return RedirectResponse(url=f"/sanitario/tarea/{record_id}", status_code=303)


@router.post("/sanitario/registro/{record_id}/completar")
def sanitario_completar(
    record_id: int, request: Request,
    confirm: str = Form(""), observations: str = Form(""),
    db: Session = Depends(get_db),
):
    w = require_waiter(request)
    if not w:
        return _login_redirect(f"/sanitario/tarea/{record_id}")
    wid, wname = w
    r = db.query(CleaningRecord).filter(CleaningRecord.id == record_id).first()
    if not r:
        return RedirectResponse(url="/sanitario/hoy")
    if confirm != "on":
        # No confirmó el procedimiento → vuelve a la tarea sin registrar.
        return RedirectResponse(url=f"/sanitario/tarea/{record_id}?err=confirm", status_code=303)
    if r.status not in ("completada", "verificada"):
        r.status = "completada"
        r.confirmed = True
        r.completed_at = cr_now()
        if not r.started_at:
            r.started_at = cr_now()
        r.observations = (observations.strip() or None)
        if not r.created_by:
            r.created_by, r.created_by_id = wname, wid
        db.commit()
    return RedirectResponse(url="/sanitario/hoy", status_code=303)


# ─── worker: QR landing (siempre pasa por login) ──────────────────────────────

@router.get("/sanitario/qr/{task_id}")
def sanitario_qr(task_id: int, request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return _login_redirect(f"/sanitario/qr/{task_id}")
    task = db.query(CleaningTask).options(joinedload(CleaningTask.area)).filter(CleaningTask.id == task_id).first()
    if not task or not task.active:
        return RedirectResponse(url="/sanitario/hoy")
    ensure_today_records(db)
    today = cr_today()
    # Toma el primer registro no completado de hoy; si no hay (p.ej. segun_programacion), lo crea.
    r = (
        db.query(CleaningRecord)
        .filter(CleaningRecord.task_id == task.id, CleaningRecord.scheduled_date == today)
        .order_by(CleaningRecord.slot.asc()).all()
    )
    target = next((x for x in r if x.status in ("pendiente", "en_proceso", "vencida")), None)
    if target is None and r:
        target = r[-1]  # todas hechas → muestra la última
    if target is None:
        target = CleaningRecord(task_id=task.id, scheduled_date=today, slot=0, status="pendiente")
        db.add(target)
        db.commit()
        db.refresh(target)
    return RedirectResponse(url=f"/sanitario/tarea/{target.id}")


# ─── worker: reportar incidencia ──────────────────────────────────────────────

@router.get("/sanitario/incidencias/nueva")
def sanitario_incidencia_form(request: Request, db: Session = Depends(get_db)):
    w = require_waiter(request)
    if not w:
        return _login_redirect("/sanitario/incidencias/nueva")
    areas = db.query(CleaningArea).filter(CleaningArea.active == True).order_by(CleaningArea.display_order, CleaningArea.name).all()  # noqa: E712
    return templates.TemplateResponse(
        "sanitario_incidencia_nueva.html",
        {"request": request, "page_title": "Reportar incidencia", "areas": areas,
         "priorities": INCIDENT_PRIORITIES, "priority_labels": PRIORITY_LABELS, "waiter_name": w[1]},
    )


@router.post("/sanitario/incidencias/nueva")
def sanitario_incidencia_create(
    request: Request,
    problem: str = Form(...), description: str = Form(""), priority: str = Form("media"),
    area_id: str = Form(""), db: Session = Depends(get_db),
):
    w = require_waiter(request)
    if not w:
        return _login_redirect("/sanitario/incidencias/nueva")
    wid, wname = w
    problem = problem.strip()
    if problem:
        db.add(CleaningIncident(
            area_id=int(area_id) if area_id.isdigit() else None,
            problem=problem[:200],
            description=(description.strip() or None),
            priority=priority if priority in INCIDENT_PRIORITIES else "media",
            reported_by_id=wid, reported_by=wname,
            status="abierta",
        ))
        db.commit()
    return RedirectResponse(url="/sanitario/hoy", status_code=303)


# ─── worker: registrar temperatura ────────────────────────────────────────────

@router.post("/sanitario/temperatura")
def sanitario_temperatura_worker(
    request: Request,
    equipment_id: str = Form(...), temperature: str = Form(...), observations: str = Form(""),
    db: Session = Depends(get_db),
):
    w = require_waiter(request)
    if not w:
        return _login_redirect("/sanitario/hoy")
    _create_temperature(db, equipment_id, temperature, observations, w[0], w[1])
    return RedirectResponse(url="/sanitario/hoy?temp=ok", status_code=303)


def _create_temperature(db: Session, equipment_id, temperature, observations, actor_id, actor_name):
    try:
        eq = db.query(TemperatureEquipment).filter(TemperatureEquipment.id == int(equipment_id)).first()
        temp = float(temperature)
    except (TypeError, ValueError):
        return None
    if not eq:
        return None
    oor = False
    if eq.min_temp is not None and temp < eq.min_temp:
        oor = True
    if eq.max_temp is not None and temp > eq.max_temp:
        oor = True
    rec = TemperatureRecord(
        equipment_id=eq.id, temperature=temp, out_of_range=oor,
        created_by_id=actor_id, created_by=actor_name,
        observations=(observations.strip() or None) if observations else None,
    )
    db.add(rec)
    db.commit()
    return rec


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════════════════════════

# ─── admin dashboard ──────────────────────────────────────────────────────────

@router.get("/admin/sanitario")
def admin_sanitario(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    ensure_today_records(db)
    today = cr_today()
    records = (
        db.query(CleaningRecord)
        .options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.scheduled_date == today).all()
    )
    views = [_record_view(r, today) for r in records]
    total = len(views)
    completed = sum(1 for v in views if v["status"] in ("completada", "verificada"))
    pending = sum(1 for v in views if v["status"] == "pendiente")
    in_proc = sum(1 for v in views if v["status"] == "en_proceso")
    overdue = sum(1 for v in views if v["status"] == "vencida")
    pct = round(completed / total * 100) if total else 0

    inc_open = db.query(func.count(CleaningIncident.id)).filter(CleaningIncident.status != "resuelta").scalar() or 0
    inc_crit = db.query(func.count(CleaningIncident.id)).filter(
        CleaningIncident.status != "resuelta", CleaningIncident.priority == "critica").scalar() or 0

    last_verified = (
        db.query(CleaningRecord).options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.verified_at != None)  # noqa: E711
        .order_by(CleaningRecord.verified_at.desc()).limit(5).all()
    )
    last_temps = (
        db.query(TemperatureRecord).options(joinedload(TemperatureRecord.equipment))
        .order_by(TemperatureRecord.recorded_at.desc()).limit(5).all()
    )
    last_pests = (
        db.query(PestControlRecord).options(joinedload(PestControlRecord.area))
        .order_by(PestControlRecord.created_at.desc()).limit(5).all()
    )
    return templates.TemplateResponse(
        "admin_sanitario.html",
        {
            "request": request, "page_title": "Control Sanitario", "today": today,
            "total": total, "completed": completed, "pending": pending,
            "in_proc": in_proc, "overdue": overdue, "pct": pct,
            "inc_open": inc_open, "inc_crit": inc_crit,
            "last_verified": last_verified, "last_temps": last_temps, "last_pests": last_pests,
            "state_labels": STATE_LABELS, "kind_labels": KIND_LABELS, "pest_state_labels": PEST_STATE_LABELS,
        },
    )


# ─── admin protocolo (áreas + tareas) ─────────────────────────────────────────

@router.get("/admin/sanitario/protocolo")
def admin_protocolo(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    areas = db.query(CleaningArea).order_by(CleaningArea.display_order, CleaningArea.name).all()
    tasks = (
        db.query(CleaningTask).options(joinedload(CleaningTask.area))
        .order_by(CleaningTask.area_id, CleaningTask.name).all()
    )
    return templates.TemplateResponse(
        "admin_sanitario_protocolo.html",
        {
            "request": request, "page_title": "Protocolo", "areas": areas, "tasks": tasks,
            "frequencies": CLEANING_FREQUENCIES, "freq_labels": FREQUENCY_LABELS,
            "moments": CLEANING_MOMENTS, "moment_labels": MOMENT_LABELS,
            "weekdays": WEEKDAYS,
        },
    )


@router.post("/admin/sanitario/areas")
def admin_area_create(request: Request, name: str = Form(...), description: str = Form(""), db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    name = name.strip()
    if name:
        last = db.query(func.max(CleaningArea.display_order)).scalar() or 0
        db.add(CleaningArea(name=name[:120], description=(description.strip() or None), display_order=last + 1))
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


@router.post("/admin/sanitario/areas/{area_id}/edit")
def admin_area_edit(area_id: int, request: Request, name: str = Form(...), description: str = Form(""), db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    a = db.query(CleaningArea).filter(CleaningArea.id == area_id).first()
    if a and name.strip():
        a.name = name.strip()[:120]
        a.description = description.strip() or None
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


@router.post("/admin/sanitario/areas/{area_id}/toggle")
def admin_area_toggle(area_id: int, request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    a = db.query(CleaningArea).filter(CleaningArea.id == area_id).first()
    if a:
        a.active = not a.active
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


def _task_form_fields(form) -> dict:
    def g(k):
        return (form.get(k) or "").strip()
    freq = g("frequency")
    moment = g("moment")
    try:
        tpd = max(1, int(form.get("times_per_day") or 1))
    except (TypeError, ValueError):
        tpd = 1
    weekday = None
    if g("weekday").isdigit():
        wd = int(g("weekday"))
        weekday = wd if 0 <= wd <= 6 else None
    return {
        "name": g("name")[:200],
        "description": g("description") or None,
        "procedure": g("procedure") or None,
        "frequency": freq if freq in CLEANING_FREQUENCIES else "diaria",
        "times_per_day": tpd,
        "weekday": weekday,
        "moment": (moment if moment in CLEANING_MOMENTS else None),
        "responsible": g("responsible")[:200] or None,
        "product": g("product")[:200] or None,
        "concentration": g("concentration")[:120] or None,
        "contact_time": g("contact_time")[:120] or None,
        "observations": g("observations") or None,
    }


@router.post("/admin/sanitario/tareas")
async def admin_task_create(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    form = await request.form()
    try:
        area_id = int(form.get("area_id"))
    except (TypeError, ValueError):
        return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)
    area = db.query(CleaningArea).filter(CleaningArea.id == area_id).first()
    fields = _task_form_fields(form)
    if area and fields["name"]:
        db.add(CleaningTask(area_id=area_id, **fields))
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


@router.post("/admin/sanitario/tareas/{task_id}/edit")
async def admin_task_edit(task_id: int, request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    form = await request.form()
    t = db.query(CleaningTask).filter(CleaningTask.id == task_id).first()
    if not t:
        return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)
    try:
        area_id = int(form.get("area_id"))
        if db.query(CleaningArea.id).filter(CleaningArea.id == area_id).first():
            t.area_id = area_id
    except (TypeError, ValueError):
        pass
    fields = _task_form_fields(form)
    if fields["name"]:
        for k, v in fields.items():
            setattr(t, k, v)
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


@router.post("/admin/sanitario/tareas/{task_id}/toggle")
def admin_task_toggle(task_id: int, request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    t = db.query(CleaningTask).filter(CleaningTask.id == task_id).first()
    if t:
        t.active = not t.active
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


@router.post("/admin/sanitario/tareas/{task_id}/delete")
def admin_task_delete(task_id: int, request: Request, confirm: str = Form(""), db: Session = Depends(get_db)):
    """Solo permite borrar una tarea que aún no tiene registros históricos.
    Si ya se ejecutó alguna vez, se debe desactivar (no borrar) para preservar
    la trazabilidad."""
    g = _admin_guard(request)
    if g:
        return g
    if confirm != "CONFIRMAR":
        return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)
    t = db.query(CleaningTask).filter(CleaningTask.id == task_id).first()
    if t:
        has_records = db.query(CleaningRecord.id).filter(CleaningRecord.task_id == task_id).first()
        if has_records:
            t.active = False  # protege el historial: se desactiva en vez de borrar
        else:
            db.delete(t)
        db.commit()
    return RedirectResponse(url="/admin/sanitario/protocolo", status_code=303)


# ─── admin tareas (catálogo + QR) ─────────────────────────────────────────────

@router.get("/admin/sanitario/tareas")
def admin_tareas_catalogo(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    areas = db.query(CleaningArea).order_by(CleaningArea.display_order, CleaningArea.name).all()
    tasks = db.query(CleaningTask).filter(CleaningTask.active == True).all()  # noqa: E712
    by_area = {}
    for t in tasks:
        by_area.setdefault(t.area_id, []).append(t)
    for lst in by_area.values():
        lst.sort(key=lambda x: x.name)
    return templates.TemplateResponse(
        "admin_sanitario_tareas.html",
        {
            "request": request, "page_title": "Tareas de limpieza",
            "areas": areas, "by_area": by_area,
            "freq_labels": FREQUENCY_LABELS, "moment_labels": MOMENT_LABELS,
        },
    )


@router.get("/admin/sanitario/qr/{task_id}.png")
def admin_task_qr_png(task_id: int, request: Request, db: Session = Depends(get_db)):
    """Genera el QR (PNG) que apunta a la URL protegida del worker para esa tarea.
    El destino /sanitario/qr/{id} siempre exige login: el QR no salta autenticación."""
    g = _admin_guard(request)
    if g:
        return g
    task = db.query(CleaningTask.id).filter(CleaningTask.id == task_id).first()
    if not task:
        return RedirectResponse(url="/admin/sanitario/tareas")
    import qrcode
    base = str(request.base_url).rstrip("/")
    url = f"{base}/sanitario/qr/{task_id}"
    img = qrcode.make(url)
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png", headers={"Cache-Control": "no-store"})


# ─── cuestionario: activador rápido del protocolo (guiado, por área) ──────────

# Procedimiento estándar de limpieza y desinfección para tareas creadas desde el
# activador. Concentración/tiempo de contacto quedan vacíos (según ficha técnica).
_PROC_LD = (
    "Retirar residuos\n"
    "Lavar con agua y jabón\n"
    "Enjuagar\n"
    "Aplicar desinfectante\n"
    "Respetar el tiempo de contacto según la ficha técnica del producto\n"
    "Secar\n"
    "Verificar"
)

# Tareas sugeridas por nombre de área: (nombre, frecuencia, momento, veces/día, procedimiento).
SUGGESTED_TASKS = {
    "Cocina": [
        ("Limpieza y desinfección de superficies", "diaria", "cierre", 1, _PROC_LD),
        ("Limpieza de equipos y utensilios", "diaria", "cierre", 1, _PROC_LD),
        ("Limpieza de paredes", "semanal", "cierre", 1, _PROC_LD),
    ],
    "Baño María": [("Limpieza y desinfección", "diaria", "cierre", 1, _PROC_LD)],
    "Baños": [
        ("Limpieza y desinfección", "varias_dia", "durante", 3, _PROC_LD),
        ("Reposición de insumos (jabón/papel)", "varias_dia", "durante", 3, None),
    ],
    "Mesas": [("Limpieza y desinfección", "varias_dia", "durante", 4, _PROC_LD)],
    "Utensilios": [("Lavado y desinfección de utensilios", "diaria", "cierre", 1, _PROC_LD)],
    "Refrigeradores": [
        ("Limpieza interna", "semanal", "apertura", 1, _PROC_LD),
        ("Control de temperatura", "diaria", "apertura", 1, None),
    ],
    "Pisos": [("Barrido y trapeado", "diaria", "cierre", 1, "Barrer\nTrapear con solución de limpieza\nDesinfectar\nDejar secar")],
    "Desagües": [("Limpieza de desagües", "diaria", "cierre", 1, "Retirar rejilla\nRetirar residuos sólidos\nLavar\nDesinfectar\nColocar rejilla")],
    "Campana": [("Limpieza de campana y filtros", "segun_programacion", None, 1, "Retirar filtros\nDesengrasar\nLavar\nEnjuagar\nSecar\nColocar filtros")],
    "Área de atención": [("Limpieza y desinfección", "diaria", "apertura", 1, _PROC_LD)],
    "Recipientes de residuos": [("Vaciado y desinfección", "diaria", "cierre", 1, "Vaciar\nLavar\nDesinfectar\nColocar bolsa nueva")],
}
# Sugerencia por defecto para áreas sin catálogo (p.ej. áreas creadas a mano).
_DEFAULT_SUGGESTION = [("Limpieza y desinfección", "diaria", "cierre", 1, _PROC_LD)]


def _suggestions_for(area_name: str):
    return SUGGESTED_TASKS.get(area_name, _DEFAULT_SUGGESTION)


@router.get("/admin/sanitario/cuestionario")
def admin_cuestionario(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    areas = db.query(CleaningArea).filter(CleaningArea.active == True).order_by(CleaningArea.display_order, CleaningArea.name).all()  # noqa: E712
    tasks = db.query(CleaningTask).all()
    # index tareas existentes por (area_id, nombre en minúscula)
    by_key = {}
    for t in tasks:
        by_key[(t.area_id, (t.name or "").strip().lower())] = t
    data = []
    for a in areas:
        items = []
        for name, freq, moment, tpd, _proc in _suggestions_for(a.name):
            existing = by_key.get((a.id, name.strip().lower()))
            items.append({
                "name": name,
                "frequency": existing.frequency if existing else freq,
                "moment": (existing.moment if existing else moment) or "",
                "times_per_day": (existing.times_per_day if existing else tpd) or 1,
                "enabled": bool(existing and existing.active),
                "exists": bool(existing),
            })
        data.append({"id": a.id, "name": a.name, "tasks": items})
    return templates.TemplateResponse(
        "sanitario_cuestionario.html",
        {
            "request": request, "page_title": "Cuestionario · Higiene y Limpieza",
            "areas_data": data,
            "frequencies": CLEANING_FREQUENCIES, "freq_labels": FREQUENCY_LABELS,
            "moments": CLEANING_MOMENTS, "moment_labels": MOMENT_LABELS,
        },
    )


class ProtocolQuizApply(BaseModel):
    area_id: int
    name: str
    enabled: bool
    frequency: str = "diaria"
    moment: str | None = None
    times_per_day: int = 1


@router.post("/admin/sanitario/cuestionario/apply")
def admin_cuestionario_apply(payload: ProtocolQuizApply, request: Request, db: Session = Depends(get_db)):
    """Activa/actualiza o desactiva una tarea sugerida. Idempotente: no duplica
    (empareja por área + nombre). Desactivar preserva el historial (no borra)."""
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    area = db.query(CleaningArea).filter(CleaningArea.id == payload.area_id).first()
    if not area:
        raise HTTPException(404, "Área no encontrada")
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(400, "Nombre requerido")
    freq = payload.frequency if payload.frequency in CLEANING_FREQUENCIES else "diaria"
    moment = payload.moment if payload.moment in CLEANING_MOMENTS else None
    try:
        tpd = max(1, min(12, int(payload.times_per_day or 1)))
    except (TypeError, ValueError):
        tpd = 1
    existing = (
        db.query(CleaningTask)
        .filter(CleaningTask.area_id == area.id, func.lower(CleaningTask.name) == name.lower())
        .first()
    )
    if payload.enabled:
        if existing:
            existing.active = True
            existing.frequency = freq
            existing.moment = moment
            existing.times_per_day = tpd
        else:
            # procedimiento sugerido del catálogo (si lo hay)
            proc = None
            for sname, _f, _m, _t, sproc in _suggestions_for(area.name):
                if sname.strip().lower() == name.lower():
                    proc = sproc
                    break
            db.add(CleaningTask(
                area_id=area.id, name=name[:200], frequency=freq, moment=moment,
                times_per_day=tpd, procedure=proc, active=True,
            ))
        db.commit()
        return {"ok": True, "enabled": True, "exists": True}
    # deshabilitar
    if existing:
        existing.active = False
        db.commit()
    return {"ok": True, "enabled": False, "exists": bool(existing)}


# ─── admin historial ──────────────────────────────────────────────────────────

@router.get("/admin/sanitario/historial")
def admin_historial(
    request: Request,
    desde: str = "", hasta: str = "", area_id: str = "", estado: str = "",
    verificado: str = "", q: str = "", db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    query = (
        db.query(CleaningRecord)
        .options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
    )
    d_from = _parse_date_opt(desde)
    d_to = _parse_date_opt(hasta)
    if d_from:
        query = query.filter(CleaningRecord.scheduled_date >= d_from.date())
    if d_to:
        query = query.filter(CleaningRecord.scheduled_date <= d_to.date())
    if area_id.isdigit():
        query = query.join(CleaningTask, CleaningRecord.task_id == CleaningTask.id).filter(CleaningTask.area_id == int(area_id))
    if estado in CLEANING_RECORD_STATES:
        query = query.filter(CleaningRecord.status == estado)
    if verificado == "si":
        query = query.filter(CleaningRecord.verified_at != None)  # noqa: E711
    elif verificado == "no":
        query = query.filter(CleaningRecord.verified_at == None)  # noqa: E711
    rows = query.order_by(CleaningRecord.scheduled_date.desc(), CleaningRecord.id.desc()).limit(500).all()
    if q.strip():
        ql = q.strip().lower()
        rows = [r for r in rows if ql in ((r.created_by or "").lower() + " " + (r.task.name if r.task else "").lower())]
    today = cr_today()
    areas = db.query(CleaningArea).order_by(CleaningArea.name).all()
    return templates.TemplateResponse(
        "admin_sanitario_historial.html",
        {
            "request": request, "page_title": "Historial sanitario",
            "rows": rows, "areas": areas, "today": today,
            "state_labels": STATE_LABELS, "states": CLEANING_RECORD_STATES,
            "effective_status": lambda r: _effective_status(r, today),
            "f": {"desde": desde, "hasta": hasta, "area_id": area_id, "estado": estado, "verificado": verificado, "q": q},
        },
    )


# ─── admin verificaciones ─────────────────────────────────────────────────────

@router.get("/admin/sanitario/verificaciones")
def admin_verificaciones(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    pendientes = (
        db.query(CleaningRecord).options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.status == "completada", CleaningRecord.verified_at == None)  # noqa: E711
        .order_by(CleaningRecord.completed_at.desc()).limit(200).all()
    )
    recientes = (
        db.query(CleaningRecord).options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.verified_at != None)  # noqa: E711
        .order_by(CleaningRecord.verified_at.desc()).limit(20).all()
    )
    return templates.TemplateResponse(
        "admin_sanitario_verificaciones.html",
        {"request": request, "page_title": "Verificaciones", "pendientes": pendientes, "recientes": recientes},
    )


@router.post("/admin/sanitario/registro/{record_id}/verificar")
def admin_verificar(record_id: int, request: Request, notes: str = Form(""), db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    r = db.query(CleaningRecord).filter(CleaningRecord.id == record_id).first()
    if r and r.status == "completada" and not r.verified_at:
        r.status = "verificada"
        r.verified_at = cr_now()
        r.verified_by = "Admin"
        r.verified_notes = (notes.strip() or None)
        db.commit()
    return RedirectResponse(url="/admin/sanitario/verificaciones", status_code=303)


# ─── admin incidencias ────────────────────────────────────────────────────────

@router.get("/admin/sanitario/incidencias")
def admin_incidencias(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    rows = (
        db.query(CleaningIncident).options(joinedload(CleaningIncident.area))
        .order_by(CleaningIncident.status != "resuelta", CleaningIncident.created_at.desc()).all()
    )
    # Orden: abiertas/en proceso primero, luego resueltas; dentro, más recientes.
    rows.sort(key=lambda i: (i.status == "resuelta", -(i.id)))
    areas = db.query(CleaningArea).order_by(CleaningArea.name).all()
    return templates.TemplateResponse(
        "admin_sanitario_incidencias.html",
        {
            "request": request, "page_title": "Incidencias", "rows": rows, "areas": areas,
            "priorities": INCIDENT_PRIORITIES, "priority_labels": PRIORITY_LABELS,
            "states": INCIDENT_STATES, "state_labels": INCIDENT_STATE_LABELS,
        },
    )


@router.post("/admin/sanitario/incidencias")
def admin_incidencia_create(
    request: Request,
    problem: str = Form(...), description: str = Form(""), priority: str = Form("media"),
    area_id: str = Form(""), responsible: str = Form(""), corrective_action: str = Form(""),
    db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    if problem.strip():
        db.add(CleaningIncident(
            area_id=int(area_id) if area_id.isdigit() else None,
            problem=problem.strip()[:200],
            description=(description.strip() or None),
            priority=priority if priority in INCIDENT_PRIORITIES else "media",
            responsible=(responsible.strip() or None),
            corrective_action=(corrective_action.strip() or None),
            reported_by="Admin", status="abierta",
        ))
        db.commit()
    return RedirectResponse(url="/admin/sanitario/incidencias", status_code=303)


@router.post("/admin/sanitario/incidencias/{inc_id}/update")
def admin_incidencia_update(
    inc_id: int, request: Request,
    status: str = Form(...), corrective_action: str = Form(""), responsible: str = Form(""),
    priority: str = Form(""), db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    inc = db.query(CleaningIncident).filter(CleaningIncident.id == inc_id).first()
    if inc:
        if status in INCIDENT_STATES:
            was_resolved = inc.status == "resuelta"
            inc.status = status
            if status == "resuelta" and not was_resolved:
                inc.resolved_at = cr_now()
            if status != "resuelta":
                inc.resolved_at = None
        if priority in INCIDENT_PRIORITIES:
            inc.priority = priority
        if corrective_action.strip():
            inc.corrective_action = corrective_action.strip()
        if responsible.strip():
            inc.responsible = responsible.strip()
        db.commit()
    return RedirectResponse(url="/admin/sanitario/incidencias", status_code=303)


# ─── admin control de temperaturas ────────────────────────────────────────────

@router.get("/admin/sanitario/temperaturas")
def admin_temperaturas(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    equipos = db.query(TemperatureEquipment).order_by(TemperatureEquipment.name).all()
    lecturas = (
        db.query(TemperatureRecord).options(joinedload(TemperatureRecord.equipment))
        .order_by(TemperatureRecord.recorded_at.desc()).limit(100).all()
    )
    return templates.TemplateResponse(
        "admin_sanitario_temperaturas.html",
        {
            "request": request, "page_title": "Control de temperaturas",
            "equipos": equipos, "lecturas": lecturas,
            "kinds": TEMP_EQUIPMENT_KINDS, "kind_labels": KIND_LABELS,
        },
    )


@router.post("/admin/sanitario/temperaturas/equipo")
def admin_temp_equipo_create(
    request: Request,
    name: str = Form(...), kind: str = Form("refrigerador"),
    min_temp: str = Form(""), max_temp: str = Form(""), db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    if name.strip():
        db.add(TemperatureEquipment(
            name=name.strip()[:120],
            kind=kind if kind in TEMP_EQUIPMENT_KINDS else "refrigerador",
            min_temp=_float_opt(min_temp), max_temp=_float_opt(max_temp),
        ))
        db.commit()
    return RedirectResponse(url="/admin/sanitario/temperaturas", status_code=303)


@router.post("/admin/sanitario/temperaturas/equipo/{eq_id}/edit")
def admin_temp_equipo_edit(
    eq_id: int, request: Request,
    name: str = Form(...), kind: str = Form("refrigerador"),
    min_temp: str = Form(""), max_temp: str = Form(""), db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    eq = db.query(TemperatureEquipment).filter(TemperatureEquipment.id == eq_id).first()
    if eq and name.strip():
        eq.name = name.strip()[:120]
        eq.kind = kind if kind in TEMP_EQUIPMENT_KINDS else eq.kind
        eq.min_temp = _float_opt(min_temp)
        eq.max_temp = _float_opt(max_temp)
        db.commit()
    return RedirectResponse(url="/admin/sanitario/temperaturas", status_code=303)


@router.post("/admin/sanitario/temperaturas/equipo/{eq_id}/toggle")
def admin_temp_equipo_toggle(eq_id: int, request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    eq = db.query(TemperatureEquipment).filter(TemperatureEquipment.id == eq_id).first()
    if eq:
        eq.active = not eq.active
        db.commit()
    return RedirectResponse(url="/admin/sanitario/temperaturas", status_code=303)


@router.post("/admin/sanitario/temperaturas/registro")
def admin_temp_registro(
    request: Request,
    equipment_id: str = Form(...), temperature: str = Form(...), observations: str = Form(""),
    db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    _create_temperature(db, equipment_id, temperature, observations, None, "Admin")
    return RedirectResponse(url="/admin/sanitario/temperaturas", status_code=303)


# ─── admin control de plagas ──────────────────────────────────────────────────

@router.get("/admin/sanitario/plagas")
def admin_plagas(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    rows = (
        db.query(PestControlRecord).options(joinedload(PestControlRecord.area))
        .order_by(PestControlRecord.inspection_date.desc(), PestControlRecord.id.desc()).limit(200).all()
    )
    areas = db.query(CleaningArea).order_by(CleaningArea.name).all()
    return templates.TemplateResponse(
        "admin_sanitario_plagas.html",
        {
            "request": request, "page_title": "Control de plagas", "rows": rows, "areas": areas,
            "states": PEST_STATES, "state_labels": PEST_STATE_LABELS,
        },
    )


@router.post("/admin/sanitario/plagas")
def admin_plaga_create(
    request: Request,
    inspection_date: str = Form(""), area_id: str = Form(""), pest_type: str = Form(""),
    evidence: str = Form(""), action_taken: str = Form(""), responsible: str = Form(""),
    status: str = Form("sin_evidencia"), observations: str = Form(""),
    db: Session = Depends(get_db),
):
    g = _admin_guard(request)
    if g:
        return g
    d = _parse_date_opt(inspection_date)
    db.add(PestControlRecord(
        inspection_date=(d.date() if d else cr_today()),
        area_id=int(area_id) if area_id.isdigit() else None,
        pest_type=(pest_type.strip() or None),
        evidence=(evidence.strip() or None),
        action_taken=(action_taken.strip() or None),
        responsible=(responsible.strip() or None),
        status=status if status in PEST_STATES else "sin_evidencia",
        observations=(observations.strip() or None),
        created_by="Admin",
    ))
    db.commit()
    return RedirectResponse(url="/admin/sanitario/plagas", status_code=303)


@router.post("/admin/sanitario/plagas/{rec_id}/estado")
def admin_plaga_estado(rec_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    r = db.query(PestControlRecord).filter(PestControlRecord.id == rec_id).first()
    if r and status in PEST_STATES:
        r.status = status
        db.commit()
    return RedirectResponse(url="/admin/sanitario/plagas", status_code=303)


# ─── admin reportes ───────────────────────────────────────────────────────────

@router.get("/admin/sanitario/reportes")
def admin_reportes(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    today = cr_today()
    default_from = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    return templates.TemplateResponse(
        "admin_sanitario_reportes.html",
        {"request": request, "page_title": "Reporte sanitario",
         "default_from": default_from, "default_to": today.strftime("%Y-%m-%d")},
    )


@router.get("/admin/sanitario/reportes/pdf")
def admin_reportes_pdf(request: Request, desde: str = "", hasta: str = "", db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    today = cr_today()
    d_from = (_parse_date_opt(desde).date() if _parse_date_opt(desde) else today - timedelta(days=30))
    d_to = (_parse_date_opt(hasta).date() if _parse_date_opt(hasta) else today)
    pdf = _build_report_pdf(db, d_from, d_to)
    fname = f"reporte-sanitario-{d_from}-a-{d_to}.pdf"
    return StreamingResponse(
        _io.BytesIO(pdf), media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ─── guías y cumplimiento ─────────────────────────────────────────────────────

@router.get("/admin/sanitario/guias")
def admin_guias(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    # ¿Qué documentos existen físicamente? (para no mostrar enlaces rotos)
    from ..database import DATA_DIR
    docdir = DATA_DIR / "uploads" / "documentation"
    docs = []
    for d in GUIDE_DOCS:
        exists = (docdir / d["file"]).exists()
        docs.append({**d, "exists": exists, "url": f"/uploads/documentation/{d['file']}"})
    return templates.TemplateResponse(
        "admin_sanitario_guias.html",
        {
            "request": request, "page_title": "Guías y Cumplimiento",
            "docs": docs, "tips": PROCEDURE_TIPS, "chlorine": CHLORINE_REFERENCE,
        },
    )


# ─── autoinspección (Guía de Inspección DAC anexo 9) ──────────────────────────

def _score_inspection(answers: dict):
    """Recalcula la calificación en el servidor a partir de las respuestas.
    answers: { 'A-0': 'cumple'|'no_cumple'|'no_aplica', ... }. Devuelve el
    resumen total y por sección (no confía en el cálculo del cliente)."""
    score = 0
    possible = 0
    critical_fail = False
    sections = []
    for s in INSPECTION_SECTIONS:
        s_score = s_possible = 0
        for i, item in enumerate(s["items"]):
            ans = answers.get(f"{s['letter']}-{i}", "")
            pts = int(item.get("points") or 0)
            if ans == "cumple":
                s_score += pts
                s_possible += pts
            elif ans == "no_cumple":
                s_possible += pts
                if item.get("critical"):
                    critical_fail = True
        score += s_score
        possible += s_possible
        sections.append({
            "letter": s["letter"], "title": s["title"],
            "score": s_score, "possible": s_possible,
            "pct": round(s_score / s_possible * 100) if s_possible else None,
        })
    pct = round(score / possible * 100) if possible else 0
    rating = next((r for r in INSPECTION_RANGES if r["min"] <= pct <= r["max"]), None)
    return {
        "score": score, "possible": possible, "pct": pct,
        "rating": rating["label"] if rating else None,
        "color": rating["color"] if rating else "red",
        "critical_fail": critical_fail, "sections": sections,
    }


@router.get("/admin/sanitario/autoinspeccion")
def admin_autoinspeccion(request: Request, db: Session = Depends(get_db)):
    g = _admin_guard(request)
    if g:
        return g
    last = db.query(SanitaryInspection).order_by(SanitaryInspection.created_at.desc()).first()
    history = (
        db.query(SanitaryInspection).order_by(SanitaryInspection.created_at.desc()).limit(10).all()
    )
    last_answers = {}
    if last and last.answers_json:
        try:
            last_answers = _json.loads(last.answers_json)
        except (ValueError, TypeError):
            last_answers = {}
    return templates.TemplateResponse(
        "admin_sanitario_autoinspeccion.html",
        {
            "request": request, "page_title": "Autoinspección",
            "sections": INSPECTION_SECTIONS, "ranges": INSPECTION_RANGES,
            "last_answers": last_answers, "last": last, "history": history,
        },
    )


class InspectionSave(BaseModel):
    answers: dict
    notes: str | None = None


@router.post("/admin/sanitario/autoinspeccion/guardar")
def admin_autoinspeccion_guardar(payload: InspectionSave, request: Request, db: Session = Depends(get_db)):
    if not require_admin(request):
        raise HTTPException(401, "Admin session required")
    valid = {"cumple", "no_cumple", "no_aplica"}
    answers = {str(k): str(v) for k, v in (payload.answers or {}).items() if str(v) in valid}
    res = _score_inspection(answers)
    snap = SanitaryInspection(
        score=res["score"], possible=res["possible"], score_pct=res["pct"],
        rating=res["rating"], critical_fail=res["critical_fail"],
        answers_json=_json.dumps(answers, ensure_ascii=False),
        section_json=_json.dumps(res["sections"], ensure_ascii=False),
        notes=(payload.notes or "").strip() or None,
        created_by="Admin",
    )
    db.add(snap)
    db.commit()
    return {"ok": True, **res, "id": snap.id}


# ─── utilidades ───────────────────────────────────────────────────────────────

def _parse_date_opt(s: str):
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _float_opt(s):
    try:
        return float(s) if str(s).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _establishment_name(db: Session) -> str:
    cfg = db.query(FacturaConfig).first()
    if cfg and (cfg.emisor_nombre or "").strip():
        return cfg.emisor_nombre.strip()
    return "SODA SILVIA"


def _build_report_pdf(db: Session, d_from: date, d_to: date) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm, bottomMargin=14 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, textColor=colors.grey)
    normal = styles["Normal"]

    story = []
    story.append(Paragraph("Reporte Sanitario — Programa de Higiene y Desinfección", h1))
    story.append(Paragraph(_establishment_name(db), styles["Heading3"]))
    story.append(Paragraph(f"Período: {d_from.strftime('%d/%m/%Y')} — {d_to.strftime('%d/%m/%Y')}", normal))
    story.append(Paragraph(f"Generado: {cr_now().strftime('%d/%m/%Y %H:%M')} (hora CR)", small))
    story.append(Paragraph(
        "Este reporte documenta la ejecución operativa del Programa de Higiene y Desinfección. "
        "Las frecuencias y procedimientos reflejan la configuración del establecimiento.", small))

    def _tbl(data, col_widths=None):
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f4c81")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d0dc")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f9")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    P = lambda s: Paragraph(str(s or "—"), ParagraphStyle("c", parent=normal, fontSize=8))

    dt_from = datetime.combine(d_from, datetime.min.time())
    dt_to = datetime.combine(d_to, datetime.max.time())

    # ── Protocolo (áreas + tareas) ──
    story.append(Paragraph("Protocolo vigente (áreas, tareas y frecuencias)", h2))
    tasks = (
        db.query(CleaningTask).options(joinedload(CleaningTask.area))
        .filter(CleaningTask.active == True).order_by(CleaningTask.area_id, CleaningTask.name).all()  # noqa: E712
    )
    rows = [["Área", "Tarea", "Frecuencia", "Momento", "Responsable"]]
    for t in tasks:
        rows.append([P(t.area.name if t.area else "—"), P(t.name),
                     P(FREQUENCY_LABELS.get(t.frequency, t.frequency)),
                     P(MOMENT_LABELS.get(t.moment or "", "—")), P(t.responsible)])
    story.append(_tbl(rows, [70, 150, 80, 70, 90]) if len(rows) > 1 else Paragraph("Sin tareas configuradas.", normal))

    # ── Registros de limpieza ──
    story.append(Paragraph("Registros de limpieza realizados", h2))
    recs = (
        db.query(CleaningRecord).options(joinedload(CleaningRecord.task).joinedload(CleaningTask.area))
        .filter(CleaningRecord.scheduled_date >= d_from, CleaningRecord.scheduled_date <= d_to)
        .order_by(CleaningRecord.scheduled_date.desc(), CleaningRecord.id.desc()).all()
    )
    total = len(recs)
    done = sum(1 for r in recs if r.status in ("completada", "verificada"))
    verified = sum(1 for r in recs if r.status == "verificada")
    pct = round(done / total * 100) if total else 0
    story.append(Paragraph(f"Total programadas: {total} · Realizadas: {done} ({pct}%) · Verificadas: {verified}", normal))
    rows = [["Fecha", "Área", "Tarea", "Estado", "Realizó", "Verificó"]]
    for r in recs[:400]:
        rows.append([
            P(r.scheduled_date.strftime("%d/%m/%Y")),
            P(r.task.area.name if r.task and r.task.area else "—"),
            P(r.task.name if r.task else "—"),
            P(STATE_LABELS.get(r.status, r.status)),
            P(r.created_by), P(r.verified_by),
        ])
    story.append(_tbl(rows, [55, 70, 130, 60, 65, 65]) if len(rows) > 1 else Paragraph("Sin registros en el período.", normal))

    # ── Incidencias ──
    story.append(Paragraph("Incidencias y acciones correctivas", h2))
    incs = (
        db.query(CleaningIncident).options(joinedload(CleaningIncident.area))
        .filter(CleaningIncident.created_at >= dt_from, CleaningIncident.created_at <= dt_to)
        .order_by(CleaningIncident.created_at.desc()).all()
    )
    rows = [["Fecha", "Área", "Problema", "Prioridad", "Acción", "Estado"]]
    for i in incs:
        rows.append([
            P(i.created_at.strftime("%d/%m/%Y")), P(i.area.name if i.area else "—"),
            P(i.problem), P(PRIORITY_LABELS.get(i.priority, i.priority)),
            P(i.corrective_action), P(INCIDENT_STATE_LABELS.get(i.status, i.status)),
        ])
    story.append(_tbl(rows, [55, 65, 120, 55, 110, 60]) if len(rows) > 1 else Paragraph("Sin incidencias en el período.", normal))

    # ── Temperaturas ──
    story.append(Paragraph("Control de temperaturas", h2))
    temps = (
        db.query(TemperatureRecord).options(joinedload(TemperatureRecord.equipment))
        .filter(TemperatureRecord.recorded_at >= dt_from, TemperatureRecord.recorded_at <= dt_to)
        .order_by(TemperatureRecord.recorded_at.desc()).limit(300).all()
    )
    rows = [["Fecha/Hora", "Equipo", "Temp.", "Rango", "Estado", "Registró"]]
    for tr in temps:
        eq = tr.equipment
        rng = f"{eq.min_temp if eq and eq.min_temp is not None else '—'} a {eq.max_temp if eq and eq.max_temp is not None else '—'} °C" if eq else "—"
        rows.append([
            P(tr.recorded_at.strftime("%d/%m/%Y %H:%M")), P(eq.name if eq else "—"),
            P(f"{tr.temperature} °C"), P(rng),
            P("FUERA DE RANGO" if tr.out_of_range else "OK"), P(tr.created_by),
        ])
    story.append(_tbl(rows, [80, 90, 55, 80, 75, 65]) if len(rows) > 1 else Paragraph("Sin lecturas en el período.", normal))

    # ── Plagas ──
    story.append(Paragraph("Control de plagas", h2))
    pests = (
        db.query(PestControlRecord).options(joinedload(PestControlRecord.area))
        .filter(PestControlRecord.inspection_date >= d_from, PestControlRecord.inspection_date <= d_to)
        .order_by(PestControlRecord.inspection_date.desc()).all()
    )
    rows = [["Fecha", "Área", "Tipo", "Evidencia", "Acción", "Estado"]]
    for p in pests:
        rows.append([
            P(p.inspection_date.strftime("%d/%m/%Y")), P(p.area.name if p.area else "—"),
            P(p.pest_type), P(p.evidence), P(p.action_taken),
            P(PEST_STATE_LABELS.get(p.status, p.status)),
        ])
    story.append(_tbl(rows, [55, 65, 70, 110, 110, 55]) if len(rows) > 1 else Paragraph("Sin registros en el período.", normal))

    story.append(Spacer(1, 10))
    story.append(Paragraph("LISTO Restaurant Software — Control Sanitario", small))
    doc.build(story)
    return buf.getvalue()
