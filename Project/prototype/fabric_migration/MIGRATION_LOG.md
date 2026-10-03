# Migration to Hyperledger Fabric: execution log

> This execution log records the migration of the Python simulator to a Hyperledger
> Fabric test network: the procedure, the implementation defects found, the measurements
> and the limitations. Entries are dated and in the order they were made. The log was
> edited for publication on 3 October 2026: headings were made descriptive, notes about
> drafting the dissertation were removed, and current-reading notes were added where a
> later result superseded an earlier one. Commands, figures and outcomes are unchanged,
> and the unedited log is kept in the author's working repository. The state of the
> delivered version is in the addendum of 2026-10-03 at the end, and in
> `chaincode/README.md`.
>
> Two terms used in the entries of June 2026 are read today as follows. «Pure endorsement»
> and «evaluate/endorse» name the timing of a read-only `VerifyChain` query through the
> Gateway (client, transport, Gateway and execution on one peer, without ordering or
> commit); it is not the endorsement of a write. «Rigorous» distinguishes the Gateway
> measurement, over a persistent connection, from the first one through the `peer` CLI.
>
> **State on 2026-06-13:** Gates A to C reached. The chaincode was tested against records
> the simulator produced (3 interoperability defects fixed), a two-organisation test network
> was brought up, the chaincode was deployed as CCaaS with AND endorsement, and latency was
> measured. It is a proof of concept of the target stack, not a production deployment. See
> **Limitations** at the end.

---

## Conventions and locations

- **External workspace (third-party, NOT versioned):** `~/fabric-workspace/` holds
  `fabric-samples/`, the binaries (`bin/`) and the `test-network`. It stays out of git
  (about 3 GB).
- **Vault (our artefacts, versioned):** this directory,
  `prototype/fabric_migration/`:
  - `00_setup_fabric.sh`: installs fabric-samples, binaries and images into the external workspace (reproducible)
  - `MIGRATION_LOG.md`: this log
  - `chaincode/`: `go.mod` and a copy of `compliance_chaincode.go` with the interop fix
  - `deploy/`: scripts that deploy the chaincode on the test network
  - `gateway/`: the Fabric Gateway SDK client used for the rigorous measurement
  - `interop/`: the canonical serialisation cross-check between Go and Python

## Pinned versions (reproducibility)

- Fabric: **2.5.x LTS** (native x86_64, on an Intel MacBook)
- Fabric CA: 1.5.x
- Go: 1.25.4 (from the system)
- Chaincode: `fabric-contract-api-go` (already used in `fabric_notes/compliance_chaincode.go`)

---

## Environment audit (2026-06-13, Phase 0)

