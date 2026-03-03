from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from datetime import datetime
from typing import Optional

from app.db.session import get_db
from app.core.deps import get_current_user

from app.models.user import User
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.chapter_deadline import ChapterDeadline

from app.models.dictamen import Dictamen
from app.models.dictamen_criterio import DictamenCriterio

from app.schemas.admin_chapters import (
    AdminChapterRowOut,
    ChapterStatusUpdateIn,
    CorreccionIn,
    AdminChapterFolioUpdateIn,
    EvaluacionUpsertIn,
)

router = APIRouter(prefix="/admin", tags=["admin-chapters"])


# =========================
# Folio helper
# =========================
def _make_dictamen_folio():
    now = datetime.now()
    return f"DIC-{now.year}-{now.month:02d}-{int(now.timestamp()) % 100000:05d}"


# =========================
# Helpers auth
# =========================
def _user_id(db: Session, user_or_payload) -> int:
    if not isinstance(user_or_payload, dict):
        return int(user_or_payload.id)

    if user_or_payload.get("id") is not None:
        return int(user_or_payload["id"])

    if user_or_payload.get("user_id") is not None:
        return int(user_or_payload["user_id"])

    sub = user_or_payload.get("sub")

    if isinstance(sub, int):
        return int(sub)

    if isinstance(sub, str) and sub.isdigit():
        return int(sub)

    if isinstance(sub, str) and "@" in sub:
        u = db.query(User).filter(User.email == sub.strip().lower()).first()
        if not u:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        return int(u.id)

    raise HTTPException(status_code=401, detail="Token inválido")


def _require_editorial(db: Session, user_or_payload) -> User:
    uid = _user_id(db, user_or_payload)
    me = db.query(User).filter(User.id == uid).first()
    if not me:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if me.role != "editorial":
        raise HTTPException(status_code=403, detail="No autorizado (solo editorial)")
    return me


# ✅ ESTO ES LO QUE TE “DIJERON QUE PEGARAS” (permiso dictaminador)
def _require_dictaminador(db: Session, user_or_payload) -> User:
    uid = _user_id(db, user_or_payload)
    me = db.query(User).filter(User.id == uid).first()
    if not me:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if me.role != "dictaminador":
        raise HTTPException(status_code=403, detail="No autorizado (solo dictaminador)")
    if getattr(me, "active", 1) != 1:
        raise HTTPException(status_code=403, detail="Usuario inactivo")
    return me


# =========================
# Inputs asignación con deadline
# =========================
class AssignEvaluatorIn(BaseModel):
    evaluator_email: str
    deadline_at: Optional[str] = None  # YYYY-MM-DD


class AssignEvaluatorWithDeadlineIn(BaseModel):
    evaluator_email: str
    deadline_at: str
    deadline_stage: Optional[str] = "DICTAMEN"


class DeadlineUpdateIn(BaseModel):
    deadline_at: str
    deadline_stage: Optional[str] = "DICTAMEN"
    note: Optional[str] = None


class DeadlineHistoryOut(BaseModel):
    id: int
    stage: str
    due_at: str
    set_by_name: Optional[str] = None
    set_by_email: Optional[str] = None
    note: Optional[str] = None
    created_at: str

    class Config:
        from_attributes = True


# =========================
# GET /admin/chapters
# =========================
@router.get("/chapters", response_model=list[AdminChapterRowOut])
def list_chapters(db: Session = Depends(get_db), user=Depends(get_current_user)):
    _require_editorial(db, user)

    rows = (
        db.query(
            Chapter.id,
            Chapter.folio,
            Chapter.title,
            Chapter.status,
            Chapter.updated_at,
            Chapter.book_id,
            Book.name.label("book_name"),
            Chapter.author_name,
            Chapter.author_email,
            Chapter.evaluator_email,
            Chapter.evaluator_name,
            Chapter.deadline_at,
            Chapter.deadline_stage,
        )
        .join(Book, Book.id == Chapter.book_id)
        .order_by(Chapter.updated_at.desc(), Chapter.id.desc())
        .all()
    )

    out: list[AdminChapterRowOut] = []
    for r in rows:
        out.append(
            AdminChapterRowOut(
                id=int(r.id),
                folio=r.folio,
                title=r.title,
                book_id=int(r.book_id),
                book_name=r.book_name,
                author_name=r.author_name,
                author_email=r.author_email,
                status=r.status,
                updated_at=str(r.updated_at),
                evaluator_email=r.evaluator_email,
                deadline_at=str(r.deadline_at) if r.deadline_at else None,
                deadline_stage=r.deadline_stage,
            )
        )
    return out


