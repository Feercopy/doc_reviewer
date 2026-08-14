from app.schemas.enums import DocumentType
from app.services.document_type_detector import detect_document_type


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
    assert "MVP" in result.explanation


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
