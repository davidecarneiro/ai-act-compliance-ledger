import json
import time
from datetime import datetime, timezone
from uuid import uuid4
from simulator import ComplianceOracle, EXPERIMENTS_DIR
import statistics

def generate_synthetic_events(count=500):
    events = []
    for i in range(count):
        events.append({
            "scenario_id": f"load_test_{i}",
            "event_type": "model_validation",
            "artifact_id": f"model_v{i}",
            "artifact_type": "model",
            "pipeline_stage": "validation",
            "risk_level": "high",
            "human_approval": True,
            "metrics": {
                "precision": 0.85,
                "demographic_parity_diff": 0.02
            }
        })
    return events

def run_load_test():
    oracle = ComplianceOracle()
    oracle.reset_ledger()
    events = generate_synthetic_events(500)
    
    print("Starting load test with 500 events...")
    start_time = time.perf_counter()
    
    latencies = []
    for event in events:
        event_start = time.perf_counter()
        oracle.process_mlops_event(event)
        event_end = time.perf_counter()
        latencies.append((event_end - event_start) * 1000)
        
    end_time = time.perf_counter()
    
    total_time = end_time - start_time
    throughput = 500 / total_time
    avg_latency = statistics.mean(latencies)
    p95_latency = statistics.quantiles(latencies, n=100)[94] if hasattr(statistics, 'quantiles') else sorted(latencies)[int(len(latencies)*0.95)]
    
    print(f"--- Load Test Results ---")
    print(f"Total events: 500")
    print(f"Total time: {total_time:.4f} seconds")
    print(f"Throughput: {throughput:.2f} events/second")
    print(f"Average Latency: {avg_latency:.4f} ms")
    print(f"P95 Latency: {p95_latency:.4f} ms")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = EXPERIMENTS_DIR / f"load_test_{timestamp}.json"
    out_path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_events": 500,
        "total_time_s": round(total_time, 4),
        "throughput_events_per_s": round(throughput, 2),
        "avg_latency_ms": round(avg_latency, 4),
        "p95_latency_ms": round(p95_latency, 4),
    }, indent=2), encoding="utf-8")
    print(f"Results saved to {out_path}")

if __name__ == "__main__":
    run_load_test()
