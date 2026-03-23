param(
    [string]$Source = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install uv first: https://docs.astral.sh/uv/getting-started/installation/"
}

$installArgs = @("tool", "install")
if ($Force) {
    $installArgs += "--force"
}

if ([string]::IsNullOrWhiteSpace($Source)) {
    $Source = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if (Test-Path $Source) {
    $resolvedSource = (Resolve-Path $Source).Path
    $installArgs += @("--editable", $resolvedSource)
}
else {
    $installArgs += $Source
}

Write-Host "Running: uv $($installArgs -join ' ')"
& uv @installArgs

Write-Host "Updating shell PATH integration..."
& uv tool update-shell

Write-Host ""
Write-Host "Installed commands:"
Write-Host "  tasklane"
Write-Host "  tasklane-bootstrap"
Write-Host "  pcs (legacy alias)"
Write-Host "  pcs-bootstrap (legacy alias)"
Write-Host ""
Write-Host "Open a new terminal if the commands are not available immediately."
