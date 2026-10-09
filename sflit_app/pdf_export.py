"""Create downloadable PDF copies of chat responses."""

from __future__ import annotations

import os
import tempfile
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .service import Source


def create_response_pdf(answer: str, sources: list[Source]) -> str:
    """Write an answer and its supporting sources to a local temporary PDF."""

    descriptor, path = tempfile.mkstemp(prefix="salesforce-lit-", suffix=".pdf")
    os.close(descriptor)

    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    body.leading = 15
    story = [Paragraph("Salesforce LIT Response", styles["Title"]), Spacer(1, 0.2 * inch)]
    for line in answer.splitlines() or [answer]:
        story.append(Paragraph(escape(_pdf_safe_text(line)) or "&nbsp;", body))
        story.append(Spacer(1, 0.06 * inch))

    if sources:
        story.extend([Spacer(1, 0.15 * inch), Paragraph("Sources", styles["Heading2"])])
        for source in sources:
            title = escape(_pdf_safe_text(source.title))
            details = f"<b>{title}</b>"
            if source.url:
                url = escape(_pdf_safe_text(source.url))
                details += f'<br/><link href="{url}">{url}</link>'
            story.append(Paragraph(details, body))
            story.append(Spacer(1, 0.08 * inch))

    document = SimpleDocTemplate(
        path,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="Salesforce LIT Response",
    )
    document.build(story)
    return path


def _pdf_safe_text(value: str) -> str:
    """Replace characters unsupported by ReportLab's built-in PDF fonts."""

    return value.encode("cp1252", errors="replace").decode("cp1252")
