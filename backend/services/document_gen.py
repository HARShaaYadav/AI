import logging
import os
import uuid
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

logger = logging.getLogger(__name__)

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_docs")
os.makedirs(DOCS_DIR, exist_ok=True)

FONT_CANDIDATES = [
    ("NotoSansDevanagari", "NotoSansDevanagari-Regular.ttf"),
    ("NotoSansDevanagari", "NotoSansDevanagari-Medium.ttf"),
    ("NirmalaUI", "Nirmala.ttc", 0),
    ("NirmalaUI", os.path.join("C:\\", "Windows", "Fonts", "Nirmala.ttc"), 0),
    ("NirmalaUI", os.path.join("C:\\", "Windows", "Fonts", "Nirmala.ttf")),
    ("Mangal", os.path.join("C:\\", "Windows", "Fonts", "Mangal.ttf")),
    ("Aparajita", os.path.join("C:\\", "Windows", "Fonts", "Aparaj.ttf")),
    ("Kokila", os.path.join("C:\\", "Windows", "Fonts", "Kokila.ttf")),
]

DETAIL_LABELS_HI = {
    "incident_description": "घटना का विवरण",
    "date_time": "दिनांक और समय",
    "location": "स्थान",
    "suspect_description": "आरोपी का विवरण",
    "witness": "गवाह",
}


def _contains_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in (text or ""))


def _resolve_font_path(path: str) -> str | None:
    if os.path.isabs(path) and os.path.exists(path):
        return path

    search_roots = [
        os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "assets", "fonts"),
        os.path.join(os.path.dirname(__file__), "..", "..", "backend", "assets", "fonts"),
        os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts"),
    ]
    for root in search_roots:
        candidate = os.path.abspath(os.path.join(root, path))
        if os.path.exists(candidate):
            return candidate
    return None


def _register_unicode_font(text_parts: list[str]) -> str:
    if not any(_contains_devanagari(part) for part in text_parts if part):
        return "Helvetica"

    for font_candidate in FONT_CANDIDATES:
        font_name = font_candidate[0]
        font_path = font_candidate[1]
        subfont_index = font_candidate[2] if len(font_candidate) > 2 else 0
        resolved_path = _resolve_font_path(font_path)
        if not resolved_path:
            continue
        try:
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, resolved_path, subfontIndex=subfont_index))
            logger.info("Using PDF font '%s' from %s", font_name, resolved_path)
            return font_name
        except Exception as exc:
            logger.warning("Could not register font %s from %s: %s", font_name, resolved_path, exc)

    logger.warning("No Unicode Devanagari font was found. Hindi text may render as boxes.")
    return "Helvetica"


def _safe_text(value: object) -> str:
    return escape("" if value is None else str(value))


def generate_pdf(user_id: str, doc_type: str, content: str, details: dict) -> str:
    """Generate a PDF document and return the file path."""
    safe_type = doc_type.lower().replace(" ", "_").replace("/", "_")
    filename = f"{safe_type}_{user_id}_{uuid.uuid4().hex[:6]}.pdf"
    filepath = os.path.join(DOCS_DIR, filename)

    try:
        language = str((details or {}).get("language", "en")).lower()
        font_name = _register_unicode_font(
            [doc_type, content, *(str(value) for value in (details or {}).values())]
        )

        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            rightMargin=2.5 * cm,
            leftMargin=2.5 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
        )

        styles = getSampleStyleSheet()
        header_style = ParagraphStyle(
            "Header",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=2,
        )
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            fontName=font_name,
            alignment=TA_CENTER,
            fontSize=18,
            textColor=colors.HexColor("#1a4a7a"),
            spaceAfter=6,
            spaceBefore=8,
        )
        subtitle_style = ParagraphStyle(
            "Subtitle",
            parent=styles["Normal"],
            fontName=font_name,
            alignment=TA_CENTER,
            fontSize=10,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=16,
        )
        section_style = ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=11,
            textColor=colors.HexColor("#1a4a7a"),
            spaceBefore=12,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=16,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
        )
        detail_style = ParagraphStyle(
            "Detail",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=15,
            spaceAfter=4,
            leftIndent=10,
        )
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=8,
            textColor=colors.HexColor("#9ca3af"),
            spaceAfter=4,
        )

        case_details_heading = "CASE DETAILS" if language != "hi" else "मामले का विवरण"
        complaint_heading = "COMPLAINT / STATEMENT" if language != "hi" else "शिकायत / बयान"
        generated_label = "Generated" if language != "hi" else "तैयार किया गया"
        reference_label = "Reference" if language != "hi" else "संदर्भ"
        signature_label = "Complainant Signature" if language != "hi" else "शिकायतकर्ता के हस्ताक्षर"
        date_label = "Date" if language != "hi" else "दिनांक"

        story = []
        story.append(Paragraph("NyayaVoice - Voice Legal Aid Assistant", header_style))
        story.append(
            Paragraph(
                _safe_text(
                    f"{generated_label}: {datetime.now().strftime('%d %B %Y, %I:%M %p')}  |  {reference_label}: {uuid.uuid4().hex[:8].upper()}"
                ),
                header_style,
            )
        )
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a4a7a"), spaceAfter=8))

        story.append(Paragraph(_safe_text(doc_type.upper()), title_style))
        story.append(Paragraph("Prepared with assistance of NyayaVoice AI Legal Aid System", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=12))

        if details:
            story.append(Paragraph(case_details_heading, section_style))
            for key, value in details.items():
                if value and key not in ("complainant_id", "language"):
                    label = DETAIL_LABELS_HI.get(key, key.replace("_", " ").title()) if language == "hi" else key.replace("_", " ").title()
                    story.append(Paragraph(f"{_safe_text(label)}: {_safe_text(value)}", detail_style))
            story.append(Spacer(1, 0.4 * cm))

        story.append(Paragraph(complaint_heading, section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))

        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                story.append(Spacer(1, 0.2 * cm))
            elif stripped.startswith("#"):
                story.append(Paragraph(_safe_text(stripped.lstrip("#").strip()), section_style))
            else:
                story.append(Paragraph(_safe_text(stripped), body_style))

        story.append(Spacer(1, 1.5 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
        story.append(Paragraph(_safe_text(f"{signature_label}: _______________________"), body_style))
        story.append(Paragraph(_safe_text(f"{date_label}: {datetime.now().strftime('%d / %m / %Y')}"), body_style))

        story.append(Spacer(1, 0.8 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
        story.append(
            Paragraph(
                "Disclaimer: This document was generated by NyayaVoice AI assistant for informational purposes only. "
                "Please review with a qualified legal professional before submission to any authority.",
                disclaimer_style,
            )
        )

        doc.build(story)
        logger.info("PDF generated: %s", filepath)
        return filepath

    except Exception as exc:
        logger.error("PDF generation failed: %s", exc)
        raise
