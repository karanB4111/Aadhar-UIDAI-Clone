# Contributing

How the three of us work in this repo. The plan and owners are in
[PLAN.md](PLAN.md); the design details are in [ARCHITECTURE.md](ARCHITECTURE.md).

## Git workflow (D10)

1. `git pull` before you start.
2. Work on your own step only. If you need to change someone else's files, tell
   them first.
3. Commit straight to `main`. Start the message with the step number, for
   example `Step 3: add docker compose and nginx for local rehearsal`.
4. `git push` when the step is done, then tell the reviewer named in PLAN.md.
5. The reviewer checks the step after it lands. Problems go in a GitHub issue or
   a follow-up commit, not a rewrite of history. Never force-push `main`.

## Never commit

- Real Aadhaar numbers or any personal data. Synthetic IDs use the `TEST-`
  prefix (FR6).
- Secrets: AWS keys, `.env`, `*.pem`, registrar logins. `.gitignore` already
  blocks the common ones.
- Terraform state or real `*.tfvars`. Commit a `*.tfvars.example` with
  placeholder values instead.
- Anything from `docs/` (course reports, git-ignored).

## Terraform (infra/)

- **One person applies per step.** Everyone else runs `plan` only. State lives
  in S3 with a lock file (ARCHITECTURE.md section 7).
- Run `terraform fmt` and `terraform validate` before each commit, and paste the
  plan summary into the commit message.
- Set every health-check, grace-period and IMDS value explicitly. Terraform's
  defaults differ from AWS's (ARCHITECTURE.md 5.2, 6.3).
- Tag every resource with `Project`, `Tier`, `Owner` and `ManagedBy` (use
  `default_tags` on the provider).
- **Run `terraform destroy` at the end of every session.** Only the `global/`
  stack stays up until step 12. A forgotten stack is the biggest threat to the
  USD 10 budget.

## Docker images

- Build for `linux/amd64`: `docker buildx build --platform linux/amd64 ...`.
  A default build on an Apple Silicon laptop produces an arm64 image that will
  not start on t3.micro.
- Tag images with the short git SHA. Tags in ECR are immutable.
- Nothing is built on the instances; they only pull from ECR.

## Results (results/)

Each experiment run gets its own folder:

```
results/<experiment>/<run_id>/
    prober.csv   one row per request (ARCHITECTURE.md 8.3)
    events.csv   every failure injection and restore, with UTC timestamps
    meta.json    git SHA, image tag, health-check settings, rate, client network
```

- `<experiment>` is the ID from ARCHITECTURE.md 8.4, lower case: `e1`, `e1b`,
  `e2`, ... `e6b`.
- `<run_id>` is `<experiment>-r<NN>-<target>`, for example `e1-r01-az-a`.
- Charts made by `analysis/` go in `results/<experiment>/charts/`.
- All timestamps are UTC in milliseconds. Sync your clock (NTP) before a run.
- Commit raw results as they come out of the run. Never edit them by hand; fix
  problems in the analysis scripts.

## Python

- One `requirements.txt` per folder that needs one (`service/`, `tests/`,
  `analysis/`), with pinned versions.
- Use a virtual environment (`.venv/`, git-ignored).

## Line endings

`.gitattributes` forces LF for shell scripts, Dockerfiles and Terraform, so
files edited on Windows still run on Linux instances. Don't override it.
