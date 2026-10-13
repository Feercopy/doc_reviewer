from __future__ import annotations

from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

from docx import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models.analysis import Analysis
from app.models.document import Document
from app.services.new_summary_titles import display_new_summary_title
from app.services.new_summary_quality import with_bilingual_document_quality
from app.services.new_summary_source_tables import verified_table_blocks
from app.services.new_summary_traction import display_traction_cell, needs_verified_revenue_total, traction_row_label, with_traction_totals
from app.services.new_summaries import NEW_SUMMARY_NUMBERED_SCHEMAS, with_summary_display_stage


PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXPORT_FORMATS = {"pdf", "docx"}

_ACCENT = "#0B6F54"
_SUCCESS = "#0FA36B"
_WARNING = "#C77800"
_DANGER = "#D92D20"
_MUTED = "#5D6675"
_LINE = "#DDE3EA"
_SURFACE = "#F6F8FA"
_TEXT = "#111827"
_VERDICT_GAP = "\u00a0" * 3


class NewSummaryExportUnavailableError(Exception):
    pass


class UnsupportedNewSummaryExportFormatError(Exception):
    pass


@dataclass(frozen=True)
class NewSummaryExport:
    content: bytes
    filename: str
    media_type: str

    @property
    def content_disposition(self) -> str:
        quoted = quote(self.filename)
        return f"attachment; filename*=UTF-8''{quoted}"


@dataclass(frozen=True)
class NewSummaryExportProvenance:
    analysis_id: str
    document_id: str
    skill_name: str
    skill_version: str
    provider: str
    model: str
    source_revision: str | None


def build_new_summary_export(
    *, analysis: Analysis, file_format: str, display_stage: str | None = None,
    document: Document | None = None,
) -> NewSummaryExport:
    normalized_format = file_format.lower()
    if normalized_format not in EXPORT_FORMATS:
        raise UnsupportedNewSummaryExportFormatError(file_format)

    report = _read_completed_report(analysis, document=document)
    if display_stage is not None:
        report = {
            **report,
            "ru": with_summary_display_stage(report["ru"], display_stage),
            "en": with_summary_display_stage(report["en"], display_stage),
        }
    provenance = _provenance(analysis=analysis, source_revision=report["source_revision"])
    title = _display_title(report["ru"])
    filename = f"{_safe_filename(title)}.{normalized_format}"
    if normalized_format == "docx":
        return NewSummaryExport(
            content=_build_docx(report, provenance),
            filename=filename,
            media_type=DOCX_MEDIA_TYPE,
        )
    return NewSummaryExport(
        content=_build_pdf(report, provenance),
        filename=filename,
        media_type=PDF_MEDIA_TYPE,
    )


def _read_completed_report(analysis: Analysis, *, document: Document | None = None) -> dict[str, Any]:
    output = analysis.structured_output if isinstance(analysis.structured_output, dict) else {}
    result = output.get("result") if isinstance(output.get("result"), dict) else {}
    state = result.get("new_summary") if isinstance(result.get("new_summary"), dict) else {}
    versions: dict[str, Any] = {"source_revision": state.get("source_revision") if isinstance(state.get("source_revision"), str) else None}
    for language in ("ru", "en"):
        variant = state.get(language) if isinstance(state.get(language), dict) else {}
        payload = variant.get("payload") if isinstance(variant.get("payload"), dict) else None
        if variant.get("status") != "completed" or payload is None:
            raise NewSummaryExportUnavailableError("New Summary is not completed")
        versions[language] = payload
    if all(versions[language].get("schema_version") not in NEW_SUMMARY_NUMBERED_SCHEMAS for language in ("ru", "en")):
        versions["ru"], versions["en"] = with_bilingual_document_quality(versions["ru"], versions["en"])
    blocks = verified_table_blocks(document) if document is not None and any(
        needs_verified_revenue_total(versions[language]) for language in ("ru", "en")
    ) else []
    versions["ru"] = with_traction_totals(versions["ru"], source_blocks=blocks)
    versions["en"] = with_traction_totals(versions["en"], source_blocks=blocks)
    return versions


def _provenance(*, analysis: Analysis, source_revision: str | None) -> NewSummaryExportProvenance:
    return NewSummaryExportProvenance(
        analysis_id=str(analysis.id),
        document_id=str(analysis.document_id),
        skill_name=str(analysis.skill_id),
        skill_version=str(analysis.skill_version),
        provider=str(analysis.provider),
        model=str(analysis.model),
        source_revision=source_revision,
    )


def _build_docx(report: dict[str, Any], provenance: NewSummaryExportProvenance) -> bytes:
    document = DocxDocument()
    document.core_properties.title = _display_title(report["ru"])
    document.core_properties.subject = "Gate Challenger AI Summary export"
    document.core_properties.comments = _short_provenance_text(provenance)
    section = document.sections[0]
    section.top_margin = Inches(0.55)
    section.bottom_margin = Inches(0.55)
    section.left_margin = Inches(0.62)
    section.right_margin = Inches(0.62)

    styles = document.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(10)

    for index, language in enumerate(("en", "ru")):
        if index:
            document.add_page_break()
        _append_docx_version(document, report[language], language)
    _append_docx_provenance(document, provenance)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _append_docx_version(document: DocxDocument, content: dict[str, Any], language: str) -> None:
    labels = _labels(language)
    title = _display_title(content)

    title_paragraph = document.add_paragraph()
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    title_run = title_paragraph.add_run(title)
    title_run.bold = True
    title_run.font.size = Pt(20)
    title_run.font.color.rgb = RGBColor(17, 24, 39)

    stage = document.add_paragraph()
    stage_run = stage.add_run(f"{labels['stage']}: ")
    stage_run.bold = True
    stage.add_run(_clean_text(content.get("stage") or "Unknown"))
    quality = content.get("document_quality_percent") if content.get("schema_version") not in NEW_SUMMARY_NUMBERED_SCHEMAS else None
    if isinstance(quality, int) and not isinstance(quality, bool):
        document.add_paragraph(f"{labels['quality']} - {quality}%")

    _append_docx_traction(document, content, labels)
    _append_docx_text_section(document, labels["context"], [_clean_text(content.get("context"))])
    _append_docx_required(document, content, labels)
    _append_docx_problems(document, labels["critical"], _problem_items(content.get("critical_problems")))
    if content.get("schema_version") not in NEW_SUMMARY_NUMBERED_SCHEMAS:
        _append_docx_list_section(document, labels["other"], _string_list(content.get("other")), RGBColor(93, 102, 117))
    _append_docx_details(document, content, labels)


