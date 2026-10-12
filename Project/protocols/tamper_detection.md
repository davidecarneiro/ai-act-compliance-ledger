# Protocol — tamper detection (section 4.4 of the article plan)

Recorded on 2026-10-12, before the experiment was run. It fixes how each
attack of the plan's table is carried out, so that the observed outcome can
be compared with the expected one. Nothing here changes after the run.

## Material

The 16 events of the credit-scoring case (`protocols/wp4_credit_case.md`),
regenerated with partition seed 42 under the case policy, are sent through
each configuration of the WP3 ablation (`ablation_arms.py`): A (SQLite row),
B0 (hash chain, unsigned), B (signed) and B+ (signed, with the signed head
anchored to an external file every **K = 5** records, so anchors at records
5, 10 and 15 and record 16 after the last anchor). Each attack is applied to
a fresh copy of that output. Configuration C (Fabric) is run on the Fabric
machine with WP7 and is not part of this run.

## Who checks what

Each configuration is checked by what a third party holding its output can
run (`ablation_arms.verify_*`): A, that row identifiers run 1..n; B0, every
record hash and parent link; B, also every signature against the issuer's
public key; B+, also every anchor against the ledger. The anchor file is
outside the attacker's reach in every attack.

An attack is **detected** when the check fails, **not detected** when it
passes, **n/a** when the attack has nothing to act on in that configuration.

## Attacks

Target record for the attacks on one record: record 8, the validation of v2,
whose decision is `rejected`; the alteration sets it to `approved`.

| # | Attack | How |
| --- | --- | --- |
| T1 | Alter a field of an intermediate record | Record 8: `decision` set to `approved`; nothing else touched. A: the row's `decision` column. |
| T2 | Alter only the signature | Record 8: one byte of the signature flipped. n/a for A and B0. |
| T3 | Alter and recompute every hash, without the key | As T1, then `record_hash` of record 8 and `parent_hash`, `chain_hash` of records 8–16 recomputed; signatures left as they were. A: as T1. |
| T4 | Swap two records | Records 8 and 9 exchange places. A: the two rows exchange their contents, identifiers kept. |
| T5 | Delete an intermediate record | Record 8 removed. A: row deleted and later identifiers shifted down by one, so they stay contiguous (an attacker with write access does this). |
| T6a | Truncate a suffix that crosses an anchor | Records 14–16 removed. |
| T6b | Truncate a suffix after the last anchor | Record 16 removed. |
| T7a | Rewrite with the issuer's key (insider), crossing an anchor | As T3 from record 8, and records 8–16 re-signed with the issuer's key. A: as T1. |
| T7b | Rewrite with the issuer's key after the last anchor | Record 16 altered (`decision` changed) and re-signed. |
| T8 | Omit an event at the source | Event 8 is never sent; the configuration records the other 15. |
| T9a | Inject a forged event upstream | An extra validation event for v2 with fabricated metrics (parity 0.05) is sent after event 8. |
| T9b | Inject a forged approval upstream | An extra deployment request for v2 with an approval in the name of `approver-demo` but signed with another key is sent after event 10. |

T9b is also reported by its decision: every configuration decides with the
same engine function, which verifies the approval against the policy.

## Expected outcome (from the plan)

| # | A | B0 | B | B+ |
| --- | --- | --- | --- | --- |
| T1 | not detected | detected | detected | detected |
| T2 | n/a | n/a | detected | detected |
| T3 | not detected | not detected | detected | detected |
| T4 | not detected | detected | detected | detected |
| T5 | not detected | detected | detected | detected |
| T6a | not detected | not detected | not detected | detected |
| T6b | not detected | not detected | not detected | not detected |
| T7a | not detected | not detected | not detected | detected |
| T7b | not detected | not detected | not detected | not detected |
| T8 | not detected | not detected | not detected | not detected |
| T9a | not detected | not detected | not detected | not detected |
| T9b | not detected by the check; rejected at the gate | idem | idem | idem |

## Output

`experiments/article/tamper/tamper_<UTC time>.json`: per attack and
configuration, the expected and the observed outcome and the issues the check
reported. Produced by `prototype/credit_case/tamper_experiment.py`.
