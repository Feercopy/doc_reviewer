from app.schemas.enums import DocumentType
from app.services.document_type_detector import detect_document_type


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
