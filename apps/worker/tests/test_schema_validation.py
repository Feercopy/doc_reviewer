import json

from results import schema_validation


def test_parse_and_validate_json_output_accepts_fenced_json(tmp_path, monkeypatch):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
                "additionalProperties": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(schema_validation, "_resolve_schema_path", lambda _: schema_path)

    payload = schema_validation.parse_and_validate_json_output(
        structured_text='\n\n```json\n{"summary": "ok"}\n```',
        schema_path="unused.schema.json",
    )

    assert payload == {"summary": "ok"}
