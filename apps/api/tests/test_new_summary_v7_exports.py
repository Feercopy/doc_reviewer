from io import BytesIO

from docx import Document
from pypdf import PdfReader

from app.services.new_summary_exports import NewSummaryExportProvenance, _build_docx, _build_pdf, _display_title


def test_existing_summary_export_title_drops_source_link():
    assert _display_title({"title": "From People to People (3sigma link) - AI Summary"}) == (
        "From People to People - AI Summary"
    )


def test_summary_export_title_drops_stage_and_language_annotations():
    assert _display_title({"title": "Cars TRX — Progress review and IC update request (ENG) - AI Summary"}) == (
        "Cars TRX - AI Summary"
    )


def test_v7_exports_one_table_with_four_rows_and_mismatch_note():
    table = {"periods": ["2026", "Total"], "rows": [
        {"label": "DTB Uplift (Cumul)", "values": ["2%", "—"]},
        {"label": "Revenue from DTB", "values": ["10", "10"]},
        {"label": "Revenue non-DTB", "values": ["20", "20"]},
        {"label": "Total Revenue", "values": ["35", "35"], "mismatch_periods": ["2026"]},
    ]}
    report = {language: {
        "schema_version": "new-summary-v7", "language": language,
        "title": "AI Summary Example", "stage": "Gate 2", "context": "Context.",
        "traction_summary": table, "required_elements": [],
    } for language in ("ru", "en")}
    provenance = NewSummaryExportProvenance("a", "d", "skill", "1", "test", "mock", None)

    document = Document(BytesIO(_build_docx(report, provenance)))
    for table in document.tables:
        if table.cell(0, 0).text.startswith("Output") and "Не равно" in table.cell(4, 1).text:
            assert len(table.rows) == 5
            assert table.cell(4, 0).text == "Total Revenue"
            assert "Не равно Rev. from DTB + Rev. non-DTB" in table.cell(4, 1).text
            break
    else:
        raise AssertionError("traction table missing")

    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(_build_pdf(report, provenance))).pages)
    assert "DTB Uplift (Cumul)" in pdf_text
    assert "Revenue non-DTB" in pdf_text
    assert "Не равно Rev. from DTB + Rev. non-DTB" in pdf_text


def test_v8_exports_title_and_em_dash_without_losing_revenue_warning():
    table = {"periods": ["2026", "Total"], "rows": [
        {"label": "DTB Uplift (Cumul)", "values": ["-", "—"]},
        {"label": "Revenue from DTB", "values": ["10", "невозможно извлечь данные"]},
        {"label": "Revenue non-DTB", "values": ["–", "no data in the document"]},
        {"label": "Total Revenue", "values": ["35", "35"], "mismatch_periods": ["2026"]},
    ]}
    report = {language: {
        "schema_version": "new-summary-v8", "language": language,
        "title": "Example - AI Summary", "stage": "Gate 2", "context": "Context.",
        "traction_summary": table, "required_elements": [],
    } for language in ("ru", "en")}
    provenance = NewSummaryExportProvenance("a", "d", "skill", "1", "test", "mock", None)

    document = Document(BytesIO(_build_docx(report, provenance)))
    assert document.paragraphs[0].text == "Example - AI Summary"
    traction = next(table for table in document.tables if table.cell(0, 0).text.startswith("Output"))
    assert traction.cell(1, 1).text == "—"
    assert traction.cell(2, 2).text == "—"
    assert "Does not equal Rev. from DTB + Rev. non-DTB" in traction.cell(4, 1).text

    pdf_text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(_build_pdf(report, provenance))).pages)
    assert "Example - AI Summary" in pdf_text
    assert "невозможно извлечь данные" not in pdf_text
    assert "Не равно Rev. from DTB + Rev. non-DTB" in pdf_text


def test_v8_exports_keep_contextual_problem_fact_in_word_and_pdf():
    fact = "Earlier review projected IRR 126%. FAQ 5 now reports 77%."
    table = {"periods": ["Total"], "rows": [
        {"label": "DTB Uplift (Cumul)", "values": ["—"]},
        {"label": "Revenue from DTB", "values": ["—"]},
        {"label": "Revenue non-DTB", "values": ["—"]},
        {"label": "Total Revenue", "values": ["—"]},
    ]}
    report = {language: {
        "schema_version": "new-summary-v8", "language": language,
        "title": "Example - AI Summary", "stage": "Progress Review", "context": "Context.",
        "traction_summary": table, "required_elements": [],
        "critical_problems": [{"issue": "The return estimate fell.", "fact": fact}],
    } for language in ("ru", "en")}
    provenance = NewSummaryExportProvenance("a", "d", "skill", "1", "test", "mock", None)

    document = Document(BytesIO(_build_docx(report, provenance)))
    assert any(fact in paragraph.text for paragraph in document.paragraphs)
    problem = next(paragraph for paragraph in document.paragraphs if paragraph.text.startswith("The return estimate fell."))
    assert problem.runs[0].bold is True
    assert problem.runs[1].bold is not True
    assert all(str(run.font.color.rgb) == "111827" for run in problem.runs)

    pdf_bytes = _build_pdf(report, provenance)
    pdf_text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf_bytes)).pages)
    assert fact in pdf_text.replace("\n", " ")
    page = PdfReader(BytesIO(pdf_bytes)).pages[0]
    operations = page.get_contents().operations
    fonts = page["/Resources"]["/Font"]
    for marker, should_be_bold in (
        ("The return estimate fell.", True),
        ("Earlier review projected IRR 126%.", False),
    ):
        position = next(index for index, (args, operator) in enumerate(operations)
                        if operator == b"Tj" and marker in str(args[0]))
        color = next(args for args, operator in reversed(operations[:position]) if operator == b"rg")
        font = next(args[0] for args, operator in reversed(operations[:position]) if operator == b"Tf")
        assert all(abs(float(actual) - expected) < 0.01
                   for actual, expected in zip(color, (17 / 255, 24 / 255, 39 / 255)))
        assert ("Bold" in str(fonts[font].get_object()["/BaseFont"])) is should_be_bold