def _append_docx_heading(document: DocxDocument, title: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.space_before = Pt(12)
    paragraph.space_after = Pt(5)
    run = paragraph.add_run(title)
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = RGBColor(17, 24, 39)


def _append_docx_text_section(document: DocxDocument, title: str, items: list[str]) -> None:
    values = [item for item in items if item]
    if not values:
        return
    _append_docx_heading(document, title)
    for item in values:
        paragraph = document.add_paragraph(item)
        paragraph.paragraph_format.space_after = Pt(3)
        paragraph.paragraph_format.line_spacing = 1.15


def _append_docx_list_section(document: DocxDocument, title: str, items: list[str], color: RGBColor) -> None:
    if not items:
        return
    _append_docx_heading(document, title)
    for item in items:
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.space_after = Pt(3)
        run = paragraph.add_run(item)
        run.font.color.rgb = color


def _append_docx_problems(document: DocxDocument, title: str, items: list[str | tuple[str, str]]) -> None:
    if not items:
        return
    _append_docx_heading(document, title)
    for item in items:
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.paragraph_format.space_after = Pt(3)
        if isinstance(item, str):
            run = paragraph.add_run(item)
            run.font.color.rgb = RGBColor(17, 24, 39)
            continue
        issue, fact = item
        issue_run = paragraph.add_run(issue)
        issue_run.bold = True
        issue_run.font.color.rgb = RGBColor(17, 24, 39)
        fact_run = paragraph.add_run(f" {fact}")
        fact_run.font.color.rgb = RGBColor(17, 24, 39)


def _append_docx_traction(document: DocxDocument, content: dict[str, Any], labels: dict[str, str]) -> None:
    tables = _traction_tables(content.get("traction_summary"))
    if not tables:
        return
    _append_docx_heading(document, labels["traction"])
    for traction in tables:
        periods = [str(item) for item in traction["periods"]]
        rows = traction["rows"]
        table = document.add_table(rows=1 + len(rows), cols=1 + len(periods))
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        table.style = "Table Grid"
        header = table.rows[0].cells
        header[0].text = _traction_output_header(content, labels)
        for index, period in enumerate(periods, start=1):
            header[index].text = period
        for row_index, row in enumerate(rows, start=1):
            cells = table.rows[row_index].cells
            cells[0].text = traction_row_label(traction, row)
            values = row.get("values") if isinstance(row.get("values"), list) else []
            for cell_index, _period in enumerate(periods, start=1):
                cells[cell_index].text = display_traction_cell(values[cell_index - 1] if cell_index - 1 < len(values) else "", content.get("schema_version"))
                if _period in row.get("mismatch_periods", []):
                    note = "Не равно Rev. from DTB + Rev. non-DTB" if content.get("language") == "ru" else "Does not equal Rev. from DTB + Rev. non-DTB"
                    cells[cell_index].add_paragraph(note)
                    for paragraph in cells[cell_index].paragraphs:
                        for run in paragraph.runs:
                            run.font.color.rgb = RGBColor(185, 28, 28)
        _set_docx_traction_table_widths(table, document)
        _style_docx_table(table)


def _set_docx_traction_table_widths(table, document: DocxDocument) -> None:
    section = document.sections[0]
    page_width = section.page_width - section.left_margin - section.right_margin
    widths = _pdf_table_widths(len(table.columns), page_width)
    table.autofit = False
    for column, width in zip(table.columns, widths, strict=True):
        column.width = int(width)
        for cell in column.cells:
            cell.width = int(width)


def _style_docx_table(table) -> None:
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(8)
                    if row_index == 0:
                        run.bold = True


def _append_docx_required(document: DocxDocument, content: dict[str, Any], labels: dict[str, str]) -> None:
    items = content.get("required_elements")
    if not isinstance(items, list) or not items:
        return
    _append_docx_heading(document, labels["required"])
    numbered = content.get("schema_version") in NEW_SUMMARY_NUMBERED_SCHEMAS
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.left_indent = Inches(0.22)
        paragraph.paragraph_format.space_after = Pt(2)
        v6 = content.get("schema_version") in {"new-summary-v6", "new-summary-v7", "new-summary-v8"}
        current_format = v6 or content.get("schema_version") == "new-summary-v5"
        counted_metrics = v6 and item.get("id") in {"gate2_metric_linkage", "stream_review_1_input_output_metric_link"}
        hypothesis_heading = (_metric_binding_heading(item, labels) if counted_metrics else None) or _gate2_hypothesis_heading(item, labels, new_format=numbered, current_format=current_format)
        if current_format and hypothesis_heading:
            heading_label, separator, counts = hypothesis_heading.partition(":")
            paragraph.add_run((f"{index}. " if numbered else "") + heading_label + separator).bold = True
            paragraph.add_run(counts).bold = False
        else:
            title = paragraph.add_run((f"{index}. " if numbered else "") + (hypothesis_heading or _clean_text(item.get("label"))))
            title.bold = not (hypothesis_heading and item.get("id") == "gate2_hypothesis_results" and content.get("schema_version") == "new-summary-v4")
        if hypothesis_heading is None and not counted_metrics:
            status = _localized_status(item, labels)
            status_run = paragraph.add_run(f"{_VERDICT_GAP}{status}")
            status_run.bold = True
            status_run.font.color.rgb = {
                "present": RGBColor(15, 163, 107),
                "partial": RGBColor(199, 120, 0),
                "missing": RGBColor(217, 45, 32),
                "fraction": RGBColor(17, 24, 39),
            }[_required_status_kind(item)]
        if item.get("evidence"):
            evidence = document.add_paragraph(_clean_text(item.get("evidence")))
            evidence.paragraph_format.left_indent = Inches(0.22)
            evidence.paragraph_format.space_after = Pt(5)
            for run in evidence.runs:
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(93, 102, 117)
        detail = item.get("detail")
        if isinstance(detail, dict):
            _append_docx_detail(document, detail, labels, inline_item_id=item.get("id"), current_format=current_format, v6=v6)


def _append_docx_details(document: DocxDocument, content: dict[str, Any], labels: dict[str, str]) -> None:
    entries = _ordered_details(content)
    if not entries:
        return
    _append_docx_heading(document, labels["appendices"])
    for index, (detail_id, detail) in enumerate(entries, start=1):
        _append_docx_heading(document, _appendix_title(content, detail_id, index))
        _append_docx_detail(document, detail, labels)


def _append_docx_detail(
    document: DocxDocument,
    detail: dict[str, Any],
    labels: dict[str, str],
    *,
    inline_item_id: str | None = None,
    current_format: bool = False,
    v6: bool = False,
) -> None:
    detail_type = detail.get("type")
    if detail_type == "hypotheses_with_thresholds":
        for item in _dict_list(detail.get("items")):
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.add_run(_clean_text(item.get("hypothesis"))).bold = True
            paragraph.add_run(f" - {_clean_text(item.get('confirmation_condition'))}")
        return
    if detail_type == "solution_validation":
        for item in _confirmed_first(_dict_list(detail.get("items")), "verdict"):
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.add_run(_clean_text(item.get("text")))
            status_run = paragraph.add_run(f"{_VERDICT_GAP}{_verdict_status(item.get('verdict'), labels)}")
            status_run.bold = True
            status_run.font.color.rgb = RGBColor(15, 163, 107) if item.get("verdict") == "confirmed" else RGBColor(199, 120, 0)
            rationale = _validation_rationale(item, labels)
            if rationale:
                rationale_run = paragraph.add_run()
                rationale_run.add_break()
                rationale_run.add_text(rationale)
                rationale_run.font.color.rgb = RGBColor(93, 102, 117)
        return
    if detail_type == "metric_binding":
        for title, key in ((labels["input_metrics"], "input_metrics"), (labels["output_metrics"], "output_metrics")):
            metrics = _confirmed_first(_dict_list(detail.get(key)), "binding")
            if not metrics:
                continue
            paragraph = document.add_paragraph()
            run = paragraph.add_run(title)
            run.bold = True
            for item in metrics:
                bullet = document.add_paragraph(style="List Bullet")
                bullet.add_run(_clean_text(item.get("metric"))).bold = True
                if current_format:
                    bullet.add_run(f" — {_clean_text(item.get('evidence'))}").bold = False
                status_run = bullet.add_run(f"{_VERDICT_GAP}{_detail_status(item.get('binding'), labels)}")
                status_run.bold = True
                status_run.font.color.rgb = RGBColor(15, 163, 107) if item.get("binding") == "confirmed" else RGBColor(199, 120, 0)
                if item.get("evidence") and not current_format:
                    evidence = bullet.add_run(f"\n{_clean_text(item.get('evidence'))}")
                    evidence.font.size = Pt(8)
                    evidence.font.color.rgb = RGBColor(93, 102, 117)
        return
    if detail_type == "source_links":
        links = _safe_source_links(detail)
        for item in links:
            paragraph = document.add_paragraph(style="List Bullet")
            hyperlink = OxmlElement("w:hyperlink")
            hyperlink.set(qn("r:id"), paragraph.part.relate_to(item["url"], RT.HYPERLINK, is_external=True))
            run = OxmlElement("w:r")
            properties = OxmlElement("w:rPr")
            color = OxmlElement("w:color")
            color.set(qn("w:val"), "0563C1")
            properties.append(color)
            run.append(properties)
            text = OxmlElement("w:t")
            text.text = item["label"]
            run.append(text)
            hyperlink.append(run)
            paragraph._p.append(hyperlink)
        if not links:
            document.add_paragraph(labels["links_absent" if detail.get("availability") == "absent" else "links_unavailable"])
        return
    if detail_type in {"next_review_plan", "plan_fact"}:
        plan_fact = detail_type == "plan_fact"
        outputs_title = labels["outputs_until_gate3"] if inline_item_id == "gate2_commitments" else labels["outputs_until_next"]
        outputs, metrics = _plan_detail_rows(detail, labels)
        if plan_fact and v6 and outputs:
            _append_docx_heading(document, labels["launches"])
            for item in _dict_list(detail.get("launches")):
                paragraph = document.add_paragraph(style="List Bullet")
                paragraph.add_run(_clean_text(item.get("output")))
                status = paragraph.add_run(_VERDICT_GAP + labels.get("launch_" + str(item.get("status")), labels["launch_unknown"]))
                status.bold = True
                status.font.color.rgb = RGBColor.from_string(_launch_color(item.get("status"))[1:])
                if item.get("comment"):
                    paragraph.add_run(f". {_clean_text(item['comment'])}")
        else:
            _append_docx_list_section(document, labels["launches"] if plan_fact else outputs_title, outputs, RGBColor(17, 24, 39))
        if metrics:
            if inline_item_id:
                _append_docx_heading(document, labels["metrics_fact"] if plan_fact else labels["metrics_until_gate3"] if inline_item_id == "gate2_commitments" else labels["metrics_until_next"])
            table = document.add_table(rows=1 + len(metrics), cols=3)
            table.style = "Table Grid"
            table.rows[0].cells[0].text = labels["metric"]
            table.rows[0].cells[1].text = labels["planned"] if plan_fact else labels["current"]
            table.rows[0].cells[2].text = labels["fact"] if plan_fact else labels["next_review"]
            for row_index, row in enumerate(metrics, start=1):
                table.rows[row_index].cells[0].text = _clean_text(row.get("metric"))
                table.rows[row_index].cells[1].text = _clean_text(row.get("current"))
                table.rows[row_index].cells[2].text = _clean_text(row.get("next_review"))
            _style_docx_table(table)
        return
    if v6 and detail_type == "stop_criteria" and detail.get("criteria"):
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(5)
        paragraph.paragraph_format.keep_with_next = True
        paragraph.add_run(labels["additional_stops"]).bold = True
    for item in _string_list(detail.get("criteria")):
        document.add_paragraph(item, style="List Number" if detail_type == "criteria_list" else "List Bullet")


def _append_docx_provenance(document: DocxDocument, provenance: NewSummaryExportProvenance) -> None:
    _append_docx_heading(document, "Provenance")
    paragraph = document.add_paragraph(_provenance_text(provenance))
    for run in paragraph.runs:
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(93, 102, 117)


def _build_pdf(report: dict[str, Any], provenance: NewSummaryExportProvenance) -> bytes:
    _register_pdf_fonts()
    buffer = BytesIO()
    margin = 1.35 * cm
    frame_width = A4[0] - (2 * margin)
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title=_display_title(report["ru"]),
        author="Gate Challenger",
        subject="Gate Challenger AI Summary export",
    )
    styles = _pdf_styles()
    story: list[Any] = []
    for index, language in enumerate(("en", "ru")):
        if index:
            story.append(PageBreak())
        _append_pdf_version(story, report[language], language, styles, frame_width)
    _append_pdf_provenance(story, provenance, styles)
    document.build(story)
    return buffer.getvalue()


