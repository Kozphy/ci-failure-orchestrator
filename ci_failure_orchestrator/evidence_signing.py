from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from typing import Any

from .production_evidence import ProductionEvidence


@dataclass(frozen=True)
class SignedEvidence:
    algorithm: str
    key_id: str
    payload: dict[str, Any]
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sign_evidence(
    evidence: ProductionEvidence,
    *,
    secret: bytes,
    key_id: str = "local-hmac",
) -> SignedEvidence:
    if not secret:
        raise ValueError("secret must not be empty")
    payload = evidence.to_dict()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret, encoded, hashlib.sha256).hexdigest()
    return SignedEvidence(
        algorithm="HMAC-SHA256",
        key_id=key_id,
        payload=payload,
        signature=signature,
    )


def verify_evidence(envelope: SignedEvidence, *, secret: bytes) -> bool:
    encoded = json.dumps(
        envelope.payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected = hmac.new(secret, encoded, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, envelope.signature)
