# Verification report of the delivered version

2 and 3 October 2026. What was run on this version of the folder, with what result,
what was not run, and the limitations that remain. The results below are
functional checks. They are not a new experimental series: the measurements the
dissertation cites are the ones recorded under `experiments/`, and the timings
printed by these runs must not replace them.

## Environment

macOS 15.8.1 (x86_64), Python 3.9.6 with cryptography 41.0.7, jsonschema 4.25.1
and pytest 7.4.3, Go 1.25.4 with the vendored dependencies. The Python
quick-start was also run in a fresh virtual environment created from
`requirements.txt`.

## Checks run on a copy of the delivered folder

| Command (folder) | Result |
|---|---|
| `python3 verify_delivery.py` (`prototype/compliance_ledger_sim`) | 7 chains, 1,831 records, all valid and equal to the published anchors |
| `python3 -m pytest tests/ -q` (same) | 98 passed |
| `python3 validate_oscal_schema.py --expect 18` (same) | 18/18 valid against the NIST OSCAL 1.1.2 schema |
| `python3 -m pytest test_bridge.py -q` (`prototype/multiflow_bridge`) | 4 passed |
| `go vet` and `go test -count=1 ./...` (`prototype/fabric_migration/chaincode`) | 10 passed, none skipped |
| `python3 test_interop.py` (`prototype/fabric_migration/interop`) | 6/6 vectors, three of them real record bodies |
| `go build` of the chaincode and of `gateway/gateway_measure.go` | builds |
| `shasum -a 256 -c LEDGER_EXPLORER.html.sha256` (`ledger_explorer`) | OK |

The commands of the demonstration guide that need no Docker (section 3.A:
`simulator.py`, `compare_oracle_vs_baseline.py`, `oscal_exporter.py`,
`validate_oscal_schema.py`, `incident_demo.py`, and `sensitivity.py`) all ran
to completion in a copy of the folder. As the guide now warns, they write new
records over the published canonical and incident ledgers; afterwards
`verify_delivery.py` reported those two chains as NOT PUBLISHED and exited with
an error, which is the intended behaviour.

**Docker route, 2 October 2026.** Sections 3, 5 and 6 of the README were run
from a clean copy of this folder, with `MULTIFLOW` and `EXPERIMENTS_DIR`
pointing outside it, on Docker 29.7.2 with Compose 5.4.0. The script cloned
MultiFlow at the pinned commit `a0a9786`, built the bridge image, brought up
ZooKeeper, Kafka (Confluent 7.6.1) and Kafdrop, and published the synthetic
stream: 4 events, 2 approved and 2 escalated, `chain 4/4 INTACT`, archived in
`results/demo/runs/multiflow_run/`. The industrial-data script then gave 29
events, 12 approved and 17 escalated, `chain 29/29 INTACT`, the same counts and
the same sequence of decisions as the published run. Both ledgers verified
again from the host with the simulator alone. Three malformed messages
published to the topic (not JSON, a two-column row, a row with `nan`) were
logged as skipped and the bridge kept running; the first attempt at this check
found that a non-JSON payload stopped the consumer, which was corrected before
the final run. The first `docker compose up` failed to pull the base image
(`DeadlineExceeded`) on a daemon that had just started, and succeeded once the
image was pulled separately. These runs produced new records and were not
archived in `experiments/`; the published runs remain those of 13 June 2026.

**Start to finish, 2 October 2026.** The README was then followed from a
clean copy, in order. Section 3 cloned MultiFlow again and gave 4 events,
chain 4/4. Section 4, after `npm install` in the three applications and the
service subset (this time the `node` and `websocket` images were built from the
pinned clone), created the project and the stream in the browser; the first
start produced no event, because the bridge still held the 3-column reference
of the synthetic stream and skipped the 409 11-column rows, which is now
stated in section 4 together with the restart that fixes it; after the restart
the stream gave the 19 expected batches and the working ledger verified 23/23.
Section 5 gave 29 events, 12 approved and 17 escalated, chain 29/29. Section 6's
commands ran as printed. Section 7.1 was run with 60 five-column rows
published to `my_topic`: a bridge on the host connected to `localhost:9092`
and received nothing, because the broker advertises `kafka:9092` (now in the
README and in the troubleshooting table); the same bridge run as a container on
the broker's network produced 2 events, approved then escalated, verified from
the host, with the OSCAL export command as printed. Section 7.2's two code
blocks ran as printed, creating a key pair for `my-platform` and a one-record
ledger that verified with the public key alone. Section 8 passed as in the
table above.

**Review of the README, 3 October 2026.** After an external review of the
README, its commands were made independent of the current directory and of
the terminal (a set-up block in section 2 that every terminal runs), and the
verification snippets of sections 6 and 7.2 were changed to exit with a
non-zero status on a broken or empty chain. Both snippets were re-run as
printed: on the real-data run of section 5 (exit 0, `chain 29/29 INTACT`), on
a copy with one record's decision altered (exit 1, record 7 named with its
three failing checks), and on an empty ledger (exit 1, `EMPTY`). The new
explorer step of section 6 was tried in a browser: the real-data run pasted
on **Open a ledger** verified 29/29 with the demonstration key recognised; the
one-record ledger of section 7.2 opened as «not trusted, signatures not
verified» until its public key was pasted under **Trust this key**, after
which it verified 1/1 under the issuer `my-platform`.

