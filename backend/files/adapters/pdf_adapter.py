import os
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pymupdf
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from files.base_adapter import FileAdapter


class PdfAdapter(FileAdapter):
    def create(self, path: Path, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise TypeError("PDF creation requires a structured object.")
        pagesize = A4 if str(payload.get("page_size", "A4")).upper() == "A4" else LETTER
        document = SimpleDocTemplate(
            str(path),
            pagesize=pagesize,
            rightMargin=0.7 * inch,
            leftMargin=0.7 * inch,
            topMargin=0.7 * inch,
            bottomMargin=0.7 * inch,
            title=str(payload.get("title", "")),
        )
        styles = getSampleStyleSheet()
        story = []
        title = payload.get("title")
        if title:
            story.extend([Paragraph(escape(str(title)), styles["Title"]), Spacer(1, 12)])
        for block in payload.get("blocks", []):
            kind = block.get("type", "paragraph")
            if kind == "heading":
                level = min(max(int(block.get("level", 1)), 1), 3)
                story.append(Paragraph(escape(str(block.get("text", ""))), styles[f"Heading{level}"]))
            elif kind == "paragraph":
                story.extend([Paragraph(escape(str(block.get("text", ""))), styles["BodyText"]), Spacer(1, 8)])
            elif kind == "page_break":
                story.append(PageBreak())
            else:
                raise ValueError(f"Unsupported PDF block: {kind}")
        if not story:
            story.append(Paragraph(" ", styles["BodyText"]))
        document.build(story)
        with pymupdf.open(path) as pdf:
            return {"format": "pdf", "pages": pdf.page_count}

    def read(self, path: Path) -> dict[str, Any]:
        with pymupdf.open(path) as pdf:
            pages = [
                {"number": index + 1, "text": page.get_text("text")}
                for index, page in enumerate(pdf)
            ]
            return {"format": "pdf", "pages": pages, "page_count": pdf.page_count}

    def edit(self, path: Path, operations: list[dict[str, Any]]) -> dict[str, Any]:
        output = path.with_name(f".{path.stem}-edited{path.suffix}")
        with pymupdf.open(path) as pdf:
            for operation in operations:
                name = operation.get("operation")
                if name == "rotate_page":
                    page = pdf[int(operation["page"]) - 1]
                    page.set_rotation(int(operation.get("degrees", 90)) % 360)
                elif name == "delete_page":
                    pdf.delete_page(int(operation["page"]) - 1)
                elif name == "add_text_overlay":
                    page = pdf[int(operation["page"]) - 1]
                    point = pymupdf.Point(float(operation.get("x", 72)), float(operation.get("y", 72)))
                    page.insert_text(
                        point,
                        str(operation.get("text", "")),
                        fontsize=float(operation.get("font_size", 11)),
                    )
                else:
                    raise ValueError(f"Unsupported PDF operation: {name}")
            pdf.save(output, garbage=4, deflate=True)
        os.replace(output, path)
        with pymupdf.open(path) as pdf:
            return {"format": "pdf", "pages": pdf.page_count}

    def verify(self, path: Path) -> dict[str, Any]:
        result = super().verify(path)
        with pymupdf.open(path) as pdf:
            result["pages"] = pdf.page_count
        return result
