#!/usr/bin/env bash
# PLAN step 7: drive one failover run against the Tier 1 ALB
# (ARCHITECTURE.md 8.4 experiments E1 / E1b / E2 and the method in 8.5).
#
# POSIX equivalent of tests/step7_run.ps1. Same preconditions:
#   - envs/tier1 is applied (default fast health-checks for E1/E2, or with
#     terraform.tfvars.e1b for E1b). Jeel runs these; see HANDOFF.md.
#   - AWS_PROFILE exports a profile allowed to SSM / EC2 the Tier 1 instances.
#   - Laptop clock is NTP-synced (ARCHITECTURE.md 8.3).
#
# Usage
#   export AWS_PROFILE=aadhaar
#   ./tests/step7_run.sh e1 1 a i-0abc1234567890def \
#       aadhaar-tier1-alb-XXXXXXXXXX.ap-south-1.elb.amazonaws.com 6cc656f

set -euo pipefail

usage() {
    cat >&2 <<'USAGE'
usage: step7_run.sh <experiment> <run-number> <target-az> <instance-id> <alb-dns> <image-tag> [duration] [inject-at] [restore-at]
  experiment: e1 | e1b | e2
  target-az : a | b
  Defaults: duration 180, inject-at 30, restore-at 120 (ARCHITECTURE.md 8.5).
USAGE
    exit 2
}

[[ $# -ge 6 ]] || usage

experiment="$1"
run_number="$2"
target_az="$3"
instance_id="$4"
alb_dns="$5"
image_tag="$6"
duration="${7:-180}"
inject_at="${8:-30}"
restore_at="${9:-120}"
region="${AWS_REGION:-ap-south-1}"

case "$experiment" in e1|e1b|e2) ;; *) usage ;; esac
case "$target_az" in a|b) ;; *) usage ;; esac
if ! [[ "$run_number" =~ ^[0-9]+$ ]] || (( run_number < 1 || run_number > 99 )); then
    usage
fi

run_id=$(printf '%s-r%02d-az-%s' "$experiment" "$run_number" "$target_az")
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
prober="$repo_root/tests/prober.py"
run_dir="$repo_root/results/$experiment/$run_id"
alb_url="http://$alb_dns/"

if [[ -f "$run_dir/prober.csv" ]]; then
    echo "prober.csv already exists under $run_dir. Pick a new run number." >&2
    exit 1
fi

if [[ -z "${AWS_PROFILE:-}" ]]; then
    echo "warning: AWS_PROFILE is not set; aws CLI will use its default profile." >&2
fi

mkdir -p "$run_dir"
case "$experiment" in
    e1|e1b)
        # Materialise the --parameters JSON into the run dir so the aws CLI
        # loads it via file:// — matches the Windows path and avoids any
        # inner-quote tokenisation surprise.
        inject_params="$run_dir/ssm-inject.json"
        restore_params="$run_dir/ssm-restore.json"
        printf '{"commands":["docker stop aadhaar-mock"]}\n' > "$inject_params"
        printf '{"commands":["docker start aadhaar-mock"]}\n' > "$restore_params"
        inject_cmd="aws ssm send-command --region $region --document-name AWS-RunShellScript --instance-ids $instance_id --parameters file://$inject_params --query Command.CommandId --output text"
        restore_cmd="aws ssm send-command --region $region --document-name AWS-RunShellScript --instance-ids $instance_id --parameters file://$restore_params --query Command.CommandId --output text"
        ;;
    e2)
        # Restore fires only start-instances; the chain driver issues
        # `docker start aadhaar-mock` via SSM once SSM reports the instance
        # online. user_data runs only on first boot, so plain start-instances
        # leaves the container down.
        inject_cmd="aws ec2 stop-instances --region $region --instance-ids $instance_id --query StoppingInstances[0].CurrentState.Name --output text"
        restore_cmd="aws ec2 start-instances --region $region --instance-ids $instance_id --query StartingInstances[0].CurrentState.Name --output text"
        ;;
esac

case "$experiment" in
    e1b) hc_interval=30; hc_timeout=5; hc_healthy=5; hc_unhealthy=2 ;;
    *)   hc_interval=5;  hc_timeout=2; hc_healthy=2; hc_unhealthy=2 ;;
esac

echo
echo "step 7 run: $run_id"
echo "  ALB     : $alb_url"
echo "  target  : $instance_id (az $target_az, $region)"
echo "  schedule: inject at ${inject_at}s, restore at ${restore_at}s, stop at ${duration}s"
echo "  hc      : interval=$hc_interval s, timeout=$hc_timeout s, healthy=$hc_healthy, unhealthy=$hc_unhealthy"
echo "  out     : $run_dir"
echo

cd "$repo_root"
python tests/prober.py "$alb_url" \
    --run-id "$run_id" \
    --rate 20 \
    --duration "$duration" \
    --image-tag "$image_tag" \
    --meta "hc_interval_s=$hc_interval" \
    --meta "hc_timeout_s=$hc_timeout" \
    --meta "hc_healthy_threshold=$hc_healthy" \
    --meta "hc_unhealthy_threshold=$hc_unhealthy" \
    --meta "instance_type=t3.micro" \
    --meta "target_instance_id=$instance_id" \
    --meta "target_az=$target_az" \
    --meta "experiment=$experiment" \
    --action "$inject_at" inject_start "$inject_cmd" \
    --action "$restore_at" restore "$restore_cmd"

echo
echo "Done. Verify with:"
echo "  python analysis/analyze.py --run-dir \"$run_dir\""
