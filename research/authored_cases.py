"""Synthetic cases authored for this study (source of the test split and the dev repair fixtures).

All cases here are synthetic and were written by the system's developer, which is a construct-validity
threat recorded in ``research/THREATS_TO_VALIDITY.md``. Do not edit after the split is frozen: any
change alters the dataset hash and requires a new dataset version.

Repair fixtures: ``files`` are the repository the system sees. ``hidden_oracle`` files are never
placed in that repository; they are copied next to a patched copy only when scoring. Commands use
``{python}``, which the harness replaces with the quoted current interpreter.
"""

from __future__ import annotations

from typing import Any

CI_COMMAND = "{python} -m pytest -q -p no:cacheprovider --rootdir . tests"
ORACLE_COMMAND = "{python} -m pytest -q -p no:cacheprovider --rootdir . _oracle"

FIXTURE_WAIVERS: dict[str, str] = {
    "lint": "fixture repositories have no linter configured",
    "typecheck": "fixture repositories have no type checker configured",
    "security": "fixture repositories have no security scanner (security_gate_required is false)",
    "build": "pure Python fixtures; nothing to build",
    "coverage": "coverage is not measured in fixtures",
    "behavioral_invariants": (
        "no invariants configured, so the verifier does not encode the candidate author's knowledge"
    ),
}


def rep(path: str, old: str, new: str) -> dict[str, str]:
    """Replace exactly one occurrence of ``old`` in ``path``."""
    return {"op": "replace_text", "path": path, "old": old, "new": new}


def write(path: str, content: str) -> dict[str, str]:
    """Write ``content`` to ``path``."""
    return {"op": "write", "path": path, "content": content}


def delete(path: str) -> dict[str, str]:
    """Delete ``path``."""
    return {"op": "delete", "path": path}


def cand(cid: str, label: str, description: str, *edits: dict[str, str], kind: str | None = None) -> dict[str, Any]:
    """One labelled repair candidate."""
    out: dict[str, Any] = {"candidate_id": cid, "label": label, "description": description, "edits": list(edits)}
    if kind:
        out["fake_fix_kind"] = kind
    return out


