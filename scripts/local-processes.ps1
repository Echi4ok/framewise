function Get-PublicProviderUrl {
    param([string]$Url)
    try { $address = [UriBuilder]::new($Url) }
    catch { throw 'Invalid model provider URL.' }
    $address.UserName = ''
    $address.Password = ''
    $address.Query = ''
    $address.Fragment = ''
    return $address.Uri.AbsoluteUri.TrimEnd('/')
}

function New-LocalProcessState {
    param($Process, [string]$Service, [string]$ProjectRoot)
    [pscustomobject]@{
        Service = $Service
        ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
        ProcessId = [int]$Process.ProcessId
        CreationTicks = $Process.CreationDate.ToUniversalTime().Ticks.ToString()
        ExecutablePath = $Process.ExecutablePath
        CommandLine = $Process.CommandLine
    }
}

function Test-LocalProcessState {
    param($State, $Process, [string]$Service, [string]$ProjectRoot)
    return $null -ne $Process -and $null -ne $State -and
        $State.Service -eq $Service -and $State.ProjectRoot -eq [IO.Path]::GetFullPath($ProjectRoot) -and
        [int]$State.ProcessId -eq [int]$Process.ProcessId -and
        $State.CreationTicks -eq $Process.CreationDate.ToUniversalTime().Ticks.ToString() -and
        $State.ExecutablePath -eq $Process.ExecutablePath -and
        $State.CommandLine -ceq $Process.CommandLine
}

function Save-LocalProcessState {
    param([int]$ProcessId, [string]$Service, [string]$ProjectRoot)
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if (-not $current) { throw "$Service exited before its process identity could be recorded." }
    $state = New-LocalProcessState $current $Service $ProjectRoot
    $stateFile = Join-Path $ProjectRoot ".runtime/$Service.process.json"
    $state | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    return $state
}

function Get-LocalProcessState {
    param([string]$Service, [string]$ProjectRoot)
    $stateFile = Join-Path $ProjectRoot ".runtime/$Service.process.json"
    if (Test-Path -LiteralPath $stateFile) {
        $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$state.ProcessId)" -ErrorAction SilentlyContinue
        if (Test-LocalProcessState $state $current $Service $ProjectRoot) { return $state }
        return $null
    }

    # Legacy PID files have no start-time field. Their write time must be close
    # to process creation, and their command must identify this local service.
    $relativePidFile = if ($Service -eq 'model') { 'logs/model.pid' } else { "$Service.pid" }
    $pidFile = Join-Path $ProjectRoot ".runtime/$relativePidFile"
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    $text = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($text -notmatch '^[1-9][0-9]*$') { return $null }
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $text" -ErrorAction SilentlyContinue
    if (-not $current) { return $null }
    $elapsed = ((Get-Item -LiteralPath $pidFile).LastWriteTimeUtc - $current.CreationDate.ToUniversalTime()).TotalSeconds
    if ($elapsed -lt 0 -or $elapsed -gt 15) { return $null }
    $expected = switch ($Service) {
        'frontend' { $current.CommandLine -like ('*' + [IO.Path]::GetFullPath((Join-Path $ProjectRoot 'frontend/node_modules/vite/bin/vite.js')) + '*') }
        'backend' { $current.ExecutablePath -eq [IO.Path]::GetFullPath((Join-Path $ProjectRoot '.venv/Scripts/python.exe')) -and $current.CommandLine -match '-m uvicorn app\.main:app' }
        'model' { $current.Name -eq 'llama-server.exe' -and $current.CommandLine -match '--alias qwen3-vl:(4b|8b)-instruct --host 127\.0\.0\.1' }
    }
    if (-not $expected) { return $null }
    return New-LocalProcessState $current $Service $ProjectRoot
}

function Get-LocalProcessTree {
    param($Parent, [array]$Processes)
    foreach ($child in $Processes | Where-Object { $_.ParentProcessId -eq $Parent.ProcessId -and $_.CreationDate -ge $Parent.CreationDate }) {
        Get-LocalProcessTree $child $Processes
    }
    return $Parent
}

function Test-LocalServicePort {
    param($State, [int]$Port, [string]$ProjectRoot)
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (-not $listeners) { return $false }
    if (-not $State) { throw "Port $Port is occupied by a process not owned by this project's launcher." }
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$State.ProcessId)" -ErrorAction SilentlyContinue
    if (-not (Test-LocalProcessState $State $current $State.Service $ProjectRoot)) { throw "The saved process identity for port $Port is stale." }
    $members = @(Get-LocalProcessTree $current @(Get-CimInstance Win32_Process))
    if ($listeners | Where-Object { $_.OwningProcess -notin $members.ProcessId }) {
        throw "Port $Port is occupied by another process."
    }
    return $true
}

function Stop-LocalProcessState {
    param($State, [string]$ProjectRoot)
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$State.ProcessId)" -ErrorAction SilentlyContinue
    if (-not (Test-LocalProcessState $State $current $State.Service $ProjectRoot)) { return }
    $processes = @(Get-CimInstance Win32_Process)
    foreach ($member in @(Get-LocalProcessTree $current $processes)) {
        $handle = Get-Process -Id $member.ProcessId -ErrorAction SilentlyContinue
        # CIM truncates creation time to microseconds; Process.StartTime keeps
        # 100ns ticks. Compare within that one-microsecond precision window.
        if ($handle -and [Math]::Abs($handle.StartTime.ToUniversalTime().Ticks - $member.CreationDate.ToUniversalTime().Ticks) -lt 10) {
            # Kill verified children before their launcher; Windows venv python
            # starts a child interpreter, which survives killing only its parent.
            Stop-Process -InputObject $handle -ErrorAction Stop
        }
    }
    Remove-Item -LiteralPath (Join-Path $ProjectRoot ".runtime/$($State.Service).process.json") -ErrorAction SilentlyContinue
    $relativePidFile = if ($State.Service -eq 'model') { 'logs/model.pid' } else { "$($State.Service).pid" }
    Remove-Item -LiteralPath (Join-Path $ProjectRoot ".runtime/$relativePidFile") -ErrorAction SilentlyContinue
}
