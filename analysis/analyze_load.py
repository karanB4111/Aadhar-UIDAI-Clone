"""Analysis for Locust load runs (PLAN step 9, ARCHITECTURE.md 5.3.3, 8.4 E0/E5a/E5b).

Companion to ``analyze.py`` (which handles the failover prober). This reads the
Locust CSVs and the fetched AWS metrics under ``results/<experiment>/<run_id>/``
and produces the load-test deliverables the course asks for [81]:

* Per run: ``load_summary.json`` with the achieved rate, the client-side latency
  percentiles (Locust) and, when ``aws_metrics.csv`` is present, the server-side
  ``TargetResponseTime`` percentiles and the instance-count range.
* Per experiment: ``load_summary.csv`` (one row per run).
* Charts in ``results/<experiment>/charts/``:
    - E0  : ``latency_vs_load.png`` - server & client p95 against offered rate.
    - E5a : ``latency_vs_instances.png`` - p95 at N=1 vs N=2 (the course's
            "response time against instance count" chart, 5.3.3 step 4).
    - E5b : ``autoscale_timeline.png`` - desired / in-service instances and the
            p95 latency over time, with the load step visible.

Why both client and server latency: Locust runs on a laptop over Wi-Fi/Internet,
so its latency carries jitter. ``TargetResponseTime`` from the ALB is the
server-side ground truth (5.3.4). We report both and chart the server value
where we have it.

Standard library plus pandas and matplotlib (analysis/requirements.txt). Never
modifies the raw files (CONTRIBUTING.md).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"

# A Locust run dir is one with the summary stats CSV present.
LOCUST_STATS = "locust_stats.csv"
LOCUST_HISTORY = "locust_stats_history.csv"
AWS_METRICS = "aws_metrics.csv"


@dataclass
class LoadSummary:
    experiment: str
    run_id: str
    target_rate_per_s: float | None = None
    achieved_rate_per_s: float | None = None
    rate_error_pct: float | None = None          # |achieved - target| / target
    requests: int = 0
    failures: int = 0
    failure_pct: float | None = None
    # Client-side (Locust), milliseconds.
    client_p50_ms: float | None = None
    client_p95_ms: float | None = None
    client_p99_ms: float | None = None
    # Server-side (ALB TargetResponseTime), milliseconds, if aws_metrics.csv exists.
    server_p50_ms: float | None = None
    server_p95_ms: float | None = None
    server_p99_ms: float | None = None
    # Instance count over the run (from served_by.json or the ASG metric).
    instances_seen: int | None = None
    asg_in_service_min: float | None = None
    asg_in_service_max: float | None = None
    valid_rate: bool | None = None               # achieved within 5% of target
    notes: str = ""


def _round(x, n=1):
    return None if x is None else round(float(x), n)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def discover_runs(results_dir: Path, experiment: str | None) -> list[Path]:
    if not results_dir.exists():
        return []
    exps = [results_dir / experiment] if experiment else sorted(
        p for p in results_dir.iterdir() if p.is_dir()
    )
    runs = []
    for exp_dir in exps:
        if not exp_dir.is_dir() or exp_dir.name == "charts":
            continue
        for run_dir in sorted(exp_dir.iterdir()):
            if run_dir.is_dir() and (run_dir / LOCUST_STATS).is_file():
                runs.append(run_dir)
    return runs


def read_meta(run_dir: Path) -> dict:
    p = run_dir / "meta.json"
    if not p.is_file():
        return {}
    try:
        # utf-8-sig: step9_load.ps1 writes meta.json via PowerShell Out-File, which
        # emits a UTF-8 BOM; plain utf-8 would corrupt the first key and lose
        # target_rate_per_s (cf. the same fix in tests/fetch_metrics.py).
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def read_aggregated_stats(run_dir: Path) -> dict | None:
    """The 'Aggregated' row of Locust's _stats.csv, as a dict (or None)."""
    df = pd.read_csv(run_dir / LOCUST_STATS)
    agg = df[df["Name"] == "Aggregated"]
    if agg.empty:
        agg = df.tail(1)  # older Locust labels it differently; last row is the total
    if agg.empty:
        return None
    return agg.iloc[0].to_dict()


