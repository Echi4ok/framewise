param(
    [string]$RuntimeDir,
    [string]$ModelDir,
    [ValidateSet('4b-instruct', '8b-instruct')][string]$Variant = '8b-instruct',
    [ValidateRange(1, 65535)][int]$Port = 11436,
    [switch]$Cpu
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'local-processes.ps1')
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    $taskModels = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3
    if ($taskModels.data.id -contains "qwen3-vl:$Variant") {
        Write-Output "Ready http://127.0.0.1:$Port/v1 model=qwen3-vl:$Variant (existing process)"
        return
    }
    throw "Port $Port is occupied by another server or model. Choose another port."
}
if (!$RuntimeDir) { $RuntimeDir = Join-Path $taskProjectRoot '.runtime/llama-b12124-cuda13.4' }
if (!$ModelDir) { $ModelDir = Join-Path $taskProjectRoot '.models' }
$RuntimeDir = [IO.Path]::GetFullPath($RuntimeDir)
$ModelDir = [IO.Path]::GetFullPath($ModelDir)
$taskLogDir = Join-Path $taskProjectRoot '.runtime/logs'
New-Item -ItemType Directory -Path $RuntimeDir, $ModelDir, $taskLogDir -Force | Out-Null

function Get-VerifiedDownload {
    param([string]$Url, [string]$Destination, [string]$Sha256)
    if (Test-Path -LiteralPath $Destination) {
        $taskExistingHash = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash
        if ($taskExistingHash -eq $Sha256) { return }
        throw "Cached file hash mismatch at $Destination. Inspect this cache entry before retrying."
    }
    $taskPartial = $Destination + '.partial'
    Write-Output "Downloading $Url"
    & curl.exe --fail --location --retry 3 --silent --show-error --continue-at - --output $taskPartial $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed, partial data retained at $taskPartial" }
    $taskDownloadedHash = (Get-FileHash -LiteralPath $taskPartial -Algorithm SHA256).Hash
    if ($taskDownloadedHash -ne $Sha256) { throw "Downloaded file hash mismatch at $taskPartial" }
    Move-Item -LiteralPath $taskPartial -Destination $Destination
}

$taskExecutable = Join-Path $RuntimeDir 'llama-server.exe'
$taskRequiredRuntimeFiles = @('llama-server.exe', 'llama-server-impl.dll', 'llama.dll', 'mtmd.dll', 'ggml.dll', 'ggml-base.dll', 'ggml-cuda.dll', 'cublas64_13.dll', 'cublasLt64_13.dll', 'cudart64_13.dll')
$taskMissingRuntimeFiles = @($taskRequiredRuntimeFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $RuntimeDir $_)) })
if ($taskMissingRuntimeFiles) {
    $taskRuntimeArchive = Join-Path $RuntimeDir 'llama.zip'
    $taskCudaArchive = Join-Path $RuntimeDir 'cudart.zip'
    Get-VerifiedDownload `
        -Url 'https://github.com/ggml-org/llama.cpp/releases/download/b12124/llama-b12124-bin-win-cuda-13.4-x64.zip' `
        -Destination $taskRuntimeArchive -Sha256 'B270EA478DE7BF881CD86F8315A290B9C0A6AF1A3BACA4183453F759608C9CAF'
    Get-VerifiedDownload `
        -Url 'https://github.com/ggml-org/llama.cpp/releases/download/b12124/cudart-llama-bin-win-cuda-13.4-x64.zip' `
        -Destination $taskCudaArchive -Sha256 '738F8C251AC22B70C3AE6F83A10CF222725DF0395246A2CF58F32BDB85FBE668'
    Expand-Archive -LiteralPath $taskRuntimeArchive -DestinationPath $RuntimeDir -Force
    Expand-Archive -LiteralPath $taskCudaArchive -DestinationPath $RuntimeDir -Force
}

$taskWeights = @{
    '4b-instruct' = @{
        Model = '3a859c4dca6883593e389a08987f04762f2a374d475cabc1538360473a72b1da'
        Projector = '70ac570fd36b65a64fbb99883c34d5196368c1cf8f63d8402802a34a0ed2b363'
    }
    '8b-instruct' = @{
        Model = 'a0c1f7c1356ebc4135b6d12f726c18487669f1a7099156323d0f7b4ca91aca99'
        Projector = '85aa79666ee786bcc4fe69ac343db5ad468b71ad6272c12bfd8dfb29a8bdf18a'
    }
}
$taskBlobDir = Join-Path $ModelDir 'blobs'
New-Item -ItemType Directory -Path $taskBlobDir -Force | Out-Null
$taskModelPath = Join-Path $taskBlobDir ('sha256-' + $taskWeights[$Variant].Model)
$taskProjectorPath = Join-Path $taskBlobDir ('sha256-' + $taskWeights[$Variant].Projector)
Get-VerifiedDownload -Url ('https://registry.ollama.ai/v2/library/qwen3-vl/blobs/sha256:' + $taskWeights[$Variant].Model) `
    -Destination $taskModelPath -Sha256 $taskWeights[$Variant].Model
Get-VerifiedDownload -Url ('https://registry.ollama.ai/v2/library/qwen3-vl/blobs/sha256:' + $taskWeights[$Variant].Projector) `
    -Destination $taskProjectorPath -Sha256 $taskWeights[$Variant].Projector

$taskUseGpu = !$Cpu
if (!(Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { $taskUseGpu = $false }
if ($taskUseGpu) {
    $taskFreeVram = & nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits
    $taskFirstGpuFree = 0
    $taskFirstGpuValue = [string]($taskFreeVram | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or ![int]::TryParse($taskFirstGpuValue.Trim(), [ref]$taskFirstGpuFree)) { $taskUseGpu = $false }
    $taskMinimumVram = if ($Variant -eq '8b-instruct') { 8500 } else { 5500 }
    if ($taskFirstGpuFree -lt $taskMinimumVram) { $taskUseGpu = $false }
}
$taskGpuLayers = if ($taskUseGpu) { '999' } else { '0' }
$taskArguments = @(
    '-m', ('"' + $taskModelPath + '"'), '--mmproj', ('"' + $taskProjectorPath + '"'),
    '--alias', "qwen3-vl:$Variant", '--host', '127.0.0.1', '--port', $Port,
    '-c', '12288', '-np', '1', '-ngl', $taskGpuLayers, '-fa', 'on',
    '--image-min-tokens', '1024', '--image-max-tokens', '1536', '--no-webui'
)
if (!$taskUseGpu) { $taskArguments += '--no-mmproj-offload' }
$taskProcess = Start-Process -FilePath $taskExecutable -ArgumentList $taskArguments -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $taskLogDir 'model.stdout.log') `
    -RedirectStandardError (Join-Path $taskLogDir 'model.stderr.log')
$taskProcess.Id | Set-Content -LiteralPath (Join-Path $taskLogDir 'model.pid')
$taskState = Save-LocalProcessState $taskProcess.Id 'model' $taskProjectRoot
try {
    for ($taskAttempt = 0; $taskAttempt -lt 90; $taskAttempt++) {
        if ($taskProcess.HasExited) { throw "Model server exited. Inspect $taskLogDir/model.stderr.log" }
        try {
            $taskHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($taskHealth.status -eq 'ok') {
                Write-Output "Ready http://127.0.0.1:$Port/v1 model=qwen3-vl:$Variant GPURequested=$taskUseGpu PID=$($taskProcess.Id)"
                return
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "Readiness timed out. Inspect $taskLogDir and the saved process ID."
} catch {
    Stop-LocalProcessState $taskState $taskProjectRoot
    throw
}
