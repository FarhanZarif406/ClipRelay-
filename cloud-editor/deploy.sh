#!/usr/bin/env sh
# Puts ClipRelay's cloud editor on Google Cloud Run, and makes the service account ClipRelay signs in with.
# Run from the ClipRelay folder after installing the Google Cloud CLI and signing in (gcloud auth login):
#   sh cloud-editor/deploy.sh my-project-id [region]
# At the end it prints the Cloud Run address and writes cliprelay-cloud-key.json: upload both in ClipRelay
# (Integrations -> Cloud editing), then delete the key file. It is a secret.
set -eu
PROJECT="${1:?Give the Google Cloud project id: sh cloud-editor/deploy.sh my-project-id}"
REGION="${2:-us-central1}"
SERVICE="${SERVICE:-cliprelay-editor}"
MAX_INSTANCES="${MAX_INSTANCES:-30}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/cliprelay/editor:latest"
CALLER="cliprelay-caller@$PROJECT.iam.gserviceaccount.com"

echo "1/6 Switching on Cloud Run, Cloud Build and Artifact Registry for $PROJECT ..."
gcloud config set project "$PROJECT" >/dev/null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com

echo "2/6 Making a place for the editor's image ..."
gcloud artifacts repositories describe cliprelay --location "$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create cliprelay --repository-format docker --location "$REGION"

echo "3/6 Building the editor (a few minutes) ..."
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/app/services"
cp "$ROOT/cloud-editor/Dockerfile" "$ROOT/cloud-editor/requirements.txt" "$ROOT/cloud-editor/main.py" "$BUILD/"
cp "$ROOT/cloud-editor/app/__init__.py" "$ROOT/cloud-editor/app/config.py" "$BUILD/app/"
cp "$ROOT/cloud-editor/app/services/__init__.py" "$BUILD/app/services/"
cp "$ROOT/backend/app/services/media.py" "$BUILD/app/services/media.py"
gcloud builds submit --tag "$IMAGE" "$BUILD"

echo "4/6 Starting it on Cloud Run (no public access) ..."
gcloud run deploy "$SERVICE" --image "$IMAGE" --region "$REGION" --no-allow-unauthenticated --concurrency 1 \
  --cpu 2 --memory 2Gi --timeout 3600 --max-instances "$MAX_INSTANCES" --cpu-boost --quiet

echo "5/6 Making the service account ClipRelay signs in with ..."
gcloud iam service-accounts describe "$CALLER" >/dev/null 2>&1 \
  || gcloud iam service-accounts create cliprelay-caller --display-name "ClipRelay server"
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --member "serviceAccount:$CALLER" --role roles/run.invoker --quiet >/dev/null

echo "6/6 Writing its key ..."
gcloud iam service-accounts keys create "$PWD/cliprelay-cloud-key.json" --iam-account "$CALLER"
URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"

echo
echo "Done. In ClipRelay, Integrations -> Cloud editing:"
echo "  Cloud Run address: $URL"
echo "  Key file:          $PWD/cliprelay-cloud-key.json   (upload it, then delete this file)"
