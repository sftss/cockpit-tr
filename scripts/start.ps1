# Construit l'interface puis lance le tableau de bord local.
# Usage : .\scripts\start.ps1            (ouvre le navigateur)
#         .\scripts\start.ps1 --no-open  (sans ouvrir le navigateur)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

foreach ($tool in "uv", "npm") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "Outil manquant : $tool. Voir la section Installation du README."
        exit 1
    }
}

Push-Location frontend
try {
    if (-not (Test-Path "node_modules")) {
        npm ci
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
finally {
    Pop-Location
}

uv run cockpit serve @args
