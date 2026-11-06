$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'local-processes.ps1')

foreach ($serviceName in @('frontend', 'backend', 'model')) {
    $state = Get-LocalProcessState $serviceName $projectRoot
    if ($state) {
        Stop-LocalProcessState $state $projectRoot
        Write-Host "Stopped $serviceName (PID $($state.ProcessId) and its children)"
    }
}