def _append_pdf_version(
    story: list[Any],
    content: dict[str, Any],
    language: str,
    styles: dict[str, ParagraphStyle],
    frame_width: float,
) -> None:
    labels = _labels(language)
    story.append(Paragraph(_xml(_display_title(content)), styles["title"]))
    story.append(Paragraph(f"<b>{_xml(labels['stage'])}:</b> {_xml(content.get('stage') or 'Unknown')}", styles["body"]))
    quality = content.get("document_quality_percent") if content.get("schema_version") not in NEW_SUMMARY_NUMBERED_SCHEMAS else None
    if isinstance(quality, int) and not isinstance(quality, bool):
        story.append(Paragraph(f"{_xml(labels['quality'])} - {quality}%", styles["body"]))
    story.append(Spacer(1, 8))
    _append_pdf_traction(story, content, labels, styles, frame_width)
    _append_pdf_text_section(story, labels["context"], [_clean_text(content.get("context"))], styles)
    _append_pdf_required(story, content, labels, styles, frame_width)
    _append_pdf_problems(story, labels["critical"], _problem_items(content.get("critical_problems")), styles)
    if content.get("schema_version") not in NEW_SUMMARY_NUMBERED_SCHEMAS:
        _append_pdf_list_section(story, labels["other"], _string_list(content.get("other")), _MUTED, styles)
    _append_pdf_details(story, content, labels, styles, frame_width)


