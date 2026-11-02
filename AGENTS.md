# Notes for AI agents

Read this before changing anything in this repo. It applies to any coding agent
(Claude Code, Copilot, Cursor, Codex and so on) used by any of the three group
members.

## What this project is

IT457 Group 17: a scaled-down, Aadhaar-style authentication service on AWS,
built to measure high availability and disaster recovery. Synthetic data only.

| File | Read it for |
|---|---|
| [PLAN.md](PLAN.md) | Steps, owners, reviewers, decisions D1–D10, and **current progress** (Status column, section 6) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | The design. The table at its top maps each PLAN step to the sections it needs. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Git workflow, Terraform, Docker and results rules |
| `<folder>/README.md` | What belongs in each folder and which step fills it |

## Before you start a task

1. `git pull`, then read the **Progress** line at the top of PLAN.md and the
   Status column in section 6. Do not trust status written anywhere else,
   including your own memory of earlier sessions.
2. Find the step you are working on and its owner. Only touch that step's
   folder unless the user says otherwise. Other members own other steps.
3. Read the ARCHITECTURE.md sections listed for that step.

## When you finish a step

- Update the step's row in PLAN.md section 6 (`✅ Done <commit> · review
  pending (<reviewer>)`) and the Progress line at the top, in the same commit
  as the work. If the commit hash isn't known yet, add it in a follow-up commit.
- Update the folder README if what's in the folder changed.
- If the build differs from ARCHITECTURE.md, note it in the relevant section
  ("As built: ...") rather than silently diverging.
- Commit message starts with `Step N:` (CONTRIBUTING.md). Push only when the
  user asks.

## Hard rules

- **No real Aadhaar numbers or personal data, ever.** UIDs are
  `TEST-NNNN-NNNN-NNNN`; the service refuses anything else.
- **No secrets** in the repo: AWS keys, `.env`, `*.pem`, `*.tfvars`, state files.
- **No AWS console actions or `terraform apply`/`destroy`.** Those are run by
  hand from Jeel's laptop (PLAN.md "Working convention"). Write the code and
  say "AWS action needed: ..." for anything that needs the console.
- Docker images are built for `linux/amd64` and tagged with the short git SHA.
- Raw files in `results/` are never edited by hand.
- Never force-push or rewrite `main`.

## Quick commands

```bash
# Service (step 2)
cd service && python -m venv .venv && .venv/Scripts/activate   # bin/activate on macOS/Linux
pip install -r requirements-dev.txt && python -m pytest
docker buildx build --platform linux/amd64 --load -t aadhaar-mock:$(git rev-parse --short HEAD) .
```
