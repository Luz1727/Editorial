# app/services/dictamen_document_service.py
import os
import uuid
import subprocess
from typing import Dict, Any, Optional

from docxtpl import DocxTemplate


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def unique_filename(prefix: str, ext: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}.{ext}"


def save_upload_to_disk(upload_file, dest_path: str):
    ensure_dir(os.path.dirname(dest_path))
    with open(dest_path, "wb") as f:
        f.write(upload_file.file.read())


def build_context(
    folio: str,
    recipient_name: Optional[str],
    data_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Placeholders esperados en Word (docxtpl):
    {{FOLIO}}, {{RECIPIENT_NAME}}, {{INSTITUTION}}, {{CVU_SNII}}, {{CIUDAD}}, {{CARGO}},
    {{INICIO_DICTAMEN}}, {{FIN_DICTAMEN}}, {{FECHA_EMISION}}
    """
    data_json = data_json or {}

    return {
        "FOLIO": folio or "",
        "RECIPIENT_NAME": recipient_name or "",

        "INSTITUTION": data_json.get("institution", ""),
        "CVU_SNII": data_json.get("cvu_snii", ""),
        "CIUDAD": data_json.get("ciudad", ""),
        "CARGO": data_json.get("cargo", ""),

        "INICIO_DICTAMEN": data_json.get("inicio_dictamen", ""),
        "FIN_DICTAMEN": data_json.get("fin_dictamen", ""),
        "FECHA_EMISION": data_json.get("fecha_emision", ""),
    }


def render_docx_from_template(template_path: str, out_path: str, context: Dict[str, Any]):
    ensure_dir(os.path.dirname(out_path))
    doc = DocxTemplate(template_path)
    doc.render(context or {})
    doc.save(out_path)


def convert_docx_to_pdf_libreoffice(docx_path: str, output_dir: str) -> str:
    """
    Convierte DOCX a PDF usando LibreOffice.
    Si no tienes LibreOffice, esta función lanzará error.
    """
    ensure_dir(output_dir)
    cmd = [
        "soffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        output_dir,
        docx_path,
    ]
    subprocess.run(cmd, check=True)

    base = os.path.splitext(os.path.basename(docx_path))[0]
    pdf_path = os.path.join(output_dir, f"{base}.pdf")
    if not os.path.exists(pdf_path):
        raise RuntimeError("LibreOffice no generó el PDF.")
    return pdf_path