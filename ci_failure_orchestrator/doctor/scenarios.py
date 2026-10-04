"""Six offline demo scenarios: a small repository, the CI log it produced, and a recorded fix.

Each scenario is a real failure in its own repository: the verify command fails at the
failing commit and passes with the recorded fix. The CI logs are written in the shape
GitHub Actions downloads, so ``analyze`` reads them exactly as it reads a real job log.
No scenario needs the network, a token or a model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    name: str
    title: str
    story: str
    files: Mapping[str, str]
    fix: Mapping[str, str]
    job: str
    step: str
    ci_log: str
    verify: tuple[str, ...]
    expected_category: str
    expected_outcome: str
    expected_rules: tuple[str, ...] = ()
    verify_timeout: int = 60


def _actions_log(*blocks: str) -> str:
    """A downloaded job log: GitHub prefixes every line with a timestamp."""
    lines = "\n".join(block.strip("\n") for block in blocks).splitlines()
    return "".join(f"2026-09-30T08:14:{i // 10:02d}.{i % 10}000000Z {line}\n" for i, line in enumerate(lines))


def _prelude(repo: str, python: str = "3.12", full: str = "3.12.6") -> str:
    return f"""
Current runner version: '2.319.1'
##[group]Run actions/checkout@v4
with:
  repository: acme/{repo}
  fetch-depth: 1
##[endgroup]
Syncing repository: acme/{repo}
##[group]Run actions/setup-python@v5
with:
  python-version: {python}
##[endgroup]
Successfully set up CPython ({full})
"""


def _step(command: str, output: str, error: str = "Process completed with exit code 1.") -> str:
    return f"""
##[group]Run {command}
{command}
shell: /usr/bin/bash -e {{0}}
##[endgroup]
{output.strip(chr(10))}
##[error]{error}
"""


_CLEANUP = """
Post job cleanup.
[command]/usr/bin/git version
git version 2.46.1
"""


def _workflow(steps: str, python: str = "3.12") -> str:
    return f"""name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "{python}"
{steps}"""


_UNITTEST = '{python} -m unittest discover -s tests -t .'

# --- dependency drift -------------------------------------------------------------------------

_DRIFT_CLIENT = """from fakelib import parse


def total_due(query):
    fields = parse(query)
    return int(fields["amount"]) - int(fields.get("paid", 0))
"""

DEPENDENCY_DRIFT = Scenario(
    name="dependency-drift",
    title="Dependency drift",
    story=(
        "requirements.txt allows any fakelib >= 1.0. CI installed fakelib 2.0.0, which renamed parse() "
        "to parse_query(), so the client no longer imports."
    ),
    files={
        "requirements.txt": "fakelib>=1.0\n",
        "fakelib/__init__.py": (
            '"""Stands in for fakelib 2.0.0, the release CI installed: parse() is now parse_query()."""\n'
            "\n"
            '__version__ = "2.0.0"\n'
            "\n"
            "\n"
            "def parse_query(text):\n"
            '    return dict(pair.split("=", 1) for pair in text.split("&") if pair)\n'
        ),
        "invoice/__init__.py": "",
        "invoice/client.py": _DRIFT_CLIENT,
        "tests/__init__.py": "",
        "tests/test_client.py": (
            "import unittest\n"
            "\n"
            "from invoice.client import total_due\n"
            "\n"
            "\n"
            "class TotalDueTest(unittest.TestCase):\n"
            "    def test_subtracts_payments(self):\n"
            '        self.assertEqual(total_due("amount=120&paid=20"), 100)\n'
        ),
        ".github/workflows/ci.yml": _workflow(
            "      - run: pip install -r requirements.txt\n"
            "      - name: Run tests\n"
            "        run: python -m pytest -q\n"
        ),
    },
    fix={
        "invoice/client.py": _DRIFT_CLIENT.replace("import parse\n", "import parse_query\n").replace(
            "= parse(query)", "= parse_query(query)"
        ),
        "requirements.txt": "fakelib>=2.0,<3\n",
    },
    job="test",
    step="Run tests",
    ci_log=_actions_log(
        _prelude("invoice"),
        """
##[group]Run pip install -r requirements.txt
pip install -r requirements.txt
shell: /usr/bin/bash -e {0}
##[endgroup]
Collecting fakelib>=1.0 (from -r requirements.txt (line 1))
  Downloading fakelib-2.0.0-py3-none-any.whl.metadata (1.2 kB)
