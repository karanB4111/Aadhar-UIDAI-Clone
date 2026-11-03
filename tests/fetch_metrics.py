"""Pull the AWS-side metrics for a load run into CSV (PLAN step 9, ARCHITECTURE.md 8.1).

Locust measures what the laptop sees, including Internet and Wi-Fi jitter. The
numbers that go in the report are the ALB's server-side metrics plus the ASG
group metrics (5.3.3 step 5):

* ``TargetResponseTime``        p50 / p95 / p99  server-side latency
* ``RequestCountPerTarget``     Sum              the scaling signal
* ``RequestCount``              Sum              total load the ALB saw
* ``HTTPCode_Target_5XX_Count`` Sum              app errors
* ``HTTPCode_ELB_5XX_Count``    Sum              ALB errors (dead/absent targets)
* ``UnHealthyHostCount``        Max              false removals under load (R6)
* ``GroupInServiceInstances``   Max              the live instance count timeline
* ``GroupDesiredCapacity``      Max              what the autoscaler asked for

It shells out to ``aws cloudwatch get-metric-data`` (AWS CLI v2, the same tool
and profile the Terraform/SSM steps use, HANDOFF.md 2), so there is nothing to
pip install. Pass the ALB and target-group ARN suffixes and the ASG name from
the Tier 2 Terraform outputs, and the run window in UTC.

    python tests/fetch_metrics.py \\
        --run-dir results/e5b/e5b-r01-step \\
        --region ap-south-1 \\
        --alb app/aadhaar-tier2-alb/abc123 \\
        --target-group targetgroup/aadhaar-tier2-tg/def456 \\
        --asg aadhaar-tier2-asg \\
        --start 2026-11-04T06:00:00Z --end 2026-11-04T06:40:00Z

``--start`` / ``--end`` default to the probe/Locust window read from the run
dir's meta.json if present, padded by one period on each side. Output:

    <run-dir>/aws_metrics.csv    one row per timestamp, one column per metric
    <run-dir>/aws_metrics.json   the raw get-metric-data response, for the record

Standard library only (Python 3.11+); needs the ``aws`` CLI on PATH.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Each entry: (column id, namespace, metric, stat, dimension-kind).
# dimension-kind picks which ARN/name dimension(s) the metric needs.
METRICS = [
    ("target_rt_p50_ms", "AWS/ApplicationELB", "TargetResponseTime", "p50", "alb"),
    ("target_rt_p95_ms", "AWS/ApplicationELB", "TargetResponseTime", "p95", "alb"),
    ("target_rt_p99_ms", "AWS/ApplicationELB", "TargetResponseTime", "p99", "alb"),
    ("request_count", "AWS/ApplicationELB", "RequestCount", "Sum", "alb"),
    ("request_count_per_target", "AWS/ApplicationELB", "RequestCountPerTarget", "Sum", "tg"),
    ("target_5xx", "AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "Sum", "alb"),
    ("elb_5xx", "AWS/ApplicationELB", "HTTPCode_ELB_5XX_Count", "Sum", "alb"),
    ("unhealthy_hosts", "AWS/ApplicationELB", "UnHealthyHostCount", "Maximum", "albtg"),
    ("healthy_hosts", "AWS/ApplicationELB", "HealthyHostCount", "Maximum", "albtg"),
    ("asg_in_service", "AWS/AutoScaling", "GroupInServiceInstances", "Maximum", "asg"),
    ("asg_desired", "AWS/AutoScaling", "GroupDesiredCapacity", "Maximum", "asg"),
    ("asg_pending", "AWS/AutoScaling", "GroupPendingInstances", "Maximum", "asg"),
]

# TargetResponseTime comes back in seconds; convert the latency columns to ms.
SECONDS_METRICS = {"target_rt_p50_ms", "target_rt_p95_ms", "target_rt_p99_ms"}


def _dimensions(kind: str, alb: str, tg: str, asg: str) -> list[dict]:
    if kind == "alb":
        return [{"Name": "LoadBalancer", "Value": alb}]
    if kind == "tg":
        return [{"Name": "TargetGroup", "Value": tg}, {"Name": "LoadBalancer", "Value": alb}]
    if kind == "albtg":
        return [{"Name": "TargetGroup", "Value": tg}, {"Name": "LoadBalancer", "Value": alb}]
    if kind == "asg":
        return [{"Name": "AutoScalingGroupName", "Value": asg}]
    raise ValueError(kind)


def _stat(stat: str) -> str:
    # CloudWatch extended stats (percentiles) are lowercase p50; base stats are
    # TitleCase (Sum, Maximum). get-metric-data wants them exactly like that.
    return stat


def build_queries(alb: str, tg: str, asg: str, period: int) -> list[dict]:
    queries = []
    for i, (col, ns, metric, stat, kind) in enumerate(METRICS):
        if kind in ("tg", "albtg") and not tg:
            continue
        if kind == "asg" and not asg:
            continue
        if kind == "alb" and not alb:
            continue
        queries.append(
            {
                "Id": f"m{i}",
                "Label": col,
                "MetricStat": {
                    "Metric": {
                        "Namespace": ns,
                        "MetricName": metric,
                        "Dimensions": _dimensions(kind, alb, tg, asg),
                    },
                    "Period": period,
                    "Stat": _stat(stat),
                },
                "ReturnData": True,
            }
        )
    return queries


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def window_from_meta(run_dir: Path, period: int) -> tuple[datetime, datetime] | None:
    """Read the probe/Locust window from meta.json, padded one period each side."""
    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    summary = meta.get("summary") or {}
    start_ms = summary.get("started_utc_ms") or meta.get("started_utc_ms")
    end_ms = summary.get("ended_utc_ms") or meta.get("ended_utc_ms")
    if not start_ms or not end_ms:
        return None
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc) - timedelta(seconds=period)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc) + timedelta(seconds=period)
    return start, end


def fetch(region: str, queries: list[dict], start: datetime, end: datetime) -> dict:
    cmd = [
        "aws", "cloudwatch", "get-metric-data",
        "--region", region,
        "--start-time", start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "--end-time", end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "--metric-data-queries", json.dumps(queries),
        "--output", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"aws cloudwatch get-metric-data failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


def to_rows(response: dict) -> tuple[list[str], list[list]]:
    """Pivot get-metric-data's per-metric series into rows keyed by timestamp."""
    series = {}  # column label -> {timestamp: value}
    for res in response.get("MetricDataResults", []):
        label = res.get("Label", res["Id"])
        col = {}
        for ts, val in zip(res.get("Timestamps", []), res.get("Values", [])):
            if label in SECONDS_METRICS:
                val = val * 1000.0
            col[ts] = val
        series[label] = col

    columns = [col for (col, *_rest) in METRICS if col in series]
    all_ts = sorted({ts for col in series.values() for ts in col})
    rows = []
    for ts in all_ts:
        row = [ts]
        for col in columns:
            v = series[col].get(ts)
            row.append("" if v is None else round(v, 3))
        rows.append(row)
    return ["timestamp_utc", *columns], rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch ALB + ASG CloudWatch metrics for a load run.")
    p.add_argument("--run-dir", type=Path, required=True,
                   help="results/<experiment>/<run_id>/ to write aws_metrics.csv into")
    p.add_argument("--region", default="ap-south-1")
    p.add_argument("--alb", required=True,
                   help="ALB ARN suffix, e.g. app/aadhaar-tier2-alb/abc123 "
                        "(from `aws elbv2` or the ALB ARN after :loadbalancer/)")
    p.add_argument("--target-group", default="",
                   help="target-group ARN suffix, e.g. targetgroup/aadhaar-tier2-tg/def456")
    p.add_argument("--asg", default="", help="Auto Scaling group name (Tier 2 output asg_name)")
    p.add_argument("--period", type=int, default=60, help="seconds per data point (default 60)")
    p.add_argument("--start", help="UTC ISO start, e.g. 2026-11-04T06:00:00Z (default: from meta.json)")
    p.add_argument("--end", help="UTC ISO end (default: from meta.json)")
    args = p.parse_args(argv)

    if not args.run_dir.is_dir():
        p.error(f"{args.run_dir} is not a directory; run the load test first")

    if args.start and args.end:
        start, end = _parse_iso(args.start), _parse_iso(args.end)
    else:
        win = window_from_meta(args.run_dir, args.period)
        if win is None:
            p.error("no --start/--end given and no usable window in meta.json")
        start, end = win
    if end <= start:
        p.error("end must be after start")

    queries = build_queries(args.alb, args.target_group, args.asg, args.period)
    response = fetch(args.region, queries, start, end)

    (args.run_dir / "aws_metrics.json").write_text(
        json.dumps(response, indent=2, default=str) + "\n", encoding="utf-8"
    )
    header, rows = to_rows(response)
    csv_path = args.run_dir / "aws_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    print(f"window {start:%Y-%m-%dT%H:%M:%SZ} .. {end:%Y-%m-%dT%H:%M:%SZ}")
    print(f"wrote {csv_path} ({len(rows)} data points, {len(header) - 1} metrics)")
    if not rows:
        print("warning: no data points. ALB metrics are only published while "
              "traffic flows, and appear ~1-2 min late. Widen the window or wait.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
