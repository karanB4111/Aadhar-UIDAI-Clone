# analysis/

Scripts that turn the raw CSVs in `results/` into summaries and charts for the
report. Filled by PLAN step 5 (owner: Khushi, reviewer: Jeel).

Method: ARCHITECTURE.md 8.5.

- Per run: first and last error relative to injection, error window, failed
  requests (count and %), last response from the failed target, rejoin time,
  and latency percentiles over successful responses.
- Per experiment: median and [min, max] across runs, next to the predicted
  range from ARCHITECTURE.md 4.3.
- Charts: a strip chart with one dot per run (error window), and a timeline
  per run (latency over time, coloured by AZ, errors marked, inject and
  restore drawn as vertical dashed lines).

Scripts read `results/` and never modify the raw files (CONTRIBUTING.md).
Outputs sit alongside the raw files:

```
results/<experiment>/<run_id>/summary.json       per-run metrics
results/<experiment>/<run_id>/timeline.png       per-run chart
results/<experiment>/summary.csv                 one row per run
results/<experiment>/aggregate.csv               median, min, max per metric
results/<experiment>/charts/strip_error_window.png
```

## Install

```bash
cd analysis
python -m venv .venv && .venv/Scripts/activate   # bin/activate on macOS/Linux
pip install -r requirements.txt
```

## Run

From the repo root:

```bash
# Everything under results/
python analysis/analyze.py

# One experiment
python analysis/analyze.py --experiment e1

# One run (useful while a run is still fresh)
python analysis/analyze.py --run-dir results/local/local-r01-app-a

# Skip the PNGs (summary.json + CSVs only)
python analysis/analyze.py --no-charts
```

## Sample input

`results/local/local-r01-app-a/` is the step 4 rehearsal against the docker
compose stack: 60 s at 20/s, `app-a` stopped at 15 s and restarted at 40 s.
nginx retries failed upstreams, so the prober recorded zero errors there and
the "failover" shows as a handful of ~2 s latency spikes rather than a 502
window (see `tests/README.md` and ARCHITECTURE.md 5.2). The script therefore
reports `error_window_s` as empty for this run and plots the spikes on the
timeline. The real ALB numbers will come from step 7.

## Tests

```bash
cd analysis
python -m pytest
```
