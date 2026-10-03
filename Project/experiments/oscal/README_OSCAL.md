# Status of the OSCAL exports

## Consistent with the redaction in force

These files were regenerated on 2026-09-16 with the current exporter. Each was
compared with the record that produced it for the free-text fields listed
below and for a UUID derived from `artifact_id`, and none was found. Passing
that comparison does not establish anonymity: the exports keep hashes, against
which a candidate value can be matched.

- `incident_run/oscal_incident_redacted.json`
- `multiflow_run/oscal_multiflow_redacted.json`
- `multiflow_run_real/oscal_multiflow_redacted.json`
- `multiflow_run_steel/oscal_multiflow_redacted.json`
- `oscal_assessment_results_redacted_20260914T221805Z.json`

Each of them was compared with the ledger that produced it, looking for
`scenario_id`, `reason`, `policy_id`, `artifact_id`, `artifact_type`,
`pipeline_stage` and the `subject-uuid` derivable from `artifact_id`. That
comparison is made by a script of the author's working repository, which is not
part of this folder. What can be run here: `tests/test_redaction_boundary.py`
applies the same sweep, field by field, to a freshly exported document, and
`python3 validate_oscal_schema.py --expect 18` validates the published files
against the NIST schema.

## Historical, from an earlier exporter

These three are outputs from 2026-04-29, produced before the three rounds that
corrected the redaction boundary. The ledger that produced them has since been
replaced, so they are **not regenerable**. They are kept because they are
genuine measurements and because Appendix B, and the count of 18 out of 18
schema-valid documents, include them.

- `oscal_assessment_results_redacted_20260429T210248Z.json`
- `oscal_assessment_results_redacted_20260429T210457Z.json`
- `oscal_assessment_results_redacted_20260429T215055Z.json`

**Do not use them to demonstrate selective disclosure.** They still copy the
`scenario_id` into the observation title and derive the `subject-uuid` from the
`artifact_id`, which are precisely the two defects that the section on selective
disclosure describes as found and corrected. For that demonstration, use any of
the five listed above.

## Why this was wrong

The exporter was corrected in three rounds, between 15 and 16 September 2026,
and the artefacts on disk did not follow. Over that interval the dissertation
described a redaction that the published evidence did not implement, and it is
the published evidence that the reader opens. A test over the code does not
catch this. Only comparing the generated file against the ledger that generated
it does, and that comparison is now part of the author's checks before each
delivery.
