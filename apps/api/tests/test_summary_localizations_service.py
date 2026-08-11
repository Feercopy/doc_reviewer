from app.services.summary_localizations import _variant


def test_completed_summary_uses_canonical_required_element_label_without_mutating_storage():
    stored = {
        "status": "completed",
        "payload": {
            "language": "en",
            "stage_checklist": [
                {
                    "id": "stream_review_1_confirmed_problem",
                    "label": "Подтвержденная проблематика",
                    "status": "green",
                    "evidence": "Present",
                }
            ],
        },
    }

    variant = _variant(stored, language="en")

    assert variant.payload["stage_checklist"][0]["label"] == "Confirmed problem"
    assert variant.payload["stage_checklist"][0]["status"] == "green"
    assert variant.payload["stage_checklist"][0]["evidence"] == "Present"
    assert stored["payload"]["stage_checklist"][0]["label"] == "Подтвержденная проблематика"


def test_unknown_required_element_label_is_preserved():
    stored = {
        "status": "completed",
        "payload": {
            "language": "en",
            "stage_checklist": [
                {
                    "id": "custom_item",
                    "label": "Custom label",
                    "status": "red",
                    "evidence": "Missing",
                }
            ],
        },
    }

    variant = _variant(stored, language="en")

    assert variant.payload["stage_checklist"][0]["label"] == "Custom label"
