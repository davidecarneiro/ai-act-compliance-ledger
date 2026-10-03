# Chaincode `compliance` (Hyperledger Fabric 2.5)

The Go counterpart of the Python Compliance Policy Engine
(`../../compliance_ledger_sim/simulator.py`). It accepts records that the Python
issuer has already decided, hashed and signed, checks them again on the peer and
appends them to the channel ledger. It does not take policy decisions itself.

`../../fabric_notes/compliance_chaincode.go` is the earlier reference version, as
it stood before it was confronted with real records; Appendix D of the
dissertation prints that version. This folder holds the corrected one.

## Interface

| Function | Who may call it | What it does |
|---|---|---|
| `RegisterIssuer(pubKeyHex)` | identities of `Org1MSP`, the authority organisation | Stores an issuer's raw Ed25519 public key under its SHA-256 fingerprint |
| `SubmitEvidence(recordJSON)` | any member whose transaction gathers the endorsements the policy asks for | Looks up the issuer key by `issuer_pubkey_fingerprint` in the registry, verifies the Ed25519 signature over the canonical body, recomputes `record_hash` and `chain_hash`, checks `parent_hash` against the head pointer, stamps the submitter's MSP identity and appends the record |
| `VerifyChain()` | any member | Walks the records from the genesis and checks each `record_hash`, the Ed25519 signature against the registered key, the `parent_hash` link and the `chain_hash` |
| `GetEvidence(evidenceID)` | any member | Returns the stored JSON of one record |
| `QueryByRequirement(article)` | any member | Returns, as a JSON array, the stored records whose `requirements_covered` lists the article |

The verification key never comes from the caller: a submitter cannot pair a
forged record with a key of its own choosing. The two queries return the stored
bytes rather than a Go struct, which keeps `scenario_id: null` as `null` (see
the 2 October 2026 entry below).

The endorsement policy is `AND('Org1MSP.peer','Org2MSP.peer')`, set when the
chaincode is deployed (`../deploy/01_up_and_deploy.sh`). The chaincode does not
check endorsements itself; the validation step at commit compares them with the
policy. The dissertation's conceptual model calls the two organisations
`TechMSP` and `ComplianceMSP`; on the test network they are `Org1MSP` and
`Org2MSP`.

## Canonical form shared with Python

The hash and the signature are computed over bytes, so Go must produce exactly
the bytes Python produced. `canonicalJSON` sorts keys, uses compact separators,
leaves `<`, `>` and `&` literal, escapes non-ASCII characters as `\uXXXX`, and
keeps every number literal as the issuer wrote it (`UseNumber`; `metrics` is a
`json.RawMessage`), because Python writes `0.0` where a float64 round trip writes
`0`. The domain this is proven on is the evidence body: strings, lists of
strings, `null` in `scenario_id`, and the numbers inside `metrics`. It is not a
general JSON canonicaliser; that would need RFC 8785 on both sides.

## Tests (no network needed)

`go test -mod=vendor ./...` runs **10 tests**, all passing, from the vendored
dependencies and without network access:

- `TestContractBootstraps` builds the contract with `contractapi.NewChaincode`,
  as the executable does at start-up, and checks that the queries return a null
  `scenario_id` as `null`;
- `TestRecordHashInterop`, `TestChainHashInterop` and
  `TestSignatureRequiresRawKeyNotFingerprint` recompute hashes and signatures of
  the real Art. 73 incident run in Go;
- `TestSubmitEvidenceEndToEnd` submits the incident run through a mock stub,
  checks `VerifyChain`, `GetEvidence` and the stamped MSP identity, and sees a
  tampered record rejected;
- `TestVerifyChainCatchesStoredTamper` alters a record already in state, and
  separately removes the last one, and sees `VerifyChain` report both;
- `TestRegisterIssuerGovernance` and `TestSubmitRejectsUnregisteredIssuer` cover
  the issuer registry;