Downloading fakelib-2.0.0-py3-none-any.whl (6.1 kB)
Installing collected packages: fakelib
Successfully installed fakelib-2.0.0
""",
        _step(
            "python -m pytest -q",
            """
==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_client.py _____________________
ImportError while importing test module '/home/runner/work/invoice/invoice/tests/test_client.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/opt/hostedtoolcache/Python/3.12.6/x64/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_client.py:3: in <module>
    from invoice.client import total_due
invoice/client.py:1: in <module>
    from fakelib import parse
E   ImportError: cannot import name 'parse' from 'fakelib' (/opt/hostedtoolcache/Python/3.12.6/x64/lib/python3.12/site-packages/fakelib/__init__.py)
=========================== short test summary info ============================
ERROR tests/test_client.py - ImportError: cannot import name 'parse' from 'fakelib' (/opt/hostedtoolcache/Python/3.12.6/x64/lib/python3.12/site-packages/fakelib/__init__.py)
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.08s
""",
            "Process completed with exit code 2.",
        ),
        _CLEANUP,
    ),
    verify=(_UNITTEST,),
    expected_category="dependency_failure",
    expected_outcome="AWAITING_HUMAN",
    expected_rules=("POL-007", "POL-014"),
)

# --- flaky test -------------------------------------------------------------------------------

_FLAKY_TEST = """from reviewers.pick import pick_reviewers

TEAM = ("ana", "bo", "cy", "di")


def test_picks_two_different_reviewers():
    picked = pick_reviewers(TEAM, 2)
    assert picked == sorted(set(picked))
"""

FLAKY_TEST = Scenario(
    name="flaky-test",
    title="Flaky test",
    story=(
        "CI repeats the suite three times. The test passed twice and failed once on the same commit: it "
        "expects random.sample() to return reviewers in sorted order."
    ),
    files={
        "reviewers/__init__.py": "",
        "reviewers/pick.py": (
            "import random\n"
            "\n"
            "\n"
            "def pick_reviewers(team, count, rng=random):\n"
            '    """``count`` different reviewers, chosen at random so review load spreads out."""\n'
            "    return rng.sample(list(team), count)\n"
        ),
        "tests/__init__.py": "",
        "tests/test_pick.py": _FLAKY_TEST,
        "tools/repeat_tests.py": (
            '"""Run every test function under 30 fixed seeds, the way CI repeats the suite."""\n'
            "\n"
            "import importlib\n"
            "import pathlib\n"
            "import random\n"
            "import sys\n"
            "\n"
            "ROOT = pathlib.Path(__file__).resolve().parents[1]\n"
            "sys.path.insert(0, str(ROOT))\n"
            "\n"
            "failures = 0\n"
            'for path in sorted((ROOT / "tests").glob("test_*.py")):\n'
            '    module = importlib.import_module(f"tests.{path.stem}")\n'
            '    for name in sorted(n for n in vars(module) if n.startswith("test_")):\n'
            "        for seed in range(30):\n"
            "            random.seed(seed)\n"
            "            try:\n"
            "                getattr(module, name)()\n"
            "            except AssertionError:\n"
            "                failures += 1\n"
            '                print(f"FAILED {path.name}::{name} with seed {seed}")\n'
            'print(f"{failures} failed")\n'
            "sys.exit(1 if failures else 0)\n"
        ),
        ".github/workflows/ci.yml": _workflow(
            "      - run: pip install pytest pytest-repeat\n"
            "      - name: Run tests\n"
            "        run: python -m pytest -v --count 3\n"
        ),
    },
    fix={
        "tests/test_pick.py": _FLAKY_TEST.replace(
            "assert picked == sorted(set(picked))",
            "assert len(set(picked)) == 2\n    assert set(picked) <= set(TEAM)",
        ),
    },
    job="test",
    step="Run tests",
    ci_log=_actions_log(
        _prelude("reviewers"),
        _step(
            "python -m pytest -v --count 3",
            """
============================= test session starts ==============================
platform linux -- Python 3.12.6, pytest-8.3.3, pluggy-1.5.0 -- /opt/hostedtoolcache/Python/3.12.6/x64/bin/python
plugins: repeat-0.9.3
collecting ... collected 3 items

