"""HMAC-SHA256 pseudonymisation of configured identifier fields.

Keys are organisation-scoped and versioned. The same identifier and key
produce the same pseudonym; rotation changes the pseudonym. Retired keys
support replay through pseudonymize_with_version.

No plaintext-to-pseudonym mapping is stored by this module; an organisation
that must recover identifiers (for a GDPR Art. 15 request, say) keeps that
mapping in its own register, off the ledger. Only exact field names in
sensitive_fields are transformed. Other fields and text remain unchanged, so
correlation and identification may remain possible.

A keyed hash is one of the measures EDPB Guidelines 02/2025 (v2.0) list for
blockchain processing; they name no algorithm. HMAC-SHA256 is an engineering
choice, available in the Python standard library.

The returned pseudonym object carries key_version. The Oracle selects
a fixed record body that does not retain this metadata independently."""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable

DEFAULT_SENSITIVE_FIELDS: tuple[str, ...] = (
    "subject_id",
    "user_id",
    "data_subject",
    "patient_id",
    "applicant_id",
    "customer_id",
)


@dataclass(frozen=True)
class PseudonymizationKey:
    """A versioned, organisation-scoped HMAC key."""

    org_id: str
    key_version: int
    secret: bytes
    created_at: str

    def fingerprint(self) -> str:
        """SHA-256 of the public key version metadata. Safe to log."""

        meta = f"{self.org_id}|{self.key_version}|{self.created_at}".encode("utf-8")
        return sha256(meta).hexdigest()


class Pseudonymizer:
    """HMAC-SHA256 pseudonymizer with persistent per-organisation keys."""

    def __init__(
        self,
        org_id: str = "compliance-oracle-org",
        keys_dir: Path | None = None,
        sensitive_fields: Iterable[str] = DEFAULT_SENSITIVE_FIELDS,
    ) -> None:
        self.org_id = org_id
        self.keys_dir = keys_dir or Path(__file__).parent / "keys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        self.sensitive_fields = tuple(sensitive_fields)
        self._key = self._load_or_create_key()

    # ------------------------------------------------------------------
    # Key management
    # ------------------------------------------------------------------

    def _key_file(self, version: int) -> Path:
        return self.keys_dir / f"pseudonym.{self.org_id}.v{version}.key"

    def _versions_file(self) -> Path:
        return self.keys_dir / f"pseudonym.{self.org_id}.versions.json"

    def _load_or_create_key(self) -> PseudonymizationKey:
        versions_path = self._versions_file()
        if versions_path.exists():
            metadata = json.loads(versions_path.read_text(encoding="utf-8"))
            current_version = metadata["current_version"]
            secret = self._key_file(current_version).read_bytes()
            return PseudonymizationKey(
                org_id=self.org_id,
                key_version=current_version,
                secret=secret,
                created_at=metadata["versions"][str(current_version)],
            )

        # First run — generate version 1.
        secret = secrets.token_bytes(32)
        created_at = datetime.now(timezone.utc).isoformat()
        self._key_file(1).write_bytes(secret)
        versions_path.write_text(
            json.dumps(
                {
                    "current_version": 1,
                    "versions": {"1": created_at},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return PseudonymizationKey(
            org_id=self.org_id,
            key_version=1,
            secret=secret,
            created_at=created_at,
        )

    def rotate_key(self) -> PseudonymizationKey:
        """Generate a new key version. Old pseudonyms remain reproducible
        by passing ``key_version`` to :meth:`pseudonymize_with_version`."""

        versions_path = self._versions_file()
        metadata = json.loads(versions_path.read_text(encoding="utf-8"))
        next_version = metadata["current_version"] + 1
        secret = secrets.token_bytes(32)
        created_at = datetime.now(timezone.utc).isoformat()
        self._key_file(next_version).write_bytes(secret)
        metadata["versions"][str(next_version)] = created_at
        metadata["current_version"] = next_version
        versions_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self._key = PseudonymizationKey(
            org_id=self.org_id,
            key_version=next_version,
            secret=secret,
            created_at=created_at,
        )
        return self._key

    @property
    def current_key(self) -> PseudonymizationKey:
        return self._key

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def pseudonymize(self, identifier: str) -> dict:
        """Return a dict with the pseudonym and its key version."""

        return self.pseudonymize_with_version(identifier, self._key.key_version)

    def pseudonymize_with_version(self, identifier: str, key_version: int) -> dict:
        """Compute the pseudonym for a specific key version (for replays)."""

        secret = self._key_file(key_version).read_bytes()
        digest = hmac.new(secret, identifier.encode("utf-8"), sha256).hexdigest()
        return {
            "pseudonym": digest,
            "key_version": key_version,
            "org_id": self.org_id,
            "alg": "HMAC-SHA256",
        }

    def apply_to_event(self, event: dict) -> dict:
        """Return a copy of ``event`` with sensitive fields pseudonymized.

        The result is structurally identical to the input event except that
        any field whose name is in ``self.sensitive_fields`` is replaced by
        a pseudonym dictionary. Non-sensitive fields are passed through
        unchanged. The caller can use the result as input to the Compliance
        Oracle without any further changes.
        """

        return self._recursive_pseudonymize(event)

    def _recursive_pseudonymize(self, value):
        if isinstance(value, dict):
            return {
                key: (
                    self.pseudonymize(str(inner))
                    if key in self.sensitive_fields
                    else self._recursive_pseudonymize(inner)
                )
                for key, inner in value.items()
            }
        if isinstance(value, list):
            return [self._recursive_pseudonymize(item) for item in value]
        return value