| Prerequisite | State |
|---|---|
| Architecture | x86_64 (no arm64 risk) |
| Docker | 29.5.3, daemon OK |
| Go | 1.25.4 |
| curl / git / jq | present |
| Free disk | ⚠️ about 17 GiB (tight; Docker's build cache was cleared to make room) |
| fabric-samples / binaries | absent → installed by `00_setup_fabric.sh` |

**Network design decision (the minimum that is defensible):** 2 organisations (TechMSP and
ComplianceMSP), 1 Raft orderer, channel `compliance-channel`, endorsement policy
`AND('TechMSP.peer','ComplianceMSP.peer')`. Justified in §3 of the parent plan.

---

## Logbook

### 2026-06-13: Phase 0 started
- Environment audit complete (table above).
- Docker's build cache cleared (`docker builder prune -f`, 2.8 GB freed).
- `00_setup_fabric.sh` created.
- Fabric 2.5.10 download: **binaries installed** (`~/fabric-workspace/fabric-samples/bin/`:
  peer, orderer, configtxgen, cryptogen and so on). Docker images pulling.

### 2026-06-13: Canonical interoperability proof (an early win, no network needed)

**Finding (going deeper into the bug in §2 of the plan):** `simulator.canonical_json` uses
`json.dumps(sort_keys=True, separators=(",",":"))` with `ensure_ascii=True`. That produces,
**confirmed empirically**, two behaviours that Go's `json.Marshal` inverts:

| Axis | Python | Go (default) |
|---|---|---|
| HTML `< > &` | literal | escaped → `<` |
| Non-ASCII (ç, ã, é) | escaped → `ç` | literal (UTF-8) |

Go by default does the **opposite on both axes**, so the dissertation's hash
interoperability claim (Chapter 4) held only by luck, because the current ledgers are pure
ASCII with no `<>&`. That is fragile.

**Fix and proof:** `interop/canonical_interop.go` is a canonical Go serialiser that
sets `SetEscapeHTML(false)` for the HTML axis and applies `asciiEscape` (`\uXXXX` escaping
with surrogate pairs) for the non-ASCII axis. The `interop/test_interop.py` harness runs it
against Python vectors:

```
[OK ] synthetic_html_nonascii      (HTML + ç/ã/é + array + unordered keys)
[OK ] real_incident                (real body from incident_run)
[OK ] real_multiflow_real          (real body from Muvu)
[OK ] real_canonical               (real body from the canonical ledger)
4/4 vectors with identical hashes across Python and Go
```

**What it means:** the claim that «the Go chaincode replicates the simulator» is
demonstrated by evidence **over the domain of the evidence body (string and list fields)**.
See LIMITATIONS about numbers and floats. It is independent of the network and reproducible
with `cd interop && python3 test_interop.py`.

### 2026-06-13: Deployable chaincode prepared (Phase 1, before the network)
- `chaincode/compliance_chaincode.go`: a copy of the `fabric_notes/` version **with the
  two-axis interop fix already folded into** `canonicalJSON` (plus the `asciiEscape` helper
  and the `bytes` import). See `chaincode/README.md`.
- `chaincode/go.mod` created (module `compliance-chaincode`, dependency
  `fabric-contract-api-go v1.2.2`). `go mod tidy` and `go build` wait for the network,
  because the modules need internet access.
- **A consistency note:** at this date the fix had not yet been applied to the reference
  version in `fabric_notes/`, which is the one the dissertation's appendix prints.

### State of the Fabric download
- Binaries. Docker images (fabric-peer, orderer, ccenv, baseos, ca and tools) pulling in
  the background. Bringing up the test network is the next step (Phase 1).

### 2026-06-13: Infrastructure incident: the Docker daemon jammed on pulls (resolved)
**Symptom:** `install-fabric.sh` hung for hours on `docker pull fabric-peer:2.5.10`
(0 bytes, the process alive but making no progress). Diagnosis:
- Network to Docker Hub fine (`auth.docker.io` 200, `registry-1.docker.io` 401 as expected, github 200).
- The daemon answered `stop` and `system df` (the control plane) but **hung on `pull` and
  `run`** (the image subsystem was jammed).
**Likely cause:** a degraded Docker Desktop VM (resource pressure with the MultiFlow
containers still running, plus a long Docker session).
**Resolution:** the MultiFlow containers were stopped (their proofs were already committed),
then `docker desktop restart`, and the daemon recovered (`docker info` OK first time). The
pull was relaunched explicitly through `~/fabric-workspace/pull_images.sh`, which waits for
the daemon and pulls the 6 images.
**Lesson for reproduction:** if pulls hang while the network is fine, restart Docker Desktop
BEFORE retrying. It is not a bandwidth problem.

**Update:** the restart did NOT fix it durably. `docker pull` hung again (0 bytes, no
progress) on a fresh daemon. Image cleanup (`docker system prune -af`) was not performed,
because it would remove the MultiFlow images used by the experiments. An environment
blocker.

### 2026-06-13: Compilation check with the interop fix (Phase 1, no Docker)
Taking advantage of `go build` depending on the Go modules (network fine) rather than on
Docker Hub:
- `go mod tidy` downloaded `fabric-contract-api-go v1.2.2` and its dependencies (go.sum
  generated and versioned).
- `go build ./...` → **BUILD OK**, `go vet ./...` → **VET OK**. A Mach-O x86_64 binary was
  produced (not versioned, and a `.gitignore` was added).
- **What it means:** the chaincode with the two-axis fix compiles against the real Fabric
  API. Only the network is missing, for deployment and measurement. Everything that does
  NOT depend on Docker is done.

### 2026-06-13: Chaincode tests with a mock stub (Gate B, no Docker)

Testing the chaincode with real records (mock stub, `go test`, no network) exposed **three
interoperability defects**, fixed and tested here, that stopped the published chaincode
(the appendix) from working with real simulator records:

| Bug | Description | Fix | Proof |
|---|---|---|---|
| **#1** | Canonical serialisation diverges on 2 axes (HTML literal against escaped; non-ASCII escaped against literal) | `canonicalJSON`: `SetEscapeHTML(false)` and `asciiEscape` | `TestRecordHashInterop`, `TestChainHashInterop` (record_hash and chain_hash identical for every real record) |
| **#2** | `issuer_pubkey_fingerprint` is the **sha256 of the key**, not the key, so `ed25519.Verify` with the fingerprint always fails | `SubmitEvidence` takes the raw public key, binds it to the fingerprint (`sha256(key)==fp`) and only then verifies | `TestSignatureRequiresRawKeyNotFingerprint` |
| **#3** | `GetStateByRange` returns in **lexical order of the key** (a random UUID) rather than by insertion, so the chain reconstruction breaks at the third record | persist under a **zero-padded sequence key** (`ev%012d`), and have `GetEvidence` scan | `TestSubmitEvidenceEndToEnd` (submits 3 real records → «chain valid: 3 records» → tampering rejected) |

**`go test ./...` → 4/4 PASS. `go build` and `go vet` clean.**

**What it means:** the scientific objective of Gate B, that «the chaincode replicates the
simulator with real cryptography», is **demonstrated by evidence**, in process, **with no
need for the Docker network**. The network only adds the measurement of distributed
endorsement latency (Gate C).

The migration identified three interoperability defects. The reference version in
`fabric_notes/compliance_chaincode.go`, which the appendix prints, still carries them; the
corrected implementation and its regression tests are in `chaincode/`.

### 2026-06-13: Docker daemon recovered
**Root cause:** `docker desktop status` showed the engine in a **`stopped`/bad** state (logs:
`com.docker.backend.ipc ... Get http://ipc/ping: context deadline exceeded` in a loop). The
`restart` had not cleared it. It was NOT disk (Docker.raw is sparse: 1 TB logical, 15 GB
physical, on a host with about 20 GB free) and not the network (curl to Docker Hub fine).
**Fix:** a clean `docker desktop stop` → `docker desktop start` cycle, and the engine came up
`running`. `docker pull hello-world` returned 0, and the Fabric image pulls progressed
(fabric-peer, orderer in progress).
**Lesson:** if pulls hang, check `docker desktop status`. If it is not `running`, do
`stop` and `start`, not just `restart`.

### 2026-06-13: Test-network execution (Gate C): two organisations and a first latency measurement

**Chaincode build blocker (solved with CCaaS):** the normal chaincode install failed
systematically with `docker build failed: ... docker.proxy.sock: broken pipe`, from the build
the peer manages through Docker Desktop's socket proxy. Confirmed systematic (two identical
failures, while a standalone build worked). **Solution:** Chaincode-as-a-Service. The
chaincode was converted to dual mode (`main()` starts a server when
`CHAINCODE_SERVER_ADDRESS` is set, otherwise the standard mode for `go test`), given its own
`Dockerfile`, built on the HOST, and deployed with `./network.sh deployCCAAS`. The chaincode
was **committed** with both organisations approving (`Org1MSP: true, Org2MSP: true`), and the
`peer0org{1,2}_compliance_ccaas` containers are running.

