import json

from research.dataset import read_lock
from research.manifest import build_manifest, contains_secret_shape, scrub

FAKE_TOKEN = "ghp_" + "A" * 36
REQUIRED = {
    "experiment_id", "timestamp", "git_commit", "dataset_version", "dataset_sha256", "split_sha256", "case_ids",
    "baseline_versions", "model", "prompt_versions", "context_policy", "seed", "retry_budget", "tool_permissions",
    "environment", "command", "config_sha256",
}


def _manifest(config: dict, command: list[str]) -> dict:
    return build_manifest(
        experiment_id="t-1", timestamp="2026-10-07T00:00:00+00:00", config=config, config_path="cfg.yaml",
        lock=read_lock() or {}, splits=["development"], case_ids={"diagnosis": ["a"], "repair": []},
        systems={"diagnosis": ["B0"], "repair": []}, system_versions={"B0": "b0/v1"}, prompts={"b1": "0" * 64},
        provider={"provider": "command", "name": "m", "version": "1", "temperature": 0, "claim_eligible": True,
                  "env_passthrough": ["MODEL_API_KEY"]},
        command=command,
    )


def test_manifest_records_every_required_field():
    manifest = _manifest({"experiment": {"seed": 5}, "repair": {"retry_budget": 3}}, ["python", "-m", "research.run"])
    assert REQUIRED <= set(manifest)
    assert manifest["seed"] == 5 and manifest["retry_budget"] == 3
    assert manifest["dataset_version"] == "1.0.0"
    assert manifest["model"]["env_passthrough_names"] == ["MODEL_API_KEY"]


def test_secrets_never_reach_the_manifest():
    config = {"model": {"api_key": "plain-secret-value", "note": f"token {FAKE_TOKEN}"}, "experiment": {}}
    manifest = _manifest(config, ["python", "-m", "research.run", f"--token={FAKE_TOKEN}"])
    text = json.dumps(manifest)
    assert not contains_secret_shape(text)
    assert "plain-secret-value" not in text
    assert FAKE_TOKEN not in text


def test_scrub_handles_nested_values():
    scrubbed = scrub({"a": [{"password": "x"}, f"Bearer {FAKE_TOKEN}"]})
    assert FAKE_TOKEN not in json.dumps(scrubbed)
    assert scrubbed["a"][0]["password"] != "x"
