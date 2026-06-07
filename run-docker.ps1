param(
    [switch]$Detached
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$dockerConfigDir = Join-Path $scriptDir '.docker-config-anon'
New-Item -ItemType Directory -Force -Path $dockerConfigDir | Out-Null
Set-Content -Path (Join-Path $dockerConfigDir 'config.json') -Value '{}' -Encoding ASCII

$previousDockerConfig = $env:DOCKER_CONFIG
$env:DOCKER_CONFIG = $dockerConfigDir

try {
    $arguments = @('compose', 'up', '--build')
    if ($Detached) {
        $arguments += '--detach'
    }

    & docker @arguments
}
finally {
    if ($null -ne $previousDockerConfig) {
        $env:DOCKER_CONFIG = $previousDockerConfig
    }
    else {
        Remove-Item Env:DOCKER_CONFIG -ErrorAction SilentlyContinue
    }
}