**Real latency measured** (`02_submit_and_measure.py`, a CLEAN run of 30 records on a fresh
chain, `chain valid: 30 records`). All times go through the `peer` CLI (a fork per call), so
they are an **upper bound**. See LIMITATIONS:

| Metric | Value | Meaning |
|---|---|---|
| Local crypto cost (simulator, in process) | **3.79 ms** | the local figure at the date of this measurement, which became exploratory on 2026-09-14 (the figure under the paired protocol is 6.47 ms, a difference of +5.08 ms) |
| `peer` CLI start-up (no network) | **about 74 ms** | overhead that EVERY CLI measurement includes |
| `query_exec` (query, no ordering, n=20) | **about 104 ms** (p95 112) | includes the 74 ms of CLI, so execution plus TLS/gRPC is roughly 30 ms |
| `write_commit` (2-org endorsement → ordering → commit, n=29) | **about 2152 ms** (p95 2200) | dominated by BatchTimeout=2s (an inference) |
| VerifyChain on the real network (recomputes record_hash and chain_hash) | **chain valid: 30 records** | content integrity and chaining |

**Reading for RQ4:** the direction holds: the bottleneck moves
from the in-process cryptographic cost (3.79 ms at the time, 6.47 ms under the protocol of
2026-09-14) to distributed coordination (durable commit about 2152 ms, dominated by the
configurable BatchTimeout). The exact multiples are not citable as properties of the system,
because the CLI measurement includes about 74 ms of process start-up plus TLS and gRPC. It is
an upper bound, symmetric to the lower bound of the local measurement. The chained design
(parent_hash == chainHead) forces each record's commit to be awaited before the next, so it
is not pipelineable. Artefacts in `experiments/runs/fabric_run`.

