"""Unit tests for analysis/analyze.py (PLAN step 5)."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyze  # noqa: E402


PROBER_COLUMNS = analyze.read_prober.__module__  # just to keep analyze imported
HEADER_PROBER = [
    "seq", "t_send_utc_ms", "t_recv_utc_ms", "latency_ms", "status",
    "error_class", "error_detail", "instance_id", "az", "region",
    "resolved_ip", "run_id",
]
HEADER_EVENTS = ["t_utc_ms", "event", "detail", "run_id"]


def _write_prober(run_dir: Path, rows: list[dict]) -> None:
    with (run_dir / "prober.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER_PROBER)
        w.writeheader()
        for row in rows:
            w.writerow({**{k: "" for k in HEADER_PROBER}, **row})


def _write_events(run_dir: Path, rows: list[dict]) -> None:
    with (run_dir / "events.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER_EVENTS)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _write_meta(run_dir: Path, meta: dict) -> None:
    (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _ok(seq: int, t: int, instance: str, az: str, lat: float = 5.0) -> dict:
    return {
        "seq": seq, "t_send_utc_ms": t, "t_recv_utc_ms": t + int(lat),
        "latency_ms": lat, "status": 200, "error_class": "",
        "instance_id": instance, "az": az, "region": "ap-south-1",
        "resolved_ip": "127.0.0.1", "run_id": "t-r01-x",
    }


def _err(seq: int, t: int, cls: str = "http_5xx", status: int = 502) -> dict:
    return {
        "seq": seq, "t_send_utc_ms": t, "t_recv_utc_ms": t + 100,
        "latency_ms": 100, "status": status, "error_class": cls,
        "instance_id": "", "az": "", "region": "",
        "resolved_ip": "127.0.0.1", "run_id": "t-r01-x",
    }


@pytest.fixture
def failover_run(tmp_path: Path) -> Path:
    """A tiny run that mimics an E1 failover: inject at t=1000, restore at t=5000."""
    exp = tmp_path / "e1"
    run = exp / "e1-r01-az-a"
    run.mkdir(parents=True)

    rows: list[dict] = []
    # Three ok requests from each instance before inject.
    for i, t in enumerate([0, 100, 200, 300, 400, 500]):
        rows.append(_ok(i, t, instance=("i-a" if i % 2 == 0 else "i-b"),
                        az=("ap-south-1a" if i % 2 == 0 else "ap-south-1b")))
    # After inject (t=1000): half the requests fail (as 502 on the dead target),
    # half succeed on i-b. Errors span 1100..1800 (window 0.7 s).
    rows.append(_err(6, 1100))
    rows.append(_ok(7, 1200, "i-b", "ap-south-1b"))
    rows.append(_err(8, 1300))
    rows.append(_ok(9, 1400, "i-b", "ap-south-1b"))
    rows.append(_err(10, 1800))
    # After the window ends, every request succeeds on i-b.
    for i, t in enumerate([2000, 3000, 4000, 4900], start=11):
        rows.append(_ok(i, t, "i-b", "ap-south-1b"))
    # After restore (t=5000), i-a serves again at t=5500.
    rows.append(_ok(15, 5300, "i-b", "ap-south-1b"))
    rows.append(_ok(16, 5500, "i-a", "ap-south-1a"))
    _write_prober(run, rows)

    _write_events(run, [
        {"t_utc_ms": -1000, "event": "probe_start", "detail": "20/s", "run_id": "e1-r01-az-a"},
        {"t_utc_ms": 1000, "event": "inject_start", "detail": "stop i-a", "run_id": "e1-r01-az-a"},
        {"t_utc_ms": 5000, "event": "restore", "detail": "start i-a", "run_id": "e1-r01-az-a"},
    ])
    _write_meta(run, {"run_id": "e1-r01-az-a", "actions": [
        {"at_s": 1.0, "event": "inject_start", "command": "stop"},
        {"at_s": 5.0, "event": "restore", "command": "start"},
    ]})
    return run


def test_summarise_failover_run(failover_run: Path) -> None:
    s = analyze.summarise_run(failover_run)
    assert s.experiment == "e1"
    assert s.run_id == "e1-r01-az-a"
    assert s.requests == 17
    assert s.errors == 3
    assert s.counts_by_class["http_5xx"] == 3
    assert s.t_inject_ms == 1000
    assert s.t_restore_ms == 5000
    assert s.first_error_s == pytest.approx(0.1, abs=1e-3)
    assert s.last_error_s == pytest.approx(0.8, abs=1e-3)
    assert s.error_window_s == pytest.approx(0.7, abs=1e-3)
    # Last response from i-a (the failed target) is at t=400, so -0.6 s.
    assert s.last_failed_target_s == pytest.approx(-0.6, abs=1e-3)
    # i-a returns at t=5500, so rejoin = 0.5 s after t_restore.
    assert s.rejoin_s == pytest.approx(0.5, abs=1e-3)


def test_no_events_falls_back_to_meta(tmp_path: Path) -> None:
    run = tmp_path / "e2" / "e2-r02-az-b"
    run.mkdir(parents=True)
    # Prober started at t=0, meta says inject at 2 s.
    _write_prober(run, [_ok(0, 0, "i-a", "a"), _err(1, 2500, "timeout")])
    (run / "events.csv").write_text("t_utc_ms,event,detail,run_id\n")  # empty
    _write_meta(run, {"actions": [{"at_s": 2.0, "event": "inject_start", "command": "x"}]})
    s = analyze.summarise_run(run)
    assert s.t_inject_ms == 2000
    assert s.first_error_s == pytest.approx(0.5, abs=1e-3)


def test_no_errors_leaves_window_empty(tmp_path: Path) -> None:
    """The local sample has 0 errors because nginx retries; window must be None."""
    run = tmp_path / "local" / "local-r02-app-a"
    run.mkdir(parents=True)
    _write_prober(run, [_ok(i, i * 50, "i-a", "a") for i in range(10)])
    _write_events(run, [{"t_utc_ms": 100, "event": "inject_start", "detail": "x",
                         "run_id": "local-r02-app-a"}])
    _write_meta(run, {})
    s = analyze.summarise_run(run)
    assert s.errors == 0
    assert s.error_window_s is None
    assert s.first_error_s is None


def test_discover_runs_skips_charts_and_empty(tmp_path: Path) -> None:
    (tmp_path / "e1" / "e1-r01-az-a").mkdir(parents=True)
    (tmp_path / "e1" / "e1-r01-az-a" / "prober.csv").write_text("a,b\n")
    (tmp_path / "e1" / "charts").mkdir(parents=True)
    (tmp_path / "e1" / "e1-r02-az-b").mkdir(parents=True)  # no prober.csv
    found = analyze.discover_runs(tmp_path)
    assert [r.name for r in found] == ["e1-r01-az-a"]


def test_analyze_writes_outputs(failover_run: Path) -> None:
    analyze.analyze([failover_run], make_charts=False)
    assert (failover_run / "summary.json").is_file()
    exp_dir = failover_run.parent
    assert (exp_dir / "summary.csv").is_file()
    assert (exp_dir / "aggregate.csv").is_file()
    agg = (exp_dir / "aggregate.csv").read_text().splitlines()
    assert agg[0] == "metric,n_runs,median,min,max"
    assert any(line.startswith("error_window_s,1,0.7,") for line in agg)


def test_analyze_writes_timeline_png(failover_run: Path) -> None:
    analyze.analyze([failover_run], make_charts=True)
    png = failover_run / "timeline.png"
    assert png.is_file() and png.stat().st_size > 0
    strip = failover_run.parent / "charts" / "strip_error_window.png"
    assert strip.is_file() and strip.stat().st_size > 0
