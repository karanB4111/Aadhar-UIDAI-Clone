# local/

Docker compose and nginx for rehearsing failover on a laptop before touching
AWS. Filled by PLAN step 3 (owner: Khushi).

- Two copies of the `service/` image, with different `INSTANCE_ID` and `AZ`
  values, behind nginx standing in for the ALB.
- Stopping one container should move all traffic to the other.
- The prober from `tests/` (step 4) runs against this setup to produce a CSV for
  the analysis scripts (step 5).