The dissertation reports these results in Chapter 5 (the Fabric migration) and in the answer to RQ4 in Chapter 6, with the topology limitations: a single orderer, CCaaS TLS off, nominal organisational separation.

### 2026-06-13: Partial hardening: MSPs through Fabric CA, and measurement through the Gateway SDK

Two hardening measures were implemented, the ones a single laptop can exercise: identities
issued by a Fabric CA and measurement through the Gateway:

- **Real MSPs (Fabric CA):** the network was brought up again with `-ca`, with identities
  issued by a separate Fabric CA per organisation (`ca_org1`, `ca_org2`, `ca_orderer`)
  instead of `cryptogen`. Closer to production, though the organisations still share one
  host, so the separation remains nominal.
- **Measurement through the Gateway SDK:** `gateway/gateway_measure.go` (Fabric Gateway SDK in
  Go, a persistent gRPC connection, the User1@org1 identity issued by the CA) replaces the
  CLI measurement. It removes the roughly 74 ms of process start-up. Result over 30 records:
  **endorsement and execution about 11 ms** (median 10, P95 16), **durable commit about
  2040 ms** (BatchTimeout). In `fabric_run/fabric_latency_gateway.json`.
  *Current reading:* what the client times as «endorsement and execution» is a read-only
  `VerifyChain` query through a persistent Gateway connection. The 11 ms figure, and the
  39 ms one below, were measured on chains of different sizes and were superseded by the
  30-record comparison in the addendum of 2026-06-13. A comparison with «the literature's
  50–500 ms» stood here and was withdrawn: that interval was in none of the cited sources
  (see the Claims Register).

**Not done, because a single laptop cannot evaluate them** (documented as future work): on one machine they would run but not be tested against the failures they exist for, so no claim could rest on them:
multiple orderers (Fabric 2.5 needs a custom configtx, with no flag on the test network),
chaincode-to-peer TLS (cosmetic on localhost) and KMS/HSM (which needs real infrastructure;
at best a demonstration with Vault in a container). True institutional separation, with the
organisations on distinct machines and domains, is not portable either.

### 2026-06-13: Hardening the design: issuer registry, O(1) state and CouchDB

The two highest-return items of `ROADMAP_ROBUSTEZ.md` (§2.1 and §2.2/§2.4) were implemented,
all on the laptop, closing findings from the critical review:

**Item 1, issuer registry, re-verifiable signature and MSP binding:**
- `RegisterIssuer(pubKeyHex)` stores authorised issuer keys in state, under
  `issuer~<fingerprint>`. Governance: only `Org1MSP` identities (the authority) may register,
  through `cid.GetMSPID`.
