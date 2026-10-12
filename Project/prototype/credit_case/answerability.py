"""Answerability of the fourteen audit questions (WP5 of the article plan).

Protocol: ``Project/protocols/wp5_answerability.md``, recorded before this
was written. The credit case's 16 events and two declared synthetic incident
events go through the configurations of the WP3 ablation; each question is
then put, as a program, to what an auditor of each configuration holds:

* A — arm A's SQLite table;
* B — arm B's signed ledger, the issuer's public key, the policy archive and
  the artefact store;
* C — arm B+ anchored after every record (stand-in for the Fabric ledger),
  with the anchor file, the policy archive, the store and the complete OSCAL
  export;
* D — the redacted OSCAL export alone.

    python3 answerability.py
"""

from __future__ import annotations

import base64
import copy
import json
import shutil
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import credit_case as cc
from ablation_arms import make_arms, verify_anchored, verify_signed
from approvals import check_approval
from artifact_store import ArtifactStore, verify_ledger_artifacts
from keys import load_or_create_key
from ledger_store import read_ledger
from oscal_exporter import OSCAL_NS, to_oscal_sar
from reexecution import reexecute_ledger
from simulator import ISSUER_ID_V2, requirements_of

OUT_DIR = cc.EXPERIMENTS_DIR / "wp5"
CONFIGURATIONS = ("A", "B", "C", "D")
COMPLETENESS_QUESTIONS = {"Q1", "Q2", "Q7", "Q8", "Q9", "Q11"}
RUN_R = "gc-run-2"

YES, PARTIAL, NO, NA = "yes", "partial", "no", "n/a"


# ----------------------------------------------------------------------
# Evidence
# ----------------------------------------------------------------------

def incident_events(model_event: dict) -> List[dict]:
    """The two synthetic incident events (declared in the protocol)."""
    base = {k: model_event[k] for k in ("artifact_id", "artifact_type", "run_id",
                                        "artifact_sha256", "off_chain_ref")}
    return [
        {**base, "scenario_id": "synthetic-incident", "event_type": event_type,
         "pipeline_stage": "post_deploy_monitoring", "risk_level": "high"}
        for event_type in ("serious_incident_detected", "incident_reported_to_authority")
    ]


def build_evidence(folder: Path) -> Dict:
    folder.mkdir(parents=True)
    store = ArtifactStore(folder / "store")
    events = cc.build_events(store, cc.MAIN_SEED, cc.approver_key()).events
    model_v2 = next(e for e in events if e["run_id"] == RUN_R and e["event_type"] == "model_trained")
    events += incident_events(model_v2)

    policy = json.loads(cc.POLICY_FILE.read_text(encoding="utf-8"))
    policy_file = folder / "policies.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    key = load_or_create_key(ISSUER_ID_V2)          # the engine's own key
    arms = make_arms(folder / "arms", policy_file, policy, key, interval=1)
    for event in events:
        for name in ("A", "B", "Bplus"):
            arms[name].process(copy.deepcopy(event))
    for arm in arms.values():
        arm.close()
    (folder / "arms" / "B0.jsonl").unlink(missing_ok=True)

    records_c = read_ledger(folder / "arms" / "Bplus.jsonl")
    integrity_c = verify_anchored(records_c, key, folder / "arms" / "external" / "anchors.jsonl")
    for redacted, name in ((False, "complete"), (True, "redacted")):
        doc = to_oscal_sar(records_c, chain_valid=integrity_c["valid"], redacted=redacted,
                           signatures_verified=integrity_c["valid"])
        (folder / f"oscal_assessment_results_{name}.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    (folder / "keys").mkdir()
    shutil.copy2(cc.SIM / "keys" / f"{ISSUER_ID_V2}.ed25519.pub.pem", folder / "keys")
    return {"events": len(events), "key": key}


# ----------------------------------------------------------------------
# Views: what each auditor holds
# ----------------------------------------------------------------------

@dataclass
class View:
    name: str
    fields: set
    items: List[dict]
    integrity: Dict = field(default_factory=dict)
    archive: Optional[Path] = None
    store: Optional[ArtifactStore] = None
    oscal: Optional[dict] = None
    anchored: bool = False
    check: Optional[Callable[[], Dict]] = None    # the configuration's own integrity check


def _a_items(db_file: Path) -> List[dict]:
    c = sqlite3.connect(str(db_file))
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute("SELECT * FROM events ORDER BY id")]
    c.close()
    return [{
        "event_type": r["event_type"], "stage": r["pipeline_stage"], "artifact_name": r["artifact_id"],
        "time": r["timestamp"], "decision": r["decision"], "rule_id": r["rule_id"],
        "reason": r["reason"], "metrics": json.loads(r["metrics_json"] or "{}"),
    } for r in rows]