A second pass on the README on the same day made the container example of
section 7.1 runnable as printed (`docker build` from this repository, the
broker's network and address in variables) and moved the OSCAL export to a
script that takes its paths as arguments. Both were run as printed: the image
built and imported the bridge module, and the export wrote the redacted
document for the `my_platform` run.

**Interface route, first run, 2 October 2026.** Section 4 of the README was then run on
the same stack: `npm install` in `app/node`, `app/react-app` and `app/ws` of the
pinned clone, the React interface started with `npm start`, and in the browser
a project was created with one stream on topic `phd_kafka`, file
`Muvu_Janeiro.csv`, 20 lines per second. Starting the project streamed the 409
rows in about twenty seconds; the bridge logged 19 batches, 12 approved and 7
escalated, in the same order as the first 19 batches of the published
real-data run, and `verify_output.py` reported the working ledger intact
(48/48, the 29 records of the previous run plus these 19). Two details of the
interface differ from the platform's README and are reflected in section 4:
the form's playback field is `Playback Configuration Type`, and a stream is
started from the play button of the project, not from the stream itself.

The explorer was opened in a browser over HTTP and its main pages (home,
verification, one-pager, decisions, connection, audit bench, an article page,
the tour) rendered without console errors.

**Fabric test network, 3 October 2026.** The current chaincode was deployed on
a two-organisation test network (Fabric 2.5.10, Fabric CA 1.5.13, LevelDB,
CCaaS, AND policy) from a copy of the delivered folder, and exercised through
the delivered Gateway client: 30 records committed and `chain valid: 30
records`; a submission before `RegisterIssuer`, a registration by Org2, an
altered signed record and a repeated record refused; a proposal endorsed by
one organisation invalidated at commit (`ENDORSEMENT_POLICY_FAILURE`); of two
proposals endorsed over the same head, the second invalidated
(`MVCC_READ_CONFLICT`); a record with `scenario_id = null` committed and
returned as `null`; `chain valid: 31 records` at the end. The 31 records
returned by the peer verify with the public key alone. The summary, the
records and the command that re-verifies them are in
`docs/fabric_check_2026-10-03/`. The network was brought up from a copy of
`fabric-samples` with the parameters of `deploy/01_up_and_deploy.sh`; that
script and the CouchDB configuration were not run. The timings of this run
(about 2,036 ms to commit, about 20 ms for a `VerifyChain` query) are those of
a functional check and do not replace the figures the dissertation cites.

**Editorial review, 3 October 2026.** After a review of comments and
documents for publication, comments in the code, the demonstration guide, the
registers under `traceability/`, the migration log and the explorer's texts
were revised. No logic changed; the test suites of the table above were run
again with the same results, and the explorer was regenerated.

## Not run

- `deploy/01_up_and_deploy.sh` and `deploy/02_submit_and_measure.py` as
  printed, and the LevelDB/CouchDB comparison, on the current chaincode.
- The simulator's own container image (`make docker-build`).
- In section 4, `docker compose up -d --build` of the whole platform: the images
  of the platform's own services (`node`, `websocket`, `faust`, `appapi`,
  `grafana`) were reused from an earlier build on the same machine, and only the
  services the route needs were started (ZooKeeper, Kafka, Kafdrop, MongoDB,
  `node`, `websocket` and the bridge, the last one built from this folder). A
  fresh build of the Grafana image failed on this machine (`apk upgrade`, exit
  127); that image is not needed to stream.
- A new measurement series on Fabric. The network runs the dissertation
  reports are from June and July 2026, with the June version of the chaincode.
- An audit of the vendored third-party code.

## Limitations that remain

- `decision = verified` on an `audit_query` record means that an audit request
  was recorded. It is not the result of an integrity check, which is
  `verify_chain()` and is not written into the record.
- `require_hash_verification` in `configs/policies.json` is declared but not
  read by the code. It stays because the policy identifier is derived from the
  file's content.
- The anchors `verify_delivery.py` compares against, the explorer's
  `.sha256` and `MANIFEST.sha256` all live inside this folder. They catch
  regeneration and accidental damage. Against deliberate replacement they help
  only when their values are compared with copies kept elsewhere.
- The demonstration private key ships in the folder, so anyone holding it can
  sign new records. A valid signature shows that a record has not changed since
  it was signed with that key, not who signed it or when.
- `VerifyChain` in the chaincode now compares the end of the chain with the
  head pointer, but the pointer lives in the same state as the records.
- The bridge's drift score is an illustrative indicator, not a validated
  detector, and its precision, parity gap and human approval are configured
  values, not measurements.
- `requirements.txt` sets minimum versions and the container images are tagged,
  not pinned by digest. The simulator uses `fcntl`, so on Windows it needs WSL.
