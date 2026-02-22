# app/schemas/admin_dictamen_documento.py
from pydantic import BaseModel
from typing import Optional, Dict, Any, Literal

DictamenStatus = Literal["BORRADOR", "GENERADO", "FIRMADO"]

class AdminDictamenDocumentoOut(BaseModel):
    id: int
    folio: str
    status: DictamenStatus

    template_docx_path: Optional[str] = None
    generated_docx_path: Optional[str] = None
    pdf_path: Optional[str] = None

    recipient_name: Optional[str] = None
    constancia_data_json: Optional[Dict[str, Any]] = None

    capituloId: int
    capitulo: str
    libro: str
    evaluador: str


class AdminDictamenDocumentoUpdateIn(BaseModel):
    recipient_name: Optional[str] = None
    data: Optional[Dict[str, Any]] = None