import subprocess
import sys

from ci_failure_orchestrator.github_actions_collector import GitHubActionsCollector
from ci_failure_orchestrator.test_runner import TargetedTestRunner
from ci_failure_orchestrator.workspace import IsolatedGitWorkspace


def test_github_actions_collector_only_returns_failed_jobs():
    jobs = [
        {"id": 1, "name": "unit", "status": "completed", "conclusion": "success"},
        {"id": 2, "name": "typecheck", "status": "completed", "conclusion": "failure", "needs": ["lint"]},
        {"id": 3, "name": "integration", "status": "completed", "conclusion": "cancelled"},
    ]
    collector = GitHubActionsCollector(
        fetch_jobs=lambda run_id: jobs,
        fetch_logs=lambda job_id: f"logs-{job_id}",
    )
    snapshots = collector.collect_failed_jobs(42)
    assert [snapshot.name for snapshot in snapshots] == ["typecheck", "integration"]
    assert snapshots[0].needs == ("lint",)
    assert snapshots[0].logs == "logs-2"


def test_targeted_runner_executes_selected_test(tmp_path):
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    runner = TargetedTestRunner(sys.executable)
    result = runner.run_pytest(tmp_path, ["test_sample.py"], timeout_seconds=30)
    assert result.passed
    assert result.returncode == 0


def test_isolated_workspace_applies_and_rolls_back_patch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    target = repo / "hello.txt"
    target.write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)

    patch = """diff --git a/hello.txt b/hello.txt
index 3367afd..3e75765 100644
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-old
+new
"""
    with IsolatedGitWorkspace(repo) as workspace:
        result = workspace.create("HEAD", "repair-test")
        workspace.apply_patch(patch)
        assert (result.path / "hello.txt").read_text(encoding="utf-8") == "new\n"
        workspace.rollback()
        assert (result.path / "hello.txt").read_text(encoding="utf-8") == "old\n"
