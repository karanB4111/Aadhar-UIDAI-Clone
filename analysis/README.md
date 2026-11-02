# analysis/

Scripts that turn the raw CSVs in `results/` into summaries and charts for the
report. Filled by PLAN step 5 (owner: Khushi).

Method: ARCHITECTURE.md 8.5.

- Per run: first and last error relative to injection, error window, failed
  requests (count and %), last response from the failed target, rejoin time.
- Per experiment: median and [min, max] across runs, next to the predicted range
  from ARCHITECTURE.md 4.3.
- Charts: a strip chart with one dot per run, and a timeline per experiment
  (latency over time, coloured by AZ or region, errors marked).

Scripts read `results/` and never modify the raw files.