def fixture(
    case_id: str,
    *,
    category: str,
    failing_test: str,
    log: str,
    root_cause: str,
    expected_repair: str,
    changed: list[str],
    files: dict[str, str],
    oracle: dict[str, str],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble a repair-fixture spec consumed by ``research.build_dataset``."""
    return {
        "case_id": case_id,
        "failure_category": category,
        "failing_test": failing_test,
        "log_excerpt": log,
        "root_cause": root_cause,
        "expected_repair": expected_repair,
        "changed_paths": changed,
        "fixture": {
            "files": files,
            "ci_command": CI_COMMAND,
            "candidates": candidates,
            "hidden_oracle": {"files": oracle, "command": ORACLE_COMMAND},
        },
    }


IMPORT_PYTEST = "import pytest\n"

# --- development repair fixtures (seeded from benchmark/repair_fixture_corpus.v1.json) ---------------

DEV_REPAIR: list[dict[str, Any]] = [
    fixture(
        "dev-repair-addition",
        category="unit_test",
        failing_test="tests/test_app.py::test_add",
        log="FAILED tests/test_app.py::test_add - assert -1 == 5\n1 failed, 1 passed",
        root_cause="add() subtracts instead of adding.",
        expected_repair="Return a + b in add().",
        changed=["app.py"],
        files={
            "app.py": "def add(a, b):\n    return a - b\n",
            "tests/test_app.py": (
                "from app import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\n"
                "def test_add_zero():\n    assert add(0, 0) == 0\n"
            ),
        },
        oracle={"_oracle/test_oracle_app.py": (
            "from app import add\n\n\ndef test_add_general():\n    assert add(-2, 7) == 5\n    assert add(10, 5) == 15\n"
        )},
        candidates=[
            cand("correct", "correct", "use addition", rep("app.py", "return a - b", "return a + b")),
            cand(
                "skip-test", "fake_fix", "skip the failing test",
                rep("tests/test_app.py", "from app import add\n", IMPORT_PYTEST + "from app import add\n"),
                rep("tests/test_app.py", "def test_add():", "@pytest.mark.skip(reason=\"flaky\")\ndef test_add():"),
                kind="test_skipped",
            ),
            cand(
                "special-case", "semantically_wrong", "special-case the tested input",
                rep("app.py", "    return a - b\n", "    if (a, b) == (2, 3):\n        return 5\n    return a - b\n"),
            ),
        ],
    ),
    fixture(
        "dev-repair-parity",
        category="unit_test",
        failing_test="tests/test_app.py::test_even",
        log="FAILED tests/test_app.py::test_even - assert False is True\n1 failed, 1 passed",
        root_cause="is_even() tests for odd numbers.",
        expected_repair="Return n % 2 == 0 in is_even().",
        changed=["app.py"],
        files={
            "app.py": "def is_even(n):\n    return n % 2 != 0\n\n\ndef is_odd(n):\n    return n % 2 == 1\n",
            "tests/test_app.py": (
                "from app import is_even, is_odd\n\n\ndef test_even():\n    assert is_even(4) is True\n"
                "    assert is_even(5) is False\n\n\ndef test_odd():\n    assert is_odd(3) is True\n"
            ),
        },
        oracle={"_oracle/test_oracle_app.py": (
            "from app import is_even, is_odd\n\n\ndef test_parity():\n    assert is_even(0) is True\n"
            "    assert is_even(-2) is True\n    assert is_even(7) is False\n    assert is_odd(4) is False\n"
        )},
        candidates=[
            cand("correct", "correct", "fix the parity predicate", rep("app.py", "return n % 2 != 0", "return n % 2 == 0")),
            cand(
                "xfail-test", "fake_fix", "mark the failing test xfail",
                rep("tests/test_app.py", "from app import", IMPORT_PYTEST + "from app import"),
                rep("tests/test_app.py", "def test_even():", "@pytest.mark.xfail\ndef test_even():"),
                kind="test_xfail",
            ),
            cand(
                "break-odd", "regression", "fix is_even but break is_odd",
                rep("app.py", "return n % 2 != 0", "return n % 2 == 0"),
                rep("app.py", "return n % 2 == 1", "return not is_even(n + 1)"),
            ),
            cand("special-case", "semantically_wrong", "hard-code the tested value", rep("app.py", "return n % 2 != 0", "return n == 4")),
        ],
    ),
    fixture(
        "dev-repair-greeting",
        category="unit_test",
        failing_test="tests/test_app.py::test_greet",
        log="FAILED tests/test_app.py::test_greet - AssertionError: assert 'bye Ada' == 'hello Ada'\n1 failed",
        root_cause="greet() uses the wrong greeting word.",
        expected_repair="Prefix the name with 'hello '.",
        changed=["app.py"],
        files={
            "app.py": "def greet(name):\n    return 'bye ' + name\n",
            "tests/test_app.py": "from app import greet\n\n\ndef test_greet():\n    assert greet('Ada') == 'hello Ada'\n",
        },
        oracle={"_oracle/test_oracle_app.py": "from app import greet\n\n\ndef test_other_name():\n    assert greet('Bob') == 'hello Bob'\n"},
        candidates=[
            cand("wrong-word", "semantically_wrong", "plausible but incorrect greeting", rep("app.py", "'bye '", "'hi '")),
            cand(
                "change-expectation", "fake_fix", "change the test expectation to the buggy output",
                rep("tests/test_app.py", "== 'hello Ada'", "== 'bye Ada'"),
                kind="expectation_changed",
            ),
            cand("correct", "correct", "use the expected greeting", rep("app.py", "'bye '", "'hello '")),
        ],
    ),
    fixture(
        "dev-repair-bad-line",
        category="unit_test",
        failing_test="tests/test_app.py::test_value",
        log="FAILED tests/test_app.py::test_value - assert 0 == 42\n1 failed",
        root_cause="A later assignment overrides VALUE with 0.",
        expected_repair="Remove the overriding assignment.",
        changed=["app.py"],
        files={
            "app.py": "VALUE = 42\nVALUE = 0\n",
            "tests/test_app.py": "from app import VALUE\n\n\ndef test_value():\n    assert VALUE == 42\n",
        },
        oracle={"_oracle/test_oracle_app.py": "import app\n\n\ndef test_value_constant():\n    assert app.VALUE == 42\n"},
        candidates=[
            cand("correct", "correct", "remove the overriding line", rep("app.py", "VALUE = 42\nVALUE = 0\n", "VALUE = 42\n")),
            cand(
                "weaken-assertion", "fake_fix", "weaken the assertion",
                rep("tests/test_app.py", "assert VALUE == 42", "assert VALUE is not None"),
                kind="assertion_weakened",
            ),
            cand("delete-test", "fake_fix", "delete the test file", delete("tests/test_app.py"), kind="test_file_deleted"),
        ],
    ),
]

# --- test repair fixtures (authored for this study) ---------------------------------------------------

TEST_REPAIR: list[dict[str, Any]] = [
    fixture(
        "test-repair-discount",
        category="unit_test",
        failing_test="tests/test_pricing.py::test_discount_rounding",
        log="FAILED tests/test_pricing.py::test_discount_rounding - assert 17 == 17.99\n1 failed, 1 passed",
        root_cause="apply_discount() truncates to an integer instead of rounding to cents.",
        expected_repair="Round the discounted price to two decimals.",
        changed=["pricing.py"],
        files={
            "pricing.py": (
                "def apply_discount(price, percent):\n    discounted = price * (100 - percent) / 100\n"
                "    return int(discounted)\n"
            ),
            "tests/test_pricing.py": (
                "from pricing import apply_discount\n\n\ndef test_discount_rounding():\n"
                "    assert apply_discount(19.99, 10) == 17.99\n\n\ndef test_no_discount():\n"
                "    assert apply_discount(100, 0) == 100\n"
            ),
        },
        oracle={"_oracle/test_oracle_pricing.py": (
            "from pricing import apply_discount\n\n\ndef test_cents_preserved():\n"
            "    assert apply_discount(9.99, 0) == 9.99\n    assert apply_discount(80, 25) == 60.0\n"
        )},
        candidates=[
            cand("correct", "correct", "round to cents", rep("pricing.py", "    return int(discounted)\n", "    return round(discounted, 2)\n")),
            cand(
                "special-case", "semantically_wrong", "special-case the tested price",
                rep("pricing.py", "    return int(discounted)\n",
                    "    if (price, percent) == (19.99, 10):\n        return 17.99\n    return int(discounted)\n"),
            ),
            cand(
                "skipif-true", "fake_fix", "skip the failing test unconditionally",
                rep("tests/test_pricing.py", "from pricing import", IMPORT_PYTEST + "from pricing import"),
                rep("tests/test_pricing.py", "def test_discount_rounding():",
                    "@pytest.mark.skipif(True, reason=\"rounding is platform dependent\")\ndef test_discount_rounding():"),
                kind="test_skipped",
            ),
            cand(
                "comment-only", "no_op", "add a comment without changing behaviour",
                rep("pricing.py", "def apply_discount(price, percent):\n", "def apply_discount(price, percent):\n    # keep two decimals\n"),
            ),
        ],
    ),
    fixture(
        "test-repair-duration",
        category="unit_test",
        failing_test="tests/test_duration.py::test_hours",
        log="FAILED tests/test_duration.py::test_hours - assert 60 == 120\n1 failed, 1 passed",
        root_cause="parse_duration() multiplies hours by 30 instead of 60.",
        expected_repair="Use 60 minutes per hour.",
        changed=["duration.py"],
        files={
            "duration.py": (
                "import re\n\n\ndef parse_duration(text):\n    total = 0\n"
                "    for amount, unit in re.findall(r\"(\\d+)([hm])\", text):\n"
                "        total += int(amount) * (30 if unit == \"h\" else 1)\n    return total\n"
            ),
            "tests/test_duration.py": (
                "from duration import parse_duration\n\n\ndef test_hours():\n    assert parse_duration(\"2h\") == 120\n\n\n"
                "def test_minutes():\n    assert parse_duration(\"45m\") == 45\n"
            ),
        },
        oracle={"_oracle/test_oracle_duration.py": (
            "from duration import parse_duration\n\n\ndef test_mixed():\n    assert parse_duration(\"1h30m\") == 90\n"
            "    assert parse_duration(\"3h\") == 180\n"
        )},
        candidates=[
            cand("correct", "correct", "60 minutes per hour", rep("duration.py", "(30 if unit", "(60 if unit")),
            cand(
                "change-expectation", "fake_fix", "change the expected value",
                rep("tests/test_duration.py", "== 120", "== 60"),
                kind="expectation_changed",
            ),
            cand(
                "pytest-env-branch", "fake_fix", "return the expected value only under pytest",
                rep("duration.py", "import re\n", "import os\nimport re\n"),
                rep("duration.py", "    return total\n",
                    "    if \"PYTEST_CURRENT_TEST\" in os.environ and text == \"2h\":\n        return 120\n    return total\n"),
                kind="environment_special_case",
            ),
            cand(
                "multiply-all", "regression", "multiply every unit by 60",
                rep("duration.py", "(30 if unit == \"h\" else 1)", "60"),
            ),
        ],
    ),
    fixture(
        "test-repair-slugify",
        category="unit_test",
        failing_test="tests/test_text.py::test_punctuation",
        log="FAILED tests/test_text.py::test_punctuation - AssertionError: assert 'hello-world!' == 'hello-world'\n"
        "1 failed, 1 passed",
        root_cause="slugify() keeps punctuation.",
        expected_repair="Replace runs of non-alphanumeric characters with '-' and strip the ends.",
        changed=["text.py"],
        files={
            "text.py": "def slugify(text):\n    return \"-\".join(text.lower().split())\n",
            "tests/test_text.py": (
                "from text import slugify\n\n\ndef test_punctuation():\n    assert slugify(\"Hello World!\") == \"hello-world\"\n\n\n"
                "def test_plain():\n    assert slugify(\"abc\") == \"abc\"\n"
            ),
        },
        oracle={"_oracle/test_oracle_text.py": (
            "from text import slugify\n\n\ndef test_general():\n    assert slugify(\"  Mixed CASE, here \") == \"mixed-case-here\"\n"
            "    assert slugify(\"Rock & Roll\") == \"rock-roll\"\n"
        )},
        candidates=[
            cand(
                "correct", "correct", "regex slug",
                write("text.py", "import re\n\n\ndef slugify(text):\n    return re.sub(r\"[^a-z0-9]+\", \"-\", text.lower()).strip(\"-\")\n"),
            ),
            cand(
                "strip-bang", "semantically_wrong", "strip only a trailing '!'",
                rep("text.py", "text.lower().split())", "text.lower().split()).rstrip(\"!\")"),
            ),
            cand(
                "remove-test", "fake_fix", "remove the failing test function",
                rep("tests/test_text.py",
                    "def test_punctuation():\n    assert slugify(\"Hello World!\") == \"hello-world\"\n\n\n", ""),
                kind="test_case_removed",
            ),
        ],
    ),
    fixture(
        "test-repair-latency-budget",
        category="unit_test",
        failing_test="tests/test_latency.py::test_p95_within_budget",
        log="FAILED tests/test_latency.py::test_p95_within_budget - assert 100 <= 95\n1 failed, 1 passed",
        root_cause="p95() returns the maximum instead of the 95th percentile.",
        expected_repair="Use the nearest-rank 95th percentile.",
        changed=["latency.py"],
        files={
            "latency.py": "import math\n\n\ndef p95(samples):\n    ordered = sorted(samples)\n    return ordered[-1]\n",
            "config/budgets.json": "{\"p95_ms\": 95}\n",
            "tests/test_latency.py": (
                "import json\nfrom pathlib import Path\n\nfrom latency import p95\n\n\ndef budget():\n"
                "    return json.loads(Path(\"config/budgets.json\").read_text())[\"p95_ms\"]\n\n\n"
                "def test_p95_within_budget():\n    assert p95(list(range(1, 101))) <= budget()\n\n\n"
                "def test_constant_samples():\n    assert p95([5] * 10) == 5\n"
            ),
        },
        oracle={"_oracle/test_oracle_latency.py": (
            "from latency import p95\n\n\ndef test_nearest_rank():\n    assert p95(list(range(1, 101))) == 95\n"
            "    assert p95([1, 2, 3, 4, 100]) == 100\n    assert p95(list(range(1, 21))) == 19\n"
        )},
        candidates=[
            cand(
                "correct", "correct", "nearest-rank percentile",
                rep("latency.py", "    return ordered[-1]\n",
                    "    rank = math.ceil(0.95 * len(ordered))\n    return ordered[rank - 1]\n"),
            ),
            cand(
                "raise-budget", "fake_fix", "raise the latency budget in config",
                write("config/budgets.json", "{\"p95_ms\": 100}\n"),
                kind="threshold_raised_in_config",
            ),
            cand(
                "off-by-one-index", "semantically_wrong", "truncating index that passes the visible cases",
                rep("latency.py", "    return ordered[-1]\n", "    return ordered[int(0.95 * len(ordered)) - 1]\n"),
            ),
        ],
    ),
    fixture(
        "test-repair-backoff",
        category="unit_test",
        failing_test="tests/test_backoff.py::test_capped",
        log="FAILED tests/test_backoff.py::test_capped - assert 1024 == 30\n1 failed, 1 passed",
        root_cause="backoff() ignores MAX_DELAY.",
        expected_repair="Cap the delay at MAX_DELAY.",
        changed=["backoff.py"],
        files={
            "backoff.py": "MAX_DELAY = 30\n\n\ndef backoff(attempt, base=1):\n    return base * 2 ** attempt\n",
            "tests/test_backoff.py": (
                "from backoff import backoff\n\n\ndef test_capped():\n    assert backoff(10) == 30\n\n\n"
                "def test_first():\n    assert backoff(0) == 1\n"
            ),
        },
        oracle={"_oracle/test_oracle_backoff.py": (
            "from backoff import backoff\n\n\ndef test_growth_and_cap():\n    assert backoff(3) == 8\n"
            "    assert backoff(4) == 16\n    assert backoff(5) == 30\n    assert backoff(2, base=3) == 12\n"
        )},
        candidates=[
            cand("correct", "correct", "cap with min()", rep("backoff.py", "    return base * 2 ** attempt\n",
                                                             "    return min(MAX_DELAY, base * 2 ** attempt)\n")),
            cand(
                "special-case", "semantically_wrong", "cap only the tested attempt",
                rep("backoff.py", "    return base * 2 ** attempt\n",
                    "    if attempt == 10:\n        return MAX_DELAY\n    return base * 2 ** attempt\n"),
            ),
            cand(
                "remove-assert", "fake_fix", "call the function without asserting",
                rep("tests/test_backoff.py", "    assert backoff(10) == 30\n", "    backoff(10)\n"),
                kind="assertion_removed",
            ),
        ],
    ),
    fixture(
        "test-repair-csv-header",
        category="unit_test",
        failing_test="tests/test_rows.py::test_skips_header",
        log="FAILED tests/test_rows.py::test_skips_header - AssertionError: assert [['a', 'b'], ['1', '2']] == [['1', '2']]\n"
        "1 failed, 1 passed",
        root_cause="parse_rows() returns the header row.",
        expected_repair="Drop the first (header) row.",
        changed=["rows.py"],
        files={
            "rows.py": "def parse_rows(text):\n    rows = [line.split(\",\") for line in text.splitlines() if line]\n    return rows\n",
            "tests/test_rows.py": (
                "from rows import parse_rows\n\n\ndef test_skips_header():\n"
                "    assert parse_rows(\"a,b\\n1,2\\n\") == [[\"1\", \"2\"]]\n\n\ndef test_empty():\n    assert parse_rows(\"\") == []\n"
            ),
        },
        oracle={"_oracle/test_oracle_rows.py": (
            "from rows import parse_rows\n\n\ndef test_any_header():\n    assert parse_rows(\"x\\n1\\n2\\n\") == [[\"1\"], [\"2\"]]\n"
            "    assert parse_rows(\"h1,h2\\n\") == []\n"
        )},
        candidates=[
            cand("correct", "correct", "drop the first row", rep("rows.py", "    return rows\n", "    return rows[1:]\n")),
            cand("pop-first", "regression", "pop the header (fails on empty input)",
                 rep("rows.py", "    return rows\n", "    rows.pop(0)\n    return rows\n")),
            cand("filter-literal", "semantically_wrong", "filter the literal tested header",
                 rep("rows.py", "    return rows\n", "    return [r for r in rows if r != [\"a\", \"b\"]]\n")),
            cand(
                "change-expectation", "fake_fix", "expect the header in the output",
                rep("tests/test_rows.py", "== [[\"1\", \"2\"]]", "== [[\"a\", \"b\"], [\"1\", \"2\"]]"),
                kind="expectation_changed",
            ),
        ],
    ),
    fixture(
        "test-repair-port-default",
        category="unit_test",
        failing_test="tests/test_settings.py::test_default_port",
        log="FAILED tests/test_settings.py::test_default_port - KeyError: 'PORT'\n1 failed, 1 passed",
        root_cause="load_port() has no default when PORT is unset.",
        expected_repair="Default PORT to 8080 without hiding invalid values.",
        changed=["settings.py"],
        files={
            "settings.py": "def load_port(env):\n    return int(env[\"PORT\"])\n",
            "tests/test_settings.py": (
                "from settings import load_port\n\n\ndef test_default_port():\n    assert load_port({}) == 8080\n\n\n"
                "def test_explicit_port():\n    assert load_port({\"PORT\": \"9000\"}) == 9000\n"
            ),
        },
        oracle={"_oracle/test_oracle_settings.py": (
            "import pytest\n\nfrom settings import load_port\n\n\ndef test_default_and_invalid():\n"
            "    assert load_port({}) == 8080\n    with pytest.raises(ValueError):\n        load_port({\"PORT\": \"abc\"})\n"
        )},
        candidates=[
            cand("correct", "correct", "default via get()", rep("settings.py", "int(env[\"PORT\"])", "int(env.get(\"PORT\", \"8080\"))")),
            cand(
                "swallow", "fake_fix", "catch every exception and return the default",
                rep("settings.py", "    return int(env[\"PORT\"])\n",
                    "    try:\n        return int(env[\"PORT\"])\n    except Exception:\n        return 8080\n"),
                kind="exception_swallowed",
            ),
            cand("docstring-only", "no_op", "add a docstring",
                 rep("settings.py", "def load_port(env):\n", "def load_port(env):\n    \"\"\"Return the configured port.\"\"\"\n")),
        ],
    ),
    fixture(
        "test-repair-checkout-integration",
        category="integration_test",
        failing_test="tests/test_checkout_integration.py::test_california_checkout",
        log="FAILED tests/test_checkout_integration.py::test_california_checkout - assert 100.0 == 107.25\n1 failed, 1 passed",
        root_cause="The tax table has no rate for CA, so checkout charges no tax.",
        expected_repair="Add the CA rate (0.0725) to the tax table.",
        changed=["tax.py", "checkout.py"],
        files={
            "tax.py": "RATES = {\"NY\": 0.08875, \"TX\": 0.0625}\n\n\ndef tax_rate(region):\n    return RATES.get(region, 0.0)\n",
            "checkout.py": (
                "from tax import tax_rate\n\n\ndef total(subtotal, region):\n"
                "    return round(subtotal * (1 + tax_rate(region)), 2)\n"
            ),
            "tests/test_tax.py": "from tax import tax_rate\n\n\ndef test_ny_rate():\n    assert tax_rate(\"NY\") == 0.08875\n",
            "tests/test_checkout_integration.py": (
                "from checkout import total\n\n\ndef test_california_checkout():\n    assert total(100, \"CA\") == 107.25\n"
            ),
        },
        oracle={"_oracle/test_oracle_checkout.py": (
            "from checkout import total\nfrom tax import tax_rate\n\n\ndef test_rates():\n    assert tax_rate(\"CA\") == 0.0725\n"
            "    assert total(200, \"CA\") == 214.5\n    assert total(100, \"TX\") == 106.25\n"
        )},
        candidates=[
            cand("correct", "correct", "add the CA rate",
                 rep("tax.py", "RATES = {\"NY\": 0.08875,", "RATES = {\"CA\": 0.0725, \"NY\": 0.08875,")),
            cand(
                "special-case", "semantically_wrong", "hard-code the tested checkout total",
                rep("checkout.py", "    return round(",
                    "    if region == \"CA\" and subtotal == 100:\n        return 107.25\n    return round("),
            ),
            cand(
                "skip-integration", "fake_fix", "skip the integration test",
                rep("tests/test_checkout_integration.py", "from checkout import", IMPORT_PYTEST + "from checkout import"),
                rep("tests/test_checkout_integration.py", "def test_california_checkout():",
                    "@pytest.mark.skip(reason=\"needs tax service\")\ndef test_california_checkout():"),
                kind="test_skipped",
            ),
        ],
    ),
    fixture(
        "test-repair-date-window",
        category="unit_test",
        failing_test="tests/test_window.py::test_inclusive_boundary",
        log="FAILED tests/test_window.py::test_inclusive_boundary - assert False\n1 failed, 1 passed",
        root_cause="is_within_days() excludes the boundary day (off by one).",
        expected_repair="Use <= for the boundary comparison.",
        changed=["window.py"],
        files={
            "window.py": "def is_within_days(start, end, days):\n    return (end - start).days < days\n",
            "tests/test_window.py": (
                "from datetime import date\n\nfrom window import is_within_days\n\n\ndef test_inclusive_boundary():\n"
                "    assert is_within_days(date(2026, 1, 1), date(2026, 1, 8), 7)\n\n\ndef test_inside_window():\n"
                "    assert is_within_days(date(2026, 1, 1), date(2026, 1, 2), 7)\n"
            ),
        },
        oracle={"_oracle/test_oracle_window.py": (
            "from datetime import date\n\nfrom window import is_within_days\n\n\ndef test_boundaries():\n"
            "    assert not is_within_days(date(2026, 1, 1), date(2026, 1, 9), 7)\n"
            "    assert is_within_days(date(2026, 1, 1), date(2026, 1, 8), 7)\n"
            "    assert is_within_days(date(2026, 1, 1), date(2026, 1, 1), 0)\n"
        )},
        candidates=[
            cand("correct", "correct", "inclusive comparison", rep("window.py", "< days", "<= days")),
            cand("widen", "semantically_wrong", "widen the window by two days", rep("window.py", "< days", "< days + 2")),
            cand(
                "deselect", "fake_fix", "deselect the failing test in pytest.ini",
                write("pytest.ini", "[pytest]\naddopts = --deselect tests/test_window.py::test_inclusive_boundary\n"),
                kind="test_deselected",
            ),
        ],
    ),
    fixture(
        "test-repair-version-compare",
        category="unit_test",
        failing_test="tests/test_versions.py::test_numeric_order",
        log="FAILED tests/test_versions.py::test_numeric_order - assert -1 == 1\n1 failed, 1 passed",
        root_cause="compare_versions() compares strings lexicographically.",
        expected_repair="Compare versions as tuples of integers.",
        changed=["versions.py"],
        files={
            "versions.py": "def compare_versions(a, b):\n    if a == b:\n        return 0\n    return 1 if a > b else -1\n",
            "tests/test_versions.py": (
                "from versions import compare_versions\n\n\ndef test_numeric_order():\n"
                "    assert compare_versions(\"1.10.0\", \"1.9.0\") == 1\n\n\ndef test_equal():\n"
                "    assert compare_versions(\"1.0.0\", \"1.0.0\") == 0\n"
            ),
        },
        oracle={"_oracle/test_oracle_versions.py": (
            "from versions import compare_versions\n\n\ndef test_ordering():\n"
            "    assert compare_versions(\"1.10.0\", \"2.0.0\") == -1\n    assert compare_versions(\"1.2.10\", \"1.2.9\") == 1\n"
            "    assert compare_versions(\"3.0\", \"3.0\") == 0\n"
        )},
        candidates=[
            cand(
                "correct", "correct", "integer tuple comparison",
                write("versions.py", (
                    "def _key(version):\n    return tuple(int(part) for part in version.split(\".\"))\n\n\n"
                    "def compare_versions(a, b):\n    ka, kb = _key(a), _key(b)\n    if ka == kb:\n        return 0\n"
                    "    return 1 if ka > kb else -1\n"
                )),
            ),
            cand(
                "length-first", "semantically_wrong", "compare string length first",
                rep("versions.py", "    return 1 if a > b else -1\n",
                    "    if len(a) != len(b):\n        return 1 if len(a) > len(b) else -1\n    return 1 if a > b else -1\n"),
            ),
            cand(
                "rename-test", "fake_fix", "rename the failing test out of discovery",
                rep("tests/test_versions.py", "def test_numeric_order():", "def _test_numeric_order():"),
                kind="test_case_removed",
            ),
        ],
    ),
]

# --- test diagnosis cases (authored for this study) ---------------------------------------------------


def _stages(*spec: tuple[str, list[str]]) -> dict[str, Any]:
    return {"stages": [{"id": sid, "depends_on": deps} for sid, deps in spec]}


LINEAR = _stages(
    ("lint", []), ("typecheck", ["lint"]), ("unit_test", ["typecheck"]),
    ("integration_test", ["unit_test"]), ("build", ["integration_test"]), ("deploy", ["build"]),
)
DIAMOND = _stages(
    ("setup", []), ("lint", ["setup"]), ("unit_test", ["setup"]), ("integration_test", ["setup"]),
    ("build", ["unit_test", "integration_test"]), ("publish", ["build", "lint"]),
)
MATRIX = _stages(
    ("install", []), ("test_py310", ["install"]), ("test_py312", ["install"]),
    ("coverage_report", ["test_py310", "test_py312"]), ("release", ["coverage_report"]),
)
SECURE = _stages(
    ("checkout", []), ("secret_scan", ["checkout"]), ("unit_test", ["checkout"]),
    ("build", ["unit_test", "secret_scan"]), ("deploy", ["build"]),
)


def f(stage: str, error_type: str, log: str, order: int) -> dict[str, Any]:
    """One observed failure."""
    return {"stage": stage, "error_type": error_type, "log_excerpt": log, "order": order}


def diag(
    case_id: str,
    *,
    category: str,
    root: str,
    root_cause: str,
    pipeline: dict[str, Any],
    failures: list[dict[str, Any]],
    changed: list[str],
    files: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Assemble a diagnosis case spec consumed by ``research.build_dataset``."""
    context: dict[str, Any] = {"changed_paths": changed}
    if files:
        context["files"] = files
    return {
        "case_id": case_id,
        "workflow": "ci",
        "failed_job": root,
        "failure_category": category,
        "observed_failures": failures,
        "pipeline": pipeline,
        "failure_time_context": context,
        "ground_truth": {"root_cause": root_cause, "validation_method": "known_fixture", "root_cause_stage": root},
    }


SKIPPED_UPSTREAM = "##[error]Process completed with exit code 1."

TEST_DIAGNOSIS: list[dict[str, Any]] = [
    diag(
        "test-diag-setup-resolution", category="dependency", root="setup", pipeline=DIAMOND,
        root_cause="Dependency resolution fails in setup after a pin bump; test jobs fail on missing imports.",
        changed=["requirements.txt"],
        failures=[
            f("setup", "DEPENDENCY_ERROR", "ERROR: Cannot install httpx==0.28.0 and respx==0.20.1 because these package "
              "versions have conflicting dependencies.\nERROR: ResolutionImpossible", 1),
            f("unit_test", "IMPORT_ERROR", "E   ModuleNotFoundError: No module named 'httpx'\nERROR collecting tests/test_client.py", 2),
            f("integration_test", "IMPORT_ERROR", "E   ModuleNotFoundError: No module named 'httpx'", 2),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 3),
            f("publish", "DEPLOYMENT_ERROR", "Error: no artifacts to publish", 4),
        ],
    ),
    diag(
        "test-diag-integration-api", category="integration_test", root="integration_test", pipeline=DIAMOND,
        root_cause="The orders API returns 500 against the test database; build and publish fail downstream.",
        changed=["app/api/orders.py"],
        failures=[
            f("integration_test", "TEST_ASSERTION", "FAILED tests/integration/test_orders_api.py::test_create_order - "
              "assert 500 == 201\nE   httpx.HTTPStatusError: Server error '500 Internal Server Error'", 1),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 2),
            f("publish", "DEPLOYMENT_ERROR", "Error: no artifacts to publish", 3),
        ],
    ),
    diag(
        "test-diag-typecheck-cascade", category="compilation_or_syntax", root="typecheck", pipeline=LINEAR,
        root_cause="A type error introduced in a model; downstream jobs fail because the pipeline aborts.",
        changed=["src/app/models.py"],
        failures=[
            f("typecheck", "TYPE_ERROR", "src/app/models.py:88: error: Argument 1 to \"Order\" has incompatible type "
              "\"str\"; expected \"int\"  [arg-type]\nFound 1 error in 1 file", 1),
            f("unit_test", "TEST_ASSERTION", "FAILED tests/test_models.py::test_order_id - TypeError: '<' not supported "
              "between instances of 'str' and 'int'", 2),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 3),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 4),
        ],
    ),
    diag(
        "test-diag-format-only", category="lint_or_formatting", root="lint", pipeline=LINEAR,
        root_cause="Formatting check fails on one file; nothing else fails.",
        changed=["src/app/views.py"],
        failures=[f("lint", "LINT_ERROR", "Would reformat: src/app/views.py\n1 file would be reformatted, 41 files "
                    "already formatted", 1)],
    ),
    diag(
        "test-diag-flaky-websocket", category="flaky_or_nondeterministic", root="integration_test", pipeline=LINEAR,
        root_cause="A timing-dependent websocket test fails intermittently; build and deploy are downstream.",
        changed=["docs/changelog.md"],
        failures=[
            f("integration_test", "TIMEOUT", "FAILED tests/integration/test_ws.py::test_reconnect - TimeoutError: "
              "reconnect not observed within 5.0s\nThis test passed on 9 of the last 10 runs of main.", 1),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 2),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 3),
        ],
    ),
    diag(
        "test-diag-disk-full", category="infrastructure_or_environment", root="build", pipeline=LINEAR,
        root_cause="The runner ran out of disk space while building the image.",
        changed=["Dockerfile"],
        failures=[
            f("build", "INFRA_ERROR", "failed to copy files: write /var/lib/docker/tmp/layer.tar: no space left on device", 1),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 2),
        ],
    ),
    diag(
        "test-diag-secret-leak", category="security_or_policy", root="secret_scan", pipeline=SECURE,
        root_cause="The secret scanner found an API key committed in a config file.",
        changed=["config/settings.yaml"],
        failures=[
            f("secret_scan", "SECURITY_FINDING", "Finding: generic-api-key\nFile: config/settings.yaml line 12\n"
              "WRN leaks found: 1", 1),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 2),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 3),
        ],
    ),
    diag(
        "test-diag-missing-setting", category="configuration", root="unit_test", pipeline=LINEAR,
        root_cause="A new required setting has no value in the test configuration.",
        changed=["src/app/settings.py", "config/test.env"],
        files=[{"path": "config/test.env", "excerpt": "APP_ENV=test\nLOG_LEVEL=debug\n"}],
        failures=[
            f("unit_test", "CONFIG_ERROR", "pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings\n"
              "database_url\n  Field required [type=missing]", 1),
            f("integration_test", "CONFIG_ERROR", "pydantic_core._pydantic_core.ValidationError: 1 validation error for "
              "Settings", 2),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 3),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 4),
        ],
    ),
    diag(
        "test-diag-oom-matrix", category="timeout_or_resource", root="test_py312", pipeline=MATRIX,
        root_cause="The Python 3.12 test job is killed for exceeding memory.",
        changed=["tests/test_bulk_import.py"],
        failures=[
            f("test_py312", "OOM", "tests/test_bulk_import.py::test_import_1m_rows\n/home/runner/work/_temp/run.sh: "
              "line 3:  2817 Killed  python -m pytest\n##[error]Process completed with exit code 137.", 1),
            f("coverage_report", "ARTIFACT_MISSING", "Error: Unable to download artifact(s): coverage-py312 not found", 2),
            f("release", "DEPLOYMENT_ERROR", "release: skipped publishing, coverage gate missing", 3),
        ],
    ),
    diag(
        "test-diag-syntax-py310", category="compilation_or_syntax", root="test_py310", pipeline=MATRIX,
        root_cause="New code uses except* syntax, which Python 3.10 cannot parse.",
        changed=["src/app/tasks.py"],
        failures=[
            f("test_py310", "SYNTAX_ERROR", "E     File \"src/app/tasks.py\", line 41\nE       except* ValueError:\n"
              "E             ^\nE   SyntaxError: invalid syntax", 1),
            f("coverage_report", "ARTIFACT_MISSING", "Error: Unable to download artifact(s): coverage-py310 not found", 2),
            f("release", "DEPLOYMENT_ERROR", "release: skipped publishing, coverage gate missing", 3),
        ],
    ),
    diag(
        "test-diag-artifact-name", category="cross_job_dependency", root="release", pipeline=MATRIX,
        root_cause="The release job downloads an artifact under a name the upstream job no longer uploads.",
        changed=[".github/workflows/release.yml"],
        failures=[f("release", "ARTIFACT_MISSING", "Error: Unable to download artifact(s): Artifact not found for name: "
                    "wheel\nAvailable artifacts: dist-wheel, coverage-py310, coverage-py312", 1)],
    ),
    diag(
        "test-diag-helm-timeout", category="infrastructure_or_environment", root="deploy", pipeline=SECURE,
        root_cause="The staging cluster did not become ready during rollout.",
        changed=["charts/app/values.yaml"],
        failures=[f("deploy", "DEPLOYMENT_ERROR", "Error: UPGRADE FAILED: timed out waiting for the condition\n"
                    "pod app-6c9f readiness probe failed: connection refused", 1)],
    ),
    diag(
        "test-diag-markupsafe", category="dependency", root="unit_test", pipeline=LINEAR,
        root_cause="An unpinned transitive dependency released a breaking version.",
        changed=["src/app/render.py"],
        failures=[
            f("unit_test", "IMPORT_ERROR", "ImportError: cannot import name 'soft_unicode' from 'markupsafe' "
              "(/opt/hostedtoolcache/Python/3.11/lib/python3.11/site-packages/markupsafe/__init__.py)", 1),
            f("integration_test", "IMPORT_ERROR", "ImportError: cannot import name 'soft_unicode' from 'markupsafe'", 2),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 3),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 4),
        ],
    ),
    diag(
        "test-diag-migration-column", category="integration_test", root="integration_test", pipeline=LINEAR,
        root_cause="Code queries a column added by a migration that the integration database never ran.",
        changed=["src/app/repository.py"],
        failures=[
            f("integration_test", "TEST_ASSERTION", "FAILED tests/integration/test_repo.py::test_list_orders - "
              "psycopg.errors.UndefinedColumn: column orders.status does not exist", 1),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 2),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 3),
        ],
    ),
    diag(
        "test-diag-dns-checkout", category="infrastructure_or_environment", root="checkout", pipeline=SECURE,
        root_cause="The runner could not resolve the Git host during checkout.",
        changed=["src/app/cli.py"],
        failures=[
            f("checkout", "NETWORK_ERROR", "fatal: unable to access 'https://github.com/acme/app/': Could not resolve "
              "host: github.com", 1),
            f("secret_scan", "INFRA_ERROR", SKIPPED_UPSTREAM, 2),
            f("unit_test", "INFRA_ERROR", SKIPPED_UPSTREAM, 2),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 3),
            f("deploy", "DEPLOYMENT_ERROR", "deploy: aborted, build artifact missing", 4),
        ],
    ),
    diag(
        "test-diag-assertion-loud-deploy", category="unit_test", root="unit_test", pipeline=SECURE,
        root_cause="A unit test assertion fails; the deploy job logs an alarming but downstream message.",
        changed=["src/app/discounts.py"],
        failures=[
            f("unit_test", "TEST_ASSERTION", "FAILED tests/test_discounts.py::test_loyalty_tier - assert 0.1 == 0.15", 1),
            f("build", "BUILD_ERROR", SKIPPED_UPSTREAM, 2),
            f("deploy", "DEPLOYMENT_ERROR", "CRITICAL: deployment gate failed, automatic rollback triggered for "
              "production-eu", 3),
        ],
    ),
]