def _ledger_items(records: List[dict]) -> List[dict]:
    return [{
        "event_type": r["event_type"], "stage": r["pipeline_stage"], "artifact_name": r["artifact_id"],
        "artifact_digest": r.get("artifact_hash"), "time": r["timestamp"], "decision": r["decision"],
        "rule_id": r["rule_id"], "reason": r["reason"], "metrics": r.get("metrics") or {},
        "run_id": r.get("run_id"), "approval": (r.get("decision_inputs") or {}).get("approval"),
        "policy_id": r.get("policy_id"), "policy_hash": r.get("policy_hash"),
        "supports": requirements_of(r), "issuer": r.get("issuer_id"),
        "issuer_fingerprint": r.get("issuer_pubkey_fingerprint"), "evidence_id": r["evidence_id"],
        "submitter": r.get("submitter_msp"), "_record": r,
    } for r in records]


def _oscal_items(doc: dict) -> List[dict]:
    result = doc["assessment-results"]["results"][0]
    observations = {o["uuid"]: o for o in result["observations"]}
    items = []
    for finding in result["findings"]:
        props = {}
        for p in finding.get("props", []):
            props.setdefault(p["name"], []).append(p["value"])
        obs = observations[finding["related-observations"][0]["observation-uuid"]]
        oprops = {p["name"]: p["value"] for p in obs.get("props", [])}
        items.append({
            "time": obs.get("collected"), "decision": oprops.get("decision"),
            "rule_id": (props.get("rule-id") or [None])[0],
            "objective": finding["target"]["target-id"],
            "status": finding["target"]["status"]["state"],
            "supports": props.get("supports-requirement", []),
            "policy_hash": (props.get("policy-hash") or [None])[0],
            "policy_id": (props.get("policy-id") or [None])[0],
            "issuer": oprops.get("issuer"),
            "evidence_id": obs["relevant-evidence"][0]["href"].split(":")[-1],
        })
    return items


def load_views(folder: Path, key) -> Dict[str, View]:
    arms = folder / "arms"
    records_b = read_ledger(arms / "B.jsonl")
    records_c = read_ledger(arms / "Bplus.jsonl")
    archive = folder / "policies_archive"
    store = ArtifactStore(folder / "store")
    complete = json.loads((folder / "oscal_assessment_results_complete.json").read_text(encoding="utf-8"))
    redacted = json.loads((folder / "oscal_assessment_results_redacted.json").read_text(encoding="utf-8"))
    ledger_fields = {"event_type", "stage", "artifact_name", "artifact_digest", "time", "decision",
                     "rule_id", "reason", "metrics", "run_id", "approval", "policy_id",
                     "policy_hash", "supports", "issuer", "evidence_id"}
    return {
        "A": View("A", {"event_type", "stage", "artifact_name", "time", "decision", "rule_id",
                        "reason", "metrics"}, _a_items(arms / "A.sqlite"),
                  integrity={"valid": None, "method": "none"}),
        "B": View("B", ledger_fields, _ledger_items(records_b),
                  integrity=verify_signed(records_b, key), archive=archive, store=store,
                  check=lambda: verify_signed(read_ledger(arms / "B.jsonl"), key)),
        "C": View("C", ledger_fields, _ledger_items(records_c),
                  integrity=verify_anchored(records_c, key, arms / "external" / "anchors.jsonl"),
                  archive=archive, store=store, oscal=complete, anchored=True,
                  check=lambda: verify_anchored(read_ledger(arms / "Bplus.jsonl"), key,
                                                arms / "external" / "anchors.jsonl")),
        "D": View("D", {"time", "decision", "rule_id", "objective", "status", "supports",
                        "policy_hash", "issuer", "evidence_id"}, _oscal_items(redacted),
                  integrity={"valid": None, "method": "none"}, oscal=redacted),
    }


