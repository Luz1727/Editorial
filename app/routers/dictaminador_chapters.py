import os
from datetime import datetime, date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel

from app.db.session import get_db
from app.core.deps import get_current_user

from app.models.user import User
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.dictamen import Dictamen
from app.models.chapter_history import ChapterHistory
from app.models.chapter_deadline import ChapterDeadline

router = APIRouter(prefix="/dictaminador", tags=["dictaminador"])

# =========================
# Schemas
# =========================
class DictaminadorChapterOut(BaseModel):
    id: int
    title: str
    status: str
    updated_at: str
    file_path: Optional[str] = None
    corrected_file_path: Optional[str] = None
    corrected_updated_at: Optional[str] = None
    book_name: Optional[str] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    
    # Fechas límite (editorial -> dictaminador)
    deadline_at: Optional[str] = None
    deadline_stage: Optional[str] = None
    days_remaining: Optional[int] = None
    is_overdue: Optional[bool] = False
    
    # ✅ NUEVO: fecha límite que el dictaminador asigna al autor
    author_deadline_at: Optional[str] = None
    author_days_remaining: Optional[int] = None
    author_is_overdue: Optional[bool] = False
    
    class Config:
        from_attributes = True


class DictaminadorStatusUpdateIn(BaseModel):
    status: str
    comment: Optional[str] = None
    # ✅ NUEVO: fecha límite para el autor (formato ISO: YYYY-MM-DDTHH:MM:SS)
    author_deadline_at: Optional[str] = None


# =========================
# Helpers
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


def _require_dictaminador(db: Session, user_or_payload) -> User:
    uid = _user_id(db, user_or_payload)
    me = db.query(User).filter(User.id == uid).first()
    if not me:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if me.role != "dictaminador":
        raise HTTPException(status_code=403, detail="No autorizado (solo dictaminador)")
    return me


def _calculate_days_remaining(deadline_date: Optional[datetime]) -> tuple[Optional[int], bool]:
    """Calcula días restantes y si está vencido"""
    if not deadline_date:
        return None, False
    
    today = date.today()
    if isinstance(deadline_date, datetime):
        deadline_date = deadline_date.date()
    
    days = (deadline_date - today).days
    return days, days < 0


