# tests/

Test tooling that drives load and records what clients see.

- **Failover prober** (PLAN step 4, owner: Kanu). Open loop at 20 requests/s, a
  new connection per request, connect timeout 2 s, total timeout 5 s. Writes one
  CSV row per request. Spec: ARCHITECTURE.md 8.3.
- **Locust file** (PLAN step 9, owner: Kanu). `FastHttpUser`, paced at a fixed
  rate. Used for calibration (E0) and the scaling experiments (E5a, E5b).

Output goes to `results/`, in the layout described in CONTRIBUTING.md.