# ----------------------------------------------------------------------
# Questions
# ----------------------------------------------------------------------

@dataclass
class Answer:
    answerable: str
    value: object = None
    missing: List[str] = field(default_factory=list)
    records_read: int = 0


def _classify(view: View, needed: List[str]) -> tuple:
    missing = [f for f in needed if f not in view.fields]
    if not missing:
        return YES, []
    return (PARTIAL if len(missing) < len(needed) else NO), missing


def _deployments(view: View) -> List[dict]:
    return [i for i in view.items if i.get("event_type") == "deployment_request"]


def q1(view: View) -> Answer:
    if "event_type" not in view.fields:
        return Answer(NO, missing=["which records are deployment requests", "artefact digest"],
                      records_read=len(view.items))
    status, missing = _classify(view, ["artifact_digest", "time", "decision"])
    deps = _deployments(view)
    value = {
        "requests": [{k: d.get(k) for k in ("artifact_name", "artifact_digest", "decision", "time")}
                     for d in deps],
        "approved": [d.get("artifact_digest") or d.get("artifact_name")
                     for d in deps if d["decision"] == "approved"],
    }
    return Answer(status, value, missing, len(view.items))


def q2(view: View) -> Answer:
    if "event_type" not in view.fields or "approval" not in view.fields:
        return Answer(NO, missing=["approvals and their approvers"], records_read=len(view.items))
    out = []
    for d in _deployments(view):
        approval = d.get("approval")
        if approval is None:
            out.append({"evidence_id": d.get("evidence_id"), "approval": None,
                        "decision": d["decision"]})
            continue
        policy = json.loads((view.archive / f"{d['policy_id']}.json").read_text(encoding="utf-8"))
        rule, reason = check_approval(approval, policy.get("authorised_approvers", {}),
                                      d.get("artifact_digest"), d.get("run_id"))
        out.append({"evidence_id": d.get("evidence_id"), "approver": approval["approver_id"],
                    "authorised_and_verifies": rule is None, "check": reason,
                    "decision": d["decision"], "rule_id": d["rule_id"]})
    return Answer(YES, {"deployment_requests": out,
                        "deployment_approved": any(d["decision"] == "approved" for d in out)},
                  records_read=len(view.items))


def q3(view: View) -> Answer:
    gated = [i for i in view.items if i.get("stage") in ("validation", "deployment")] \
        if "stage" in view.fields else view.items
    if view.name == "D":
        return Answer(PARTIAL, [{"rule_id": i["rule_id"], "status": i["status"],
                                 "policy_hash": i["policy_hash"]} for i in gated
                                if (i["rule_id"] or "").startswith("threshold.")],
                      ["metric values", "thresholds", "which records are validation decisions"],
                      len(view.items))
    out, missing = [], []
    thresholds = None
    if view.archive is not None:
        thresholds = {}
        for i in gated:
            policy = json.loads((view.archive / f"{i['policy_id']}.json").read_text(encoding="utf-8"))
            thresholds[i["policy_id"]] = {k: policy[k] for k in
                                          ("min_precision", "max_demographic_parity_diff")}
    else:
        missing = ["thresholds of the deciding policy (only the failing one, in the reason text)"]
    for i in gated:
        out.append({"event_type": i["event_type"], "metrics": i["metrics"], "decision": i["decision"],
                    "rule_id": i["rule_id"],
                    "thresholds": thresholds[i["policy_id"]] if thresholds else i["reason"]})
    return Answer(PARTIAL if missing else YES, out, missing, len(view.items))


