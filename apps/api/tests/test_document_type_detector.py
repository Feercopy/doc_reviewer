from decimal import Decimal

from app.schemas.enums import DocumentType
from app.services.document_type_detector import detect_document_type, progress_review_display_stage


def test_document_type_enum_matches_gate_challenger_stages():
    assert [item.value for item in DocumentType] == [
        "gate_2",
        "stream_review_1",
        "stream_review_2_plus",
        "progress_review",
        "gate_3",
        "unknown",
    ]


def test_detects_gate_2_from_realistic_defense_text():
    text = """
    Gate 2 investment defense

    The team has shipped an MVP for the target segment and included the
    current traction, scope, product metrics, key risks, and business case.
    The document asks for approval to continue from MVP validation into the
    next delivery stage.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_2
    assert result.confidence >= 0.45
    assert "Gate 2" in result.explanation
    assert "Document title" in result.explanation


def test_current_gate_in_executive_summary_wins_over_previous_gate_mentions():
    text = """
    [Page 1]
    Cars transaction bet Gate 3 25/05/26
    Previous and current review executive summary
    Review Executive summary
    Last event - Gate & IC
    Previously defended at Gate 2. The MVP, scope, metrics, risks, and business case were reviewed.
    [Page 2]
    Current
    Gate 3
    The team reports results since Gate 2 and plans the next review.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_3
    assert result.confidence == Decimal("0.95")
    assert result.explanation.startswith("Current defense:")


def test_current_defense_overrides_conflicting_document_title():
    text = """
    Initiative Gate 2 draft
    Executive Summary
    Previous Defense: Gate 2
    Current Defense: Gate 3
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_3
    assert "document title says Gate 2" in result.explanation


def test_current_defense_in_markdown_table_has_priority():
    text = """
    Initiative overview
    Executive Summary
    | Review | Description |
    | --- | --- |
    | Previous Gate | Gate 2 |
    | Current Defense | Stream Review 2+ |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation.startswith("Current defense:")


def test_title_stage_wins_over_historical_review_mentions():
    text = """
    [Page 1]
    GenAI initiative - Stream Review 2+
    Previous review: Stream Review 1
    The prior roadmap, planned traction, resources, and IC readiness were discussed.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation.startswith("Document title:")


def test_current_metric_is_not_treated_as_current_defense():
    text = """
    Initiative Gate 3
    Current revenue is below the Gate 2 business case.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_3
    assert result.explanation.startswith("Document title:")


def test_unrelated_current_row_outside_executive_summary_does_not_override_title():
    text = """
    Initiative Gate 3
    Current
    Gate 2
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_3
    assert result.explanation.startswith("Document title:")


def test_current_progress_review_has_its_own_document_type():
    text = """
    [Page 1]
    Auction InvCom May'26
    Previous and current review executive summary
    [Page 2]
    Review Executive summary
    Current
    progres
    s review
    Date: May'26
    FAQ 8. When will you come for the next Gate 3 or Progress review?
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.PROGRESS_REVIEW
    assert result.explanation.startswith("Current defense: Progress Review")
    assert "using Stream Review 2+ rules" not in result.explanation


def test_current_progress_review_in_pdf_table_cell_overrides_gate_3_history():
    text = """
    [Page 1]
    Auction InvCom May'26
    Previous and current review executive summary
    [Page 2]
    | Review | Executive summary |
    | --- | --- |
    | Current<br>progres<br>s review<br>Date:<br>May'26 | Last review commitment October 2025<br>Plan versus fact for PMF and CSAT |
    FAQ: The previous milestone was Gate 3 and the next commitment is Gate 4.
    """

    result = detect_document_type(text, title="Auction")

    assert result.document_type == DocumentType.PROGRESS_REVIEW
    assert result.confidence == Decimal("0.95")
    assert result.explanation == "Current defense: Progress Review"