def _col(row: dict, *names):
    """First present, non-null column from a Locust stats row (names vary by version)."""
    for n in names:
        if n in row and pd.notna(row[n]):
            return row[n]
    return None


def read_served_by(run_dir: Path) -> dict:
    p = run_dir / "served_by.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))  # tolerate a BOM
    except (OSError, ValueError):
        return {}


def read_aws_metrics(run_dir: Path) -> pd.DataFrame | None:
    p = run_dir / AWS_METRICS
    if not p.is_file():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True)
    return df.sort_values("timestamp_utc").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Per-run summary
# ---------------------------------------------------------------------------


def summarise_run(run_dir: Path) -> LoadSummary:
    experiment = run_dir.parent.name
    meta = read_meta(run_dir)
    row = read_aggregated_stats(run_dir) or {}
    served = read_served_by(run_dir)
    aws = read_aws_metrics(run_dir)

    s = LoadSummary(experiment=experiment, run_id=run_dir.name)
    s.target_rate_per_s = meta.get("target_rate_per_s")
    s.requests = int(_col(row, "Request Count", "# requests") or 0)
    s.failures = int(_col(row, "Failure Count", "# failures") or 0)
    s.failure_pct = _round(100.0 * s.failures / s.requests, 3) if s.requests else None
    s.achieved_rate_per_s = _round(_col(row, "Requests/s"), 2)
    s.client_p50_ms = _round(_col(row, "50%", "Median Response Time"))
    s.client_p95_ms = _round(_col(row, "95%"))
    s.client_p99_ms = _round(_col(row, "99%"))

    if s.target_rate_per_s and s.achieved_rate_per_s is not None:
        s.rate_error_pct = _round(
            100.0 * abs(s.achieved_rate_per_s - s.target_rate_per_s) / s.target_rate_per_s, 2
        )
        s.valid_rate = s.rate_error_pct <= 5.0  # 5.3.4 validity check

    # Server-side latency: median over the run of each percentile column.
    if aws is not None:
        for col, attr in (
            ("target_rt_p50_ms", "server_p50_ms"),
            ("target_rt_p95_ms", "server_p95_ms"),
            ("target_rt_p99_ms", "server_p99_ms"),
        ):
            if col in aws.columns:
                vals = pd.to_numeric(aws[col], errors="coerce").dropna()
                if not vals.empty:
                    setattr(s, attr, _round(vals.median()))
        if "asg_in_service" in aws.columns:
            vals = pd.to_numeric(aws["asg_in_service"], errors="coerce").dropna()
            if not vals.empty:
                s.asg_in_service_min = _round(vals.min())
                s.asg_in_service_max = _round(vals.max())

    # Instance count: prefer the ASG metric's max; fall back to the client tally.
    if s.asg_in_service_max is not None:
        s.instances_seen = int(s.asg_in_service_max)
    elif served.get("distinct_instances"):
        s.instances_seen = int(served["distinct_instances"])

    bits = []
    if s.valid_rate is False:
        bits.append(f"achieved rate off target by {s.rate_error_pct}% (>5%, 5.3.4)")
    if aws is None:
        bits.append("no aws_metrics.csv; server-side latency not available")
    s.notes = "; ".join(bits)
    return s


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def chart_latency_vs_load(exp_dir: Path, summaries: list[LoadSummary]) -> Path | None:
    """E0: p95 latency against offered rate. One dot per run, sorted by rate."""
    rows = sorted((s for s in summaries if s.target_rate_per_s), key=lambda s: s.target_rate_per_s)
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(8, 5))
    x = [s.target_rate_per_s for s in rows]
    if any(s.server_p95_ms is not None for s in rows):
        ax.plot(x, [s.server_p95_ms for s in rows], "o-", color="tab:red",
                label="server p95 (ALB)")
    ax.plot(x, [s.client_p95_ms for s in rows], "s--", color="tab:blue",
            label="client p95 (Locust)")
    for s in rows:
        if s.failures:
            ax.annotate(f"{s.failures} fail", (s.target_rate_per_s, s.client_p95_ms or 0),
                        fontsize=7, color="red", xytext=(3, 4), textcoords="offset points")
    ax.set_xlabel("offered rate (requests/s)")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title(f"{exp_dir.name}: latency against load (R_max = knee point)")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend()
    return _save(exp_dir, fig, "latency_vs_load.png")