def q4(view: View) -> Answer:
    if view.name == "D":
        fairness = [i for i in view.items if i["objective"] == "obj-fairness-threshold"]
        return Answer(PARTIAL, [{"time": i["time"], "outcome": i["status"]} for i in fairness],
                      ["metric value", "order relative to the deployment request"], len(view.items))
    deps = sorted(i["time"] for i in _deployments(view))
    first = deps[0] if deps else None
    out = [{"event_type": i["event_type"], "artifact": i.get("artifact_digest") or i["artifact_name"],
            "parity": i["metrics"]["demographic_parity_diff"], "decision": i["decision"],
            "time": i["time"]}
           for i in view.items if "demographic_parity_diff" in i["metrics"]
           and (first is None or i["time"] < first)]
    return Answer(YES, {"first_deployment_request": first, "examinations": out},
                  records_read=len(view.items))


def q5(view: View) -> Answer:
    status, missing = _classify(view, ["run_id", "artifact_digest", "event_type"])
    if status != YES:
        return Answer(NO if status == NO or "run_id" in missing else status, missing=missing,
                      records_read=len(view.items))
    trained = [i for i in view.items if i["event_type"] == "model_trained" and i["run_id"] == RUN_R][0]
    dataset = [i for i in view.items if i["event_type"] == "data_ingested"
               and i["run_id"] == trained["run_id"]][0]
    split = [i for i in view.items if i["event_type"] == "data_split"
             and i["run_id"] == trained["run_id"]][0]
    stored = {s["evidence_id"]: s["status"] for s in
              verify_ledger_artifacts([dataset["_record"], split["_record"], trained["_record"]],
                                      view.store)}
    return Answer(YES, {"model": trained["artifact_digest"], "dataset": dataset["artifact_digest"],
                        "partition": split["artifact_digest"], "artefacts_in_store": stored},
                  records_read=len(view.items))


def q6(view: View) -> Answer:
    if view.name == "D":
        return Answer(PARTIAL, sorted({i["policy_hash"] for i in view.items if i["policy_hash"]}),
                      ["re-execution (no decision inputs, no policy content)"], len(view.items))
    if view.archive is None:
        return Answer(NO, missing=["policy identity", "decision inputs", "policy archive"],
                      records_read=len(view.items))
    summary = reexecute_ledger([i["_record"] for i in view.items], view.archive)
    return Answer(YES, {"policies": sorted({i["policy_id"] for i in view.items}),
                        "reexecution": summary["counts"]}, records_read=len(view.items))


def q7(view: View) -> Answer:
    if "run_id" not in view.fields:
        return Answer(NO, missing=["run identifier"], records_read=len(view.items))
    members = [i["evidence_id"] for i in view.items if i["run_id"] == RUN_R]
    return Answer(YES, {"run": RUN_R, "events": len(members), "evidence_ids": members},
                  records_read=len(view.items))


def q8(view: View) -> Answer:
    alerts = [{"time": i["time"], "decision": i["decision"]} for i in view.items
              if i.get("rule_id") == "monitoring.drift_alert"]
    if view.name == "D":
        return Answer(PARTIAL, {"alerts": alerts}, ["order relative to deployment"], len(view.items))
    deps = sorted(i["time"] for i in _deployments(view))
    return Answer(YES, {"alerts": alerts, "first_deployment_request": deps[0] if deps else None,
                        "deployment_approved": any(i["decision"] == "approved" for i in _deployments(view))},
                  records_read=len(view.items))


def q9(view: View) -> Answer:
    drift = [i["time"] for i in view.items if i.get("rule_id") == "monitoring.drift_alert"]
    incident = [i["time"] for i in view.items if i.get("rule_id") == "incident.reportable"]
    if not drift or not incident:
        return Answer(NO, missing=["drift alert or incident"], records_read=len(view.items))
    return Answer(YES, {"drift_alert": drift[0], "incident": incident[0],
                        "drift_precedes_incident": drift[0] < incident[0]},
                  records_read=len(view.items))