def _append_pdf_heading(story: list[Any], title: str, styles: dict[str, ParagraphStyle]) -> None:
    story.append(Spacer(1, 8))
    story.append(Paragraph(_xml(title), styles["heading"]))


def _append_pdf_text_section(story: list[Any], title: str, items: list[str], styles: dict[str, ParagraphStyle]) -> None:
    values = [item for item in items if item]
    if not values:
        return
    _append_pdf_heading(story, title, styles)
    for item in values:
        story.append(Paragraph(_xml(item), styles["body"]))


def _append_pdf_list_section(
    story: list[Any],
    title: str,
    items: list[str],
    color: str,
    styles: dict[str, ParagraphStyle],
) -> None:
    if not items:
        return
    if title:
        _append_pdf_heading(story, title, styles)
    story.append(
        ListFlowable(
            [ListItem(Paragraph(f'<font color="{color}">{_xml(item)}</font>', styles["body"])) for item in items],
            bulletType="bullet",
            leftIndent=15,
        )
    )


def _append_pdf_problems(
    story: list[Any], title: str, items: list[str | tuple[str, str]], styles: dict[str, ParagraphStyle]
) -> None:
    if not items:
        return
    _append_pdf_heading(story, title, styles)
    paragraphs = []
    for item in items:
        if isinstance(item, str):
            markup = _xml(item)
        else:
            issue, fact = item
            markup = f"<b>{_xml(issue)}</b> {_xml(fact)}"
        paragraphs.append(ListItem(Paragraph(markup, styles["body"])))
    story.append(ListFlowable(paragraphs, bulletType="bullet", leftIndent=15))


def _append_pdf_traction(
    story: list[Any],
    content: dict[str, Any],
    labels: dict[str, str],
    styles: dict[str, ParagraphStyle],
    frame_width: float,
) -> None:
    tables = _traction_tables(content.get("traction_summary"))
    if not tables:
        return
    _append_pdf_heading(story, labels["traction"], styles)
    for traction in tables:
        _append_pdf_traction_table(story, traction, styles, frame_width, _traction_output_header(content, labels), language=content.get("language", "en"), schema_version=content.get("schema_version"))


def _append_pdf_traction_table(
    story: list[Any], traction: dict[str, Any], styles: dict[str, ParagraphStyle], frame_width: float, output_header: str,
    *, language: str = "en", schema_version: str | None = None,
) -> None:
    periods = [str(item) for item in traction["periods"]]
    data = [[Paragraph(_xml(output_header), styles["table_header"])] + [Paragraph(_xml(item), styles["table_header"]) for item in periods]]
    for row in traction["rows"]:
        values = row.get("values") if isinstance(row.get("values"), list) else []
        cells = [Paragraph(_xml(traction_row_label(traction, row)), styles["table_header"])]
        for index, period in enumerate(periods):
            value = _xml(display_traction_cell(values[index] if index < len(values) else "", schema_version))
            if period in row.get("mismatch_periods", []):
                note = "Не равно Rev. from DTB + Rev. non-DTB" if language == "ru" else "Does not equal Rev. from DTB + Rev. non-DTB"
                value = f'<font color="#B91C1C">{value}<br/>{_xml(note)}</font>'
            cells.append(Paragraph(value, styles["table_body"]))
        data.append(cells)
    table = Table(data, colWidths=_pdf_table_widths(len(data[0]), frame_width), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_SURFACE)),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(_LINE)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))


