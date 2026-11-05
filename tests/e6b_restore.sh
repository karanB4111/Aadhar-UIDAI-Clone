#!/usr/bin/env bash
# PLAN step 11 (E6b): reverse e6b_inject.sh — put the original NACL back
# on each Mumbai app subnet. Reads the state the inject script wrote to
# /tmp/mu-acl-assoc.txt (one line per subnet: `<assoc-id> <original-nacl-id>`).

set -euo pipefail

REGION="${REGION:-ap-south-1}"
STATE_FILE="${STATE_FILE:-/tmp/mu-acl-assoc.txt}"

: "${AWS_PROFILE:?set AWS_PROFILE (e.g. aadhaar)}"
test -s "$STATE_FILE" || { echo "no state file at $STATE_FILE; did inject run?" >&2; exit 2; }

while read -r ASSOC_ID ORIG_NACL; do
  [ -z "$ASSOC_ID" ] && continue
  echo "restore: $ASSOC_ID -> $ORIG_NACL" >&2
  aws ec2 replace-network-acl-association --region "$REGION" \
    --association-id "$ASSOC_ID" --network-acl-id "$ORIG_NACL" \
    --query 'NewAssociationId' --output text >/dev/null
done < "$STATE_FILE"

mv "$STATE_FILE" "$STATE_FILE.done.$(date -u +%Y%m%dT%H%M%S)"
echo "restored originals on all subnets" >&2
