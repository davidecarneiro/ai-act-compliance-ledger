# Running the article's measurements on the measurement machine

For whoever runs the measurements on the physical machine (the one that hosts
the Fabric network, if possible). Each measurement follows a protocol in this
folder, recorded before it was run; please do not change parameters. If
anything has to differ from what is written here, note it and send the note
back with the results.

## Before any measurement

1. Check out branch `article` of `davidecarneiro/ai-act-compliance-ledger`
   and note the commit (`git rev-parse HEAD`).
2. Python 3.11 or later, in a virtual environment:

       cd Project/prototype/compliance_ledger_sim
       python3 -m venv .venv && . .venv/bin/activate
       pip install -r requirements.txt pytest

3. Run the tests once: `python3 -m pytest tests/ -q` (all must pass).
4. Close other applications; keep the machine on mains power, with sleep
   disabled for the duration (macOS: `caffeinate -i` in front of the command).
   Do not run it inside a container or a virtual machine, and keep the
   repository on the machine's internal disk.

## WP3 — cost of verifiable evidence (about 2 to 5 minutes)

Protocol: `protocols/wp3_ablation.md`.

    cd Project/prototype/compliance_ledger_sim
    caffeinate -i python3 bench_ablation.py --label <machine-name>   # macOS
    python3 bench_ablation.py --label <machine-name>                 # Linux

Use a short label that names the machine, for example `rui-macbook-m1`.
Labels starting with `validation` mark runs that do not count; do not use
that prefix here.

The script writes one file,
`Project/experiments/article/wp3/ablation_<label>_<UTC time>.json`, with the
environment, every observation and the summaries. Send that file back (or
commit it on a branch), together with the commit hash and any note.

Run it once. If it has to be repeated (interrupted, machine busy), keep both
files and say why.

## WP7 — Fabric anchoring (about 1 hour of machine time, mostly waiting)

Protocol: `protocols/wp7_fabric_anchoring.md`. It needs the Fabric test
network of the dissertation (`fabric_migration/00_setup_fabric.sh` already
run, Docker running) and Go 1.24 or later. Run WP3 first, or on another day:
the two must not overlap.

In the same virtual environment, add the credit case's dependencies (the
credit case is anchored on the chain too):

    pip install -r Project/prototype/credit_case/requirements.txt

**1. Prepare the inputs** (no network needed, about a minute; the engine signs
with its own key, created on first use):

    cd Project/prototype/fabric_migration/wp7
    python3 run_wp7.py prepare --out ~/wp7-prep

**2. BatchTimeout 2 s, LevelDB** (about 40 minutes):

    cd ../deploy && BATCH_TIMEOUT=2s bash 01_up_and_deploy.sh
    cd ../wp7 && caffeinate -i python3 run_wp7.py measure --prep ~/wp7-prep --label <machine-name>-bt2s

**3. BatchTimeout 250 ms, LevelDB** (about 8 minutes):

    cd ../deploy && BATCH_TIMEOUT=250ms bash 01_up_and_deploy.sh
    cd ../wp7 && caffeinate -i python3 run_wp7.py measure --prep ~/wp7-prep --label <machine-name>-bt250ms

**4. CouchDB, queries only** (about 5 minutes):

    cd ../deploy && BATCH_TIMEOUT=250ms STATE_DB=couchdb bash 01_up_and_deploy.sh
    cd ../wp7 && caffeinate -i python3 run_wp7.py measure --prep ~/wp7-prep --label <machine-name>-couchdb --queries-only

On Linux, drop `caffeinate -i`. Each `01_up_and_deploy.sh` takes the network
down and brings a fresh one up, so every run starts from an empty ledger. The
same `~/wp7-prep` folder serves the three runs; do not prepare it again in
between.

**5. Summary and tear-down:**

    python3 run_wp7.py summarise ../../../experiments/article/wp7/fabric_<machine-name>-*.json
    cd ~/fabric-workspace/fabric-samples/test-network && ./network.sh down
    mv configtx/configtx.yaml.bak configtx/configtx.yaml    # restores BatchTimeout 2s

**Send back** everything the runs wrote under
`Project/experiments/article/wp7/` (three `fabric_*.json` files, the
`credit_case_*` folder, the `summary_*.json` file), `~/wp7-prep/manifest.json`,
the commit hash and any note. If a run stops with an error, keep what it
wrote and send the message: the runner stops at the first failed submission
rather than continue with a broken network.

A single-organisation endorsement check is part of each run: it is expected
to be refused (`ENDORSEMENT_POLICY_FAILURE`), and the runner records the
refusal; a message about it is not an error.