def _append_pdf_required(
    story: list[Any],
    content: dict[str, Any],
    labels: dict[str, str],
    styles: dict[str, ParagraphStyle],
    frame_width: float = A4[0] - (2 * 1.35 * cm),
) -> None:
    items = content.get("required_elements")
    if not isinstance(items, list) or not items:
        return
    _append_pdf_heading(story, labels["required"], styles)
    numbered = content.get("schema_version") in NEW_SUMMARY_NUMBERED_SCHEMAS
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        color = {
            "present": _SUCCESS,
            "partial": _WARNING,
            "missing": _DANGER,
            "fraction": _TEXT,
        }[_required_status_kind(item)]
        status = _localized_status(item, labels)
        v6 = content.get("schema_version") in {"new-summary-v6", "new-summary-v7", "new-summary-v8"}
        current_format = v6 or content.get("schema_version") == "new-summary-v5"
        counted_metrics = v6 and item.get("id") in {"gate2_metric_linkage", "stream_review_1_input_output_metric_link"}
        hypothesis_heading = (_metric_binding_heading(item, labels) if counted_metrics else None) or _gate2_hypothesis_heading(item, labels, new_format=numbered, current_format=current_format)
        heading = (f"<b>{_xml(hypothesis_heading)}</b>" if hypothesis_heading else
                   f"<b>{_xml(item.get('label'))}</b>{_VERDICT_GAP}<font color=\"{color}\"><b>{_xml(status)}</b></font>")
        if hypothesis_heading and item.get("id") == "gate2_hypothesis_results" and content.get("schema_version") == "new-summary-v4":
            heading = _xml(hypothesis_heading)
        if current_format and hypothesis_heading:
            heading_label, separator, counts = hypothesis_heading.partition(":")
            heading = f"<b>{_xml(heading_label + separator)}</b> {_xml(counts)}"
        elif counted_metrics:
            heading = f"<b>{_xml(item.get('label'))}</b>"
        if numbered:
            heading = f"{index}. {heading}"
        story.append(Paragraph(heading, styles["required"]))
        if item.get("evidence"):
            story.append(Paragraph(f'<font color="{_MUTED}">{_xml(item.get("evidence"))}</font>', styles["evidence"]))
        detail = item.get("detail")
        if isinstance(detail, dict):
            _append_pdf_detail(story, detail, labels, styles, frame_width, inline_item_id=item.get("id"), current_format=current_format, v6=v6)


def _append_pdf_details(
    story: list[Any],
    content: dict[str, Any],
    labels: dict[str, str],
    styles: dict[str, ParagraphStyle],
    frame_width: float,
) -> None:
    entries = _ordered_details(content)
    if not entries:
        return
    _append_pdf_heading(story, labels["appendices"], styles)
    for index, (detail_id, detail) in enumerate(entries, start=1):
        story.append(Paragraph(_xml(_appendix_title(content, detail_id, index)), styles["subheading"]))
        _append_pdf_detail(story, detail, labels, styles, frame_width)


def _append_pdf_detail(
    story: list[Any],
    detail: dict[str, Any],
    labels: dict[str, str],
    styles: dict[str, ParagraphStyle],
    frame_width: float,
    *,
    inline_item_id: str | None = None,
    current_format: bool = False,
    v6: bool = False,
) -> None:
    detail_type = detail.get("type")
    if detail_type == "hypotheses_with_thresholds":
        items = [
            Paragraph(f"<b>{_xml(item.get('hypothesis'))}</b> - {_xml(item.get('confirmation_condition'))}", styles["body"])
            for item in _dict_list(detail.get("items"))
        ]
        if items:
            story.append(ListFlowable([ListItem(item) for item in items], bulletType="bullet", leftIndent=15))
        return
    if detail_type == "solution_validation":
        items = []
        for item in _confirmed_first(_dict_list(detail.get("items")), "verdict"):
            color = _SUCCESS if item.get("verdict") == "confirmed" else _WARNING
            entry = f"{_xml(item.get('text'))}{_VERDICT_GAP}<font color=\"{color}\"><b>{_xml(_verdict_status(item.get('verdict'), labels))}</b></font>"
            rationale = _validation_rationale(item, labels)
            if rationale:
                entry += f'<br/><font color="{_MUTED}">{_xml(rationale)}</font>'
            items.append(Paragraph(entry, styles["body"]))
        if items:
            story.append(ListFlowable([ListItem(item) for item in items], bulletType="bullet", leftIndent=15))
        return
    if detail_type == "metric_binding":
        for title, key in ((labels["input_metrics"], "input_metrics"), (labels["output_metrics"], "output_metrics")):
            metrics = _confirmed_first(_dict_list(detail.get(key)), "binding")
            if not metrics:
                continue
            story.append(Paragraph(_xml(title), styles["subheading"]))
            entries = []
            for item in metrics:
                color = _SUCCESS if item.get("binding") == "confirmed" else _WARNING
                metric = f"<b>{_xml(item.get('metric'))}</b>"
                status = f"{_VERDICT_GAP}<font color=\"{color}\"><b>{_xml(_detail_status(item.get('binding'), labels))}</b></font>"
                evidence = _xml(item.get("evidence"))
                entry = (f"{metric} — {evidence}{status}" if current_format else
                         f'{metric}{status}<br/><font size="8" color="{_MUTED}">{evidence}</font>')
                entries.append(
                    Paragraph(
                        entry,
                        styles["body"],
                    )
                )
            story.append(ListFlowable([ListItem(item) for item in entries], bulletType="bullet", leftIndent=15))
        return
    if detail_type == "source_links":
        links = _safe_source_links(detail)
        for item in links:
            story.append(Paragraph(f'<link href="{_xml(item["url"])}" color="#0563C1">{_xml(item["label"])}</link>', styles["body"]))
        if not links:
            story.append(Paragraph(_xml(labels["links_absent" if detail.get("availability") == "absent" else "links_unavailable"]), styles["body"]))
        return
    if detail_type in {"next_review_plan", "plan_fact"}:
        plan_fact = detail_type == "plan_fact"
        outputs_title = labels["outputs_until_gate3"] if inline_item_id == "gate2_commitments" else labels["outputs_until_next"]
        outputs, metrics = _plan_detail_rows(detail, labels)
        if plan_fact and v6 and outputs:
            story.append(Paragraph(_xml(labels["launches"]), styles["subheading"]))
            entries = []
            for item in _dict_list(detail.get("launches")):
                status = labels.get("launch_" + str(item.get("status")), labels["launch_unknown"])
                entry = f'{_xml(item.get("output"))}{_VERDICT_GAP}<font color="{_launch_color(item.get("status"))}"><b>{_xml(status)}</b></font>'
                if item.get("comment"):
                    entry += f'. {_xml(item["comment"])}'
                entries.append(ListItem(Paragraph(entry, styles["body"])))
            story.append(ListFlowable(entries, bulletType="bullet", leftIndent=15))
        else:
            _append_pdf_list_section(story, labels["launches"] if plan_fact else outputs_title, outputs, _TEXT, styles)
        if metrics:
            if inline_item_id:
                story.append(Spacer(1, 10))
                story.append(Paragraph(_xml(labels["metrics_fact"] if plan_fact else labels["metrics_until_gate3"] if inline_item_id == "gate2_commitments" else labels["metrics_until_next"]), styles["subheading"]))
            rows = [
                [
                    Paragraph(_xml(labels["metric"]), styles["table_header"]),
                    Paragraph(_xml(labels["planned"] if plan_fact else labels["current"]), styles["table_header"]),
                    Paragraph(_xml(labels["fact"] if plan_fact else labels["next_review"]), styles["table_header"]),
                ]
            ]
            rows.extend(
                [
                    Paragraph(_xml(row.get("metric")), styles["table_body"]),
                    Paragraph(_xml(row.get("current")), styles["table_body"]),
                    Paragraph(_xml(row.get("next_review")), styles["table_body"]),
                ]
                for row in metrics
            )
            table = Table(rows, colWidths=_pdf_table_widths(3, frame_width), repeatRows=1)
            table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(_LINE)), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_SURFACE)), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(table)
        return
    if detail_type == "criteria_list":
        entries = [Paragraph(_xml(item), styles["body"]) for item in _string_list(detail.get("criteria"))]
        if entries:
            story.append(ListFlowable([ListItem(item) for item in entries], bulletType="1", leftIndent=15))
        return
    if v6 and detail.get("criteria"):
        story.append(Paragraph(_xml(labels["additional_stops"]), styles["subheading"]))
    _append_pdf_list_section(story, "", _string_list(detail.get("criteria")), _TEXT, styles)