tests/test_pick.py::test_picks_two_different_reviewers[1-3] PASSED       [ 33%]
tests/test_pick.py::test_picks_two_different_reviewers[2-3] FAILED       [ 66%]
tests/test_pick.py::test_picks_two_different_reviewers[3-3] PASSED       [100%]

=================================== FAILURES ===================================
__________________ test_picks_two_different_reviewers[2-3] ___________________

    def test_picks_two_different_reviewers():
        picked = pick_reviewers(TEAM, 2)
>       assert picked == sorted(set(picked))
E       AssertionError: assert ['di', 'bo'] == ['bo', 'di']

tests/test_pick.py:8: AssertionError
=========================== short test summary info ============================
FAILED tests/test_pick.py::test_picks_two_different_reviewers[2-3] - AssertionError: assert ['di', 'bo'] == ['bo', 'di']
========================= 1 failed, 2 passed in 0.03s ==========================
""",
        ),
        _CLEANUP,
    ),
    verify=("{python} tools/repeat_tests.py",),
    expected_category="flaky_failure",
    # The fix is right, but it changes what the test checks; only a person can confirm the old
    # expectation was wrong rather than loosened until it passed.
    expected_outcome="AWAITING_HUMAN",
    expected_rules=("POL-019",),
)

# --- network failure --------------------------------------------------------------------------

_RATES_CLIENT = """import json
from urllib.request import urlopen

RATES_URL = "https://rates.example.com/v1/latest?base=EUR"


def latest_rate(currency):
    with urlopen(RATES_URL, timeout=10) as response:
        return json.load(response)["rates"][currency]
"""

NETWORK_FAILURE = Scenario(
    name="network-failure",
    title="Network failure",
    story=(
        "The runner could not resolve the rates API's host name. The code is fine; a patch that "
        "retries or mocks the call would only hide that the network was missing."
    ),
    files={
        "rates/__init__.py": "",
        "rates/client.py": _RATES_CLIENT,
        "tests/__init__.py": (
            '"""The demo runs offline: host name lookups fail the way they did on the CI runner."""\n'
            "\n"
            "import socket\n"
            "\n"
            'RUNNER_ERROR = "Name or service not known"\n'
            "\n"
            "\n"
            "def _offline(*args, **kwargs):\n"
            "    raise socket.gaierror(-2, RUNNER_ERROR)\n"
            "\n"
            "\n"
            "socket.getaddrinfo = _offline\n"
        ),
        "tests/test_client.py": (
            "import unittest\n"
            "\n"
            "from rates.client import latest_rate\n"
            "\n"
            "\n"
            "class LatestRateTest(unittest.TestCase):\n"
            "    def test_usd_rate_is_positive(self):\n"
            '        self.assertGreater(latest_rate("USD"), 0)\n'
        ),
        ".github/workflows/ci.yml": _workflow(
            "      - run: pip install pytest\n"
            "      - name: Run tests\n"
            "        run: python -m pytest -q\n"
        ),
    },
    fix={
        "rates/client.py": _RATES_CLIENT.replace(
            "import json\n", "import json\nimport time\n"
        ).replace(
            "def latest_rate(currency):\n"
            "    with urlopen(RATES_URL, timeout=10) as response:\n"
            '        return json.load(response)["rates"][currency]\n',
            "def latest_rate(currency, attempts=3):\n"
            "    for attempt in range(attempts):\n"
            "        try:\n"
            "            with urlopen(RATES_URL, timeout=10) as response:\n"
            '                return json.load(response)["rates"][currency]\n'
            "        except OSError:\n"
            "            if attempt == attempts - 1:\n"
            "                raise\n"
            "            time.sleep(2**attempt)\n",
        ),
    },
    job="test",
    step="Run tests",
    ci_log=_actions_log(
        _prelude("rates"),
        _step(
            "python -m pytest -q",
            """
F                                                                        [100%]
=================================== FAILURES ===================================
_____________________ LatestRateTest.test_usd_rate_is_positive _____________________
/opt/hostedtoolcache/Python/3.12.6/x64/lib/python3.12/urllib/request.py:1344: in do_open
    h.request(req.get_method(), req.selector, req.data, headers,
/opt/hostedtoolcache/Python/3.12.6/x64/lib/python3.12/socket.py:963: in getaddrinfo
    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):
E   socket.gaierror: [Errno -2] Name or service not known

