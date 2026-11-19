"""Try to recover a policy from a digest by exhaustive search.

A policy has few unknowns: a handful of thresholds on a coarse scale, a list of
stages and a flag. Whoever knows its format, which is public, can build every
candidate, hash it in canonical form and compare. This module runs that search
on the grid fixed by the WP5 protocol (amendment of 2026-11-19), so that the
article can say what an unkeyed policy digest discloses and what a keyed
commitment does not.

The searcher is assumed to know every field outside the grid (the approver
entry, the event types that need a signed approval). That is a generous
assumption for the searcher, which is the point: the result bounds what the
digest protects.
"""

from __future__ import annotations

import itertools
import time
from typing import Dict, Iterable, Iterator, Optional

from simulator import policy_identity

STAGES = ("validation", "deployment", "monitoring")


def _steps(start: int, stop: int, scale: float) -> list:
    return [round(i * scale, 2) for i in range(start, stop + 1)]


def candidates(template: Dict) -> Iterator[Dict]:
    """Every policy on the protocol's grid, other fields from the template."""
    stage_sets = [list(c) for k in (1, 2) for c in itertools.combinations(STAGES, k)]
    for precision in _steps(1, 99, 0.01):
        for parity in _steps(1, 30, 0.01):
            for drift in _steps(1, 10, 0.05):
                for stages in stage_sets:
                    for approval in (False, True):
                        yield dict(template, min_precision=precision,
                                   max_demographic_parity_diff=parity,
                                   drift_alert_threshold=drift,
                                   metric_threshold_stages=stages,
                                   require_human_approval_for_high_risk=approval)


def search(values: Iterable[str], template: Dict) -> Dict:
    """Compare each value with the digest of every candidate policy.

    Returns the recovered policy (or None), the number of candidates tried and
    the time taken. A keyed commitment never matches: without the key there is
    nothing to compute a candidate's value with."""
    targets = {v for v in values if v}
    tried = 0
    found: Optional[Dict] = None
    started = time.perf_counter()
    if targets:
        for candidate in candidates(template):
            tried += 1
            if policy_identity(candidate)[1] in targets:
                found = candidate
                break
    return {"recovered": found is not None, "policy": found, "candidates_tried": tried,
            "seconds": round(time.perf_counter() - started, 2)}