# =========================
# PATCH /admin/chapters/{id}/status
# =========================
@router.patch("/chapters/{chapter_id}/status", response_model=AdminChapterRowOut)
def update_status(
    chapter_id: int,
    payload: ChapterStatusUpdateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    c.status = payload.status
    c.updated_at = func.now()

    db.add(c)
    db.commit()
    db.refresh(c)

    b = db.query(Book).filter(Book.id == c.book_id).first()

    return AdminChapterRowOut(
        id=int(c.id),
        folio=c.folio,
        title=c.title,
        book_id=int(c.book_id),
        book_name=b.name if b else "",
        author_name=c.author_name,
        author_email=c.author_email,
        status=c.status,
        updated_at=str(c.updated_at),
        evaluator_email=c.evaluator_email,
        deadline_at=str(c.deadline_at) if c.deadline_at else None,
        deadline_stage=c.deadline_stage,
    )


# =========================
# POST /admin/chapters/{id}/correccion
# =========================
@router.post("/chapters/{chapter_id}/correccion")
def add_correccion(
    chapter_id: int,
    payload: CorreccionIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    c.status = "CORRECCIONES_SOLICITADAS_A_AUTOR"
    c.updated_at = func.now()

    db.add(c)
    db.commit()

    return {"ok": True}


# =========================
# POST /admin/chapters/{id}/assign
# =========================
@router.post("/chapters/{chapter_id}/assign", response_model=AdminChapterRowOut)
def assign_evaluator(
    chapter_id: int,
    payload: AssignEvaluatorIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    email = (payload.evaluator_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Escribe el correo del dictaminador.")

    evaluator = (
        db.query(User)
        .filter(
            User.email == email,
            User.role == "dictaminador",
            User.active == 1,
        )
        .first()
    )
    if not evaluator:
        raise HTTPException(status_code=400, detail="No existe un dictaminador activo con ese correo.")

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    c.evaluator_id = int(evaluator.id)
    c.evaluator_name = evaluator.name
    c.evaluator_email = evaluator.email
    c.status = "ASIGNADO_A_DICTAMINADOR"
    c.updated_at = func.now()

    if payload.deadline_at:
        try:
            deadline_date = datetime.strptime(payload.deadline_at, "%Y-%m-%d")
            c.deadline_at = deadline_date
            c.deadline_stage = "DICTAMEN"
            c.deadline_set_at = datetime.now()
            c.deadline_set_by = _user_id(db, user)

            deadline_record = ChapterDeadline(
                chapter_id=c.id,
                stage="DICTAMEN",
                due_at=deadline_date,
                set_by=_user_id(db, user),
                note="Fecha límite establecida al asignar dictaminador",
            )
            db.add(deadline_record)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    db.add(c)
    db.commit()
    db.refresh(c)

    b = db.query(Book).filter(Book.id == c.book_id).first()

    return AdminChapterRowOut(
        id=int(c.id),
        folio=c.folio,
        title=c.title,
        book_id=int(c.book_id),
        book_name=b.name if b else "",
        author_name=c.author_name,
        author_email=c.author_email,
        status=c.status,
        updated_at=str(c.updated_at),
        evaluator_email=c.evaluator_email,
        deadline_at=str(c.deadline_at) if c.deadline_at else None,
        deadline_stage=c.deadline_stage,
    )


# =========================
# POST /admin/chapters/{id}/assign-with-deadline
# =========================
@router.post("/chapters/{chapter_id}/assign-with-deadline", response_model=AdminChapterRowOut)
def assign_evaluator_with_deadline(
    chapter_id: int,
    payload: AssignEvaluatorWithDeadlineIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    email = (payload.evaluator_email or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Escribe el correo del dictaminador.")

    evaluator = (
        db.query(User)
        .filter(User.email == email, User.role == "dictaminador", User.active == 1)
        .first()
    )
    if not evaluator:
        raise HTTPException(status_code=400, detail="No existe un dictaminador activo con ese correo.")

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    c.evaluator_id = int(evaluator.id)
    c.evaluator_name = evaluator.name
    c.evaluator_email = evaluator.email
    c.status = "ASIGNADO_A_DICTAMINADOR"
    c.updated_at = func.now()

    try:
        deadline_date = datetime.strptime(payload.deadline_at, "%Y-%m-%d")
        c.deadline_at = deadline_date
        c.deadline_stage = payload.deadline_stage or "DICTAMEN"
        c.deadline_set_at = datetime.now()
        c.deadline_set_by = _user_id(db, user)

        deadline_record = ChapterDeadline(
            chapter_id=c.id,
            stage=c.deadline_stage,
            due_at=deadline_date,
            set_by=_user_id(db, user),
            note="Fecha límite establecida al asignar dictaminador",
        )
        db.add(deadline_record)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    db.add(c)
    db.commit()
    db.refresh(c)

    b = db.query(Book).filter(Book.id == c.book_id).first()

    return AdminChapterRowOut(
        id=int(c.id),
        folio=c.folio,
        title=c.title,
        book_id=int(c.book_id),
        book_name=b.name if b else "",
        author_name=c.author_name,
        author_email=c.author_email,
        status=c.status,
        updated_at=str(c.updated_at),
        evaluator_email=c.evaluator_email,
        deadline_at=str(c.deadline_at) if c.deadline_at else None,
        deadline_stage=c.deadline_stage,
    )


# =========================
# PATCH /admin/chapters/{id}/deadline
# =========================
@router.patch("/chapters/{chapter_id}/deadline", response_model=AdminChapterRowOut)
def update_deadline(
    chapter_id: int,
    payload: DeadlineUpdateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    try:
        deadline_date = datetime.strptime(payload.deadline_at, "%Y-%m-%d")
        old_deadline = str(c.deadline_at) if c.deadline_at else "ninguna"

        c.deadline_at = deadline_date
        c.deadline_stage = payload.deadline_stage
        c.deadline_set_at = datetime.now()
        c.deadline_set_by = _user_id(db, user)
        c.updated_at = func.now()

        note = payload.note or f"Fecha límite actualizada: {old_deadline} → {payload.deadline_at}"
        deadline_record = ChapterDeadline(
            chapter_id=c.id,
            stage=payload.deadline_stage,
            due_at=deadline_date,
            set_by=_user_id(db, user),
            note=note,
        )
        db.add(deadline_record)

        db.add(c)
        db.commit()
        db.refresh(c)

    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")

    b = db.query(Book).filter(Book.id == c.book_id).first()

    return AdminChapterRowOut(
        id=int(c.id),
        folio=c.folio,
        title=c.title,
        book_id=int(c.book_id),
        book_name=b.name if b else "",
        author_name=c.author_name,
        author_email=c.author_email,
        status=c.status,
        updated_at=str(c.updated_at),
        evaluator_email=c.evaluator_email,
        deadline_at=str(c.deadline_at) if c.deadline_at else None,
        deadline_stage=c.deadline_stage,
    )


# =========================
# GET /admin/chapters/{id}/deadlines
# =========================
@router.get("/chapters/{chapter_id}/deadlines", response_model=list[DeadlineHistoryOut])
def get_deadline_history(
    chapter_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    deadlines = (
        db.query(ChapterDeadline)
        .filter(ChapterDeadline.chapter_id == chapter_id)
        .order_by(ChapterDeadline.created_at.desc())
        .all()
    )

    result = []
    for d in deadlines:
        setter_name = d.setter.name if getattr(d, "setter", None) else None
        setter_email = d.setter.email if getattr(d, "setter", None) else None

        result.append(
            DeadlineHistoryOut(
                id=d.id,
                stage=d.stage,
                due_at=str(d.due_at),
                set_by_name=setter_name,
                set_by_email=setter_email,
                note=d.note,
                created_at=str(d.created_at),
            )
        )
    return result


# =========================
# PATCH /admin/chapters/{id}/folio
# =========================
@router.patch("/chapters/{chapter_id}/folio", response_model=AdminChapterRowOut)
def update_chapter_folio(
    chapter_id: int,
    payload: AdminChapterFolioUpdateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    _require_editorial(db, user)

    folio = (payload.folio or "").strip()
    if not folio:
        raise HTTPException(status_code=400, detail="El folio no puede ir vacío.")

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    c.folio = folio
    c.updated_at = func.now()

    try:
        db.add(c)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ese folio ya está en uso por otro capítulo.")

    db.refresh(c)
    b = db.query(Book).filter(Book.id == c.book_id).first()

    return AdminChapterRowOut(
        id=int(c.id),
        folio=c.folio,
        title=c.title,
        book_id=int(c.book_id),
        book_name=b.name if b else "",
        author_name=c.author_name,
        author_email=c.author_email,
        status=c.status,
        updated_at=str(c.updated_at),
        evaluator_email=getattr(c, "evaluator_email", None),
        deadline_at=str(c.deadline_at) if c.deadline_at else None,
        deadline_stage=c.deadline_stage,
    )


# =========================================================
# ✅✅ EVALUACIÓN (DICTAMINADOR) - LO QUE TE FALTABA
# =========================================================

@router.get("/chapters/{chapter_id}/evaluacion")
def get_evaluacion_actual(
    chapter_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Devuelve la evaluación del dictaminador asignado (si existe),
    para precargar tu formulario del frontend.
    """
    # Permitir editorial o dictaminador
    me_dict = None
    try:
        _require_editorial(db, user)
    except HTTPException:
        me_dict = _require_dictaminador(db, user)

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    # dictaminador solo ve el suyo y si está asignado
    if me_dict:
        if not c.evaluator_id or int(c.evaluator_id) != int(me_dict.id):
            raise HTTPException(status_code=403, detail="Este capítulo no está asignado a tu usuario")

    # buscar dictamen por evaluador asignado
    evaluador_id = int(me_dict.id) if me_dict else (int(c.evaluator_id) if c.evaluator_id else None)
    if not evaluador_id:
        return {"exists": False, "data": None}

    d = (
        db.query(Dictamen)
        .filter(Dictamen.chapter_id == int(chapter_id), Dictamen.evaluador_id == evaluador_id)
        .first()
    )
    if not d:
        return {"exists": False, "data": None}

    criterios = (
        db.query(DictamenCriterio)
        .filter(DictamenCriterio.dictamen_id == int(d.id))
        .order_by(DictamenCriterio.id.asc())
        .all()
    )

    return {
        "exists": True,
        "data": {
            "dictamen_id": int(d.id),
            "folio": d.folio,
            "tipo": d.tipo,
            "promedio": d.promedio,
            "decision": d.decision,
            "comentarios": d.comentarios,
            "conflicto_interes": d.conflicto_interes,
            "status": d.status,
            "criterios": [{"criterio": x.criterio, "value": x.value} for x in criterios],
        },
    }


@router.post("/chapters/{chapter_id}/evaluacion/upsert")
def upsert_evaluacion(
    chapter_id: int,
    payload: EvaluacionUpsertIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Crea o actualiza evaluación (dictamen + criterios).
    - Dictaminador: solo si está asignado al capítulo
    - Editorial: permitido (si quieres), usando evaluator_id del capítulo
    """
    me_dict = None
    me_edit = None

    try:
        me_edit = _require_editorial(db, user)
    except HTTPException:
        me_dict = _require_dictaminador(db, user)

    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")

    # dictaminador: debe ser el asignado
    if me_dict:
        if not c.evaluator_id or int(c.evaluator_id) != int(me_dict.id):
            raise HTTPException(status_code=403, detail="Este capítulo no está asignado a tu usuario")

    evaluador_id = int(me_dict.id) if me_dict else (int(c.evaluator_id) if c.evaluator_id else None)
    if not evaluador_id:
        raise HTTPException(status_code=400, detail="El capítulo no tiene dictaminador asignado")

    # 1) Obtener o crear dictamen (por UNIQUE chapter_id+evaluador_id)
    d = (
        db.query(Dictamen)
        .filter(Dictamen.chapter_id == int(chapter_id), Dictamen.evaluador_id == int(evaluador_id))
        .first()
    )

    if d and getattr(d, "status", None) == "FIRMADO":
        raise HTTPException(status_code=409, detail="El dictamen ya está FIRMADO y no se puede modificar")

    if not d:
        d = Dictamen(
            folio=_make_dictamen_folio(),
            chapter_id=int(chapter_id),
            evaluador_id=int(evaluador_id),
            status="BORRADOR",
            created_at=datetime.now(),
        )
        db.add(d)
        db.flush()  # d.id

    # 2) Actualizar campos
    if payload.tipo is not None:
        d.tipo = payload.tipo.strip() if payload.tipo else None

    if payload.decision is not None:
        d.decision = payload.decision

    if payload.comentarios is not None:
        d.comentarios = payload.comentarios

    if payload.conflicto_interes is not None:
        d.conflicto_interes = payload.conflicto_interes

    # 3) Reemplazar criterios
    db.query(DictamenCriterio).filter(DictamenCriterio.dictamen_id == int(d.id)).delete(synchronize_session=False)

    total = 0
    count = 0

    for it in (payload.criterios or []):
        crit_name = (it.criterio or "").strip()
        if not crit_name:
            continue

        val = int(it.value)
        if val < 1 or val > 5:
            raise HTTPException(status_code=400, detail="Cada criterio debe tener value entre 1 y 5")

        total += val
        count += 1

        db.add(
            DictamenCriterio(
                dictamen_id=int(d.id),
                criterio=crit_name,
                value=val,
            )
        )

    d.promedio = (total / count) if count > 0 else None

    # 4) Actualizar status del capítulo según decision (opcional pero recomendado)
    if payload.decision:
        if payload.decision == "APROBADO":
            c.status = "APROBADO"
        elif payload.decision == "CORRECCIONES":
            c.status = "CORRECCIONES_SOLICITADAS_A_AUTOR"
        elif payload.decision == "RECHAZADO":
            c.status = "RECHAZADO"

        c.updated_at = func.now()
        db.add(c)

    db.add(d)
    db.commit()
    db.refresh(d)

    return {
        "ok": True,
        "dictamen_id": int(d.id),
        "folio": d.folio,
        "promedio": d.promedio,
        "decision": d.decision,
        "status": d.status,
    }