def q10(view: View) -> Answer:
    if view.name in ("A", "D"):
        return Answer(NO, missing=["any integrity check"], records_read=0)
    report = view.check()                         # timed: the check is the answer
    valid = report["valid"]
    if view.anchored:
        return Answer(YES, {"altered": not valid, "issues": report["issues"][:5]},
                      records_read=len(view.items))
    return Answer(PARTIAL, {"altered_without_the_key": not valid},
                  ["an alteration re-signed by the key holder"], len(view.items))


def q11(view: View) -> Answer:
    if not view.anchored:
        return Answer(NO, missing=["anything outside the issuer's reach to exclude truncation"],
                      records_read=len(view.items))
    report = view.check()                         # timed: the check is the answer
    first = next(k for k, i in enumerate(view.items) if i["run_id"] == RUN_R)
    return Answer(YES, {"t1_record": first + 1, "t2_record": len(view.items),
                        "complete_up_to_last_anchor": report["valid"],
                        "anchors": report.get("anchors")}, records_read=len(view.items))


def q12(view: View) -> Answer:
    if view.name == "A":
        return Answer(NO, missing=["submitter"], records_read=len(view.items))
    submitters = {i.get("submitter") for i in view.items}
    if submitters != {None}:
        return Answer(YES, sorted(s for s in submitters if s), records_read=len(view.items))
    issuers = sorted({i["issuer"] for i in view.items})
    return Answer(PARTIAL, {"issuers": issuers},
                  ["organisation (in Fabric, stamped by the chaincode as submitter_msp)"],
                  len(view.items))


def q13(view: View) -> Answer:
    if "supports" not in view.fields:
        return Answer(NO, missing=["provisions supported"], records_read=len(view.items))
    out = {}
    for i in view.items:
        outcome = i.get("status") or i["decision"]
        for article in i["supports"]:
            out.setdefault(article, {}).setdefault(outcome, 0)
            out[article][outcome] += 1
    return Answer(YES, out, records_read=len(view.items))


def q14(view: View, reference: View) -> Answer:
    if view.name != "D":
        return Answer(NA)
    text = json.dumps(view.oscal, ensure_ascii=False)
    needles = {}
    for i in reference.items:
        needles[f"artifact name {i['artifact_name']}"] = i["artifact_name"]
        if i.get("artifact_digest"):
            needles[f"artefact digest {i['artifact_digest'][:12]}…"] = i["artifact_digest"]
        needles[f"subject UUID of {i['artifact_name']}"] = str(
            uuid.uuid5(OSCAL_NS, f"subj:{i['artifact_name']}"))
        needles[f"reason '{i['reason'][:40]}'"] = i["reason"]
        for metric, value in i["metrics"].items():
            needles[f"metric {metric}={value}"] = repr(value)
        needles[f"scenario {i['_record'].get('scenario_id')}"] = i["_record"].get("scenario_id") or "\u0000"
    for key in ("min_precision", "max_demographic_parity_diff", "drift_alert_threshold",
                "authorised_approvers", "metric_threshold_stages"):
        needles[f"policy field {key}"] = key
    found = sorted({label for label, needle in needles.items() if needle and needle in text})
    return Answer(YES, {"disclosed": found, "checked": len(needles)},
                  records_read=len(view.items))