During handling of the above exception, another exception occurred:
tests/test_client.py:8: in test_usd_rate_is_positive
    self.assertGreater(latest_rate("USD"), 0)
rates/client.py:8: in latest_rate
    with urlopen(RATES_URL, timeout=10) as response:
E   urllib.error.URLError: <urlopen error [Errno -2] Name or service not known>
=========================== short test summary info ============================
FAILED tests/test_client.py::LatestRateTest::test_usd_rate_is_positive - urllib.error.URLError: <urlopen error [Errno -2] Name or service not known>
1 failed in 0.21s
""",
        ),
        _CLEANUP,
    ),
    verify=(_UNITTEST,),
    expected_category="network_failure",
    expected_outcome="AWAITING_HUMAN",
)

# --- timeout ----------------------------------------------------------------------------------

_POLLER = """import time


def wait_until_ready(is_ready, attempts=5, delay=0.0):
    \"\"\"Poll ``is_ready`` up to ``attempts`` times; True as soon as it reports ready.\"\"\"
    tried = 0
    while tried < attempts:
        if is_ready():
            return True
        time.sleep(delay)
    return False
"""

TIMEOUT = Scenario(
    name="timeout",
    title="Timeout",
    story=(
        "The test step hit its 10-minute limit. wait_until_ready() never counts its attempts, so it "
        "polls forever when the service never becomes ready."
    ),
    files={
        "jobs/__init__.py": "",
        "jobs/poller.py": _POLLER,
        "tests/__init__.py": "",
        "tests/test_poller.py": (
            "import unittest\n"
            "\n"
            "from jobs.poller import wait_until_ready\n"
            "\n"
            "\n"
            "class WaitUntilReadyTest(unittest.TestCase):\n"
            "    def test_returns_once_ready(self):\n"
            "        self.assertTrue(wait_until_ready(lambda: True))\n"
            "\n"
            "    def test_gives_up_when_never_ready(self):\n"
            "        self.assertFalse(wait_until_ready(lambda: False, attempts=3))\n"
        ),
        ".github/workflows/ci.yml": _workflow(
            "      - run: pip install pytest\n"
            "      - name: Run tests\n"
            "        timeout-minutes: 10\n"
            "        run: python -m pytest -v\n"
        ),
    },
    fix={
        "jobs/poller.py": _POLLER.replace(
            "        time.sleep(delay)\n", "        tried += 1\n        time.sleep(delay)\n"
        ),
    },
    job="test",
    step="Run tests",
    ci_log=_actions_log(
        _prelude("jobs"),
        _step(
            "python -m pytest -v",
            """
============================= test session starts ==============================
platform linux -- Python 3.12.6, pytest-8.3.3, pluggy-1.5.0 -- /opt/hostedtoolcache/Python/3.12.6/x64/bin/python
collecting ... collected 2 items

tests/test_poller.py::WaitUntilReadyTest::test_gives_up_when_never_ready
""",
            "The action 'Run tests' has timed out after 10 minutes.",
        ),
        _CLEANUP,
    ),
    verify=(_UNITTEST,),
    expected_category="timeout_failure",
    expected_outcome="AWAITING_HUMAN",
    expected_rules=("POL-014",),
    verify_timeout=5,
)

# --- configuration error ----------------------------------------------------------------------

_APP_INI = """[http]
base_url = https://billing.internal.example
retry_limt = 3
timeout_seconds = 10
"""

CONFIGURATION_ERROR = Scenario(
    name="configuration-error",
    title="Configuration error",
    story=(
        "A typo in config/app.ini (retry_limt) is rejected by the settings loader in the "
        "\"Check configuration\" step."
    ),
    files={
        "config/app.ini": _APP_INI,
        "billing/__init__.py": "",
        "billing/settings.py": (
            "import configparser\n"
            "\n"
            'KNOWN = {"base_url", "retry_limit", "timeout_seconds"}\n'
            "\n"
            "\n"
            "class ConfigError(Exception):\n"
            "    pass\n"
            "\n"
            "\n"
            'def load(path="config/app.ini"):\n'
            "    parser = configparser.ConfigParser()\n"
            '    if not parser.read(path, encoding="utf-8"):\n'
            '        raise ConfigError(f"cannot read {path}")\n'
            '    section = parser["http"]\n'
            "    unknown = sorted(set(section) - KNOWN)\n"
            "    if unknown:\n"
            '        raise ConfigError(f"unknown setting {unknown[0]!r} in [http] of {path}")\n'
            "    return {\n"
            '        "base_url": section["base_url"],\n'
            '        "retry_limit": section.getint("retry_limit"),\n'
            '        "timeout_seconds": section.getint("timeout_seconds"),\n'
            "    }\n"
            "\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    print(load())\n"
        ),
        ".github/workflows/ci.yml": _workflow(
            "      - name: Check configuration\n"
            "        run: python -m billing.settings\n"
        ),
    },
    fix={"config/app.ini": _APP_INI.replace("retry_limt", "retry_limit")},
    job="config",
    step="Check configuration",
    ci_log=_actions_log(
        _prelude("billing"),
        _step(
            "python -m billing.settings",
            """
Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "/home/runner/work/billing/billing/billing/settings.py", line 26, in <module>
    print(load())
          ^^^^^^
  File "/home/runner/work/billing/billing/billing/settings.py", line 17, in load
    raise ConfigError(f"unknown setting {unknown[0]!r} in [http] of {path}")