def chart_latency_vs_instances(exp_dir: Path, summaries: list[LoadSummary]) -> Path | None:
    """E5a: p95 latency against instance count (the course deliverable, 5.3.3 step 4)."""
    rows = [s for s in summaries if s.instances_seen]
    if not rows:
        return None
    rows.sort(key=lambda s: s.instances_seen)
    fig, ax = plt.subplots(figsize=(7, 5))
    x = [s.instances_seen for s in rows]
    if any(s.server_p95_ms is not None for s in rows):
        ax.plot(x, [s.server_p95_ms for s in rows], "o-", color="tab:red",
                label="server p95 (ALB)")
    ax.plot(x, [s.client_p95_ms for s in rows], "s--", color="tab:blue",
            label="client p95 (Locust)")
    for s in rows:
        y = s.server_p95_ms or s.client_p95_ms or 0
        ax.annotate(s.run_id.rsplit("-", 1)[-1], (s.instances_seen, y),
                    fontsize=8, xytext=(4, 4), textcoords="offset points")
    ax.set_xlabel("in-service instances")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_xticks(sorted(set(x)))
    ax.set_title(f"{exp_dir.name}: response time against instance count")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend()
    ax.set_ylim(bottom=0)
    return _save(exp_dir, fig, "latency_vs_instances.png")


def chart_autoscale_timeline(exp_dir: Path, run_dirs: list[Path]) -> Path | None:
    """E5b: desired / in-service instances and p95 latency over time, from aws_metrics.csv."""
    frames = []
    for rd in run_dirs:
        df = read_aws_metrics(rd)
        if df is not None:
            df = df.assign(run=rd.name)
            frames.append(df)
    if not frames:
        return None
    data = pd.concat(frames, ignore_index=True).sort_values("timestamp_utc")
    t0 = data["timestamp_utc"].min()
    mins = (data["timestamp_utc"] - t0).dt.total_seconds() / 60.0

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax2 = ax1.twinx()
    plotted = False
    for col, style, label in (
        ("asg_desired", "--", "desired capacity"),
        ("asg_in_service", "-", "in-service instances"),
    ):
        if col in data.columns:
            y = pd.to_numeric(data[col], errors="coerce")
            ax1.step(mins, y, style, where="post", label=label, color="tab:green"
                     if col == "asg_in_service" else "tab:olive")
            plotted = True
    if "target_rt_p95_ms" in data.columns:
        ax2.plot(mins, pd.to_numeric(data["target_rt_p95_ms"], errors="coerce"),
                 color="tab:red", label="server p95 (ms)")
        plotted = True
    if not plotted:
        plt.close(fig)
        return None
    ax1.set_xlabel(f"minutes since {t0:%H:%M:%S} UTC")
    ax1.set_ylabel("instances")
    ax2.set_ylabel("p95 latency (ms)")
    ax1.set_ylim(bottom=0)
    ax2.set_ylim(bottom=0)
    ax1.set_title(f"{exp_dir.name}: autoscaling timeline (1 -> 2 and back)")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=8)
    ax1.grid(True, linestyle=":", alpha=0.4)
    return _save(exp_dir, fig, "autoscale_timeline.png")


