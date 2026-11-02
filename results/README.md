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

`local/` holds rehearsal runs against the docker compose stack in `local/`
(step 3), not report measurements. `local/local-r01-app-a` is the step 4
sample: 60 s at 20/s, `app-a` stopped at 15 s and started at 40 s. It is the
input for building the step 5 analysis before AWS runs exist.