__main__.ConfigError: unknown setting 'retry_limt' in [http] of config/app.ini
""",
        ),
        _CLEANUP,
    ),
    verify=("{python} -m billing.settings",),
    expected_category="configuration_failure",
    expected_outcome="AWAITING_HUMAN",
)

# --- environment mismatch ---------------------------------------------------------------------

ENVIRONMENT_MISMATCH = Scenario(
    name="environment-mismatch",
    title="Environment mismatch",
    story=(
        "pyproject.toml requires Python >= 3.10, but the workflow still sets up Python 3.8, so pip "
        "refuses to install the package."
    ),
    files={
        "pyproject.toml": (
            "[project]\n"
            'name = "invoice-tools"\n'
            'version = "1.4.0"\n'
            'requires-python = ">=3.10"\n'
        ),
        "invoice_tools/__init__.py": (
            "def describe(status):\n"
            "    match status:\n"
            '        case "paid":\n'
            '            return "settled"\n'
            "        case _:\n"
            '            return "open"\n'
        ),
        "tools/check_runtime.py": (
            '"""Fail when the workflow sets up an older Python than pyproject.toml requires."""\n'
            "\n"
            "import pathlib\n"
            "import re\n"
            "import sys\n"
            "\n"
            "ROOT = pathlib.Path(__file__).resolve().parents[1]\n"
            'workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")\n'
            'project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")\n'
            "used = tuple(int(n) for n in re.search(r'python-version: \"?(\\d+)\\.(\\d+)', workflow).groups())\n"
            "floor = tuple(int(n) for n in re.search(r'requires-python = \">=(\\d+)\\.(\\d+)', project).groups())\n"
            "if used < floor:\n"
            "    print(f\"ci.yml sets up Python {used[0]}.{used[1]}; pyproject.toml requires >={floor[0]}.{floor[1]}\")\n"
            "    sys.exit(1)\n"
            "print(\"runtime matches the declaration\")\n"
        ),
        ".github/workflows/ci.yml": _workflow(
            "      - name: Install package\n"
            "        run: pip install .\n",
            python="3.8",
        ),
    },
    fix={
        ".github/workflows/ci.yml": _workflow(
            "      - name: Install package\n"
            "        run: pip install .\n",
            python="3.12",
        ),
    },
    job="test",
    step="Install package",
    ci_log=_actions_log(
        _prelude("invoice-tools", python="3.8", full="3.8.18"),
        _step(
            "pip install .",
            """
Processing /home/runner/work/invoice-tools/invoice-tools
  Installing build dependencies: started
  Installing build dependencies: finished with status 'done'
  Getting requirements to build wheel: started
  Getting requirements to build wheel: finished with status 'done'
  Preparing metadata (pyproject.toml): started
  Preparing metadata (pyproject.toml): finished with status 'done'
ERROR: Package 'invoice-tools' requires a different Python: 3.8.18 not in '>=3.10'
""",
        ),
        _CLEANUP,
    ),
    verify=("{python} tools/check_runtime.py",),
    expected_category="environment_failure",
    expected_outcome="AWAITING_HUMAN",
    expected_rules=("POL-004", "POL-014"),
)

SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (DEPENDENCY_DRIFT, FLAKY_TEST, NETWORK_FAILURE, TIMEOUT, CONFIGURATION_ERROR, ENVIRONMENT_MISMATCH)
}
