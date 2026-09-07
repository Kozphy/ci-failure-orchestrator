from ci_failure_orchestrator.openai_backend import REPAIR_SCHEMA


def test_live_backend_schema_is_strict_and_allowlisted():
    assert REPAIR_SCHEMA["additionalProperties"] is False
    repair = REPAIR_SCHEMA["properties"]["repairs"]["items"]
    assert repair["additionalProperties"] is False
    assert set(repair["properties"]["strategy"]["enum"]) == {
        "replace_text",
        "append_line",
        "remove_line",
    }
    assert "shell" not in repair["properties"]
    assert "command" not in repair["properties"]