def _launch_color(status: Any) -> str:
    return {"completed": _SUCCESS, "partial": _WARNING, "not_completed": _DANGER}.get(status, _MUTED)


def _append_pdf_provenance(
    story: list[Any],
    provenance: NewSummaryExportProvenance,
    styles: dict[str, ParagraphStyle],
) -> None:
    story.append(Spacer(1, 8))
    story.append(Paragraph("Provenance", styles["heading"]))
    story.append(Paragraph(_xml(_provenance_text(provenance)), styles["evidence"]))


def _safe_source_links(detail: dict[str, Any]) -> list[dict[str, str]]:
    return [item for item in _dict_list(detail.get("links"))
            if isinstance(item.get("url"), str) and item["url"].lower().startswith(("https://", "http://"))
            and isinstance(item.get("label"), str)]


def _plan_detail_rows(detail: dict[str, Any], labels: dict[str, str]) -> tuple[list[str], list[dict[str, Any]]]:
    if detail.get("type") != "plan_fact":
        return _string_list(detail.get("outputs_until_next_review")), _dict_list(detail.get("metrics_until_next_review"))
    outputs = [
        f"{_clean_text(item.get('output'))} — {labels.get('launch_' + str(item.get('status')), labels['launch_unknown'])}"
        + (f". {_clean_text(item['comment'])}" if item.get("comment") else "")
        for item in _dict_list(detail.get("launches"))
    ]
    metrics = [{"metric": item.get("metric"), "current": item.get("planned"), "next_review": item.get("actual")}
               for item in _dict_list(detail.get("metrics"))]
    return outputs, metrics


def _labels(language: str) -> dict[str, str]:
    if language == "en":
        return {
            "appendices": "Appendices",
            "additional_stops": "Additional stop criteria",
            "binding_confirmed": "Binding is relevant",
            "binding_insufficient": "Binding seems irrelevant",
            "output_header": "Output metrics — uplifts",
            "launches": "Launches: plan vs actual",
            "metrics_fact": "Metrics: plan vs actual",
            "planned": "Plan",
            "fact": "Actual",
            "launch_completed": "Completed",
            "launch_partial": "Partially completed",
            "launch_not_completed": "Not completed",
            "launch_unknown": "No data",
            "links_absent": "No links are provided in the document",
            "links_unavailable": "Could not copy links from the document",
            "metrics_until_next": "Metrics until the next Review",
            "context": "Initiative context",
            "quality": "Document quality",
            "critical": "Identified problems",
            "current": "Current value",
            "input_metrics": "Input metrics",
            "metric": "Metric",
            "missing": "Missing",
            "partial": "Partially confirmed",
            "next_review": "Next review value",
            "other": "Other observations",
            "output_metrics": "Output metrics",
            "outputs_until_next": "Outputs until the next review",
            "outputs_until_gate3": "Outputs until Gate 3",
            "metrics_until_gate3": "Metrics until Gate 3",
            "present": "Present",
            "required": "Required document elements",
            "stage": "Initiative stage",
            "traction": "Traction Summary",
            "verdict_confirmed": "Confirmed",
            "verdict_insufficient": "Not sufficiently confirmed",
            "test": "Test",
            "expected": "expected",
            "actual": "observed",
        }
    return {
        "appendices": "Appendices",
        "binding_confirmed": "Связь подтверждена",
        "binding_insufficient": "Связь кажется неподтвержденной",
        "output_header": "Output-метрики — uplifts",
        "launches": "План-факт по запускам",
        "additional_stops": "Дополнительные найденные Stop критерии",
        "metrics_fact": "План-факт по метрикам",
        "planned": "План",
        "fact": "Факт",
        "launch_completed": "Выполнено",
        "launch_partial": "Частично выполнено",
        "launch_not_completed": "Не выполнено",
        "launch_unknown": "Нет данных",
        "links_absent": "Ссылки в документе не представлены",
        "links_unavailable": "Не удалось скопировать ссылки из документа",
        "metrics_until_next": "Metrics until the next Review",
        "context": "Краткий контекст инициативы",
        "quality": "Качество документа",
        "critical": "Выявленные проблемы",
        "current": "Текущее значение",
        "input_metrics": "Input metrics",
        "metric": "Метрика",
        "missing": "Нет",
        "partial": "Частично подтверждено",
        "next_review": "Значение к следующему ревью",
        "other": "Другие наблюдения",
        "output_metrics": "Output metrics",
        "outputs_until_next": "Outputs until the next Review",
        "outputs_until_gate3": "Outputs until Gate 3",
        "metrics_until_gate3": "Metrics until Gate 3",
        "present": "Есть",
        "required": "Обязательные элементы документа",
        "stage": "Стадия инициативы",
        "traction": "Traction Summary",
        "verdict_confirmed": "Подтверждено",
        "verdict_insufficient": "Недостаточно подтверждено",
        "test": "Проверка",
        "expected": "ожидали",
        "actual": "получили",
    }


