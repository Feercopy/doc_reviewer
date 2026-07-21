import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe import (
    HttpResult,
    build_first_response_payload,
    build_followup_payload,
    _error_mentions_model_none,
    extract_response_id,
    extract_text,
    redact_secrets,
)


class ProbeHelpersTest(unittest.TestCase):
    def test_followup_payload_uses_previous_response_id(self) -> None:
        payload = build_followup_payload(
            model="openai/gpt-5.5",
            marker="probe-marker",
            previous_response_id="resp_123",
        )

        self.assertEqual(payload["model"], "openai/gpt-5.5")
        self.assertEqual(payload["previous_response_id"], "resp_123")
        self.assertIn("probe-marker", payload["input"])

    def test_first_payload_requests_storage(self) -> None:
        payload = build_first_response_payload(model="openai/gpt-5.5", marker="probe-marker")

        self.assertTrue(payload["store"])
        self.assertEqual(payload["max_output_tokens"], 80)

    def test_extract_text_from_output_text(self) -> None:
        response = {"output_text": "stored"}

        self.assertEqual(extract_text(response), "stored")

    def test_extract_text_from_output_content_blocks(self) -> None:
        response = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "hello"},
                        {"type": "text", "text": " world"},
                    ],
                }
            ]
        }

        self.assertEqual(extract_text(response), "hello world")

    def test_extract_response_id_accepts_polling_id(self) -> None:
        self.assertEqual(extract_response_id({"polling_id": "litellm_poll_123"}), "litellm_poll_123")

    def test_redact_secrets_masks_bearer_and_api_keys(self) -> None:
        value = {
            "headers": {"Authorization": "Bearer sk-secret123", "x-litellm-api-key": "sk-secret456"},
            "body": "request used sk-secret789",
        }

        redacted = redact_secrets(value)

        self.assertNotIn("sk-secret123", str(redacted))
        self.assertNotIn("sk-secret456", str(redacted))
        self.assertNotIn("sk-secret789", str(redacted))
        self.assertIn("sk-...", str(redacted))

    def test_error_mentions_model_none_detects_litellm_passthrough_error(self) -> None:
        result = HttpResult(
            ok=False,
            status=400,
            data={"error": {"message": "litellm.BadRequestError: You passed in model=None."}},
            error="HTTP Error 400",
            elapsed_ms=1,
        )

        self.assertTrue(_error_mentions_model_none(result))


if __name__ == "__main__":
    unittest.main()
