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

## WP7 — Fabric anchoring

Instructions will be added here with the WP7 scripts, before any
measurement.