def _traction_tables(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    candidates = value.get("tables") if isinstance(value.get("tables"), list) else [value]
    return [
        table for table in candidates
        if isinstance(table, dict)
        and isinstance(table.get("periods"), list) and table["periods"]
        and isinstance(table.get("rows"), list) and table["rows"]
    ]


def _traction_output_header(content: dict[str, Any], labels: dict[str, str]) -> str:
    if content.get("schema_version") in {"new-summary-v7", "new-summary-v8"}:
        return "Output-метрики" if content.get("language") == "ru" else "Output metrics"
    return labels["output_header"]


def _ordered_details(content: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    details = content.get("required_details")
    if not isinstance(details, dict):
        return []
    ids = [item.get("id") for item in _dict_list(content.get("required_elements")) if isinstance(item.get("id"), str)]
    ordered_ids = [*ids, *sorted(key for key in details if key not in ids)]
    return [(key, details[key]) for key in ordered_ids if isinstance(details.get(key), dict)]


def _appendix_title(content: dict[str, Any], detail_id: str, index: int) -> str:
    for item in _dict_list(content.get("required_elements")):
        if item.get("id") == detail_id and item.get("label"):
            return f"Appendix {index}. {_clean_text(item.get('label'))}"
    return f"Appendix {index}"


def _required_status_kind(item: dict[str, Any]) -> str:
    status = str(item.get("status", "")).lower()
    if status in {"есть", "present"}:
        return "present"
    if status in {"частично подтверждено", "partially confirmed"}:
        return "partial"
    numerator, separator, denominator = status.partition("/")
    if separator and numerator.isdecimal() and denominator.isdecimal():
        return "fraction"
    return "missing"


def _localized_status(item: dict[str, Any], labels: dict[str, str]) -> str:
    kind = _required_status_kind(item)
    return str(item.get("status")) if kind == "fraction" else labels[kind]


def _confirmed_first(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: item.get(key) != "confirmed")


def _gate2_hypothesis_heading(item: dict[str, Any], labels: dict[str, str], *, new_format: bool = False, current_format: bool = False) -> str | None:
    detail = item.get("detail")
    gate2 = item.get("id") == "gate2_hypothesis_results"
    if not (gate2 or (new_format and item.get("id") == "stream_review_1_solution_validation")) or not isinstance(detail, dict) or detail.get("type") != "solution_validation":
        return None
    items = _dict_list(detail.get("items"))
    if not items:
        return None
    total = len(items)
    confirmed = sum(entry.get("verdict") == "confirmed" for entry in items)
    insufficient = total - confirmed
    english = labels["required"] == "Required document elements"
    if not new_format:
        return (f"Gate hypothesis validation: {confirmed} of {total} hypotheses confirmed, {insufficient} of {total} insufficiently confirmed." if english
                else f"Результаты проверки гипотез из Gate: {confirmed} гипотез из {total} подтверждены, {insufficient} гипотез из {total} недостаточно подтверждены.")
    if english:
        heading = "Gate 1 hypothesis validation" if gate2 else ("Solution validation through quantitative research, prototypes or fake doors" if current_format else "Solution validation")
        return f"{heading}: {confirmed} of {total} {'hypotheses' if gate2 else 'checks'} confirmed, {insufficient} of {total} insufficiently confirmed."
    forms = ("гипотеза", "гипотезы", "гипотез") if gate2 else ("проверка", "проверки", "проверок")
    heading = "Результаты проверки гипотез из Gate 1" if gate2 else ("Подтверждение решения через количественники, прототипы или фейкдоры" if current_format else "Подтвержденные решения")
    return (f"{heading}: {confirmed} {_ru_count(confirmed, forms)} из {total} {'подтверждена' if confirmed == 1 else 'подтверждены'}, "
            f"{insufficient} {_ru_count(insufficient, forms)} из {total} недостаточно {'подтверждена' if insufficient == 1 else 'подтверждены'}.")


def _metric_binding_heading(item: dict[str, Any], labels: dict[str, str]) -> str | None:
    detail = item.get("detail")
    if not isinstance(detail, dict) or detail.get("type") != "metric_binding":
        return None
    metrics = _dict_list(detail.get("input_metrics")) + _dict_list(detail.get("output_metrics"))
    total = len(metrics)
    if not total:
        return None
    confirmed = sum(entry.get("binding") == "confirmed" for entry in metrics)
    insufficient = total - confirmed
    label = _clean_text(item.get("label")).rstrip(".:")
    if labels["required"] == "Required document elements":
        return f"{label}: binding of {confirmed} of {total} metrics confirmed, binding of {insufficient} of {total} insufficiently confirmed."
    noun = lambda count: "метрики" if count % 10 == 1 and count % 100 != 11 else "метрик"
    return f"{label}: связь {confirmed} {noun(confirmed)} из {total} подтверждена, связь {insufficient} {noun(insufficient)} из {total} недостаточно подтверждена."


def _ru_count(value: int, forms: tuple[str, str, str]) -> str:
    if 11 <= value % 100 <= 14:
        return forms[2]
    tail = value % 10
    return forms[0] if tail == 1 else forms[1] if 2 <= tail <= 4 else forms[2]


def _validation_rationale(item: dict[str, Any], labels: dict[str, str]) -> str:
    parts = [f"{labels[label]}: {_clean_text(item.get(key)).rstrip('.')}" for key, label in (
        ("test", "test"), ("expected_result", "expected"), ("actual_result", "actual"),
    ) if _clean_text(item.get(key))]
    return "; ".join(parts) + "." if parts else ""


def _detail_status(status: Any, labels: dict[str, str]) -> str:
    return labels["binding_confirmed"] if status == "confirmed" else labels["binding_insufficient"]


def _verdict_status(status: Any, labels: dict[str, str]) -> str:
    return labels["verdict_confirmed"] if status == "confirmed" else labels["verdict_insufficient"]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _problem_items(value: Any) -> list[str | tuple[str, str]]:
    if not isinstance(value, list):
        return []
    items: list[str | tuple[str, str]] = []
    for item in value:
        if isinstance(item, str) and _clean_text(item):
            items.append(_clean_text(item))
        elif isinstance(item, dict):
            issue, fact = _clean_text(item.get("issue")), _clean_text(item.get("fact"))
            if issue and fact:
                items.append((issue, fact))
    return items


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())


def _display_title(content: dict[str, Any]) -> str:
    title = _clean_text(content.get("title") or "AI Summary")
    return display_new_summary_title(title)


def _xml(value: Any) -> str:
    return escape(_clean_text(value))


def _safe_filename(title: str) -> str:
    value = "".join(character if character.isalnum() or character in " ._-" else "_" for character in title).strip()
    return value[:120] or "AI Summary"


def _provenance_text(provenance: NewSummaryExportProvenance) -> str:
    values = [
        f"analysis_id={provenance.analysis_id}",
        f"document_id={provenance.document_id}",
        f"skill={provenance.skill_name}@{provenance.skill_version}",
        f"provider_model={provenance.provider}/{provenance.model}",
    ]
    if provenance.source_revision:
        values.append(f"new_summary_source_revision={provenance.source_revision}")
    return "; ".join(values)


def _short_provenance_text(provenance: NewSummaryExportProvenance) -> str:
    return f"analysis_id={provenance.analysis_id}; document_id={provenance.document_id}"


def _pdf_table_widths(column_count: int, frame_width: float) -> list[float]:
    if column_count <= 1:
        return [frame_width]
    first = frame_width * 0.32
    rest = (frame_width - first) / (column_count - 1)
    return [first, *([rest] * (column_count - 1))]


def _register_pdf_fonts() -> None:
    if "GateSummaryRegular" in pdfmetrics.getRegisteredFontNames():
        return
    regular, bold = _find_font_paths()
    pdfmetrics.registerFont(TTFont("GateSummaryRegular", str(regular)))
    pdfmetrics.registerFont(TTFont("GateSummaryBold", str(bold or regular)))
    addMapping("GateSummary", 0, 0, "GateSummaryRegular")
    addMapping("GateSummary", 1, 0, "GateSummaryBold")
    addMapping("GateSummary", 0, 1, "GateSummaryRegular")
    addMapping("GateSummary", 1, 1, "GateSummaryBold")


def _find_font_paths() -> tuple[Path, Path | None]:
    regular_candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/local/share/fonts/DejaVuSans.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    ]
    bold_candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/local/share/fonts/DejaVuSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    regular = next((path for path in regular_candidates if path.is_file()), None)
    if regular is None:
        raise NewSummaryExportUnavailableError("No Unicode font is available for PDF export")
    bold = next((path for path in bold_candidates if path.is_file()), None)
    return regular, bold


