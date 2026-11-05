#!/usr/bin/env bash
# PLAN step 11 (E6b): attach the deny-all NACL to Mumbai's two app
# subnets so ALB targets become unreachable. The matching restore script
# is tests/e6b_restore.sh.
#
# Reads the state it needs on every call from AWS (and from tier3 outputs),
# so no per-run state file is left around. After injection it writes the
# original NACL association ids to /tmp/mu-acl-assoc.txt (one line per
# subnet: `<assoc-id> <original-nacl-id>`). e6b_restore.sh reads that file.
#
# Needs AWS_PROFILE set (see HANDOFF.md).

set -euo pipefail

REGION="${REGION:-ap-south-1}"
VPC_NAME="${VPC_NAME:-aadhaar-tier3-mu}"
STATE_FILE="${STATE_FILE:-/tmp/mu-acl-assoc.txt}"

: "${AWS_PROFILE:?set AWS_PROFILE (e.g. aadhaar)}"

VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=tag:Name,Values=$VPC_NAME" \
  --query 'Vpcs[0].VpcId' --output text)
test "$VPC_ID" != "None" || { echo "no VPC named $VPC_NAME in $REGION" >&2; exit 2; }

DENY_NACL=$(aws ec2 describe-network-acls --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" \
            "Name=tag:Name,Values=${VPC_NAME}-deny-all" \
  --query 'NetworkAcls[0].NetworkAclId' --output text)
test "$DENY_NACL" != "None" || { echo "deny-all NACL not found in $VPC_ID" >&2; exit 2; }

APP_SUBNETS=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC_ID" "Name=tag:Role,Values=app" \
  --query 'Subnets[*].SubnetId' --output text)

: > "$STATE_FILE"
for SN in $APP_SUBNETS; do
  # Find the subnet's current ACL association.
  read -r ASSOC_ID ORIG_NACL < <(aws ec2 describe-network-acls --region "$REGION" \
    --filters "Name=association.subnet-id,Values=$SN" \
    --query "NetworkAcls[*].Associations[?SubnetId=='$SN'].[NetworkAclAssociationId,NetworkAclId] | [0][0]" \
    --output text)
  echo "subnet $SN: swap $ASSOC_ID ($ORIG_NACL) -> $DENY_NACL" >&2
  NEW_ASSOC=$(aws ec2 replace-network-acl-association --region "$REGION" \
    --association-id "$ASSOC_ID" --network-acl-id "$DENY_NACL" \
    --query 'NewAssociationId' --output text)
  echo "$NEW_ASSOC $ORIG_NACL" >> "$STATE_FILE"
done

echo "injected: deny-all NACL on $APP_SUBNETS; original associations in $STATE_FILE" >&2