def _save(exp_dir: Path, fig, name: str) -> Path:
    charts = exp_dir / "charts"
    charts.mkdir(exist_ok=True)
    out = charts / name
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

SUMMARY_COLUMNS = [
    "experiment", "run_id", "target_rate_per_s", "achieved_rate_per_s",
    "rate_error_pct", "valid_rate", "requests", "failures", "failure_pct",
    "client_p50_ms", "client_p95_ms", "client_p99_ms",
    "server_p50_ms", "server_p95_ms", "server_p99_ms",
    "instances_seen", "asg_in_service_min", "asg_in_service_max", "notes",
]


def write_summary_json(run_dir: Path, s: LoadSummary) -> None:
    with (run_dir / "load_summary.json").open("w", encoding="utf-8", newline="\n") as f:
        json.dump(asdict(s), f, indent=2)
        f.write("\n")


def write_experiment_csv(exp_dir: Path, summaries: list[LoadSummary]) -> Path:
    out = exp_dir / "load_summary.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
        w.writeheader()
        for s in summaries:
            w.writerow({k: getattr(s, k, "") for k in SUMMARY_COLUMNS})
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def analyze(run_dirs: list[Path], make_charts: bool = True) -> dict[str, list[LoadSummary]]:
    by_exp: dict[str, list[LoadSummary]] = {}
    exp_dirs: dict[str, Path] = {}
    run_dirs_by_exp: dict[str, list[Path]] = {}
    for run_dir in run_dirs:
        try:
            s = summarise_run(run_dir)
        except (OSError, ValueError, KeyError, pd.errors.ParserError) as exc:
            print(f"skip {run_dir}: {exc}", file=sys.stderr)
            continue
        write_summary_json(run_dir, s)
        by_exp.setdefault(s.experiment, []).append(s)
        exp_dirs.setdefault(s.experiment, run_dir.parent)
        run_dirs_by_exp.setdefault(s.experiment, []).append(run_dir)
        flag = "" if s.valid_rate is not False else "  [RATE OFF TARGET]"
        print(f"{s.run_id}: rate {s.achieved_rate_per_s}/{s.target_rate_per_s} req/s  "
              f"client_p95={s.client_p95_ms}ms server_p95={s.server_p95_ms}ms  "
              f"instances={s.instances_seen} failures={s.failures}{flag}")

    for exp, summaries in by_exp.items():
        exp_dir = exp_dirs[exp]
        write_experiment_csv(exp_dir, summaries)
        if not make_charts:
            continue
        # Pick the chart that fits the experiment; draw whatever the data supports.
        if exp == "e0":
            chart_latency_vs_load(exp_dir, summaries)
        elif exp == "e5a":
            chart_latency_vs_instances(exp_dir, summaries)
        elif exp == "e5b":
            chart_autoscale_timeline(exp_dir, run_dirs_by_exp[exp])
        else:
            # Unknown experiment: draw what applies.
            chart_latency_vs_load(exp_dir, summaries)
            chart_latency_vs_instances(exp_dir, summaries)
            chart_autoscale_timeline(exp_dir, run_dirs_by_exp[exp])
    return by_exp


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Summarise Locust load runs and draw charts (PLAN step 9).")
    p.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    p.add_argument("--experiment", help="restrict to one experiment folder (e0, e5a, e5b)")
    p.add_argument("--run-dir", type=Path, action="append", default=[],
                   help="analyse one specific Locust run dir; repeatable")
    p.add_argument("--no-charts", action="store_true")
    args = p.parse_args(argv)

    run_dirs = list(args.run_dir) if args.run_dir else discover_runs(args.results_dir, args.experiment)
    if not run_dirs:
        print("no Locust runs found (looking for locust_stats.csv)", file=sys.stderr)
        return 1
    analyze(run_dirs, make_charts=not args.no_charts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
