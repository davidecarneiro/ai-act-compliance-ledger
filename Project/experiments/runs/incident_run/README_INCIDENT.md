# The serious-incident run (AI Act Art. 73)

Produced by `incident_demo.py` from `build_incident_scenario()`: three chained
events, detection of a serious incident, a reporting event and an audit query.
The chain verifies 3/3 and each record carries the label `Art.73`.

The report to the authority is **simulated**: the scenario writes a record of
type `incident_reported_to_authority`, and nothing is sent to any authority.
The timestamps are the issuer's own, so the interval between detection and
report can be compared with the deadlines of Art. 73, but it is not proof that
a report was received.

Files: `ledger.json`, `oscal_incident.json`, `oscal_incident_redacted.json`
and `RUN_TIMESTAMP.txt`.
