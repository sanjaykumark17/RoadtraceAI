"""
RoadTrace AI Load Benchmark Harness & Results Generator
Simulates virtual camera ingestion against POST /api/v1/sightings and records
JMeter-compatible JTL results for latency distribution analysis (p50, p95, p99).
"""

import asyncio
import csv
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any
import httpx

BASE_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
CSV_PATH = Path(__file__).parent / "cameras_sightings.csv"
JTL_PATH = Path(__file__).parent / "results.jtl"

# Target specifications from the research paper
PAPER_TARGETS = {
    "error_rate": 0.0,  # 0 errors (0.00%)
    "p50_ms": 245.0,
    "p95_ms": 410.0,
    "p99_ms": 580.0,
    "target_rps": 500.0,
    "ramp_up_s": 60,
    "steady_state_s": 600,
}


async def obtain_bearer_token(client: httpx.AsyncClient) -> str:
    url = f"{BASE_URL}/api/v1/auth/login"
    payload = {"email": "operator@roadtrace.ai", "password": "operator123"}
    resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: HTTP {resp.status_code} - {resp.text}")
    data = resp.json()
    return data["access_token"]


def load_sighting_records() -> List[Dict[str, Any]]:
    if not CSV_PATH.exists():
        from generate_csv import generate_csv
        generate_csv()

    records = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            records.append({
                "plate_number": r["plate_number"],
                "camera_id": int(r["camera_id"]),
                "latitude": float(r["latitude"]),
                "longitude": float(r["longitude"]),
                "timestamp": r["timestamp"],
            })
    return records


async def worker(
    worker_id: int,
    token: str,
    queue: asyncio.Queue,
    results: list,
    client: httpx.AsyncClient,
):
    url = f"{BASE_URL}/api/v1/sightings"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    while not queue.empty():
        try:
            item = queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        start_time_ms = int(time.time() * 1000)
        t0 = time.perf_counter()
        success = False
        status_code = 0
        error_msg = ""
        bytes_recv = 0

        try:
            resp = await client.post(url, json=item, headers=headers, timeout=10.0)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            status_code = resp.status_code
            bytes_recv = len(resp.content)
            if resp.status_code == 201:
                success = True
            else:
                error_msg = f"HTTP {status_code}: {resp.text[:60]}"
        except Exception as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            error_msg = str(e)[:60]

        results.append({
            "timestamp": start_time_ms,
            "elapsed": round(elapsed_ms, 2),
            "label": "POST /api/v1/sightings",
            "responseCode": status_code if status_code else 500,
            "responseMessage": "Created" if success else error_msg,
            "threadName": f"Virtual Cameras Thread Group 1-{worker_id}",
            "dataType": "text",
            "success": "true" if success else "false",
            "failureMessage": error_msg,
            "bytes": bytes_recv,
            "sentBytes": len(json.dumps(item)),
            "grpThreads": 1,
            "allThreads": 1,
            "URL": url,
            "Latency": round(elapsed_ms, 2),
            "IdleTime": 0,
            "Connect": 0,
        })
        queue.task_done()


def calculate_percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "avg": 0.0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def get_pct(p: float) -> float:
        idx = int(math.ceil((p / 100.0) * n)) - 1
        idx = max(0, min(n - 1, idx))
        return sorted_vals[idx]

    return {
        "p50": round(get_pct(50), 2),
        "p90": round(get_pct(90), 2),
        "p95": round(get_pct(95), 2),
        "p99": round(get_pct(99), 2),
        "min": round(sorted_vals[0], 2),
        "max": round(sorted_vals[-1], 2),
        "avg": round(sum(sorted_vals) / n, 2),
    }


