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
    ✅ Placeholders EXACTOS del Word (docxtpl):

    {{FOLIO}}
    {{CIUDAD_ESTADO}}
    {{FECHA_EMISION_TEXTO}}
    {{RECIPIENT_NOMBRE}}
    {{RECIPIENT_INSTITUCION}}
    {{CVU_SNII}}
    {{CAPITULO_TITULO}}
    {{LIBRO_TITULO}}
    {{ENTREGA_TEXTO}}
    {{INICIO_DICTAMEN_TEXTO}}
    {{FIN_DICTAMEN_TEXTO}}
    {{CARGO_TEXTO}}
    {{FIRMA1_NOMBRE}}
    {{FIRMA2_NOMBRE}}
    """
    data_json = data_json or {}

    # recipient_name lo guardas en columna, pero también lo puedes mandar dentro de JSON.
    # Si viene en JSON, preferimos el de columna para no romper tu modelo.
    recipient_nombre = (recipient_name or data_json.get("recipient_nombre") or "").strip()

    return {
        # === Folio sale de la BD
        "FOLIO": (folio or "").strip(),

        # === Datos del encabezado
        "CIUDAD_ESTADO": (data_json.get("ciudad_estado") or "").strip(),
        "FECHA_EMISION_TEXTO": (data_json.get("fecha_emision_texto") or "").strip(),

        # === Destinatario
        "RECIPIENT_NOMBRE": recipient_nombre,
        "RECIPIENT_INSTITUCION": (data_json.get("recipient_institucion") or "").strip(),
        "CVU_SNII": (data_json.get("cvu_snii") or "").strip(),

        # === Obra
        "CAPITULO_TITULO": (data_json.get("capitulo_titulo") or "").strip(),
        "LIBRO_TITULO": (data_json.get("libro_titulo") or "").strip(),
        "ENTREGA_TEXTO": (data_json.get("entrega_texto") or "").strip(),

        # === Periodos / cargo
        "INICIO_DICTAMEN_TEXTO": (data_json.get("inicio_dictamen_texto") or "").strip(),
        "FIN_DICTAMEN_TEXTO": (data_json.get("fin_dictamen_texto") or "").strip(),
        "CARGO_TEXTO": (data_json.get("cargo_texto") or "").strip(),

        # === Firmas
        "FIRMA1_NOMBRE": (data_json.get("firma1_nombre") or "").strip(),
        "FIRMA2_NOMBRE": (data_json.get("firma2_nombre") or "").strip(),
    }


def render_docx_from_template(template_path: str, out_path: str, context: Dict[str, Any]):
    ensure_dir(os.path.dirname(out_path))
    doc = DocxTemplate(template_path)
    doc.render(context or {})
    doc.save(out_path)


def convert_docx_to_pdf_libreoffice(docx_path: str, output_dir: str) -> str:
    """
    Convierte DOCX a PDF usando LibreOffice.
    - En Windows, intenta localizar soffice.exe si no está en PATH.
    - Si falla, lanza error con mensaje útil.
    """
    ensure_dir(output_dir)

    # 1) comando base (Linux / si está en PATH)
    soffice_cmd = os.getenv("SOFFICE_PATH", "soffice")

    # 2) fallback Windows típico si "soffice" no existe en PATH
    if os.name == "nt":
        # si el env no apunta a un exe real, probamos rutas comunes
        if soffice_cmd == "soffice" or not os.path.exists(soffice_cmd):
            candidates = [
                r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
            ]
            for c in candidates:
                if os.path.exists(c):
                    soffice_cmd = c
                    break

    cmd = [
        soffice_cmd,
        "--headless",
        "--nologo",
        "--nolockcheck",
        "--nodefault",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        output_dir,
        docx_path,
    ]

    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        raise RuntimeError(
            f"No se encontró LibreOffice (soffice). "
            f"Instálalo o define SOFFICE_PATH apuntando a soffice.exe."
        )

    if p.returncode != 0:
        raise RuntimeError(f"LibreOffice falló:\nSTDOUT: {p.stdout}\nSTDERR: {p.stderr}")

    base = os.path.splitext(os.path.basename(docx_path))[0]
    pdf_path = os.path.join(output_dir, f"{base}.pdf")

    if not os.path.exists(pdf_path):
        raise RuntimeError(f"LibreOffice terminó pero no generó el PDF: {pdf_path}")

    return pdf_path