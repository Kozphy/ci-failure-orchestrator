"""Deterministic risk score for a repair diff.

The score decides how much human involvement a verified repair still needs: LOW may be
marked verified without a person, MEDIUM needs human approval before merge, HIGH needs a
human review before it can be called verified at all. Paths and a few added-line markers
are matched by whole word, so ``tokenizer.py`` is not mistaken for an authentication file.
Areas where a wrong-but-green change does the most damage (authentication, authorization,
payments, migrations, secrets) force HIGH regardless of the score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .verification_integrity import is_ci_path, is_test_path, parse_unified_diff

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
_LEVEL_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2}

MEDIUM_THRESHOLD = 20
HIGH_THRESHOLD = 50

_AUTHN = frozenset({
    "auth", "authn", "authentication", "authenticate", "login", "logout", "session", "sessions",
    "oauth", "oauth2", "jwt", "password", "passwords", "credential", "sso", "saml", "oidc",
})
_AUTHZ = frozenset({
    "authz", "authorization", "authorize", "permission", "permissions", "rbac", "acl", "acls",
    "role", "roles", "privilege", "privileges",
})
_PAYMENTS = frozenset({
    "payment", "payments", "billing", "invoice", "invoices", "charge", "charges", "refund",
    "refunds", "ledger", "checkout", "stripe", "paypal", "wallet",
})
_MIGRATION = frozenset({"migration", "migrations", "alembic", "migrate", "flyway", "liquibase"})
_SECRETS = frozenset({"secret", "secrets", "credentials", "vault", "keystore"})
_INFRA_DIRS = frozenset({
    "terraform", "k8s", "kubernetes", "helm", "infra", "infrastructure", "deploy", "deployment",
    "ansible", "pulumi", "cloudformation",
})
_DEPENDENCY_FILES = frozenset({
    "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "pipfile.lock",
    "poetry.lock", "uv.lock", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "gemfile", "gemfile.lock", "pom.xml",
    "build.gradle", "build.gradle.kts",
})
_AUTH_CODE_MARKERS = re.compile(
    r"\b(login_required|is_authenticated|has_perm(ission)?s?|is_admin|is_superuser|check_password|"
    r"verify_token|verify_password|require_role|permission_classes|authorize|jwt\.decode)\b"
)
_TOKEN_SPLIT = re.compile(r"[/_.\-\s]+")


@dataclass(frozen=True)
class DiffRisk:
    score: int
    risk_level: str
    reasons: tuple[str, ...]
    factors: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_score": self.score,
            "risk_level": self.risk_level,
            "reasons": list(self.reasons),
            "factors": dict(self.factors),
        }


def max_level(*levels: str | None) -> str:
    known = [lvl for lvl in levels if lvl in _LEVEL_ORDER]
    return max(known, key=_LEVEL_ORDER.__getitem__) if known else HIGH


def _tokens(path: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT.split(path.lower()) if t}


def _is_prose(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    return p.endswith((".md", ".rst", ".txt", ".adoc")) or p.startswith("docs/")


def _is_dependency(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in _DEPENDENCY_FILES or (name.startswith("requirements") and name.endswith((".txt", ".in")))


def _is_secret_config(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.startswith(".env") or bool(_tokens(path) & _SECRETS) or name.endswith((".pem", ".key"))


def _is_infra(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    return (
        name.endswith((".tf", ".tfvars"))
        or name == "dockerfile"
        or name.startswith(("docker-compose", "compose."))
        or bool(set(p.split("/")[:-1]) & _INFRA_DIRS)
    )


def score_diff_risk(patch: str) -> DiffRisk:
    files = [f for f in parse_unified_diff(patch) if f.path]
    lines_changed = sum(len(f.added) + len(f.removed) for f in files)
    score = 0
    reasons: list[str] = []
    forced_high: list[str] = []
    factors: dict[str, Any] = {"files_changed": len(files), "lines_changed": lines_changed}

    def add(points: int, reason: str, *, force: bool = False) -> None:
        nonlocal score
        score += points
        reasons.append(reason)
        if force:
            forced_high.append(reason)

    if len(files) > 10:
        add(20, f"{len(files)} files changed")
    elif len(files) > 3:
        add(10, f"{len(files)} files changed")
    if lines_changed > 200:
        add(20, f"{lines_changed} lines changed")
    elif lines_changed > 50:
        add(10, f"{lines_changed} lines changed")

    def matching(pred) -> list[str]:
        return sorted({f.path for f in files if pred(f)})

    checks = (
        ("tests_modified", 10, lambda f: is_test_path(f.path) and bool(f.removed), "existing tests modified", False),
        ("ci_config", 25, lambda f: is_ci_path(f.path), "CI configuration changed", False),
        ("dependencies", 20, lambda f: _is_dependency(f.path), "dependencies changed", False),
        ("authentication", 40, lambda f: not is_test_path(f.path) and bool(_tokens(f.path) & _AUTHN),
         "authentication code changed", True),
        ("authorization", 40, lambda f: not is_test_path(f.path) and (
            bool(_tokens(f.path) & _AUTHZ) or any(_AUTH_CODE_MARKERS.search(ln) for ln in f.added + f.removed)
        ), "authorization code changed", True),
        ("payments", 30, lambda f: not is_test_path(f.path) and bool(_tokens(f.path) & _PAYMENTS),
         "payment code changed", True),
        ("migration", 30, lambda f: bool(_tokens(f.path) & _MIGRATION) or f.path.lower().endswith(".sql"),
         "database migration changed", True),
        ("secrets_config", 30, lambda f: _is_secret_config(f.path), "secrets or credential configuration changed",
         True),
        ("infrastructure", 25, lambda f: _is_infra(f.path), "infrastructure changed", False),
    )
    for key, points, pred, reason, force in checks:
        hits = matching(pred)
        factors[key] = hits
        if hits:
            add(points, f"{reason}: {', '.join(hits[:3])}", force=force)

    production = matching(lambda f: not is_test_path(f.path) and not _is_prose(f.path))
    factors["production_files"] = production
    if production:
        add(5, "production code changed")

    if forced_high or score >= HIGH_THRESHOLD:
        level = HIGH
    elif score >= MEDIUM_THRESHOLD:
        level = MEDIUM
    else:
        level = LOW
    return DiffRisk(score=score, risk_level=level, reasons=tuple(reasons), factors=factors)
