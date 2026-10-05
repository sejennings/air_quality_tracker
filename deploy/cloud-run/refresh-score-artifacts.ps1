param(
    [Parameter(Mandatory=$true)][string]$Image,
    [string]$Project = 'air-quality-tracker-510721',
    [string]$Gcloud = "$env:LOCALAPPDATA/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
)
$ErrorActionPreference = 'Stop'
function Invoke-Cloud {
    & $Gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "Google Cloud command failed: $($args[0])" }
}
if ($Image -notmatch '@sha256:[a-f0-9]{64}$') { throw 'Use a tested immutable image digest.' }
$scratchRoot = Join-Path $PSScriptRoot '../../runtime/score-refresh'
$scratch = [IO.Path]::GetFullPath((Join-Path $scratchRoot ([guid]::NewGuid().ToString('N'))))
New-Item -ItemType Directory -Path "$scratch/models", "$scratch/input" -Force | Out-Null
try {
    Invoke-Cloud storage cp "gs://$Project-models/active.json" "$scratch/models/active.json"
    $modelId = (Get-Content "$scratch/models/active.json" -Raw | ConvertFrom-Json).run_id
    if ($modelId -notmatch '^[a-zA-Z0-9-]+$') { throw 'Invalid active model identifier.' }
    New-Item -ItemType Directory -Path "$scratch/models/$modelId" | Out-Null
    foreach ($name in @('model.keras', 'scaler.joblib', 'metadata.json')) {
        Invoke-Cloud storage cp "gs://$Project-models/$modelId/$name" "$scratch/models/$modelId/$name"
    }
    $scoreUris = & $Gcloud storage ls "gs://$Project-operational/scores/**"
    if ($LASTEXITCODE -ne 0) { throw 'Could not list retained scores.' }
    foreach ($uri in $scoreUris) {
        if ($uri -notmatch '\.parquet$') { continue }
        $key = [guid]::NewGuid().ToString('N')
        Invoke-Cloud storage cp $uri "$scratch/input/$key.parquet"
        New-Item -ItemType Directory -Path "$scratch/output-$key" | Out-Null
        docker run --rm --read-only --tmpfs /tmp:size=256m -v "${scratch}/models:/models:ro" -v "${scratch}/input:/input:ro" -v "${scratch}/output-${key}:/operational" $Image score --input "/input/$key.parquet"
        if ($LASTEXITCODE -ne 0) { throw 'Rescoring failed; existing cloud scores were not overwritten.' }
        $results = @(Get-ChildItem -LiteralPath "$scratch/output-$key/scores" -Filter '*.parquet')
        if ($results.Count -ne 1) { throw 'Expected exactly one score artifact.' }
        $verify = 'import pandas as pd, numpy as np; from pathlib import Path; old=pd.read_parquet("/input/source.parquet").sort_values("date").reset_index(drop=True); new=pd.read_parquet(next(Path("/result/scores").glob("*.parquet"))).sort_values("date").reset_index(drop=True); assert old.date.equals(new.date); assert old.model_version.equals(new.model_version); assert old.anomaly.equals(new.anomaly); assert np.allclose(old.reconstruction_error,new.reconstruction_error,rtol=1e-5,atol=1e-6), "Existing model scores changed"; print(f"Verified {len(new)} rows: model and flags unchanged")'
        docker run --rm --read-only --tmpfs /tmp:size=256m --entrypoint python -v "${scratch}/input/${key}.parquet:/input/source.parquet:ro" -v "${scratch}/output-${key}:/result:ro" $Image -c $verify
        if ($LASTEXITCODE -ne 0) { throw 'Verification failed; cloud scores were not overwritten.' }
        Invoke-Cloud storage cp $results[0].FullName $uri
    }
} finally {
    $resolvedScratch = [IO.Path]::GetFullPath($scratch)
    $resolvedRoot = [IO.Path]::GetFullPath($scratchRoot) + [IO.Path]::DirectorySeparatorChar
    if (-not $resolvedScratch.StartsWith($resolvedRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe scratch cleanup path.' }
    Remove-Item -LiteralPath $resolvedScratch -Recurse -Force
}