QUESTIONS: Dict[str, Callable] = {
    "Q1": q1, "Q2": q2, "Q3": q3, "Q4": q4, "Q5": q5, "Q6": q6, "Q7": q7,
    "Q8": q8, "Q9": q9, "Q10": q10, "Q11": q11, "Q12": q12, "Q13": q13,
}
TEXT = {
    "Q1": "Which model version (artefact digest) was approved for deployment, and when?",
    "Q2": "Was deployment approved by an authorised human overseer, and by whom?",
    "Q3": "Which validation metrics and thresholds supported the decision?",
    "Q4": "Was bias examined before deployment, with which metric and outcome?",
    "Q5": "Which dataset version (digest) trained model version X?",
    "Q6": "Which policy version decided, and does re-execution reproduce the decision?",
    "Q7": "Which events belong to run or release R?",
    "Q8": "Were drift alerts raised after deployment, and when?",
    "Q9": "Did the drift alert precede serious incident Y?",
    "Q10": "Has any record been altered since issuance?",
    "Q11": "Is the record sequence complete between t1 and t2?",
    "Q12": "Which organisation submitted each record?",
    "Q13": "From the redacted export alone, which articles are supported and with which technical outcome?",
    "Q14": "Does the redacted export disclose the artefact identity or the policy logic?",
}


def verifiable(question: str, view: View, answer: Answer) -> str:
    if answer.answerable in (NO, NA):
        return NA
    if question == "Q14":
        return NA                    # a property of the document itself
    if view.name in ("A", "D"):
        return NO
    if not view.integrity.get("valid"):
        return NO
    if question == "Q10" and not view.anchored:
        return PARTIAL
    if question in COMPLETENESS_QUESTIONS and not view.anchored:
        return PARTIAL
    return YES


def evaluate(views: Dict[str, View]) -> Dict:
    matrix: Dict[str, Dict[str, dict]] = {}
    for q in list(QUESTIONS) + ["Q14"]:
        matrix[q] = {}
        for name in CONFIGURATIONS:
            view = views[name]
            t0 = time.perf_counter()
            answer = q14(view, views["C"]) if q == "Q14" else QUESTIONS[q](view)
            elapsed = (time.perf_counter() - t0) * 1000
            matrix[q][name] = {
                "answerable": answer.answerable,
                "verifiable": verifiable(q, view, answer),
                "missing": answer.missing,
                "records_read": answer.records_read,
                "ms": round(elapsed, 3),
                "answer": answer.value,
            }
    return matrix


def condensed(matrix: Dict) -> Dict[str, Dict[str, int]]:
    """Table T10: per configuration, answerable yes/partial/no and verifiable yes."""
    out = {}
    for name in CONFIGURATIONS:
        cells = [matrix[q][name] for q in matrix if matrix[q][name]["answerable"] != NA]
        out[name] = {
            "questions": len(cells),
            "yes": sum(c["answerable"] == YES for c in cells),
            "partial": sum(c["answerable"] == PARTIAL for c in cells),
            "no": sum(c["answerable"] == NO for c in cells),
            "verifiable_yes": sum(c["verifiable"] == YES for c in cells),
            "verifiable_partial": sum(c["verifiable"] == PARTIAL for c in cells),
        }
    return out


def _strip(value):
    """Drop the raw records the views carry, for the output file."""
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k != "_record"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def run(out_dir: Path = OUT_DIR) -> Path:
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    folder = out_dir / f"evidence_{stamp}"
    info = build_evidence(folder)
    views = load_views(folder, info["key"])
    matrix = evaluate(views)
    output = {
        "protocol": "Project/protocols/wp5_answerability.md",
        "generated_at": started.isoformat(),
        "environment": cc.environment(),
        "evidence": {"folder": folder.name, "events": info["events"],
                     "synthetic_events": ["serious_incident_detected", "incident_reported_to_authority"],
                     "integrity": {n: views[n].integrity.get("valid") for n in CONFIGURATIONS}},
        "questions": TEXT,
        "table_t10": condensed(matrix),
        "matrix": _strip(matrix),
    }
    path = out_dir / f"answerability_{stamp}.json"
    path.write_text(json.dumps(output, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{'':4}" + "".join(f"{n:>22}" for n in CONFIGURATIONS))
    for q in matrix:
        print(f"{q:4}" + "".join(f"{matrix[q][n]['answerable'] + ' / ' + matrix[q][n]['verifiable']:>22}"
                                 for n in CONFIGURATIONS))
    print(json.dumps(output["table_t10"]))
    print(f"saved to {path}")
    return path


if __name__ == "__main__":
    run()
    sys.exit(0)