# =========================
# GET /dictaminador/chapters
# =========================
@router.get("/chapters", response_model=List[DictaminadorChapterOut])
def list_my_chapters(
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Obtiene los capítulos asignados al dictaminador actual"""
    
    dictaminador = _require_dictaminador(db, user)
    
    chapters = (
        db.query(
            Chapter.id,
            Chapter.title,
            Chapter.status,
            Chapter.updated_at,
            Chapter.file_path,
            Chapter.corrected_file_path,
            Chapter.corrected_updated_at,
            Chapter.book_id,
            Book.name.label("book_name"),
            Chapter.author_name,
            Chapter.author_email,
            Chapter.deadline_at,
            Chapter.deadline_stage,
            Chapter.author_deadline_at,  # ✅ NUEVO
        )
        .join(Book, Book.id == Chapter.book_id)
        .filter(Chapter.evaluator_id == dictaminador.id)
        .order_by(
            Chapter.deadline_at.asc().nulls_last(),
            Chapter.author_deadline_at.asc().nulls_last(),
            Chapter.updated_at.desc()
        )
        .all()
    )
    
    result = []
    
    for c in chapters:
        # Calcular días para fecha límite de editorial
        days_remaining, is_overdue = _calculate_days_remaining(c.deadline_at)
        
        # ✅ NUEVO: calcular días para fecha límite de autor
        author_days, author_overdue = _calculate_days_remaining(c.author_deadline_at)
        
        result.append(DictaminadorChapterOut(
            id=c.id,
            title=c.title,
            status=c.status,
            updated_at=str(c.updated_at),
            file_path=c.file_path,
            corrected_file_path=c.corrected_file_path,
            corrected_updated_at=str(c.corrected_updated_at) if c.corrected_updated_at else None,
            book_name=c.book_name,
            author_name=c.author_name,
            author_email=c.author_email,
            deadline_at=str(c.deadline_at) if c.deadline_at else None,
            deadline_stage=c.deadline_stage,
            days_remaining=days_remaining,
            is_overdue=is_overdue,
            # ✅ NUEVO
            author_deadline_at=str(c.author_deadline_at) if c.author_deadline_at else None,
            author_days_remaining=author_days,
            author_is_overdue=author_overdue
        ))
    
    return result


# =========================
# GET /dictaminador/chapters/{chapter_id}
# =========================
@router.get("/chapters/{chapter_id}", response_model=DictaminadorChapterOut)
def get_chapter_detail(
    chapter_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Obtiene detalle de un capítulo específico"""
    
    dictaminador = _require_dictaminador(db, user)
    
    c = (
        db.query(
            Chapter.id,
            Chapter.title,
            Chapter.status,
            Chapter.updated_at,
            Chapter.file_path,
            Chapter.corrected_file_path,
            Chapter.corrected_updated_at,
            Chapter.book_id,
            Book.name.label("book_name"),
            Chapter.author_name,
            Chapter.author_email,
            Chapter.deadline_at,
            Chapter.deadline_stage,
            Chapter.author_deadline_at,  # ✅ NUEVO
        )
        .join(Book, Book.id == Chapter.book_id)
        .filter(
            Chapter.id == chapter_id,
            Chapter.evaluator_id == dictaminador.id
        )
        .first()
    )
    
    if not c:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado o no asignado a ti")
    
    days_remaining, is_overdue = _calculate_days_remaining(c.deadline_at)
    author_days, author_overdue = _calculate_days_remaining(c.author_deadline_at)
    
    return DictaminadorChapterOut(
        id=c.id,
        title=c.title,
        status=c.status,
        updated_at=str(c.updated_at),
        file_path=c.file_path,
        corrected_file_path=c.corrected_file_path,
        corrected_updated_at=str(c.corrected_updated_at) if c.corrected_updated_at else None,
        book_name=c.book_name,
        author_name=c.author_name,
        author_email=c.author_email,
        deadline_at=str(c.deadline_at) if c.deadline_at else None,
        deadline_stage=c.deadline_stage,
        days_remaining=days_remaining,
        is_overdue=is_overdue,
        author_deadline_at=str(c.author_deadline_at) if c.author_deadline_at else None,
        author_days_remaining=author_days,
        author_is_overdue=author_overdue
    )


# =========================
# PATCH /dictaminador/chapters/{chapter_id}/status
# =========================
@router.patch("/chapters/{chapter_id}/status")
def update_chapter_status(
    chapter_id: int,
    payload: DictaminadorStatusUpdateIn,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Actualizar estado de un capítulo (con opción de fecha límite para autor)"""
    dictaminador = _require_dictaminador(db, user)
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.evaluator_id == dictaminador.id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")
    
    # Validar el estado
    valid_statuses = [
        "EN_REVISION", 
        "CORRECCIONES", 
        "APROBADO", 
        "RECHAZADO",
        "EN_REVISION_DICTAMINADOR", 
        "CORRECCIONES_SOLICITADAS_A_AUTOR"
    ]
    if payload.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Estado inválido. Permitidos: {valid_statuses}")
    
    # Validaciones específicas
    if payload.status == "CORRECCIONES":
        if not payload.comment:
            raise HTTPException(status_code=400, detail="Se requiere comentario para solicitar correcciones")
        if not payload.author_deadline_at:
            raise HTTPException(status_code=400, detail="Se requiere fecha límite para el autor")
    
    if payload.status == "RECHAZADO" and not payload.comment:
        raise HTTPException(status_code=400, detail="Se requiere motivo de rechazo")
    
    # Actualizar estado
    chapter.status = payload.status
    chapter.updated_at = datetime.now()
    
    # ✅ NUEVO: Guardar fecha límite para el autor (si se proporciona)
    if payload.author_deadline_at:
        try:
            # Convertir string a datetime (maneja formatos ISO)
            author_deadline = datetime.fromisoformat(payload.author_deadline_at.replace('Z', '+00:00'))
            chapter.author_deadline_at = author_deadline
            chapter.author_deadline_set_at = datetime.now()
            chapter.author_deadline_set_by = dictaminador.id
            
            # Guardar en historial de deadlines
            deadline_record = ChapterDeadline(
                chapter_id=chapter.id,
                stage="AUTOR",
                due_at=author_deadline,
                set_by=dictaminador.id,
                note=f"Fecha límite para autor establecida por dictaminador: {payload.comment[:100]}"
            )
            db.add(deadline_record)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Formato de fecha inválido: {str(e)}. Use ISO format (YYYY-MM-DDTHH:MM:SS)"
            )
    
    # Guardar comentario en historial
    if payload.comment:
        history = ChapterHistory(
            chapter_id=chapter.id,
            by=dictaminador.name,
            action=f"Cambio de estado a {payload.status}",
            detail=payload.comment,
            at=datetime.now()
        )
        db.add(history)
    
    # Si es CORRECCIONES, también crear un registro en dictamen (opcional)
    if payload.status == "CORRECCIONES" and payload.comment:
        # Buscar si ya existe un dictamen para este capítulo
        existing_dictamen = db.query(Dictamen).filter(
            Dictamen.chapter_id == chapter.id,
            Dictamen.evaluador_id == dictaminador.id
        ).first()
        
        if existing_dictamen:
            existing_dictamen.decision = "CORRECCIONES"
            existing_dictamen.status = "GENERADO"
            existing_dictamen.comentarios = payload.comment
            existing_dictamen.updated_at = datetime.now()
        else:
            # Crear nuevo dictamen
            from app.core.utils import generar_folio
            nuevo_dictamen = Dictamen(
                folio=generar_folio("DICT"),
                chapter_id=chapter.id,
                evaluador_id=dictaminador.id,
                tipo="INVESTIGACION",
                decision="CORRECCIONES",
                status="GENERADO",
                comentarios=payload.comment
            )
            db.add(nuevo_dictamen)
    
    db.commit()
    db.refresh(chapter)
    
    # Obtener datos del libro para la respuesta
    book = db.query(Book).filter(Book.id == chapter.book_id).first()
    
    days_remaining, is_overdue = _calculate_days_remaining(chapter.deadline_at)
    author_days, author_overdue = _calculate_days_remaining(chapter.author_deadline_at)
    
    return {
        "ok": True,
        "id": chapter.id,
        "title": chapter.title,
        "status": chapter.status,
        "updated_at": chapter.updated_at.isoformat(),
        "book_name": book.name if book else None,
        "author_name": chapter.author_name,
        "author_email": chapter.author_email,
        "deadline_at": chapter.deadline_at.isoformat() if chapter.deadline_at else None,
        "deadline_stage": chapter.deadline_stage,
        "author_deadline_at": chapter.author_deadline_at.isoformat() if chapter.author_deadline_at else None,
        "days_remaining": days_remaining,
        "is_overdue": is_overdue,
        "author_days_remaining": author_days,
        "author_is_overdue": author_overdue
    }


# =========================
# GET /dictaminador/chapters/{chapter_id}/view-latest
# =========================
@router.get("/chapters/{chapter_id}/view-latest")
def view_latest_file(
    chapter_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Ver el último archivo del capítulo en el navegador"""
    dictaminador = _require_dictaminador(db, user)
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.evaluator_id == dictaminador.id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")
    
    # Determinar qué archivo mostrar (el más reciente)
    file_path = chapter.corrected_file_path or chapter.file_path
    
    if not file_path:
        raise HTTPException(status_code=404, detail="No hay archivo disponible")
    
    # Construir ruta física (ajusta según tu configuración de almacenamiento)
    storage_dir = os.getenv("STORAGE_DIR", "storage")
    if file_path.startswith("/api/storage/"):
        file_path = file_path.replace("/api/storage/", "")
    
    physical_path = os.path.join(storage_dir, file_path.lstrip("/"))
    
    if not os.path.exists(physical_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en el servidor")
    
    # Determinar media type
    ext = os.path.splitext(physical_path)[1].lower()
    media_type = "application/octet-stream"
    if ext == ".pdf":
        media_type = "application/pdf"
    elif ext in [".doc", ".docx"]:
        media_type = "application/msword"
    
    return FileResponse(
        path=physical_path,
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename=\"{os.path.basename(physical_path)}\""}
    )


# =========================
# GET /dictaminador/chapters/{chapter_id}/download-latest
# =========================
@router.get("/chapters/{chapter_id}/download-latest")
def download_latest_file(
    chapter_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Descargar el último archivo del capítulo"""
    dictaminador = _require_dictaminador(db, user)
    
    chapter = db.query(Chapter).filter(
        Chapter.id == chapter_id,
        Chapter.evaluator_id == dictaminador.id
    ).first()
    
    if not chapter:
        raise HTTPException(status_code=404, detail="Capítulo no encontrado")
    
    file_path = chapter.corrected_file_path or chapter.file_path
    
    if not file_path:
        raise HTTPException(status_code=404, detail="No hay archivo disponible")
    
    # Construir ruta física
    storage_dir = os.getenv("STORAGE_DIR", "storage")
    if file_path.startswith("/api/storage/"):
        file_path = file_path.replace("/api/storage/", "")
    
    physical_path = os.path.join(storage_dir, file_path.lstrip("/"))
    
    if not os.path.exists(physical_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en el servidor")
    
    # Determinar si es corregido para el nombre
    is_corrected = bool(chapter.corrected_file_path)
    suffix = "_CORREGIDO" if is_corrected else ""
    
    # Generar nombre de archivo
    safe_title = "".join(c for c in chapter.title if c.isalnum() or c in (" ", "-", "_")).strip()
    if not safe_title:
        safe_title = f"capitulo_{chapter.id}"
    
    ext = os.path.splitext(physical_path)[1]
    filename = f"{safe_title}{suffix}{ext}".replace(" ", "_")
    
    # Determinar media type
    media_type = "application/octet-stream"
    if ext.lower() == ".pdf":
        media_type = "application/pdf"
    elif ext.lower() in [".doc", ".docx"]:
        media_type = "application/msword"
    
    return FileResponse(
        path=physical_path,
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )


# =========================
# POST /dictaminador/dictamenes/{dictamen_id}/upload-signed
# =========================
@router.post("/dictamenes/{dictamen_id}/upload-signed")
async def upload_signed_dictamen(
    dictamen_id: int,
    file: UploadFile = File(...),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    """Dictaminador sube PDF firmado"""
    dictaminador = _require_dictaminador(db, user)
    
    dictamen = db.query(Dictamen).filter(
        Dictamen.id == dictamen_id,
        Dictamen.evaluador_id == dictaminador.id
    ).first()
    
    if not dictamen:
        raise HTTPException(status_code=404, detail="Dictamen no encontrado")
    
    # Validar que sea PDF
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos PDF")
    
    # Crear directorio si no existe
    dictamenes_dir = os.path.join(os.getenv("STORAGE_DIR", "storage"), "dictamenes")
    os.makedirs(dictamenes_dir, exist_ok=True)
    
    # Generar nombre único
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"dictamen_firmado_{dictamen.id}_{timestamp}.pdf"
    file_path = os.path.join(dictamenes_dir, filename)
    
    # Guardar archivo
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    
    # Construir URL pública
    public_url = f"/api/storage/dictamenes/{filename}"
    
    # Actualizar dictamen
    dictamen.signed_pdf_path = public_url
    dictamen.status = "FIRMADO"
    dictamen.signed_at = datetime.now()
    dictamen.updated_at = datetime.now()
    
    if note:
        dictamen.comentarios = (dictamen.comentarios or "") + f"\n[Nota de firma]: {note}"
    
    # Actualizar capítulo si corresponde
    if dictamen.chapter_id:
        chapter = db.query(Chapter).filter(Chapter.id == dictamen.chapter_id).first()
        if chapter:
            chapter.status = "FIRMADO"
            chapter.updated_at = datetime.now()
            db.add(chapter)
    
    db.add(dictamen)
    db.commit()
    
    return {
        "ok": True,
        "dictamen_id": dictamen.id,
        "signed_pdf_path": public_url,
        "status": dictamen.status
    }