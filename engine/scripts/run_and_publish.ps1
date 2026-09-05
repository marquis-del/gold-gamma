$ErrorActionPreference = "Stop"
$engineDir = Split-Path -Parent $PSScriptRoot
$repoDir = Split-Path -Parent $engineDir
$venvPython = Join-Path $engineDir ".venv\Scripts\python.exe"

Set-Location $engineDir
& $venvPython -m src.run_daily --source yfinance

Set-Location $repoDir
git add docs
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "Auto-update levels $(Get-Date -Format 'yyyy-MM-dd HH:mm') ET"
    git push
}
