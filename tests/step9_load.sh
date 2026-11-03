#!/usr/bin/env bash
# PLAN step 9: drive one Locust load point against the Tier 2 ALB
# (ARCHITECTURE.md 8.4 E0 / E5a / E5b, method in 5.3.3-5.3.4). Bash twin of
# step9_load.ps1; the group deploys from Macs (HANDOFF.md 2).
#
# Set the ASG capacity / scaling for the experiment in AWS FIRST (5.3.3); this
# script only drives load, it does not change capacity.
#
# Usage:
#   tests/step9_load.sh e5a 2 n2 <alb-dns> <image-tag> \
#       --users 18 --rps-per-user 10 --run-time 5m [--network wired]
#
# Positional: <experiment e0|e5a|e5b> <run-number> <run-label> <alb-dns> <image-tag>
set -euo pipefail

if [[ $# -lt 5 ]]; then
  sed -n '2,13p' "$0"; exit 2
fi

experiment=$1; run_number=$2; run_label=$3; alb_dns=$4; image_tag=$5
shift 5

users=""; rps_per_user=10; spawn_rate=0; run_time=""
endpoint="/api/v1/authenticate"; factor="otp"; network="other"; client_location=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --users) users=$2; shift 2 ;;
    --rps-per-user) rps_per_user=$2; shift 2 ;;
    --spawn-rate) spawn_rate=$2; shift 2 ;;
    --run-time) run_time=$2; shift 2 ;;
    --endpoint) endpoint=$2; shift 2 ;;
    --factor) factor=$2; shift 2 ;;
    --network) network=$2; shift 2 ;;
    --client-location) client_location=$2; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

case "$experiment" in e0|e5a|e5b) ;; *) echo "experiment must be e0|e5a|e5b" >&2; exit 2 ;; esac
[[ -n "$users" && -n "$run_time" ]] || { echo "--users and --run-time are required" >&2; exit 2; }
[[ "$run_label" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "run-label must be kebab-case" >&2; exit 2; }

run_id=$(printf '%s-r%02d-%s' "$experiment" "$run_number" "$run_label")
repo_root=$(cd "$(dirname "$0")/.." && pwd)
locustfile="$repo_root/tests/locustfile.py"
run_dir="$repo_root/results/$experiment/$run_id"
alb_url="http://$alb_dns"
target_rate=$(python3 -c "print(round($users * $rps_per_user, 2))")
[[ "$spawn_rate" == 0 ]] && spawn_rate=$users   # default: all users at once (a step)

if [[ -f "$run_dir/locust_stats.csv" ]]; then
  echo "locust_stats.csv already exists under $run_dir. Pick a new run-number." >&2; exit 1
fi
mkdir -p "$run_dir"
command -v locust >/dev/null || { echo "locust not on PATH; pip install -r tests/requirements.txt" >&2; exit 1; }

csv_prefix="$run_dir/locust"
html_path="$run_dir/locust.html"
tally_path="$run_dir/served_by.json"
start_ms=$(( $(date -u +%s) * 1000 ))

cat <<EOF

step 9 load run: $run_id
  host      : $alb_url$endpoint  (factor $factor)
  users     : $users at $rps_per_user req/s each  => target $target_rate req/s
  spawn rate: $spawn_rate users/s
  run time  : $run_time
  out       : $run_dir

Reminder: set ASG capacity / scaling for $experiment in AWS first (5.3.3).
EOF

export LOCUST_RPS_PER_USER="$rps_per_user"
export LOCUST_ENDPOINT="$endpoint"
export LOCUST_FACTOR="$factor"
export LOCUST_TALLY_OUT="$tally_path"

# On Git-Bash / MSYS (Windows), a value like /api/v1/authenticate passed to a
# native .exe is rewritten into a Windows path (e.g. C:/Program Files/Git/api/..).
# locust.exe is native, so disable MSYS path conversion for this call, otherwise
# LOCUST_ENDPOINT and --host reach Locust mangled. No effect on macOS/Linux.
set +e
( cd "$repo_root" && MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
    locust -f "$locustfile" --headless --host "$alb_url" \
    --users "$users" --spawn-rate "$spawn_rate" --run-time "$run_time" \
    --csv "$csv_prefix" --csv-full-history --html "$html_path" --only-summary )
locust_exit=$?
set -e
unset LOCUST_TALLY_OUT

end_ms=$(( $(date -u +%s) * 1000 ))
git_sha=$(git -C "$repo_root" rev-parse --short HEAD 2>/dev/null || echo "")
locust_version=$(locust --version 2>/dev/null || echo "")

cat > "$run_dir/meta.json" <<EOF
{
  "run_id": "$run_id",
  "experiment": "$experiment",
  "tool": "locust",
  "host": "$alb_url",
  "endpoint": "$endpoint",
  "factor": "$factor",
  "users": $users,
  "rps_per_user": $rps_per_user,
  "target_rate_per_s": $target_rate,
  "spawn_rate": $spawn_rate,
  "run_time": "$run_time",
  "image_tag": "$image_tag",
  "client_location": "$client_location",
  "client_network": "$network",
  "git_sha": "$git_sha",
  "locust_version": "$locust_version",
  "locust_exit_code": $locust_exit,
  "started_utc_ms": $start_ms,
  "ended_utc_ms": $end_ms,
  "note": "Set ASG capacity/scaling in AWS before the run (5.3.3). Validity: achieved rate within 5% of target, no Locust CPU warnings (5.3.4)."
}
EOF

echo
[[ $locust_exit -ne 0 ]] && echo "WARNING: locust exited $locust_exit; the run may be invalid." >&2
cat <<EOF
Done. Validity checks (ARCHITECTURE.md 5.3.4):
  - achieved req/s in locust_stats.csv within 5% of $target_rate
  - no Locust CPU-bound warnings above
  - served_by.json shows the expected number of instances

Now pull the server-side metrics for this window (needs Tier 2 ARNs):
  python tests/fetch_metrics.py --run-dir "$run_dir" --region ap-south-1 \\
      --alb app/aadhaar-tier2-alb/<id> --target-group targetgroup/aadhaar-tier2-tg/<id> \\
      --asg <asg_name>

When all points for an experiment are in:
  python analysis/analyze_load.py --experiment $experiment
EOF
