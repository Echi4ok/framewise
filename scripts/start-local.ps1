param(
    [string]$Python = 'python',
    [string]$RuntimeDir = '',
    [string]$ModelDir = '',
    [string]$ModelName = 'qwen3-vl:8b-instruct',
    [string]$ModelBaseUrl = 'http://127.0.0.1:11436/v1',
    [switch]$SkipModel
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeState = Join-Path $projectRoot '.runtime'
. (Join-Path $PSScriptRoot 'local-processes.ps1')
New-Item -ItemType Directory -Path $runtimeState -Force | Out-Null
$started = @()

function Test-Endpoint([string]$Url) {
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

# Check ownership before installing dependencies or starting any process.
$backendState = Get-LocalProcessState 'backend' $projectRoot
$frontendState = Get-LocalProcessState 'frontend' $projectRoot
$apiAlreadyRunning = Test-LocalServicePort $backendState 8000 $projectRoot
$frontendAlreadyRunning = Test-LocalServicePort $frontendState 5173 $projectRoot
if ($backendState -and -not $apiAlreadyRunning) { throw 'The recorded API process is running but not listening. Check .runtime logs or stop it before retrying.' }
if ($frontendState -and -not $frontendAlreadyRunning) { throw 'The recorded frontend process is running but not listening. Check .runtime logs or stop it before retrying.' }
if ($apiAlreadyRunning) {
    $runningApi = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3
    if ($runningApi.model -ne $ModelName -or (Get-PublicProviderUrl $runningApi.provider) -ne (Get-PublicProviderUrl $ModelBaseUrl)) {
        throw 'Port 8000 already serves this project with a different model configuration. Stop it or use matching options.'
    }
}

try {
    if (-not $SkipModel) {
        $modelUri = [uri]$ModelBaseUrl
        if ($modelUri.Scheme -ne 'http' -or $modelUri.Host -notin @('127.0.0.1', 'localhost') -or $modelUri.AbsolutePath.TrimEnd('/') -ne '/v1' -or $modelUri.Query -or $modelUri.Fragment) {
            throw 'Automatic model startup requires http://127.0.0.1:<port>/v1. Use -SkipModel for an external endpoint.'
        }
        if ($ModelName -notin @('qwen3-vl:4b-instruct', 'qwen3-vl:8b-instruct')) {
            throw 'Use -SkipModel with an external model endpoint, or choose a supported local Qwen model.'
        }
        $previousModel = Get-LocalProcessState 'model' $projectRoot
        if (-not (Test-Endpoint ($modelUri.GetLeftPart([UriPartial]::Authority) + '/health'))) {
            $modelArguments = @{ Variant = $ModelName.Split(':')[1]; Port = $modelUri.Port }
            if ($RuntimeDir) { $modelArguments.RuntimeDir = $RuntimeDir }
            if ($ModelDir) { $modelArguments.ModelDir = $ModelDir }
            & (Join-Path $PSScriptRoot 'start-model.ps1') @modelArguments
            $newModel = Get-LocalProcessState 'model' $projectRoot
            if (-not $previousModel -and $newModel) { $started += $newModel }
        }
        $availableModels = Invoke-RestMethod -Uri ($ModelBaseUrl.TrimEnd('/') + '/models') -TimeoutSec 5
        if ($availableModels.data.id -notcontains $ModelName) { throw "The running model does not expose $ModelName." }
    }

    $venvRoot = Join-Path $projectRoot '.venv'
    $venvPython = Join-Path $venvRoot 'Scripts/python.exe'
    if (-not $apiAlreadyRunning) {
        if (-not (Test-Path -LiteralPath $venvPython)) {
            & $Python -m venv $venvRoot
            if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python virtual environment.' }
        }
        & $venvPython -m pip install --quiet --disable-pip-version-check -r (Join-Path $projectRoot 'backend/requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Backend dependency installation failed.' }
        $env:MODEL_NAME = $ModelName
        $env:MODEL_BASE_URL = $ModelBaseUrl
        $backendProcess = Start-Process -FilePath $venvPython -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeState 'backend.out.log') -RedirectStandardError (Join-Path $runtimeState 'backend.err.log') -PassThru
        $backendState = Save-LocalProcessState $backendProcess.Id 'backend' $projectRoot
        $started += $backendState
        Set-Content -LiteralPath (Join-Path $runtimeState 'backend.pid') -Value $backendProcess.Id
    }

    if (-not $frontendAlreadyRunning) {
        Push-Location (Join-Path $projectRoot 'frontend')
        try {
            & npm.cmd ci --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        } finally { Pop-Location }
        $nodePath = (Get-Command node.exe).Source
        $vitePath = Join-Path $projectRoot 'frontend/node_modules/vite/bin/vite.js'
        $frontendProcess = Start-Process -FilePath $nodePath -ArgumentList @(('"' + $vitePath + '"'), '--host', '127.0.0.1', '--port', '5173', '--strictPort') -WorkingDirectory (Join-Path $projectRoot 'frontend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeState 'frontend.out.log') -RedirectStandardError (Join-Path $runtimeState 'frontend.err.log') -PassThru
        $frontendState = Save-LocalProcessState $frontendProcess.Id 'frontend' $projectRoot
        $started += $frontendState
        Set-Content -LiteralPath (Join-Path $runtimeState 'frontend.pid') -Value $frontendProcess.Id
    }

    $deadline = (Get-Date).AddSeconds(45)
    while (-not ((Test-Endpoint 'http://127.0.0.1:8000/api/health') -and (Test-Endpoint 'http://127.0.0.1:5173'))) {
        if ((Get-Date) -gt $deadline) { throw "Startup timed out. See $runtimeState logs." }
        Start-Sleep -Seconds 1
    }
    Test-LocalServicePort $backendState 8000 $projectRoot | Out-Null
    Test-LocalServicePort $frontendState 5173 $projectRoot | Out-Null
    Write-Host 'Framewise is running at http://127.0.0.1:5173'
    Write-Host 'API documentation: http://127.0.0.1:8000/docs'
} catch {
    for ($index = $started.Count - 1; $index -ge 0; $index--) {
        Stop-LocalProcessState $started[$index] $projectRoot
    }
    throw
}
