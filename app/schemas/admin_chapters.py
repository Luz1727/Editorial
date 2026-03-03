from pydantic import BaseModel
from typing import Optional, Literal, List

# =========================
# Status completos
# =========================
ChapterStatus = Literal[
    "RECIBIDO",
    "ASIGNADO_A_DICTAMINADOR",
    "ENVIADO_A_DICTAMINADOR",
    "EN_REVISION_DICTAMINADOR",
    "CORRECCIONES_SOLICITADAS_A_AUTOR",
    "CORRECCIONES",
    "REENVIADO_POR_AUTOR",
    "REVISADO_POR_EDITORIAL",
    "LISTO_PARA_FIRMA",
    "FIRMADO",
    "EN_REVISION",
    "APROBADO",
    "RECHAZADO",
]

# =========================
# Respuestas Admin Chapters
# =========================
class AdminChapterRowOut(BaseModel):
    id: int
    folio: Optional[str] = None
    title: str
    book_id: int
    book_name: str
    author_name: str
    author_email: str
    status: ChapterStatus
    updated_at: str
    evaluator_email: Optional[str] = None
    deadline_at: Optional[str] = None
    deadline_stage: Optional[str] = None

    class Config:
        from_attributes = True


class ChapterStatusUpdateIn(BaseModel):
    status: ChapterStatus


class CorreccionIn(BaseModel):
    comment: str


class AdminChapterFolioUpdateIn(BaseModel):
    folio: str


# =========================
# ✅ Evaluación / Dictamen (Schemas)
# =========================
DecisionType = Literal["APROBADO", "CORRECCIONES", "RECHAZADO"]


class EvaluacionCriterioIn(BaseModel):
    criterio: str
    value: int  # 1..5


class EvaluacionUpsertIn(BaseModel):
    tipo: Optional[str] = None
    criterios: Optional[List[EvaluacionCriterioIn]] = None
    decision: Optional[DecisionType] = None
    comentarios: Optional[str] = None
    conflicto_interes: Optional[str] = None  # Ej: "NO", "SI (explicar...)"