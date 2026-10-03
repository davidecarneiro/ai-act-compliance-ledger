# The bridge logs of the MultiFlow runs

Each `multiflow_run*/bridge_log.txt` is the bridge container's log as it stood
when the run was archived. The log is cumulative: it also holds the output of
the runs that came before it, each starting with two reconnection lines. The
bridge's connection messages in these logs are in Portuguese, the language of
the code at the time. The files are
published as archived; this note says which lines belong to which ledger.

| Log | Batches in the log | Ledger | Correspondence |
|---|---|---|---|
| `multiflow_run/bridge_log.txt` | 4 | 8 records | The four batches are records 5 to 8 of the ledger. The log is not a complete log of the eight records. |
| `multiflow_run_real/bridge_log.txt` | 33 | 29 records | Lines 1 to 10 are the earlier synthetic run. The real-data run reconnects at lines 11 and 12, and its 29 batches are recorded from line 13 onwards. |
| `multiflow_run_steel/bridge_log.txt` | 1,783 | 1,750 records | Lines 1 to 70 are earlier runs. The Steel run reconnects at lines 71 and 72, and its 1,750 batches are recorded from line 73 onwards. |

In each case the `chain_hash` prefixes printed in the segment named above match
the `chain_hash` of the corresponding ledger records, in order. The ledgers,
not the logs, are the evidence: `python3 verify_delivery.py` re-verifies them.
