# Puts ClipRelay's cloud editor on Google Cloud Run, and makes the service account ClipRelay signs in with.
# Run from the ClipRelay folder after installing the Google Cloud CLI and signing in (gcloud auth login):
#   powershell -ExecutionPolicy Bypass -File cloud-editor\deploy.ps1 -Project my-project-id
# At the end it prints the Cloud Run address and writes cliprelay-cloud-key.json: upload both in ClipRelay
# (Integrations -> Cloud editing), then delete the key file. It is a secret.
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [string]$Region = "us-central1",
    [string]$Service = "cliprelay-editor",
    [int]$MaxInstances = 30
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$image = "$Region-docker.pkg.dev/$Project/cliprelay/editor:latest"
$caller = "cliprelay-caller"
$callerEmail = "$caller@$Project.iam.gserviceaccount.com"

Write-Host "1/6 Switching on Cloud Run, Cloud Build and Artifact Registry for $Project ..."
gcloud config set project $Project | Out-Null
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com iam.googleapis.com
if ($LASTEXITCODE -ne 0) { throw "Could not switch the services on. Is billing set up for the project?" }

Write-Host "2/6 Making a place for the editor's image ..."
gcloud artifacts repositories describe cliprelay --location $Region 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { gcloud artifacts repositories create cliprelay --repository-format docker --location $Region }

Write-Host "3/6 Building the editor (a few minutes) ..."
$build = Join-Path ([System.IO.Path]::GetTempPath()) ("cliprelay-editor-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force (Join-Path $build "app\services") | Out-Null
Copy-Item (Join-Path $root "cloud-editor\Dockerfile"), (Join-Path $root "cloud-editor\requirements.txt"), (Join-Path $root "cloud-editor\main.py") $build
Copy-Item (Join-Path $root "cloud-editor\app\__init__.py"), (Join-Path $root "cloud-editor\app\config.py") (Join-Path $build "app")
Copy-Item (Join-Path $root "cloud-editor\app\services\__init__.py") (Join-Path $build "app\services")
Copy-Item (Join-Path $root "backend\app\services\media.py") (Join-Path $build "app\services\media.py")
try {
    gcloud builds submit --tag $image $build
    if ($LASTEXITCODE -ne 0) { throw "The build failed (see above)." }
} finally {
    Remove-Item -Recurse -Force $build
}

Write-Host "4/6 Starting it on Cloud Run (no public access) ..."
gcloud run deploy $Service --image $image --region $Region --no-allow-unauthenticated --concurrency 1 --cpu 2 --memory 2Gi --timeout 3600 --max-instances $MaxInstances --cpu-boost --quiet
if ($LASTEXITCODE -ne 0) { throw "Cloud Run did not start the editor (see above)." }

Write-Host "5/6 Making the service account ClipRelay signs in with ..."
gcloud iam service-accounts describe $callerEmail 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { gcloud iam service-accounts create $caller --display-name "ClipRelay server" }
gcloud run services add-iam-policy-binding $Service --region $Region --member "serviceAccount:$callerEmail" --role roles/run.invoker --quiet | Out-Null

Write-Host "6/6 Writing its key ..."
$key = Join-Path (Get-Location) "cliprelay-cloud-key.json"
gcloud iam service-accounts keys create $key --iam-account $callerEmail
$url = gcloud run services describe $Service --region $Region --format "value(status.url)"

Write-Host ""
Write-Host "Done. In ClipRelay, Integrations -> Cloud editing:"
Write-Host "  Cloud Run address: $url"
Write-Host "  Key file:          $key   (upload it, then delete this file)"