- `TestCurrentPythonLedgerVerifiesInGo` and `TestBoundaryLedgerVerifiesInGo`
  verify, in Go, the current six-record canonical ledger and the ledger of the
  boundary matrix that `compliance_ledger_sim/tests/test_fronteiras.py` writes.

A missing fixture makes a test fail rather than skip, because a skipped test
still lets `go test` print `ok`. The incident ledger is looked up both where the
delivered `Project/` folder keeps it and where the author's vault does.

`../interop/test_interop.py` checks the canonical form separately, on three
synthetic vectors (HTML and non-ASCII, an astral-plane emoji, the DEL character)
and on the first record body of three real ledgers.

What these tests do not show: the MVCC conflict on the head pointer, which only
a peer enforces, and endorsement, which happens outside the chaincode. Both were
observed on a test network on 3 October 2026 (see below).

`VerifyChain` compares the end of the walk with the head pointer, so a record
removed from the end of the chain is reported. The pointer lives in the same
state as the records, though: whoever can rewrite the state can rewrite both,
and only an anchor kept outside the ledger (a published final `chain_hash`)
covers that case.

## On the network

| Date | What ran | Artefacts |
|---|---|---|
| 13 June 2026 | Two-organisation test network, CCaaS deployment, AND policy. First measurement through the `peer` CLI (`../deploy/02_submit_and_measure.py`) | `fabric_run/fabric_latency.json` |
| 13 June 2026 | Network brought up again with `-ca` (a Fabric CA per organisation), issuer registry and head pointer in place. Measurement through the Fabric Gateway SDK (`../gateway/gateway_measure.go`), LevelDB and CouchDB, 30 records each. These are the figures the dissertation cites | `fabric_run/fabric_latency_gateway_*.json`, `gateway/records.json` |
| 5 July 2026 | Five records submitted, and block chaining confirmed with `peer channel getinfo` and `configtxlator` | `fabric_run/_gen_ledger.json`, `fabric_run/block_chaining/` |
| 3 October 2026 | Functional check of the current chaincode: 31 records committed and verified, refusals at endorsement, a single-organisation endorsement invalidated at commit, an MVCC conflict on the head pointer | `docs/fabric_check_2026-10-03/` (from the root of the delivered folder) |

Paths in the first three rows are relative to `experiments/runs/` in the
delivered folder.

The chaincode that ran in June and July is the June version, and the figures
the dissertation cites come from those runs. The changes made afterwards were
deployed for the first time in the functional check of 3 October 2026, which is
not a measurement series:

- September 2026: the struct gained the four fields of the 23-field evidence
  model, `metrics` became a `json.RawMessage` decoded with `UseNumber`, and
  `scenario_id` became a `*string`;
- 2 October 2026: `GetEvidence` and `QueryByRequirement` return the stored JSON.
  With the pointer field, returning the struct made `contractapi.NewChaincode`
  refuse the contract, and the executable stopped at start-up with a panic
  before reaching the network. `TestContractBootstraps` now covers that path.
  `VerifyChain` also compares the end of the chain with the head pointer.

`main()` runs as a CCaaS server when `CHAINCODE_SERVER_ADDRESS` is set (TLS off,
for the test network only), and in the standard peer-launched mode otherwise.
Outside a peer it stops at once asking for `CORE_CHAINCODE_ID_NAME`, which is
expected.

## Reproducing

`../00_setup_fabric.sh`, then `../deploy/01_up_and_deploy.sh` (it brings the
network up with `-ca`; `FABRIC_CA=0` uses cryptogen instead), then
`go run ../gateway/gateway_measure.go records.json pubkey.txt` from `../gateway/`.
A new run produces new records, with new timestamps and hashes. It shows that
the method works again; it does not confirm the published records, which are
confirmed by recomputing them (`compliance_ledger_sim/verify_delivery.py`).
`../MIGRATION_LOG.md` records how the migration went, including the three
interoperability defects found on the way.
