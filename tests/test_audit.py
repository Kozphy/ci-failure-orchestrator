import json

from ci_failure_orchestrator.audit import HashChainedAuditLog


def test_hash_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = HashChainedAuditLog(path)
    first = log.append("a", {"x": 1})
    second = log.append("b", {"x": 2})
    assert second["prev_hash"] == first["hash"]
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert len(lines) == 2
