import os
import uuid
import logging
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

logger = logging.getLogger(__name__)

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated_docs")
os.makedirs(DOCS_DIR, exist_ok=True)


def generate_pdf(user_id: str, doc_type: str, content: str, details: dict) -> str:
    """Generate a PDF document and return the file path."""
    safe_type = doc_type.lower().replace(" ", "_").replace("/", "_")
    filename = f"{safe_type}_{user_id}_{uuid.uuid4().hex[:6]}.pdf"
    filepath = os.path.join(DOCS_DIR, filename)

    try:
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
            fontSize=9,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=2,
        )
        title_style = ParagraphStyle(
            "DocTitle",
            parent=styles["Heading1"],
            alignment=TA_CENTER,
            fontSize=18,
            textColor=colors.HexColor("#1a4a7a"),
            spaceAfter=6,
            spaceBefore=8,
        )
        subtitle_style = ParagraphStyle(
            "Subtitle",
            parent=styles["Normal"],
            alignment=TA_CENTER,
            fontSize=10,
            textColor=colors.HexColor("#6b7280"),
            spaceAfter=16,
        )
        section_style = ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontSize=11,
            textColor=colors.HexColor("#1a4a7a"),
            spaceBefore=12,
            spaceAfter=4,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontSize=10,
            leading=16,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
        )
        detail_style = ParagraphStyle(
            "Detail",
            parent=styles["Normal"],
            fontSize=10,
            leading=15,
            spaceAfter=4,
            leftIndent=10,
        )
        disclaimer_style = ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#9ca3af"),
            fontName="Helvetica-Oblique",
            spaceAfter=4,
        )

        story = []

        # ── Header ──────────────────────────────────────────────────────────
        story.append(Paragraph("NyayaVoice — Voice Legal Aid Assistant", header_style))
        story.append(Paragraph(
            f"Generated: {datetime.now().strftime('%d %B %Y, %I:%M %p')}  |  Reference: {uuid.uuid4().hex[:8].upper()}",
            header_style,
        ))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a4a7a"), spaceAfter=8))

        # ── Title ────────────────────────────────────────────────────────────
        story.append(Paragraph(doc_type.upper(), title_style))
        story.append(Paragraph("Prepared with assistance of NyayaVoice AI Legal Aid System", subtitle_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=12))

        # ── Case Details ─────────────────────────────────────────────────────
        if details:
            story.append(Paragraph("CASE DETAILS", section_style))
            for k, v in details.items():
                if v and k not in ("complainant_id",):
                    label = k.replace("_", " ").title()
                    story.append(Paragraph(f"<b>{label}:</b>  {v}", detail_style))
            story.append(Spacer(1, 0.4 * cm))

        # ── Main Content ─────────────────────────────────────────────────────
        story.append(Paragraph("COMPLAINT / STATEMENT", section_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))

        for line in content.split("\n"):
            stripped = line.strip()
            if not stripped:
                story.append(Spacer(1, 0.2 * cm))
            elif stripped.startswith("#"):
                story.append(Paragraph(f"<b>{stripped.lstrip('#').strip()}</b>", section_style))
            else:
                story.append(Paragraph(stripped, body_style))

        # ── Signature Block ──────────────────────────────────────────────────
        story.append(Spacer(1, 1.5 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=8))
        story.append(Paragraph("<b>Complainant Signature:</b> _______________________", body_style))
        story.append(Paragraph(
            f"<b>Date:</b> {datetime.now().strftime('%d / %m / %Y')}",
            body_style,
        ))

        # ── Disclaimer ───────────────────────────────────────────────────────
        story.append(Spacer(1, 0.8 * cm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=6))
        story.append(Paragraph(
            "Disclaimer: This document was generated by NyayaVoice AI assistant for informational purposes only. "
            "Please review with a qualified legal professional before submission to any authority.",
            disclaimer_style,
        ))

        doc.build(story)
        logger.info(f"PDF generated: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise
