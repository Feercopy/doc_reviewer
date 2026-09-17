from decimal import Decimal

from app.schemas.enums import DocumentType
from app.services.document_type_detector import detect_document_type, progress_review_display_stage


def test_document_type_enum_matches_gate_challenger_stages():
    assert [item.value for item in DocumentType] == [
        "gate_2",
        "stream_review_1",
        "stream_review_2_plus",
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


def test_current_progress_review_uses_stream_review_2_plus_rules():
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

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation.startswith("Current defense: Progress Review")
    assert "using Stream Review 2+ rules" in result.explanation


def test_progress_review_in_title_uses_stream_review_2_plus_rules():
    text = """
    Operator of Financial Platforms - Progress Review
    Previous defense at Gate 3. The next Gate 3 commitments were discussed.
    """

    result = detect_document_type(text)

    assert result.document_type == DocumentType.STREAM_REVIEW_2_PLUS
    assert result.explanation.startswith("Document title: Progress Review")


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