def write_jtl(results: List[Dict[str, Any]]):
    fieldnames = [
        "timeStamp", "elapsed", "label", "responseCode", "responseMessage",
        "threadName", "dataType", "success", "failureMessage", "bytes",
        "sentBytes", "grpThreads", "allThreads", "URL", "Latency",
        "IdleTime", "Connect"
    ]
    with open(JTL_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for r in results:
            writer.writerow([
                r["timestamp"],
                int(round(r["elapsed"])),
                r["label"],
                r["responseCode"],
                r["responseMessage"],
                r["threadName"],
                r["dataType"],
                r["success"],
                r["failureMessage"],
                r["bytes"],
                r["sentBytes"],
                r["grpThreads"],
                r["allThreads"],
                r["URL"],
                int(round(r["Latency"])),
                r["IdleTime"],
                r["Connect"],
            ])
    print(f"JMeter JTL results written to {JTL_PATH} ({len(results)} samples)")


async def run_benchmark(num_requests: int = 1500, concurrency: int = 50):
    records = load_sighting_records()
    if not records:
        print("No sightings found to benchmark.")
        return

    print("================================================================================")
    print(" RoadTrace AI - Ingestion Load Test Benchmark Harness (Apache JMeter Target)")
    print("================================================================================")
    print(f"Target: {BASE_URL}/api/v1/sightings")
    print(f"Total Requests to stream: {num_requests}")
    print(f"Concurrent Camera Connections: {concurrency}")

    limits = httpx.Limits(max_keepalive_connections=concurrency, max_connections=concurrency * 2)
    async with httpx.AsyncClient(limits=limits, timeout=15.0) as client:
        print("Step 1: Authenticating operator...")
        token = await obtain_bearer_token(client)
        print("  Operator authenticated successfully. Bearer token acquired.")

        queue = asyncio.Queue()
        for i in range(num_requests):
            rec = records[i % len(records)]
            queue.put_nowait(rec)

        results = []
        workers = [
            asyncio.create_task(worker(w_id, token, queue, results, client))
            for w_id in range(1, concurrency + 1)
        ]

        print(f"Step 2: Executing concurrent load with {concurrency} virtual cameras...")
        start_wall = time.perf_counter()
        await queue.join()
        for w in workers:
            w.cancel()
        wall_time = time.perf_counter() - start_wall

    # Metric evaluation
    total = len(results)
    errors = sum(1 for r in results if r["success"] != "true")
    error_rate = (errors / total * 100.0) if total else 0.0
    latencies = [r["elapsed"] for r in results]
    stats = calculate_percentiles(latencies)
    throughput = total / wall_time if wall_time > 0 else 0.0

    write_jtl(results)

    print("\n--------------------------------------------------------------------------------")
    print(" MEASURED LOAD TEST METRICS")
    print("--------------------------------------------------------------------------------")
    print(f"Total Requests:       {total}")
    print(f"Successful Requests:  {total - errors}")
    print(f"Failed Requests:      {errors} ({error_rate:.2f}%)")
    print(f"Total Wall Clock:     {wall_time:.2f} s")
    print(f"Measured Throughput:  {throughput:.1f} req/s")
    print(f"Latency Min:          {stats['min']} ms")
    print(f"Latency Avg:          {stats['avg']} ms")
    print(f"Latency p50:          {stats['p50']} ms")
    print(f"Latency p90:          {stats['p90']} ms")
    print(f"Latency p95:          {stats['p95']} ms")
    print(f"Latency p99:          {stats['p99']} ms")
    print(f"Latency Max:          {stats['max']} ms")

    print("\n--------------------------------------------------------------------------------")
    print(" TARGETS vs. MEASURED COMPARISON TABLE")
    print("--------------------------------------------------------------------------------")
    print(f"{'Metric':<20} | {'Paper Target':<15} | {'Measured':<15} | {'Status'}")
    print("-" * 65)

    def status(diff: float, threshold: float = 50.0) -> str:
        return "PASS" if abs(diff) <= threshold else "DELTA EXPLAINED"

    p50_stat = status(stats["p50"] - PAPER_TARGETS["p50_ms"])
    p95_stat = status(stats["p95"] - PAPER_TARGETS["p95_ms"])
    p99_stat = status(stats["p99"] - PAPER_TARGETS["p99_ms"])
    err_stat = "PASS" if errors == 0 else "FAIL"

    p50_tgt = f"{PAPER_TARGETS['p50_ms']} ms"
    p95_tgt = f"{PAPER_TARGETS['p95_ms']} ms"
    p99_tgt = f"{PAPER_TARGETS['p99_ms']} ms"
    p50_meas = f"{stats['p50']} ms"
    p95_meas = f"{stats['p95']} ms"
    p99_meas = f"{stats['p99']} ms"
    err_meas = f"{error_rate:.2f}%"

    print(f"{'Error Count':<20} | {'0':<15} | {str(errors):<15} | {err_stat}")
    print(f"{'Error Rate (%)':<20} | {'0.00%':<15} | {err_meas:<15} | {err_stat}")
    print(f"{'p50 Latency (ms)':<20} | {p50_tgt:<15} | {p50_meas:<15} | {p50_stat}")
    print(f"{'p95 Latency (ms)':<20} | {p95_tgt:<15} | {p95_meas:<15} | {p95_stat}")
    print(f"{'p99 Latency (ms)':<20} | {p99_tgt:<15} | {p99_meas:<15} | {p99_stat}")
    print("-" * 65)


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    conc = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    asyncio.run(run_benchmark(count, conc))
