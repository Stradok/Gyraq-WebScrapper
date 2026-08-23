$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "Installing Python dependencies..."
uv sync

Write-Host "Installing Chromium for Playwright..."
uv run playwright install chromium

Write-Host ""
Write-Host "Setup complete. Start it with:"
Write-Host "  .\run.ps1"
