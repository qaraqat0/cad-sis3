#!/usr/bin/env bash
# One command deploy:  ./deploy.sh [project-name]
# Second copy for the reproducibility test:  ./deploy.sh sis3-copy
set -euo pipefail
cd "$(dirname "$0")"

P="${1:-sis3}"
ENV_NAME="${ENV_NAME:-dev}"
REGION="${AWS_REGION:-us-east-1}"
export AWS_REGION="$REGION"

deploy() { # stack-name template [Key=Value ...]
  echo ">>> Deploying stack $1"
  aws cloudformation deploy \
    --stack-name "$1" --template-file "$2" \
    --capabilities CAPABILITY_IAM \
    --no-fail-on-empty-changeset \
    --tags Project="$P" \
    --parameter-overrides ProjectName="$P" "${@:3}"
}

output() { # stack-name output-key
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

deploy "$P-network"   templates/network.yaml
deploy "$P-messaging" templates/messaging.yaml
deploy "$P-ecr"       templates/ecr.yaml

# Immutable tag = git commit (+timestamp if there are uncommitted changes)
TAG="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
if [ "$TAG" = "nogit" ] || [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  TAG="$TAG-$(date +%Y%m%d%H%M%S)"
fi

REPO_URI="$(output "$P-ecr" RepositoryUri)"
if aws ecr describe-images --repository-name "$P-app" --image-ids imageTag="$TAG" >/dev/null 2>&1; then
  echo ">>> Image $TAG already in ECR, skipping build"
else
  echo ">>> Building and pushing $REPO_URI:$TAG"
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%%/*}"
  docker build --provenance=false --platform linux/arm64 -t "$REPO_URI:$TAG" app
  docker push "$REPO_URI:$TAG"
fi

deploy "$P-app" templates/app.yaml ImageTag="$TAG" Environment="$ENV_NAME"

echo
echo "Done. App URL: $(output "$P-app" AppUrl)"
