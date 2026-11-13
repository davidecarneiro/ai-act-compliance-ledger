# Run note — WP3 and WP7 on `davide-m4pro`, 2026-11-13

Measurements launched by Claude Code on Davide Carneiro's Mac (Apple M4 Pro,
macOS 26.6.2, Docker Desktop 14 CPUs / 8 GB), following
`protocols/RUNNING_MEASUREMENTS.md`, `wp3_ablation.md` and
`wp7_fabric_anchoring.md`. No protocol parameter was changed.

- Starting commit: `443c604a8af9d9ec20af7546c7e99f606ce17060` (branch `article`).
- Python 3.12.7 virtual environment; `pytest tests/ -q`: 261 passed.
- Go 1.27.4 was already installed (≥ 1.24), so `brew install go` was not run.
- Fabric 2.5.10 / CA 1.5.13 installed with `00_setup_fabric.sh` (arm64 images).
- `~/wp7-prep` was prepared once and served all WP7 runs; the engine key
  created by `prepare` was kept.

## Files that count

| Measurement | File |
| --- | --- |
| WP3 | `wp3/ablation_davide-m4pro_20261113T090759Z.json` |
| WP7, BatchTimeout 2 s, LevelDB | `wp7/fabric_davide-m4pro-bt2s_20261113T090921Z.json` (+ `credit_case_davide-m4pro-bt2s_20261113T090921Z/`) |
| WP7, BatchTimeout 250 ms, LevelDB | `wp7/fabric_davide-m4pro-bt250ms_20261113T101547Z.json` (+ `credit_case_davide-m4pro-bt250ms_20261113T101547Z/`) |
| WP7, CouchDB, queries only | `wp7/fabric_davide-m4pro-couchdb_20261113T102152Z.json` |
| WP7 summary | `wp7/summary_20261113T102316Z.json` (built from the three files above only) |
| Prepared inputs | `wp7/manifest.json` (copy of `~/wp7-prep/manifest.json`) |

In every WP7 run all submissions, anchors and queries succeeded, and the
single-organisation check was refused with `ENDORSEMENT_POLICY_FAILURE`, as
expected.

## Deviations

1. **Other workload during the first WP3 run and the first 2 s run.** Seven
   unrelated Docker containers had been running for two days (aas-gui,
   aas-innoa, agents_db, flexmas-mongo-demo, flexmas-mongo-express,
   visionware-concursos-qdrant-1, visionware-concursos-mongo-1; about 3 % CPU
   in total and about 2.1 GB of Docker's 8 GB). This was noticed in the
   container list that the first WP7 run records. The containers were then
   stopped (not removed), and WP3 and the 2 s run were repeated with nothing
   else running. The first files are kept but superseded and are **not**
   used:
   `wp3/ablation_davide-m4pro_20261113T074543Z.json`,
   `wp7/fabric_davide-m4pro-bt2s_20261113T074915Z.json`,
   `wp7/credit_case_davide-m4pro-bt2s_20261113T074915Z/`.
   Because of them, `run_wp7.py summarise` was given the three valid files
   explicitly instead of the glob `fabric_davide-m4pro-*.json`.
2. **Network stopped instead of taken down before the WP3 repeat.** The Fabric
   containers from the first 2 s run were stopped with `docker stop`, not
   `network.sh down`, so that nothing ran during WP3. The next
   `01_up_and_deploy.sh` took the network down as usual.
3. **Leftover chaincode containers.** `network.sh down` does not remove the
   chaincode-as-a-service containers (`peer0org{1,2}_compliance_ccaas`). The
   first bring-up for 250 ms failed with a container-name conflict
   ("Conflict. The container name "/peer0org1_compliance_ccaas" is already in
   use"); no measurement ran and nothing was written. The two stale containers
   were removed (`docker rm -f`, no volumes) before the 250 ms bring-up was
   repeated unchanged, and again before the CouchDB bring-up. The two
   containers from the CouchDB run are still present after the final
   tear-down.

## Tear-down

`network.sh down` done; `configtx/configtx.yaml.orig` moved back
(BatchTimeout 2s, as shipped).
