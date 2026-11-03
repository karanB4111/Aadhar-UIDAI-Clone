"""Unit tests for analysis/analyze_load.py (PLAN step 9)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyze_load  # noqa: E402

# A minimal Locust 2.x _stats.csv: header + one request row + the Aggregated row.
STATS_HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,"
    "Average Response Time,Min Response Time,Max Response Time,"
    "Average Content Size,Requests/s,Failures/s,"
    "50%,66%,75%,80%,90%,95%,98%,99%,99.9%,99.99%,100%"
)


def _write_stats(run_dir: Path, *, requests: int, failures: int, rps: float,
                 p50: float, p95: float, p99: float) -> None:
    line = (
        f"POST,/api/v1/authenticate,{requests},{failures},{p50},{p50},1,{p99},"
        f"500,{rps},0,{p50},{p50},{p50},{p50},{p95},{p95},{p99},{p99},{p99},{p99},{p99}"
    )
    agg = (
        f"None,Aggregated,{requests},{failures},{p50},{p50},1,{p99},"
        f"500,{rps},0,{p50},{p50},{p50},{p50},{p95},{p95},{p99},{p99},{p99},{p99},{p99}"
    )
    (run_dir / "locust_stats.csv").write_text(
        "\n".join([STATS_HEADER, line, agg]) + "\n", encoding="utf-8"
    )


def _write_meta(run_dir: Path, target_rate: float) -> None:
    (run_dir / "meta.json").write_text(
        json.dumps({"run_id": run_dir.name, "target_rate_per_s": target_rate,
                    "tool": "locust"}),
        encoding="utf-8",
    )


def _write_aws(run_dir: Path, rows: list[dict]) -> None:
    cols = ["timestamp_utc", "target_rt_p50_ms", "target_rt_p95_ms",
            "target_rt_p99_ms", "asg_in_service", "asg_desired"]
    lines = [",".join(cols)]
    for r in rows:
        lines.append(",".join(str(r.get(c, "")) for c in cols))
    (run_dir / "aws_metrics.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_served_by(run_dir: Path, instances: list[str]) -> None:
    tally = {"requests_by_instance": {i: 10 for i in instances},
             "distinct_instances": len(instances)}
    (run_dir / "served_by.json").write_text(json.dumps(tally), encoding="utf-8")


def _make_run(root: Path, exp: str, run_id: str) -> Path:
    d = root / exp / run_id
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------


def test_summarise_rate_validity(tmp_path):
    rd = _make_run(tmp_path, "e0", "e0-r01-ramp")
    _write_meta(rd, target_rate=100.0)
    _write_stats(rd, requests=6000, failures=0, rps=98.0, p50=30, p95=80, p99=150)

    s = analyze_load.summarise_run(rd)
    assert s.achieved_rate_per_s == 98.0
    assert s.rate_error_pct == 2.0           # 2% off target
    assert s.valid_rate is True              # within 5% (5.3.4)
    assert s.client_p95_ms == 80
    assert s.failure_pct == 0.0


def test_rate_off_target_flagged(tmp_path):
    rd = _make_run(tmp_path, "e0", "e0-r02-ramp")
    _write_meta(rd, target_rate=200.0)
    _write_stats(rd, requests=1000, failures=12, rps=150.0, p50=40, p95=400, p99=900)

    s = analyze_load.summarise_run(rd)
    assert s.valid_rate is False             # 25% short -> invalid run
    assert "off target" in s.notes
    assert s.failures == 12


def test_server_metrics_and_instance_count(tmp_path):
    rd = _make_run(tmp_path, "e5a", "e5a-r02-n2")
    _write_meta(rd, target_rate=90.0)
    _write_stats(rd, requests=5400, failures=0, rps=90.0, p50=20, p95=60, p99=110)
    _write_aws(rd, [
        {"timestamp_utc": "2026-11-04T06:00:00Z", "target_rt_p50_ms": 18,
         "target_rt_p95_ms": 50, "target_rt_p99_ms": 95, "asg_in_service": 2, "asg_desired": 2},
        {"timestamp_utc": "2026-11-04T06:01:00Z", "target_rt_p50_ms": 20,
         "target_rt_p95_ms": 54, "target_rt_p99_ms": 100, "asg_in_service": 2, "asg_desired": 2},
    ])

    s = analyze_load.summarise_run(rd)
    assert s.server_p95_ms == 52             # median of 50 and 54
    assert s.instances_seen == 2             # from the ASG metric max
    assert s.asg_in_service_max == 2


def test_instance_count_falls_back_to_served_by(tmp_path):
    rd = _make_run(tmp_path, "e5a", "e5a-r01-n1")
    _write_meta(rd, target_rate=90.0)
    _write_stats(rd, requests=5400, failures=0, rps=90.0, p50=25, p95=90, p99=160)
    _write_served_by(rd, ["i-aaa"])          # no aws_metrics.csv

    s = analyze_load.summarise_run(rd)
    assert s.instances_seen == 1
    assert s.server_p95_ms is None
    assert "no aws_metrics.csv" in s.notes


def test_e5a_instance_chart_and_csv(tmp_path):
    for run_id, n, p95 in (("e5a-r01-n1", 1, 90), ("e5a-r02-n2", 2, 50)):
        rd = _make_run(tmp_path, "e5a", run_id)
        _write_meta(rd, target_rate=90.0)
        _write_stats(rd, requests=5400, failures=0, rps=90.0, p50=20, p95=p95, p99=p95 + 40)
        _write_aws(rd, [{"timestamp_utc": "2026-11-04T06:00:00Z",
                         "target_rt_p95_ms": p95, "asg_in_service": n, "asg_desired": n}])

    runs = analyze_load.discover_runs(tmp_path, "e5a")
    assert len(runs) == 2
    analyze_load.analyze(runs, make_charts=True)

    exp_dir = tmp_path / "e5a"
    assert (exp_dir / "load_summary.csv").is_file()
    assert (exp_dir / "charts" / "latency_vs_instances.png").is_file()
    for run_id in ("e5a-r01-n1", "e5a-r02-n2"):
        assert (exp_dir / run_id / "load_summary.json").is_file()


def test_e5b_timeline_chart(tmp_path):
    rd = _make_run(tmp_path, "e5b", "e5b-r01-step-up")
    _write_meta(rd, target_rate=160.0)
    _write_stats(rd, requests=9600, failures=0, rps=160.0, p50=30, p95=120, p99=250)
    _write_aws(rd, [
        {"timestamp_utc": "2026-11-04T06:00:00Z", "target_rt_p95_ms": 300,
         "asg_in_service": 1, "asg_desired": 1},
        {"timestamp_utc": "2026-11-04T06:05:00Z", "target_rt_p95_ms": 120,
         "asg_in_service": 2, "asg_desired": 2},
    ])

    runs = analyze_load.discover_runs(tmp_path, "e5b")
    analyze_load.analyze(runs, make_charts=True)
    assert (tmp_path / "e5b" / "charts" / "autoscale_timeline.png").is_file()


def test_discover_ignores_non_locust_dirs(tmp_path):
    # A prober-only run (no locust_stats.csv) must not be picked up.
    rd = _make_run(tmp_path, "e1", "e1-r01-az-a")
    (rd / "prober.csv").write_text("seq\n1\n", encoding="utf-8")
    assert analyze_load.discover_runs(tmp_path, None) == []
