# results/

Raw measurements and the charts made from them. These are the numbers the
report quotes.

Layout (details in CONTRIBUTING.md):

```
results/<experiment>/<run_id>/prober.csv
results/<experiment>/<run_id>/events.csv
results/<experiment>/<run_id>/meta.json
results/<experiment>/charts/
```

Experiment IDs (`e0` … `e7`) are defined in ARCHITECTURE.md 8.4. Raw files are
committed as recorded and never edited by hand.

## Load-test runs (step 9: e0, e5a, e5b)

The Locust experiments use the same `<experiment>/<run_id>/` layout but a
different set of raw files (written by `tests/step9_load.ps1` and
`tests/fetch_metrics.py`):

```
results/<experiment>/<run_id>/locust_stats.csv          Locust per-endpoint + Aggregated totals
results/<experiment>/<run_id>/locust_stats_history.csv  per-interval history (used for timelines)
results/<experiment>/<run_id>/locust_failures.csv       failures, if any
results/<experiment>/<run_id>/locust.html               Locust's own report
results/<experiment>/<run_id>/served_by.json            request counts per AZ / instance
results/<experiment>/<run_id>/aws_metrics.csv           ALB TargetResponseTime + ASG metrics
results/<experiment>/<run_id>/meta.json                 rate, host, image tag, UTC window
results/<experiment>/<run_id>/load_summary.json         analyze_load.py output
results/<experiment>/charts/                            latency_vs_load / _vs_instances / autoscale_timeline
```

Run ids label the load point, not an AZ target: `e0-r01-ramp`, `e5a-r01-n1`,
`e5a-r02-n2`, `e5b-r01-step-up`. No AWS runs exist yet — these folders appear
once the Tier 2 stack is applied and the runs are done (owner: Kanu).

`local/` holds rehearsal runs against the docker compose stack in `local/`
(step 3), not report measurements. `local/local-r01-app-a` is the step 4
sample: 60 s at 20/s, `app-a` stopped at 15 s and started at 40 s. It is the
input for building the step 5 analysis before AWS runs exist.
