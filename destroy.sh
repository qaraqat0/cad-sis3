#!/usr/bin/env bash
# Delete everything:  ./destroy.sh [project-name]
# Order matters: app imports from the others, so it goes first.
set -euo pipefail
P="${1:-sis3}"
export AWS_REGION="${AWS_REGION:-us-east-1}"

for s in app ecr messaging network; do
  echo ">>> Deleting $P-$s"
  aws cloudformation delete-stack --stack-name "$P-$s"
  aws cloudformation wait stack-delete-complete --stack-name "$P-$s"
done
echo "All stacks for $P deleted."
