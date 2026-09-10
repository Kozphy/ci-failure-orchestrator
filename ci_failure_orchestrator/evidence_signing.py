from __future__ import annotations

"""HMAC-based evidence signing for CI repair platform.

This module provides cryptographic signing and verification of
ProductionEvidence artifacts using HMAC-SHA256. It enables
producers to sign evidence with a secret key and consumers to
verify the signature before accepting the evidence.

Module responsibility:
    - Sign ProductionEvidence with HMAC-SHA256
    - Verify signed evidence signatures
    - Provide tamper-evident envelope structure

Key invariants:
    - SignedEvidence is immutable (frozen dataclass)
    - Signature is computed from canonical JSON representation
    - Empty secret raises ValueError
    - Verification uses constant-time comparison (hmac.compare_digest)

Safety boundaries:
    - Secret must not be empty
    - Signature verification is timing-safe to prevent attacks
    - Canonical JSON uses sorted keys and compact separators

Audit Notes:
    - sign_evidence() and verify_evidence() use the same canonical serialization
    - key_id allows multiple keys to be used with the same verification code
    - algorithm is hardcoded to HMAC-SHA256 for consistency
"""

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
from typing import Any

from .production_evidence import ProductionEvidence


@dataclass(frozen=True)
class SignedEvidence:
    """Signed evidence envelope with algorithm, key_id, payload, and signature.

    Represents a cryptographically signed evidence artifact that can be
    verified by any party with access to the signing secret.

    Attributes:
        algorithm: Cryptographic algorithm used (always "HMAC-SHA256")
        key_id: Identifier for the key used for signing
        payload: The signed evidence payload as a dictionary
        signature: HMAC-SHA256 hex digest of the canonical payload
    """

    algorithm: str
    key_id: str
    payload: dict[str, Any]
    signature: str

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable dictionary representation.

        Returns:
            Dictionary with all envelope fields
        """
        return asdict(self)


def sign_evidence(
    evidence: ProductionEvidence,
    *,
    secret: bytes,
    key_id: str = "local-hmac",
) -> SignedEvidence:
    """Sign ProductionEvidence with HMAC-SHA256.

    Creates a SignedEvidence envelope containing the evidence payload
    and a cryptographic signature. The signature is computed from the
    canonical JSON representation of the payload.

    Args:
        evidence: ProductionEvidence to sign
        secret: Signing key as bytes (must not be empty)
        key_id: Identifier for the signing key

    Returns:
        SignedEvidence envelope with payload and signature

    Raises:
        ValueError: If secret is empty

    Side effects:
        None.

    Audit Notes:
        - Canonical JSON uses sorted keys and compact separators
        - Same serialization must be used for verification
        - key_id allows multiple keys to be distinguished
    """
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
    """Verify a signed evidence envelope.

    Recomputes the signature from the payload using the provided secret
    and compares it to the envelope's signature using constant-time
    comparison to prevent timing attacks.

    Args:
        envelope: SignedEvidence to verify
        secret: Signing key as bytes (must match the key used to sign)

    Returns:
        True if signature is valid, False otherwise

    Side effects:
        None.

    Audit Notes:
        - Uses hmac.compare_digest() for timing-safe comparison
        - Must use same canonical JSON serialization as sign_evidence()
        - Returns False for any mismatch (invalid secret, tampered payload, etc.)
    """
    encoded = json.dumps(
        envelope.payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    expected = hmac.new(secret, encoded, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, envelope.signature)