- `SubmitEvidence(recordJSON)` no longer takes the submitter's key: it fetches it from the
  **on-chain registry** by fingerprint, and rejects an unregistered issuer. It stamps the
  submitter's Fabric identity (`SubmitterMSP` and `SubmitterID` through `cid`) as provenance,
  outside the signed body, which `stripDerived` removes.
- `VerifyChain` now **re-verifies the Ed25519 signature** against the registered key, and not
  only the hashes. That is a stronger guarantee than the simulator's, made possible because
  the key is now on chain. *Current-reading note (3 October 2026): the simulator also
  verifies Ed25519 signatures. Fabric adds an issuer registry governed by an MSP and records
  the submitting identity; the difference is issuer governance and network provenance.*
- This closes «non-MSP binding», «VerifyChain does not verify the signature» and «the key came
  from the submitter».

**Item 2, O(1) state, MVCC concurrency and CouchDB:**
- A head pointer `__head__` ({seq, chain_hash}) is read and written on every
  `SubmitEvidence`, so obtaining the head is **O(1)** (it was O(n) per submit, hence O(n²)
  over the chain). Reading and writing the SAME key makes **Fabric's MVCC reject concurrent
  submissions** (a read conflict), serialising in the chaincode rather than in the client,
  which closes the latent race of §2.4.
- Range scans are restricted to `["ev","ew")`, to skip the head and the issuer registry.
- Deployment with **CouchDB** (`-s couchdb`) as the state database, a scalable production
  backend that supports indexes and rich queries, while the chaincode keeps testable range
  scans.

**`go test ./... 7/7 PASS`**, including the new tests for RegisterIssuer governance, the
rejection of an unregistered issuer, and the verified MSP binding of the submitter. Identity
in the tests comes from an ephemeral certificate plus a `SerializedIdentity` in the MockStub
(`setCreator`).

**Confirmed on the CouchDB network (Gateway SDK, 30 records, chain valid 30/30):** evaluate
(VerifyChain, which now also re-verifies signatures) about 39 ms, up from about 11 ms because
of the extra signature work and CouchDB.
Commit about 2072 ms (BatchTimeout). In `fabric_latency_gateway.json`.

**A genuine bug that CouchDB revealed:** CouchDB rejects state keys beginning with `_`, which
it reserves for `_id` and `_rev`. The `headKey` was `__head__` and `SubmitEvidence` failed
with «invalid key, cannot begin with "_"». It was invisible on the default LevelDB and in the
MockStub. It was corrected to `meta~head`. The CouchDB run exposed a state-key restriction
that the LevelDB run and the mock tests had not revealed.

**Design limitations CLOSED by this hardening** (against the LIMITATIONS section): the
issuer-to-MSP binding (there is now a registry, governance and a submitter stamp), VerifyChain
not re-verifying the signature (it now does), O(n²) per submit (now O(1) through the
pointer), the concurrency race (now serialised by MVCC) and a scalable state database
(CouchDB). Still open: a single orderer, CCaaS TLS off, nominal institutional separation,
KMS/HSM, and numeric canonicalisation to RFC 8785.

### To reproduce (summary)
`bash 00_setup_fabric.sh` → `bash deploy/01_up_and_deploy.sh` (which already uses CCaaS as the
PRIMARY route, the one that works on Docker Desktop) → `python3 deploy/02_submit_and_measure.py`
(run right after the deployment, on an empty chain, for a clean run). To stop the network:
`cd ~/fabric-workspace/fabric-samples/test-network && ./network.sh down`.

---

## Limitations (as of June 2026)

This is a **proof of concept of the target stack**, not a production deployment. These are
real limitations, raised in the critical review of 2026-06-13:

