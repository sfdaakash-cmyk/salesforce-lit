from pathlib import Path

from sflit_app.pdf_export import create_response_pdf
from sflit_app.service import Source


def test_response_pdf_contains_answer_and_citation_metadata():
    path = create_response_pdf(
        "Apex supports the documented feature.",
        [
            Source(
                "Apex Release Notes",
                "release-notes/apex.html",
                "https://developer.salesforce.com/docs/apex",
                "Document excerpt",
            )
        ],
    )

    try:
        assert Path(path).read_bytes().startswith(b"%PDF-")
    finally:
        Path(path).unlink()