import os
import re
import uuid
import shutil
import zipfile
from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from docxtpl import DocxTemplate

from app.db.session import get_db
from app.core.deps import get_current_user

from app.models.user import User
from app.models.book import Book
from app.models.chapter import Chapter
from app.models.admin_template import AdminTemplate

from app.schemas.admin_templates import AdminTemplateOut, AdminTemplateGenerateIn

router = APIRouter(prefix="/admin/templates", tags=["admin-templates"])

# =========================
# Storage
# =========================
BASE_STORAGE = os.getenv("EDITORIAL_STORAGE_DIR", "storage")
TPL_DIR = os.path.join(BASE_STORAGE, "templates")
GEN_DIR = os.path.join(BASE_STORAGE, "generated")

os.makedirs(TPL_DIR, exist_ok=True)
os.makedirs(GEN_DIR, exist_ok=True)

# =========================
# Helpers (igual a tu estilo)
# =========================
def require_admin(payload: dict):
    if payload.get("role") != "editorial":
        raise HTTPException(status_code=403, detail="Solo editorial/admin puede realizar esta acción.")

def safe_filename(filename: str) -> str:
    filename = (filename or "").strip().replace("\\", "/").split("/")[-1]
    filename = re.sub(r"[^\w\-.]+", "_", filename, flags=re.UNICODE)
    return filename[:200] or "archivo.docx"

def safe_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"[^\w\-. ]+", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or "plantilla"

def ensure_docx(filename: str):
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Solo se permite .docx")

def _user_id(db: Session, payload: dict) -> int:
    # tu estilo de token
    if payload.get("id") is not None:
        return int(payload["id"])
    if payload.get("user_id") is not None:
        return int(payload["user_id"])

    sub = payload.get("sub")
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

def _ctx_for_author(db: Session, author: User) -> Dict[str, Any]:
    """
    Placeholders sugeridos:
      {{nombre}}, {{email}}, {{fecha}}, {{folio}}, {{titulo_capitulo}}, {{libro}}
    """
    ctx = {
        "nombre": author.name,
        "email": author.email,
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "folio": "",
        "titulo_capitulo": "",
        "libro": "",
    }

    # capítulo más reciente del autor (si existe)
    ch = (
        db.query(Chapter)
        .filter(Chapter.author_id == author.id)
        .order_by(desc(Chapter.updated_at), desc(Chapter.id))
        .first()
    )
    if ch:
        ctx["folio"] = getattr(ch, "folio", "") or ""
        ctx["titulo_capitulo"] = getattr(ch, "title", "") or ""

        b = db.query(Book).filter(Book.id == ch.book_id).first()
        if b:
            ctx["libro"] = getattr(b, "name", "") or ""

    return ctx

def _authors_for_mode(db: Session, body: AdminTemplateGenerateIn) -> List[User]:
    if body.mode == "ALL":
        return (
            db.query(User)
            .filter(User.role == "autor", User.active == 1)
            .order_by(User.id.asc())
            .all()
        )

    if body.mode == "SELECTED":
        if not body.user_ids:
            return []
        return (
            db.query(User)
            .filter(User.role == "autor", User.active == 1, User.id.in_(body.user_ids))
            .order_by(User.id.asc())
            .all()
        )

    if body.mode == "BOOK":
        if not body.book_id:
            return []

        # autores de ese libro por capítulos (DISTINCT chapters.author_id)
        rows = (
            db.query(Chapter.author_id)
            .filter(Chapter.book_id == body.book_id)
            .distinct()
            .all()
        )
        ids = [int(r[0]) for r in rows if r and r[0] is not None]
        if not ids:
            return []

        return (
            db.query(User)
            .filter(User.role == "autor", User.active == 1, User.id.in_(ids))
            .order_by(User.id.asc())
            .all()
        )

    return []

# =========================
# GET /admin/templates
# =========================
@router.get("", response_model=list[AdminTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user),
):
    require_admin(payload)

    rows = db.query(AdminTemplate).order_by(AdminTemplate.id.desc()).all()
    # Pydantic from_attributes trabaja, pero created_at a iso lo convertimos por consistencia
    out = []
    for r in rows:
        out.append(
            AdminTemplateOut(
                id=int(r.id),
                name=r.name,
                original_filename=r.original_filename,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
        )
    return out

# =========================
# POST /admin/templates  (multipart)
# =========================
@router.post("", response_model=AdminTemplateOut)
async def upload_template(
    name: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user),
):
    require_admin(payload)

    original = safe_filename(file.filename or "plantilla.docx")
    ensure_docx(original)

    tpl_name = safe_name(name) if name.strip() else safe_name(original.replace(".docx", ""))

    token = uuid.uuid4().hex
    stored = f"tpl_{token}.docx"
    save_path = os.path.join(TPL_DIR, stored)

    content = await file.read()
    if not content or len(content) < 200:
        raise HTTPException(status_code=400, detail="Archivo vacío o inválido.")

    with open(save_path, "wb") as f:
        f.write(content)

    created_by = _user_id(db, payload)

    row = AdminTemplate(
        name=tpl_name,
        original_filename=original,
        file_path=save_path,
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return AdminTemplateOut(
        id=int(row.id),
        name=row.name,
        original_filename=row.original_filename,
        created_at=row.created_at.isoformat() if row.created_at else "",
    )

# =========================
# DELETE /admin/templates/{id}
# =========================
@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user),
):
    require_admin(payload)

    row = db.query(AdminTemplate).filter(AdminTemplate.id == template_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")

    try:
        if row.file_path and os.path.exists(row.file_path):
            os.remove(row.file_path)
    except Exception:
        pass

    db.delete(row)
    db.commit()
    return {"ok": True}

# =========================
# POST /admin/templates/{id}/generate  -> ZIP
# =========================
@router.post("/{template_id}/generate")
def generate_zip(
    template_id: int,
    body: AdminTemplateGenerateIn,
    db: Session = Depends(get_db),
    payload: dict = Depends(get_current_user),
):
    require_admin(payload)

    tpl = db.query(AdminTemplate).filter(AdminTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    if not tpl.file_path or not os.path.exists(tpl.file_path):
        raise HTTPException(status_code=500, detail="Archivo de plantilla no disponible")

    authors = _authors_for_mode(db, body)
    if not authors:
        raise HTTPException(status_code=400, detail="No hay autores para generar.")

    run_id = uuid.uuid4().hex
    run_dir = os.path.join(GEN_DIR, f"run_{run_id}")
    os.makedirs(run_dir, exist_ok=True)

    try:
        generated_paths: List[str] = []

        for a in authors:
            ctx = _ctx_for_author(db, a)

            doc = DocxTemplate(tpl.file_path)
            doc.render(ctx)

            out_name = safe_filename(f"{a.name}_{a.id}.docx")
            out_path = os.path.join(run_dir, out_name)
            doc.save(out_path)
            generated_paths.append(out_path)

        zip_filename = safe_filename(f"{tpl.name}_generados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")
        zip_path = os.path.join(GEN_DIR, f"{run_id}_{zip_filename}")

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in generated_paths:
                z.write(p, arcname=os.path.basename(p))

        return FileResponse(zip_path, media_type="application/zip", filename=zip_filename)

    finally:
        try:
            shutil.rmtree(run_dir, ignore_errors=True)
        except Exception:
            pass