def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "GateSummaryTitle",
            parent=base["Title"],
            fontName="GateSummaryBold",
            fontSize=18,
            leading=22,
            alignment=TA_LEFT,
            textColor=colors.HexColor(_TEXT),
            spaceAfter=8,
        ),
        "heading": ParagraphStyle(
            "GateSummaryHeading",
            parent=base["Heading2"],
            fontName="GateSummaryBold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor(_TEXT),
            spaceAfter=5,
        ),
        "subheading": ParagraphStyle(
            "GateSummarySubheading",
            parent=base["Heading3"],
            fontName="GateSummaryBold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor(_ACCENT),
            spaceBefore=5,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "GateSummaryBody",
            parent=base["BodyText"],
            fontName="GateSummaryRegular",
            fontSize=9.5,
            leading=13,
            textColor=colors.HexColor(_TEXT),
            spaceAfter=4,
            splitLongWords=1,
        ),
        "required": ParagraphStyle(
            "GateSummaryRequired",
            parent=base["BodyText"],
            fontName="GateSummaryRegular",
            fontSize=9.5,
            leading=13,
            leftIndent=12,
            textColor=colors.HexColor(_TEXT),
            spaceAfter=1,
            splitLongWords=1,
        ),
        "evidence": ParagraphStyle(
            "GateSummaryEvidence",
            parent=base["BodyText"],
            fontName="GateSummaryRegular",
            fontSize=8,
            leading=10,
            leftIndent=12,
            textColor=colors.HexColor(_MUTED),
            spaceAfter=5,
            splitLongWords=1,
        ),
        "table_header": ParagraphStyle(
            "GateSummaryTableHeader",
            parent=base["BodyText"],
            fontName="GateSummaryBold",
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor(_TEXT),
            splitLongWords=1,
        ),
        "table_body": ParagraphStyle(
            "GateSummaryTableBody",
            parent=base["BodyText"],
            fontName="GateSummaryRegular",
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor(_TEXT),
            splitLongWords=1,
        ),
    }
