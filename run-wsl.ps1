# run-wsl.ps1
# Launches the lab schedule app inside WSL Ubuntu.
# On first run, pass -Setup to install dependencies.
param(
    [switch]$Setup
)

$wslPath = "/mnt/c/Users/James/python_labschedule"

if ($Setup) {
    Write-Host "Running setup in WSL..." -ForegroundColor Cyan
    wsl -d Ubuntu -- bash -c "cd '$wslPath' && chmod +x setup.sh && ./setup.sh"
}

Write-Host "Starting app in WSL (http://localhost:8080)..." -ForegroundColor Green
wsl -d Ubuntu -- bash -c "cd '$wslPath' && chmod +x run.sh && ./run.sh"