**Latency measurement (resolved through the Gateway SDK).** The first measurement
(`02_submit_and_measure.py`, the `peer` CLI) was an upper bound contaminated by about 74 ms
of process start-up. It was replaced by a measurement through
`gateway/gateway_measure.go` (Fabric Gateway SDK, persistent gRPC connection): endorsement
and execution **about 11 ms** (median 10, P95 16), durable commit **about 2040 ms**
(BatchTimeout). The 11 ms no longer include the CLI start-up. Attributing the commit to BatchTimeout=2s
remains an inference, because there was no control run with a smaller timeout, but
endorsement is no longer an upper bound. The result is in
`fabric_run/fabric_latency_gateway.json`, and the CLI version remains as a cross-check in
`fabric_latency.json`.

**Canonical interop.** The Go-to-Python equivalence is **byte-identical over the domain of
the evidence body (string fields and lists of strings)**, proved on real records and on a
hard HTML/non-ASCII vector. It is NOT universal: a round trip through a map coerces numbers
to float64 (1 against 1.0, and large integers lose precision). The signed body has no numeric
fields, so interop holds. A numeric field would demand canonicalisation that preserves
int against float.

**Chaincode (UPDATED after the hardening of items 1 and 2, with several CLOSED).**
(a) ~~O(n²)~~ → **CLOSED**: `SubmitEvidence` uses the O(1) head pointer. `GetEvidence` and
`QueryByRequirement` still scan the `["ev","ew")` range (O(n) per query, not per submit),
which CouchDB rich queries would mitigate.
(b) ~~a latent race imposed by the client~~ → **MITIGATED in the design**: reading and writing
the `meta~head` key makes Fabric's MVCC reject concurrent submissions, serialising in the
chaincode. Caveat (June 2026): this is a property of real Fabric that is **asserted, not tested**,
because the MockStub has no MVCC versioning or conflict. *Superseded on 2026-10-03: the
conflict was observed on a peer, see the addendum of that date.*
(c) ~~VerifyChain does not re-verify the signature~~ → **CLOSED**: it re-verifies each
record's Ed25519 signature against the key registered on chain.
(d) ~~non-MSP binding~~ → **CLOSED**: an issuer registry with governance (`RegisterIssuer`,
authority organisation only) and a stamp of the submitter's Fabric identity (`SubmitterMSP`
and `SubmitterID`).
**Still open (canonicalisation):** `canonicalJSON` is byte-identical to Python only over the
string domain (0x7F was corrected; numbers, null and nil slices would diverge, and that would
require JCS/RFC 8785).

**Topology and security.** A **single** orderer (a one-node Raft, with no fault tolerance): a
narrative of decentralisation has to acknowledge this central point, and multiple orderers on
Fabric 2.5 need a custom configtx, with no flag on the test network. Future work.
**Chaincode-to-peer TLS is disabled** on CCaaS (`TLSProps{Disabled:true}`), for demonstration
only. The MSPs are now issued by **a separate Fabric CA per organisation** (`-ca`, the
ca_org1 and ca_org2 containers), which is closer to production than cryptogen, but Org1 and
Org2 remain **on the same machine**, so the institutional separation is still nominal. The
Ed25519 key is a **demonstration** key, since a real KMS or HSM is not demonstrable on a
laptop and the pattern remains future work. The submission identity's key (User1) is managed
by Fabric's MSP and CA.

**Reproduction.** `fabric-samples` comes from the `main` branch, not pinned to a tag, and the
default `test-network` is assumed intact (paths and ports are hardcoded in
`02_submit_and_measure.py`). The system Go is 1.25.4, while `go.mod` and the Dockerfile pin
`go 1.21`, which is what counts for the build.

---

## Addendum 2026-06-13: Controlled re-measurement of latency (LevelDB against CouchDB)

The loose gateway figures cited above (about 11 ms and about 39 ms) were measured at
different moments with **chains of different sizes**. Because `VerifyChain` re-verifies the
Ed25519 signature of **every** record, its latency scales with the number of records in the
chain, so those values were not comparable with each other. The measurement was redone in a
**controlled** way: the **same 30 records** in both configurations, to isolate the state
engine rather than the size of the chain.

