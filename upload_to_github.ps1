$ErrorActionPreference = "Stop"

$repo = "git@github.com:Syuanya/douyin_monitor.git"
if (-not (Test-Path ".git")) {
  git init
  git remote add origin $repo
} else {
  git remote set-url origin $repo
}

git branch -M main
git add -A
git status
git commit -m "Update clean GitHub source" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "No changes to commit or commit failed. Continuing to push..."
}
git push -u origin main
