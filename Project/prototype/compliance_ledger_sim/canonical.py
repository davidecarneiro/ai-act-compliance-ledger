"""Versioned canonical form of evidence records.

Every digest and signature in the ledger is computed over a canonical byte
serialisation of a JSON value. The record body carries the version of that
serialisation, so a verifier can recompute the bytes the issuer signed:

* schema version 1 (records without a ``schema_version`` field): the form the
  dissertation shipped, ``json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=True)``. Keys are ordered by code point, non-ASCII is escaped
  as ``\\uXXXX`` and numbers keep Python's ``repr``. The Go chaincode had to
  replicate those choices one by one (Table T11 of the article plan).
* schema version 2: RFC 8785, the JSON Canonicalization Scheme (JCS). Keys are
  ordered by UTF-16 code units, strings are emitted as UTF-8 with the minimal
  escape set, and numbers follow the ECMAScript ``Number.prototype.toString``
  rules, so ``0.0`` and ``0`` canonicalise to the same bytes in every
  conforming implementation.

Records written under version 1 stay verifiable: the verifier dispatches on the
version found in each record, never on the version the issuer currently emits.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Dict, Mapping

import rfc8785

SCHEMA_V1 = 1
SCHEMA_V2 = 2
SUPPORTED_SCHEMA_VERSIONS = (SCHEMA_V1, SCHEMA_V2)


def _issued_schema_version() -> int:
    """Schema version new records are issued under.

    Version 2 unless ``EVIDENCE_SCHEMA_VERSION=1`` is set, which reproduces the
    records of the dissertation (tag thesis-v1.0) and lets the test suite run
    against both forms. Anything else is refused at import: a typo must not
    silently select a canonical form."""
    raw = os.environ.get("EVIDENCE_SCHEMA_VERSION", "").strip()
    if not raw:
        return SCHEMA_V2
    if raw not in {str(v) for v in SUPPORTED_SCHEMA_VERSIONS}:
        raise ValueError(
            f"EVIDENCE_SCHEMA_VERSION={raw!r}; supported: "
            f"{', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))}"
        )
    return int(raw)


CURRENT_SCHEMA_VERSION = _issued_schema_version()

# Fields computed from the canonical body and therefore not part of it.
DERIVED_FIELDS = frozenset({"record_hash", "issuer_signature", "chain_hash"})

# Largest integer magnitude that survives a round trip through an IEEE 754
# double, which is the number domain RFC 8785 (section 3.2.2.3) admits.
JCS_MAX_SAFE_INTEGER = 2**53 - 1


class UnsupportedSchemaVersion(ValueError):
    """A record declares a canonical form this verifier does not implement."""


def canonical_v1(payload) -> bytes:
    """Schema version 1: the serialisation the dissertation's records use.

    ``ensure_ascii=True`` is the ``json.dumps`` default but is stated because it
    is part of the contract the Go chaincode replicates for version 1."""
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def canonical_v2(payload) -> bytes:
    """Schema version 2: RFC 8785 (JCS).

    Raises ``rfc8785.CanonicalizationError`` (or one of its subclasses) for
    values outside the JCS domain: non-finite floats, integers beyond
    +/-(2**53 - 1), non-string keys and text that is not valid Unicode. Callers
    that hash untrusted input map such values first (see
    ``simulator._canonical_source``)."""
    return rfc8785.dumps(payload)


_CANONICALISERS: Dict[int, Callable[[object], bytes]] = {
    SCHEMA_V1: canonical_v1,
    SCHEMA_V2: canonical_v2,
}


def canonicaliser(version: int) -> Callable[[object], bytes]:
    """Return the canonical serialisation for a schema version."""
    try:
        return _CANONICALISERS[version]
    except (KeyError, TypeError):
        raise UnsupportedSchemaVersion(
            f"schema_version {version!r} is not supported; "
            f"supported: {', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))}"
        ) from None


def schema_version_of(record: Mapping) -> int:
    """The schema version a stored record was written under.

    A record without the field predates versioning and is version 1. A record
    that names a version must name a supported one, as an integer: a string
    "2" or a boolean is refused rather than coerced, because the field is part
    of the signed body and coercion would let two different bodies select the
    same canonical form."""
    if "schema_version" not in record:
        return SCHEMA_V1
    version = record["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise UnsupportedSchemaVersion(
            f"schema_version must be an integer, got {type(version).__name__}"
        )
    if version not in _CANONICALISERS:
        raise UnsupportedSchemaVersion(
            f"schema_version {version} is not supported; "
            f"supported: {', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))}"
        )
    if version == SCHEMA_V1:
        # Version 1 records never carried the field. Accepting an explicit 1
        # would create a second byte form for the same logical record.
        raise UnsupportedSchemaVersion(
            "schema_version 1 is implicit; a record that names it is malformed"
        )
    return version


def record_body(record: Mapping) -> dict:
    """The signed body of a stored record: the record without derived fields."""
    return {k: v for k, v in record.items() if k not in DERIVED_FIELDS}


def record_body_bytes(record: Mapping) -> bytes:
    """Canonical bytes of a stored record's body, in the record's own version."""
    return canonicaliser(schema_version_of(record))(record_body(record))
