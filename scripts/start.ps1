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

# Recupere ce qui a ete publie depuis le dernier lancement : fiches du jour,
# veilles hebdomadaires, code fusionne. Hors ligne, ou si la copie locale ne
# peut pas avancer simplement, l'application demarre avec ce qui est present.
if (Get-Command git -ErrorAction SilentlyContinue) {
    $env:GIT_TERMINAL_PROMPT = "0"
    git pull --ff-only --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "git pull impossible (hors ligne, ou copie locale en avance) : lancement avec la version locale."
    }
}

Push-Location frontend
try {
    # Réinstalle les dépendances à la première fois et quand leur liste a changé
    # (après un git pull, par exemple) : npm date son installation dans ce fichier.
    $wanted = Get-Item "package-lock.json"
    $installed = Get-Item "node_modules/.package-lock.json" -Force -ErrorAction SilentlyContinue
    if (-not $installed -or $installed.LastWriteTimeUtc -lt $wanted.LastWriteTimeUtc) {
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
