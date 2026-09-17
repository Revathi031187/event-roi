"""
Phase F validation: masking must genuinely redact, not just "look configured."

Run with: .venv/Scripts/python.exe -m pytest backend/evals/tests/test_masking.py -v
(or plain `python backend/evals/tests/test_masking.py` — no pytest required,
see the __main__ block).

Per references/security-production.md: "test it against more than one
realistic example, and cover tool-call arguments/results, not just chat
message content." These cases specifically include a Databricks token and a
Gemini API key riding inside a nested dict shaped like a real tool-call
result (GenieService._sync_ask_once's return shape), not just a flat string.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.observability import mask_sensitive_data  # noqa: E402


def _assert_redacted(raw: str, masked, must_not_contain: list[str], label: str):
    masked_str = str(masked)
    for secret in must_not_contain:
        assert secret not in masked_str, (
            f"[{label}] FAILED — secret '{secret}' leaked into masked output: {masked_str}"
        )
    print(f"[{label}] OK — no leaked secrets in: {masked_str[:200]}")


def test_flat_string_with_email_and_phone():
    raw = "Contact Jane Doe at jane.doe@example-corp.com or (415) 555-0134 for questions."
    masked = mask_sensitive_data(data=raw)
    _assert_redacted(
        raw, masked,
        ["jane.doe@example-corp.com", "(415) 555-0134", "415) 555-0134"],
        "email+phone in free text",
    )
    assert "[REDACTED_EMAIL]" in masked
    assert "[REDACTED_PHONE]" in masked


def test_databricks_token_in_nested_toolcall_result():
    """Shaped like GenieService's request/response — a nested dict, not a
    flat string. This is the case Phase F explicitly calls out: masking that
    only covers flat chat content and misses nested tool-call structures."""
    raw = {
        "question": "Show registrations for NRF 2026",
        "databricks_host": "https://acme-corp.cloud.databricks.com",
        "databricks_token": "dapi1234567890abcdef1234567890abcdef",
        "status": "SUCCEEDED",
        "data_rows": [["NRF 2026", 4200, "jane.doe@example-corp.com"]],
    }
    masked = mask_sensitive_data(data=raw)
    _assert_redacted(
        str(raw), masked,
        ["dapi1234567890abcdef1234567890abcdef", "jane.doe@example-corp.com"],
        "databricks token + email nested in tool-call result",
    )
    assert masked["databricks_token"] == "[REDACTED]"
    # Non-secret fields must survive untouched so the trace stays useful.
    assert masked["question"] == raw["question"]
    assert masked["status"] == "SUCCEEDED"


def test_gemini_api_key_and_bearer_token():
    raw = "Authorization: Bearer AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r additional context"
    masked = mask_sensitive_data(data=raw)
    _assert_redacted(
        raw, masked,
        ["AIzaSyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r"],
        "google api key shape",
    )


def test_generic_request_body_with_secret_shaped_key_name():
    """A field merely NAMED like a secret (api_key, password, ...) must be
    redacted even if the value doesn't match any known shape regex — this is
    the defense-in-depth layer for secret formats we didn't anticipate."""
    raw = {"gemini_api_key": "totally-made-up-value-123", "event_name": "NRF 2026"}
    masked = mask_sensitive_data(data=raw)
    assert masked["gemini_api_key"] == "[REDACTED]"
    assert masked["event_name"] == "NRF 2026"
    print("[key-name-based redaction] OK")


def test_masking_failure_fails_closed_not_open():
    """If the masking function itself throws, content must be withheld, not
    passed through unmasked (fail CLOSED here — the one place in this codebase
    that should NOT fail open, since the failure mode is data exposure).

    Trigger a real exception inside the recursive masker (a dict key whose
    __str__ raises, hit by `str(k)` in the dict branch) rather than asserting
    against a case that happens to not raise at all.
    """

    class BadKey:
        def __str__(self):
            raise RuntimeError("boom")

        def __hash__(self):
            return 1

    masked = mask_sensitive_data(data={BadKey(): "some value with secret@example.com"})
    assert masked == "[MASKING_ERROR — CONTENT_WITHHELD]", (
        f"Expected content to be withheld on masking error, got: {masked!r}"
    )
    print(f"[fail-closed-on-masking-error] OK — result: {masked}")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} masking tests passed")
    sys.exit(1 if failed else 0)
