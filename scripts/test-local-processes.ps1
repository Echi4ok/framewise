$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'local-processes.ps1')
$root = 'C:\Framewise Test\project'
$created = [DateTime]::Parse('2026-11-06T10:00:00Z').ToUniversalTime()
$parent = [pscustomobject]@{ ProcessId = 100; ParentProcessId = 1; CreationDate = $created; ExecutablePath = 'C:\Framewise Test\project\.venv\Scripts\python.exe'; CommandLine = 'python -m uvicorn app.main:app --port 8000' }
$child = [pscustomobject]@{ ProcessId = 101; ParentProcessId = 100; CreationDate = $created.AddSeconds(1); ExecutablePath = 'C:\Python\python.exe'; CommandLine = $parent.CommandLine }
$grandchild = [pscustomobject]@{ ProcessId = 103; ParentProcessId = 101; CreationDate = $created.AddSeconds(2); ExecutablePath = 'C:\Python\helper.exe'; CommandLine = 'helper' }
$older = [pscustomobject]@{ ProcessId = 102; ParentProcessId = 100; CreationDate = $created.AddSeconds(-1) }
$script:processes = @($parent, $child, $grandchild, $older)
$script:stopped = @()

function Assert-True($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

$localProvider = 'http://127.0.0.1:11436/v1'
Assert-True ((Get-PublicProviderUrl $localProvider) -eq $localProvider) 'A plain local provider URL must remain unchanged.'
Assert-True ((Get-PublicProviderUrl ($localProvider + '/')) -eq $localProvider) 'A trailing slash must remain ignored.'
$healthProvider = [pscustomobject]@{ provider = 'https://example.invalid:8443/v1' }
Assert-True ((Get-PublicProviderUrl $healthProvider.provider) -eq (Get-PublicProviderUrl 'https://test-user:placeholder-password@example.invalid:8443/v1/?token=placeholder-token#placeholder-fragment')) 'Redacted health provider must match credentials/query/fragment removed from the requested URL.'
Assert-True ((Get-PublicProviderUrl $healthProvider.provider) -ne (Get-PublicProviderUrl 'https://example.invalid:8443/v2')) 'Different provider paths must still be rejected.'

$identity = New-LocalProcessState $parent 'backend' $root
Assert-True (Test-LocalProcessState $identity $parent 'backend' $root) 'An unchanged owned process must match.'
$reused = $parent.PSObject.Copy()
$reused.CreationDate = $created.AddSeconds(10)
Assert-True (-not (Test-LocalProcessState $identity $reused 'backend' $root)) 'A reused PID must be rejected even with the same executable and command.'
Assert-True (-not (Test-LocalProcessState $identity $parent 'backend' 'C:\Other Project')) 'A state copied from another checkout must be rejected.'
$changed = $parent.PSObject.Copy()
$changed.CommandLine = 'python -m uvicorn app.main:app --port 9000'
Assert-True (-not (Test-LocalProcessState $identity $changed 'backend' $root)) 'A changed command must be rejected.'
Assert-True (-not (Test-LocalProcessState $identity $null 'backend' $root)) 'An exited process must be rejected.'
$tree = @(Get-LocalProcessTree $parent $script:processes)
Assert-True (($tree.ProcessId -join ',') -eq '103,101,100') 'Children must precede their wrapper, and older stale-parent processes must be excluded.'

# All OS process/stop/delete functions below are local mocks. This script never
# starts or stops real processes and never removes actual files.
function Get-CimInstance { param($ClassName, $Filter, $ErrorAction); if ($Filter) { return $script:processes | Where-Object { $_.ProcessId -eq 100 } }; return $script:processes }
function Get-Process { param($Id, $ErrorAction); $member = $script:processes | Where-Object { $_.ProcessId -eq $Id }; return [pscustomobject]@{ Id = $Id; StartTime = $member.CreationDate.AddTicks(9) } }
function Stop-Process { param($InputObject, $ErrorAction); $script:stopped += $InputObject.Id }
function Remove-Item { param($LiteralPath, $ErrorAction) }
function Get-NetTCPConnection { param($LocalPort, $State, $ErrorAction); return [pscustomobject]@{ OwningProcess = 101 } }
Assert-True (Test-LocalServicePort $identity 8000 $root) 'A child interpreter may own the listening port.'
$rejected = $false
try { Test-LocalServicePort $null 8000 $root | Out-Null } catch { $rejected = $true }
Assert-True $rejected 'An occupied port without owned state must be rejected.'
Stop-LocalProcessState $identity $root
Assert-True (($script:stopped -join ',') -eq '103,101,100') 'Stopping must terminate the verified child tree before the venv wrapper.'
$script:stopped = @()
$script:processes = @($reused)
Stop-LocalProcessState $identity $root
Assert-True ($script:stopped.Count -eq 0) 'Stopping with stale identity must leave a reused PID untouched.'
Write-Output '14 provider URL/process ownership/port/tree checks passed with mocked OS calls.'