| Config | VerifyChain (evaluate, no ordering) | submit_commit |
|---|---|---|
| LevelDB | about 17 ms (median 16.9, P95 18.4) | about 2031 ms (median 2030.7) |
| CouchDB | about 27 ms (median 27.1, P95 31.6) | about 2054 ms (median 2053.7) |

Artefacts preserved: `experiments/runs/fabric_run/fabric_latency_gateway_leveldb.json`
and `_couchdb.json`, and `fabric_latency_gateway.json` becomes a copy of the LevelDB run, the
primary figure for RQ4. The dissertation (Chapter 5, `subsec:migracao_fabric`, and RQ4 in
Chapter 6, in both trees and the single file) was reconciled to these values. The conclusion
is unchanged: the bottleneck is distributed ordering (BatchTimeout of about 2 s), not the
cryptography and not the endorsement. CouchDB adds about 10 ms to verification.

---

## Addendum 2026-07-05: Block chaining demonstrated (closing an evidence gap)

The «two layers of integrity» paragraph of Chapter 5 (`subsec:migracao_fabric`, added on
2026-06-13) claimed that `configtxlator` exposes the block header's `previous_hash` and that
`peer channel getinfo` confirms it, but there was no artefact and no entry here recording the
execution: the only `configtxlator` runs in the workspace came from the test network's
automatic setup. It was actually executed today: the network was brought up, the issuer was
registered (`RegisterIssuer`, fingerprint 838006e8…), 5 real records were submitted with AND
endorsement, and then:

- `peer channel getinfo` → height 12, previousBlockHash `zgB+VWnN…` (base64) =
  `ce007e5569cd9cc0…` (hex);
- `peer channel fetch newest` and `configtxlator proto_decode` → block 11 with
  `previous_hash = ce007e5569cd9cc0…`, **byte for byte identical** to the one from getinfo.

Artefacts preserved in `experiments/runs/fabric_run/block_chaining/` (getinfo.txt,
last_block.pb and .json, DESCRICAO.txt). The dissertation's sentence needed no change: it
went from assertion to demonstrated. NOTE: the 5-record run used here overwrote
`fabric_run/fabric_latency.json` (the 30-record CLI cross-check). It was restored from git
immediately afterwards, and the reference figures (gateway LevelDB and CouchDB) were never
touched.

---

## Addendum 2026-10-03: The current chaincode on a test network (functional check)

The chaincode as delivered, with the changes of September and October 2026 (the 23-field
struct, `metrics` kept as raw JSON, `scenario_id` as a pointer, the queries returning the
stored JSON, `VerifyChain` compared with the head pointer), was deployed on a two-organisation
test network (Fabric 2.5.10, Fabric CA 1.5.13, LevelDB, CCaaS, AND policy) and exercised
through the delivered Gateway client. Until this date those changes had been tested without a
network only.

- 30 records submitted and committed; `VerifyChain` returned `chain valid: 30 records`, and
  `chain valid: 31 records` after one more record with `scenario_id = null`.
- Refused at endorsement: a submission before `RegisterIssuer`, a registration by Org2, a
  signed record with one field altered, and an earlier record submitted again.
- A proposal endorsed by Org1MSP alone was ordered and then invalidated at commit
  (`ENDORSEMENT_POLICY_FAILURE`). A transaction that fails validation stays in its block,
  marked invalid, and does not change the state.
- **MVCC, observed.** Two proposals endorsed over the same version of `meta~head` were
  submitted one after the other: the first was committed and the second invalidated with
  `MVCC_READ_CONFLICT`. This replaces the «asserted, not tested» caveat of June.
- The 31 records returned by the peer verify with the public key alone, once the two
  fields the chaincode adds at commit are set aside.

This was a functional check, not a measurement series: the figures the dissertation cites
remain those of 2026-06-13 above. A summary and the records are in
`docs/fabric_check_2026-10-03/` of the delivered folder. What it does not show is unchanged:
one orderer, both organisations on one machine, CCaaS without TLS, a demonstration key.
