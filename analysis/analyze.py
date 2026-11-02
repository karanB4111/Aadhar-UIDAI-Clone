"""Analysis for failover prober runs (PLAN step 5, ARCHITECTURE.md 8.5).

Reads the raw CSVs that the step 4 prober writes under
``results/<experiment>/<run_id>/`` and produces:

* ``results/<experiment>/<run_id>/summary.json`` and ``timeline.png`` per run
* ``results/<experiment>/summary.csv`` with one row per run
* ``results/<experiment>/aggregate.csv`` with median and [min, max] per metric
* ``results/<experiment>/charts/strip_error_window.png`` across runs

The script never modifies the raw ``prober.csv``, ``events.csv`` or
``meta.json`` (CONTRIBUTING.md). Metrics follow ARCHITECTURE.md 8.5:

* first and last error relative to ``t_inject`` (the first ``inject_start``
  event, or the earliest action in ``meta.json`` if that is missing)
* error window = last error minus first error
* failed requests, as a count and as a percentage of the whole run
* last response from the failed target, relative to ``t_inject``
* rejoin time = first response from the restored target minus ``t_restore``
  (``restore`` or ``inject_end`` event)

Chart content:

* Per run, a timeline: latency against time, one dot per request, coloured
  by ``az`` (or the empty label when no response arrived), with errors drawn
  as red crosses and the inject/restore events as vertical dashed lines.
* Per experiment, a strip chart with one dot per run for the error window.

Standard libraries plus pandas and matplotlib (see ``requirements.txt``).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")  # headless; the laptop may not have a display during a run
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"

# Error classes written by the prober (tests/prober.py).
ERROR_CLASSES = ("timeout", "conn_error", "http_5xx", "http_other")
INJECT_EVENTS = ("inject_start", "inject")
RESTORE_EVENTS = ("restore", "inject_end")


@dataclass
class RunSummary:
    """Per-run metrics; ARCHITECTURE.md 8.5."""

    experiment: str
    run_id: str
    requests: int
    ok: int
    errors: int
    error_rate_pct: float
    counts_by_class: dict = field(default_factory=dict)
    t_inject_ms: int | None = None
    t_restore_ms: int | None = None
    first_error_s: float | None = None
    last_error_s: float | None = None
    error_window_s: float | None = None
    last_failed_target_s: float | None = None
    rejoin_s: float | None = None
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    p99_latency_ms: float | None = None
    max_latency_ms: float | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Discovery and parsing
# ---------------------------------------------------------------------------


def discover_runs(results_dir: Path, experiment: str | None = None) -> list[Path]:
    """Return every run directory under ``results_dir`` that has a prober.csv."""
    if not results_dir.exists():
        return []
    runs: list[Path] = []
    experiments = [results_dir / experiment] if experiment else sorted(
        p for p in results_dir.iterdir() if p.is_dir()
    )
    for exp_dir in experiments:
        if not exp_dir.is_dir() or exp_dir.name == "charts":
            continue
        for run_dir in sorted(exp_dir.iterdir()):
            if run_dir.is_dir() and (run_dir / "prober.csv").is_file():
                runs.append(run_dir)
    return runs


def read_events(run_dir: Path) -> pd.DataFrame:
    path = run_dir / "events.csv"
    if not path.is_file():
        return pd.DataFrame(columns=["t_utc_ms", "event", "detail", "run_id"])
    df = pd.read_csv(path)
    if not df.empty:
        df["t_utc_ms"] = pd.to_numeric(df["t_utc_ms"], errors="coerce")
    return df


def read_prober(run_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(run_dir / "prober.csv")
    for col in ("t_send_utc_ms", "t_recv_utc_ms", "latency_ms", "status"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("error_class", "error_detail", "instance_id", "az", "region"):
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)
    return df


def read_meta(run_dir: Path) -> dict:
    path = run_dir / "meta.json"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def inject_restore_times(events: pd.DataFrame, meta: dict, probe_start_ms: int) -> tuple[int | None, int | None]:
    """Pick ``t_inject`` and ``t_restore`` from events.csv, falling back to meta.json."""
    t_inject: int | None = None
    t_restore: int | None = None
    if not events.empty:
        injs = events[events["event"].isin(INJECT_EVENTS)]
        if not injs.empty:
            t_inject = int(injs["t_utc_ms"].iloc[0])
        rests = events[events["event"].isin(RESTORE_EVENTS)]
        if not rests.empty:
            t_restore = int(rests["t_utc_ms"].iloc[-1])
    # Fallback: offsets in meta.json. Only used when the events.csv has no
    # inject row (e.g. a dry run) so the chart still shows the markers.
    if t_inject is None:
        for action in meta.get("actions") or []:
            if action.get("event") in INJECT_EVENTS and action.get("at_s") is not None:
                t_inject = probe_start_ms + int(float(action["at_s"]) * 1000)
                break
    if t_restore is None:
        for action in meta.get("actions") or []:
            if action.get("event") in RESTORE_EVENTS and action.get("at_s") is not None:
                t_restore = probe_start_ms + int(float(action["at_s"]) * 1000)
    return t_inject, t_restore


# ---------------------------------------------------------------------------
# Per-run summary
# ---------------------------------------------------------------------------


def summarise_run(run_dir: Path) -> RunSummary:
    experiment = run_dir.parent.name
    run_id = run_dir.name
    prober = read_prober(run_dir)
    events = read_events(run_dir)
    meta = read_meta(run_dir)

    probe_start_ms = int(prober["t_send_utc_ms"].min()) if not prober.empty else 0
    t_inject, t_restore = inject_restore_times(events, meta, probe_start_ms)

    is_error = prober["error_class"].isin(ERROR_CLASSES) if not prober.empty else pd.Series(dtype=bool)
    errors_df = prober[is_error] if not prober.empty else prober
    ok_df = prober[~is_error] if not prober.empty else prober

    counts_by_class = {cls: int((prober["error_class"] == cls).sum()) for cls in ERROR_CLASSES}
    requests = int(len(prober))
    errors = int(len(errors_df))
    ok = requests - errors
    err_pct = 100.0 * errors / requests if requests else 0.0

    # Error window relative to t_inject.
    first_error_s: float | None = None
    last_error_s: float | None = None
    error_window_s: float | None = None
    if t_inject is not None and not errors_df.empty:
        first_error_s = (errors_df["t_send_utc_ms"].min() - t_inject) / 1000.0
        last_error_s = (errors_df["t_send_utc_ms"].max() - t_inject) / 1000.0
        error_window_s = last_error_s - first_error_s

    # Last response from the failed target. We treat the "failed target" as
    # whichever instance_id disappears from the ok stream after t_inject: the
    # last ok response from any target seen before t_inject that is not seen
    # again between t_inject and t_restore. If several targets fade (unlikely
    # on a two-instance test) we take the latest such timestamp.
    last_failed_target_s: float | None = None
    if t_inject is not None and not ok_df.empty:
        before = ok_df[ok_df["t_send_utc_ms"] < t_inject]
        if not before.empty:
            before_targets = set(before["instance_id"].unique()) - {""}
            after_window = ok_df[
                (ok_df["t_send_utc_ms"] >= t_inject)
                & (ok_df["t_send_utc_ms"] <= (t_restore if t_restore is not None else math.inf))
            ]
            after_targets = set(after_window["instance_id"].unique())
            missing = before_targets - after_targets
            if missing:
                # Last ok timestamp for any missing target, relative to inject.
                last_ms = before[before["instance_id"].isin(missing)]["t_send_utc_ms"].max()
                last_failed_target_s = (last_ms - t_inject) / 1000.0

    # Rejoin time: first response from the restored target after t_restore.
    rejoin_s: float | None = None
    if t_restore is not None and not ok_df.empty:
        after_restore = ok_df[ok_df["t_send_utc_ms"] >= t_restore]
        if not after_restore.empty and last_failed_target_s is not None:
            # Prefer the target we detected as failed, if we can.
            before = ok_df[ok_df["t_send_utc_ms"] < (t_inject or t_restore)]
            missing = set(before["instance_id"].unique()) - set(
                ok_df[(ok_df["t_send_utc_ms"] >= (t_inject or t_restore))
                      & (ok_df["t_send_utc_ms"] < t_restore)]["instance_id"].unique()
            )
            missing.discard("")
            rejoin_row = after_restore[after_restore["instance_id"].isin(missing)]
            source = rejoin_row if not rejoin_row.empty else after_restore
            rejoin_s = (source["t_send_utc_ms"].min() - t_restore) / 1000.0

    # Latency distribution: only on successful requests, so a timeout cap does
    # not drag the p95 up and hide the server response time.
    def pct(series: pd.Series, q: float) -> float | None:
        if series.empty:
            return None
        return float(series.quantile(q / 100.0))

    ok_lat = ok_df["latency_ms"].dropna() if "latency_ms" in ok_df.columns else pd.Series(dtype=float)

    return RunSummary(
        experiment=experiment,
        run_id=run_id,
        requests=requests,
        ok=ok,
        errors=errors,
        error_rate_pct=round(err_pct, 4),
        counts_by_class=counts_by_class,
        t_inject_ms=t_inject,
        t_restore_ms=t_restore,
        first_error_s=_round(first_error_s, 3),
        last_error_s=_round(last_error_s, 3),
        error_window_s=_round(error_window_s, 3),
        last_failed_target_s=_round(last_failed_target_s, 3),
        rejoin_s=_round(rejoin_s, 3),
        p50_latency_ms=_round(pct(ok_lat, 50), 1),
        p95_latency_ms=_round(pct(ok_lat, 95), 1),
        p99_latency_ms=_round(pct(ok_lat, 99), 1),
        max_latency_ms=_round(float(ok_lat.max()) if not ok_lat.empty else None, 1),
    )


def _round(x: float | None, n: int) -> float | None:
    return None if x is None else round(float(x), n)


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def plot_timeline(run_dir: Path, summary: RunSummary) -> Path | None:
    prober = read_prober(run_dir)
    if prober.empty:
        return None

    probe_start_ms = int(prober["t_send_utc_ms"].min())
    t_inject = summary.t_inject_ms
    ref_ms = t_inject if t_inject is not None else probe_start_ms
    xs = (prober["t_send_utc_ms"] - ref_ms) / 1000.0
    ys = prober["latency_ms"].astype(float)

    is_error = prober["error_class"].isin(ERROR_CLASSES)
    ok = prober[~is_error]
    err = prober[is_error]

    fig, ax = plt.subplots(figsize=(10, 4))

    # One scatter group per AZ (empty label = no response, keep visible).
    az_values = sorted(ok["az"].fillna("").unique(), key=lambda v: (v == "", v))
    palette = plt.get_cmap("tab10").colors
    for i, az in enumerate(az_values):
        mask = ok["az"].fillna("") == az
        label = az if az else "(no az)"
        ax.scatter(
            (ok.loc[mask, "t_send_utc_ms"] - ref_ms) / 1000.0,
            ok.loc[mask, "latency_ms"],
            s=10, color=palette[i % len(palette)], alpha=0.75, label=label,
        )

    if not err.empty:
        err_lat = err["latency_ms"].astype(float).clip(lower=0)
        ax.scatter(
            (err["t_send_utc_ms"] - ref_ms) / 1000.0, err_lat,
            s=30, marker="x", color="red", label=f"error (n={len(err)})",
        )

    if t_inject is not None:
        ax.axvline(0.0, color="black", linestyle="--", linewidth=1, label="inject")
    if summary.t_restore_ms is not None and t_inject is not None:
        ax.axvline((summary.t_restore_ms - ref_ms) / 1000.0, color="green",
                   linestyle="--", linewidth=1, label="restore")

    ax.set_xlabel("seconds since inject" if t_inject is not None else "seconds since probe start")
    ax.set_ylabel("latency (ms)")
    xlo = float(xs.min())
    xhi = float(xs.max())
    if xhi - xlo < 1:
        xhi = xlo + 1
    ax.set_xlim(xlo, xhi)
    ax.set_ylim(bottom=0)
    title_bits = [summary.run_id, f"errors={summary.errors}"]
    if summary.error_window_s is not None:
        title_bits.append(f"window={summary.error_window_s:.1f}s")
    if summary.rejoin_s is not None:
        title_bits.append(f"rejoin={summary.rejoin_s:.1f}s")
    ax.set_title("  ".join(title_bits))
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    fig.tight_layout()

    out = run_dir / "timeline.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def plot_strip(exp_dir: Path, summaries: list[RunSummary]) -> Path | None:
    rows = [s for s in summaries if s.error_window_s is not None]
    if not rows:
        return None
    charts_dir = exp_dir / "charts"
    charts_dir.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(6, 4))
    xs = [1 + 0.03 * (i - len(rows) / 2) for i in range(len(rows))]  # tiny jitter
    ys = [s.error_window_s for s in rows]
    ax.scatter(xs, ys, s=40, color="tab:blue")
    for x, y, s in zip(xs, ys, rows):
        ax.annotate(s.run_id.rsplit("-", 2)[-1], (x, y), fontsize=7,
                    xytext=(4, 2), textcoords="offset points")
    ax.set_xticks([1])
    ax.set_xticklabels([exp_dir.name])
    ax.set_ylabel("error window (s)")
    ax.set_title(f"{exp_dir.name}: error window across {len(rows)} run(s)")
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    out = charts_dir / "strip_error_window.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------


def write_summary_json(run_dir: Path, summary: RunSummary) -> Path:
    out = run_dir / "summary.json"
    with out.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(asdict(summary), f, indent=2)
        f.write("\n")
    return out


SUMMARY_CSV_COLUMNS = [
    "experiment", "run_id", "requests", "ok", "errors", "error_rate_pct",
    "first_error_s", "last_error_s", "error_window_s",
    "last_failed_target_s", "rejoin_s",
    "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "max_latency_ms",
    "count_timeout", "count_conn_error", "count_http_5xx", "count_http_other",
]


def write_experiment_summary(exp_dir: Path, summaries: list[RunSummary]) -> Path:
    out = exp_dir / "summary.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_CSV_COLUMNS)
        w.writeheader()
        for s in summaries:
            row = {k: getattr(s, k, "") for k in SUMMARY_CSV_COLUMNS if hasattr(s, k)}
            row["count_timeout"] = s.counts_by_class.get("timeout", 0)
            row["count_conn_error"] = s.counts_by_class.get("conn_error", 0)
            row["count_http_5xx"] = s.counts_by_class.get("http_5xx", 0)
            row["count_http_other"] = s.counts_by_class.get("http_other", 0)
            w.writerow(row)
    return out


AGG_METRICS = [
    "error_window_s", "first_error_s", "last_error_s",
    "last_failed_target_s", "rejoin_s",
    "p50_latency_ms", "p95_latency_ms", "p99_latency_ms", "max_latency_ms",
    "error_rate_pct",
]


def write_experiment_aggregate(exp_dir: Path, summaries: list[RunSummary]) -> Path:
    """Median and [min, max] per metric across runs (ARCHITECTURE.md 8.5)."""
    out = exp_dir / "aggregate.csv"
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "n_runs", "median", "min", "max"])
        for metric in AGG_METRICS:
            values = [getattr(s, metric) for s in summaries if getattr(s, metric) is not None]
            if not values:
                w.writerow([metric, 0, "", "", ""])
            else:
                values.sort()
                median = values[len(values) // 2] if len(values) % 2 \
                    else (values[len(values) // 2 - 1] + values[len(values) // 2]) / 2
                w.writerow([metric, len(values), round(median, 3), round(values[0], 3), round(values[-1], 3)])
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def analyze(run_dirs: Iterable[Path], make_charts: bool = True) -> dict[str, list[RunSummary]]:
    by_experiment: dict[str, list[RunSummary]] = {}
    exp_dirs: dict[str, Path] = {}
    for run_dir in run_dirs:
        try:
            summary = summarise_run(run_dir)
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            print(f"skip {run_dir}: {exc}", file=sys.stderr)
            continue
        write_summary_json(run_dir, summary)
        if make_charts:
            plot_timeline(run_dir, summary)
        by_experiment.setdefault(summary.experiment, []).append(summary)
        exp_dirs.setdefault(summary.experiment, run_dir.parent)
        print(f"{summary.run_id}: requests={summary.requests} errors={summary.errors} "
              f"window={summary.error_window_s} rejoin={summary.rejoin_s}")
    for exp, summaries in by_experiment.items():
        exp_dir = exp_dirs[exp]
        write_experiment_summary(exp_dir, summaries)
        write_experiment_aggregate(exp_dir, summaries)
        if make_charts:
            plot_strip(exp_dir, summaries)
    return by_experiment


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Summarise failover prober runs and draw charts (PLAN step 5).",
    )
    p.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR,
                   help=f"root of results/ (default: {DEFAULT_RESULTS_DIR})")
    p.add_argument("--experiment", help="restrict to one experiment folder (e.g. e1, local)")
    p.add_argument("--run-dir", type=Path, action="append", default=[],
                   help="analyse one specific run directory; repeatable")
    p.add_argument("--no-charts", action="store_true", help="skip PNG generation")
    args = p.parse_args(argv)

    if args.run_dir:
        run_dirs = list(args.run_dir)
    else:
        run_dirs = discover_runs(args.results_dir, args.experiment)
    if not run_dirs:
        print("no runs found", file=sys.stderr)
        return 1
    # list() so we can iterate twice (process + per-experiment aggregates).
    run_dirs = list(run_dirs)
    analyze(run_dirs, make_charts=not args.no_charts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