def test_current_stage_is_read_from_its_table_cell_not_historical_stage():
    text = """
    Executive Summary
    | Review | Stage |
    | --- | --- |
    | Previous Defense | Gate 3 |
    | Current Defense | Progress Review |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.PROGRESS_REVIEW
    assert result.explanation == "Current defense: Progress Review"


def test_review_history_with_cyrillic_current_and_stream_title_is_later_stream_review():
    text = """[Page 1]
    Initiative summary
    | Review | Executive summary |
    | --- | --- |
    | Previous review<br>Nov 2025 | Results since last review |
    | Сurrent review<br>May 2026 | Plan and fact across the стримам |
    FAQ: A future Gate 3 is planned.
    """

    result = detect_document_type(text, title="Stream_review_TnS_May_2026.docx")

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation == "Previous and Current Review rows with a Stream Review signal"


def test_linked_previous_review_is_unwrapped_without_using_link_url_as_a_stage_cue():
    text = """Previous and current review executive summary
    | Review | Executive summary |
    | --- | --- |
    | [Previous review](https://example.test/notes/gate3)<br>Nov 2025 | Outcomes from the prior review |
    | Сurrent review<br>May 2026 | Progress across all стримам |
    """

    result = detect_document_type(text, title="Stream review initiative.docx")

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.confidence == Decimal("0.80")


def test_review_history_after_previous_gate_is_progress_review():
    text = """Executive Summary
    | Review | Stage |
    | --- | --- |
    | Previous Review | Gate 3, June 2025 |
    | Current Review | Product results and next milestones |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.PROGRESS_REVIEW
    assert result.confidence == Decimal("0.80")


def test_explicit_current_stage_wins_over_review_history_inference():
    text = """Executive Summary
    | Review | Stage |
    | --- | --- |
    | Previous Review | Gate 3 |
    | Current Review | Stream Review 2+ |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation == "Current defense: Stream Review 2+"


def test_review_history_with_conflicting_cues_is_unknown():
    text = """Executive Summary
    | Review | Stage |
    | --- | --- |
    | Previous Review | Gate 3 |
    | Current Review | Results across all streams |
    """

    result = detect_document_type(text, title="Stream_review_initiative.docx")

    assert result.document_type == DocumentType.UNKNOWN
    assert "conflict" in result.explanation


def test_unpaired_or_unspecified_review_history_does_not_guess_a_stage():
    unpaired = "Executive Summary\n| Review | Stage |\n| Current Review | Across the streams |"
    unspecified = "Executive Summary\n| Previous Review | May |\n| Current Review | Nov |"

    assert detect_document_type(unpaired).document_type == DocumentType.UNKNOWN
    assert detect_document_type(unspecified).document_type == DocumentType.UNKNOWN


def test_current_gate_in_long_adjacent_table_cell_keeps_explicit_stage():
    text = """
    Executive Summary
    | Review | Stage |
    | --- | --- |
    | Previous Defense | Progress Review |
    | Current Defense | Gate 3<br>This longer note explains the agenda for the current defense and the document review in detail. |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_3
    assert result.explanation == "Current defense: Gate 3"


def test_current_gate_number_in_adjacent_table_cell_is_detected():
    for number, expected in (("2", DocumentType.GATE_2), ("3", DocumentType.GATE_3)):
        text = f"Executive Summary\n| Review | Stage |\n| --- | --- |\n| Current Gate | {number} |"

        result = detect_document_type(text)

        assert result.document_type == expected
        assert result.explanation == f"Current defense: Gate {number}"


def test_neighboring_summary_cell_cannot_override_current_review_cell():
    text = """
    Executive Summary
    | Review | Executive summary |
    | --- | --- |
    | Previous Defense | Current Defense: Gate 3 was discussed in the previous review. |
    | Current<br>progres<br>s review | The team compares plan and fact. |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.PROGRESS_REVIEW


def test_current_gate_3_is_not_replaced_by_previous_progress_review():
    text = """
    Executive Summary
    | Review | Stage |
    | --- | --- |
    | Previous Defense | Progress Review |
    | Current Defense | Gate 3 |
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.GATE_3
    assert result.explanation == "Current defense: Gate 3"


def test_gate_3_keyword_fallback_is_unknown_when_progress_review_is_also_mentioned():
    text = """
    Auction initiative
    General case overview
    Gate 3 results: MLP, PMF, Gate 4, customer experience, Contact Rate and CSAT.
    FAQ: When will you come for the next Progress Review?
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.UNKNOWN
    assert result.confidence < Decimal("0.45")
    assert "current review" in result.explanation.lower()


def test_explicit_gate_3_title_wins_over_future_progress_review_mention():
    result = detect_document_type(
        "Auction - Gate 3\nFAQ: When will you come for the next Progress Review?"
    )

    assert result.document_type == DocumentType.GATE_3
    assert result.explanation == "Document title: Gate 3"


def test_progress_review_in_title_has_its_own_document_type():
    text = """
    Operator of Financial Platforms - Progress Review
    Previous defense at Gate 3. The next Gate 3 commitments were discussed.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.PROGRESS_REVIEW
    assert result.explanation.startswith("Document title: Progress Review")


def test_filename_progress_review_is_used_when_document_text_has_no_current_stage():
    result = detect_document_type(
        "Executive Summary\nPrevious Defense: Gate 3\nPlan-fact and next half-year metrics",
        title="Auction - Progress Review.pdf",
    )

    assert result.document_type == DocumentType.PROGRESS_REVIEW
    assert result.explanation.startswith("Document title: Progress Review")


def test_explicit_current_stream_review_wins_over_progress_review_filename_and_previous_stage():
    result = detect_document_type(
        "Executive Summary\nPrevious Defense: Progress Review\nCurrent Defense: Stream Review 2+",
        title="Auction - Progress Review.pdf",
    )

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation.startswith("Current defense: Stream Review 2+")


def test_progress_review_display_stage_uses_current_defense_not_historical_mentions():
    progress_text = """Initiative Stream Review 2+
Executive Summary
Previous Defense: Stream Review 2+
Current Defense: Progress Review
"""
    stream_text = """Initiative Stream Review 2+
Executive Summary
Previous Defense: Progress Review
Current Defense: Stream Review 2+
"""

    assert progress_review_display_stage(progress_text, DocumentType.STREAM_REVIEW_2_PLUS.value) == "Progress Review"
    assert progress_review_display_stage(stream_text, DocumentType.STREAM_REVIEW_2_PLUS.value) is None
    assert progress_review_display_stage(progress_text, DocumentType.GATE_2.value) is None
    assert progress_review_display_stage(None, DocumentType.STREAM_REVIEW_2_PLUS.value) is None
    assert progress_review_display_stage(None, DocumentType.PROGRESS_REVIEW.value) == "Progress Review"


def test_progress_review_display_stage_uses_case_title_only_without_a_conflicting_document_stage():
    auction_text = "[Page 1]\nAuction InvCom May'26 [Eng]\nCase properties & validation\n"
    stream_text = "Executive Summary\nCurrent Defense: Stream Review 2+\n"

    assert progress_review_display_stage(
        auction_text, DocumentType.STREAM_REVIEW_2_PLUS.value, title="Auction - Progress Review"
    ) == "Progress Review"
    assert progress_review_display_stage(
        stream_text, DocumentType.STREAM_REVIEW_2_PLUS.value, title="Auction - Progress Review"
    ) is None
    assert progress_review_display_stage(
        auction_text, DocumentType.GATE_3.value, title="Auction - Progress Review"
    ) is None


def test_stream_review_number_with_hash_in_title():
    result = detect_document_type("Initiative - Stream Review #1\nPrevious Gate 2 results")

    assert result.document_type == DocumentType.STREAM_REVIEW_1
    assert result.explanation.startswith("Document title:")


def test_detects_first_stream_review_from_stage_signals():
    text = """
    1st Stream Review package

    The document summarizes discovery results, validated product ideas,
    planned traction, resources, roadmap, IC readiness, and success criteria
    for the next SR.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_1
    assert result.confidence >= 0.45
    assert "1st Stream Review" in result.explanation


def test_detects_unqualified_stream_review_as_first_review_from_supporting_signals():
    text = """
    Stream review package

    The document summarizes planned traction, roadmap, and success criteria
    for the next SR.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_1
    assert result.confidence >= 0.45
    assert "Stream review" in result.explanation


def test_detects_later_stream_review_from_stage_signals():
    text = """
    Stream review 2+ package

    The team compares plan / fact results since the previous SR, backlog
    updates, traction model changes, resource assumptions, and next SR
    commitments.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.confidence >= 0.45
    assert "Stream review 2+" in result.explanation


def test_detects_unqualified_stream_review_as_later_review_from_supporting_signals():
    text = """
    Stream review package

    The team compares plan / fact results since the previous SR, backlog
    updates, traction model changes, resource assumptions, and next SR
    commitments.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.confidence >= 0.45
    assert "Stream review" in result.explanation


def test_gate_1_is_not_a_supported_gate_challenger_document_type():
    text = """
    Gate 1 opportunity brief

    The document describes problem, hypothesis, opportunity, and discovery
    context before a Gate 2 defense exists.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.UNKNOWN
