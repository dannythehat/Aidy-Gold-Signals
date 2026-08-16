$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Template = Join-Path $RepoRoot "wrangler.test.example.jsonc"
$LocalConfig = Join-Path $RepoRoot "wrangler.test.local.jsonc"

if (-not (Get-Command uvx -ErrorAction SilentlyContinue)) {
    throw "uv/uvx is required. Install uv, then run this script again."
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is required by Wrangler. Install Node.js, then run this script again."
}

if (-not (Test-Path $LocalConfig)) {
    Copy-Item $Template $LocalConfig
}

Push-Location $RepoRoot
try {
    Write-Host "[1/4] Checking Cloudflare authentication..."
    & uvx --from workers-py pywrangler whoami
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Cloudflare login is required. A browser window will open."
        & uvx --from workers-py pywrangler login
        if ($LASTEXITCODE -ne 0) { throw "Cloudflare login failed." }
    }

    Write-Host "[2/4] Deploying AIDY test Worker and provisioning draft D1/R2 bindings..."
    $deployOutput = (& uvx --from workers-py pywrangler deploy --config $LocalConfig 2>&1) | Tee-Object -Variable deployLines
    if ($LASTEXITCODE -ne 0) { throw "Cloudflare test deployment failed." }

    Write-Host "[3/4] Applying AIDY D1 migrations..."
    & uvx --from workers-py pywrangler d1 migrations apply AIDY_OPS --remote --yes --config $LocalConfig
    if ($LASTEXITCODE -ne 0) { throw "D1 migration failed." }

    $joined = ($deployLines -join "`n")
    $match = [regex]::Match($joined, 'https://[A-Za-z0-9.-]+\.workers\.dev')
    if (-not $match.Success) {
        throw "Deployment succeeded, but the workers.dev URL could not be detected. Re-run pywrangler deploy and use the printed URL with POST /day1/storage-smoke."
    }

    $smokeUrl = $match.Value.TrimEnd('/') + "/day1/storage-smoke"
    Write-Host "[4/4] Running real D1 -> outbox -> R2 storage smoke test..."
    $result = Invoke-RestMethod -Method Post -Uri $smokeUrl
    $result | ConvertTo-Json -Depth 8
    if (-not $result.ok) { throw "AIDY storage smoke test returned ok=false." }
    Write-Host "AIDY Day 1 Cloudflare storage smoke: PASS"
}
finally {
    Pop-Location
}
