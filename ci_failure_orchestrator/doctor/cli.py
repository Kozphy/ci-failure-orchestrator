"""``actions-doctor``: the CI Doctor command line (read-only diagnosis and an offline demo)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

from ..github_client import GitHubActionsClient, GitHubAPIError
from ..service.untrusted import clean_untrusted
from .demo import run_scenario
from .diagnose import Diagnosis, diagnose_log, diagnose_run
from .render import render_text
from .scenarios import SCENARIOS

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_INPUT = 3
_RUN_URL_RE = re.compile(r"^https://github\.com/([\w.-]+/[\w.-]+)/actions/runs/(\d+)(?:/attempts/(\d+))?/?(?:[?#].*)?$")


def parse_run_url(url: str) -> tuple[str, int, int | None]:
    """Parse a GitHub Actions run URL.

    Returns:
        ``(repository, run_id, attempt)``; attempt is None when the URL names no attempt.

    Raises:
        ValueError: When the URL is not a github.com Actions run URL.
    """
    match = _RUN_URL_RE.match(url.strip())
    if not match:
        raise ValueError("expected https://github.com/<owner>/<repo>/actions/runs/<run id>")
    repository, run_id, attempt = match.groups()
    return repository, int(run_id), int(attempt) if attempt else None


def _emit(diagnosis: Diagnosis, args: argparse.Namespace) -> None:
    payload = diagnosis.to_dict()
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "diagnosis.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(payload, indent=2) + "\n" if args.json else render_text(diagnosis))


def cmd_analyze(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run the analyze command: diagnose one run or saved log; ``EXIT_INPUT`` when it cannot be read."""
    if args.log:
        if args.run or args.attempt:
            parser.error("--run and --attempt apply to --repo or --url, not --log")
        try:
            log = Path(args.log).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            print(f"error: cannot read {args.log}: {exc.strerror}", file=sys.stderr)
            return EXIT_INPUT
        _emit(diagnose_log(log, job=args.job or Path(args.log).stem, step=args.step or ""), args)
        return EXIT_OK
    if args.step:
        parser.error("--step applies to --log; with --repo or --url the step comes from the run")

    if args.url:
        if args.run:
            parser.error("--run is part of --url")
        try:
            repository, run_id, url_attempt = parse_run_url(args.url)
        except ValueError as exc:
            parser.error(str(exc))
        attempt = args.attempt or url_attempt
    else:
        if not args.run:
            parser.error("--repo needs --run <run id>")
        repository, run_id, attempt = args.repo, args.run, args.attempt

    client = GitHubActionsClient(token=args.token, api_url=args.api_url)
    try:
        diagnosis = diagnose_run(client, repository, run_id, attempt=attempt, job=args.job)
    except (GitHubAPIError, ValueError, OSError) as exc:
        print(f"error: {clean_untrusted(str(exc))[:500]}", file=sys.stderr)
        return EXIT_INPUT
    _emit(diagnosis, args)
    return EXIT_OK


def cmd_demo(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Run the demo command: list or run offline fixture scenarios; ``EXIT_UNEXPECTED`` if any result differs."""
    if args.list:
        for scenario in SCENARIOS.values():
            print(f"{scenario.name:<22}{scenario.title}")
        return EXIT_OK
    if bool(args.scenario) == bool(args.all):
        parser.error(f"name one scenario or pass --all; scenarios: {', '.join(SCENARIOS)}")
    if args.workdir:
        workdir = Path(args.workdir)
        if workdir.exists() and any(workdir.iterdir()):
            parser.error(f"--workdir must be empty or not exist yet: {workdir}")
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="ci-doctor-demo-"))
    print(f"CI Doctor demo | offline | work directory: {workdir.resolve()}\n")
    names = list(SCENARIOS) if args.all else [args.scenario]
    results = []
    for name in names:
        result, lines = run_scenario(SCENARIOS[name], workdir.resolve())
        results.append(result)
        print("\n".join(lines))
    if len(results) > 1:
        print("Summary")
        for result in results:
            rules = " ".join(rule[:7] for rule in result.rules) or "-"
            mark = "ok" if result.as_expected else "UNEXPECTED"
            print(f"  {result.scenario:<22}{result.category:<23}{result.outcome:<16}{rules:<18}{mark}")
    return EXIT_OK if all(result.as_expected for result in results) else EXIT_UNEXPECTED


def build_parser() -> argparse.ArgumentParser:
    """Build the ``actions-doctor`` argument parser with the analyze and demo subcommands."""
    parser = argparse.ArgumentParser(
        prog="actions-doctor",
        description=(
            "CI Doctor: diagnose GitHub Actions failures from log evidence. analyze is read-only; "
            "demo writes only to its own work directory."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser(
        "analyze",
        help="Diagnose one failed run or one saved job log (read-only)",
        description="Diagnose one failed run or one saved job log. Never writes to a repository.",
    )
    source = analyze.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Run URL: https://github.com/<owner>/<repo>/actions/runs/<id>")
    source.add_argument("--repo", help="Repository as owner/name (with --run)")
    source.add_argument("--log", help="Saved job log file (offline; no token needed)")
    analyze.add_argument("--run", type=int, help="Workflow run ID (with --repo)")
    analyze.add_argument("--attempt", type=int, help="Run attempt (default: latest)")
    analyze.add_argument("--job", help="Only this job; with --log, the job name to show")
    analyze.add_argument("--step", help="With --log: the name of the step that failed")
    analyze.add_argument("--token", help="GitHub token; defaults to GITHUB_TOKEN. Never printed or stored")
    analyze.add_argument("--api-url", default="https://api.github.com")
    analyze.add_argument("--json", action="store_true", help="Print the diagnosis as JSON")
    analyze.add_argument("--out", help="Also write diagnosis.json to this directory")
    analyze.set_defaults(func=cmd_analyze)

    demo = sub.add_parser(
        "demo",
        help="Run offline failure scenarios end to end (diagnose, verify a recorded fix, policy decision)",
        description=(
            "Builds a throwaway repository per scenario, diagnoses its saved CI log, verifies a recorded fix "
            "in a disposable worktree and shows the policy decision and audit evidence. No network, token or model."
        ),
    )
    demo.add_argument("scenario", nargs="?", choices=list(SCENARIOS), help="Scenario to run")
    demo.add_argument("--all", action="store_true", help="Run every scenario")
    demo.add_argument("--list", action="store_true", help="List the scenarios")
    demo.add_argument("--workdir", help="Empty directory for the repositories and evidence (default: a new temp dir)")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse ``argv`` and run the chosen ``actions-doctor`` subcommand, returning its exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args, parser)


if __name__ == "__main__":
    raise SystemExit(main())
