#!/usr/bin/env python3
"""Validate OSCAL Assessment Results documents against the official NIST schema.

Reproducible companion to the dissertation's OSCAL claim. It validates one or
more exported documents against the official OSCAL 1.1.2 ``assessment-results``
JSON Schema (vendored under ``tests/fixtures/``) using the ``jsonschema``
library. Two practical details are handled explicitly:

* the NIST schema declares JSON Schema *draft-07*, so the draft-07 validator is
  used (the 2020-12 validator does not resolve the schema's ``$id`` anchors);
* the schema's ``pattern`` regexes use ECMA-262 Unicode property escapes
  (``\\p{...}``) that Python's ``re`` cannot compile, so the ``regex`` module is
  used via a small custom keyword.

This performs JSON Schema validation (structure, required fields, value
formats, closed property sets). It does not run the OSCAL Metaschema semantic
constraints that the Java ``oscal-cli`` adds on top; that fuller validation,
which needs a JRE 11+, is noted as future work in the dissertation.

Usage:
    python3 validate_oscal_schema.py <file.json> [<file.json> ...]
    python3 validate_oscal_schema.py            # validates the experiments dir
Exit code is 1 if any document is invalid.
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import regex as _re
from jsonschema import Draft7Validator, validators
from jsonschema.exceptions import ValidationError

SCHEMA_PATH = (
    Path(__file__).parent
    / "tests"
    / "fixtures"
    / "oscal_assessment-results_1.1.2_schema.json"
)


def _unicode_pattern(validator, patrn, instance, schema):
    if validator.is_type(instance, "string"):
        try:
            if _re.search(patrn, instance) is None:
                yield ValidationError(f"{instance!r} does not match {patrn!r}")
        except _re.error as exc:
            # A pattern the engine cannot compile must not pass silently: a
            # constraint that never ran would otherwise be reported as [PASS].
            raise RuntimeError(
                f"schema pattern {patrn!r} did not compile: {exc}"
            ) from exc


def _unicode_pattern_properties(validator, pattern_properties, instance, schema):
    if not validator.is_type(instance, "object"):
        return
    for pattern, subschema in pattern_properties.items():
        try:
            rx = _re.compile(pattern)
        except _re.error as exc:
            # Same reasoning as in _unicode_pattern: silence here would turn an
            # unverified constraint into a clean validation result.
            raise RuntimeError(
                f"schema patternProperties {pattern!r} did not compile: {exc}"
            ) from exc
        for key, value in instance.items():
            if rx.search(key):
                yield from validator.descend(
                    value, subschema, path=key, schema_path=pattern
                )


UnicodeDraft7 = validators.extend(
    Draft7Validator,
    {"pattern": _unicode_pattern, "patternProperties": _unicode_pattern_properties},
)


def main(argv: list[str]) -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = UnicodeDraft7(schema)

    # --expect N: the number of documents that must be found. Without it a
    # missing folder would validate nothing and still look like a pass.
    expected = None
    if "--expect" in argv:
        i = argv.index("--expect")
        try:
            expected = int(argv[i + 1])
        except (IndexError, ValueError):
            print("--expect needs a whole number", file=sys.stderr)
            return 2
        argv = argv[:i] + argv[i + 2:]

    if argv:
        files = argv
    else:
        from paths import EXPERIMENTS_DIR
        base = EXPERIMENTS_DIR
        files = sorted(
            set(
                glob.glob(str(base / "**" / "oscal_*.json"), recursive=True)
                + glob.glob(str(base / "oscal_assessment_results_*.json"))
            )
        )

    print(f"oscal-schema-validate :: OSCAL 1.1.2 assessment-results")
    print(f"schema: {SCHEMA_PATH.name} (official NIST release v1.1.2)")
    print(f"engine: jsonschema draft-07 + regex (Unicode \\p escapes)\n")

    invalid = 0
    for path in files:
        name = Path(path).name
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            invalid += 1
            print(f"[FAIL] {name} (not readable as JSON: {exc})")
            continue
        errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
        if not errors:
            print(f"[PASS] {name}")
        else:
            invalid += 1
            print(f"[FAIL] {name} ({len(errors)} error(s))")
            for error in errors[:5]:
                location = "/".join(str(p) for p in error.path) or "(root)"
                print(f"       @{location}: {error.message}")

    total = len(files)
    print(f"\nResult: {total - invalid}/{total} valid against the NIST schema.")
    if total == 0:
        print("No OSCAL document was found, so nothing was validated.")
        return 1
    if expected is not None and total != expected:
        print(f"Expected {expected} documents and found {total}.")
        return 1
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
