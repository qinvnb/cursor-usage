<#
.SYNOPSIS
  Measure idle CPU time and disk writes of Cursor Usage and all child processes
  (taskbar widget, floating ball, WebView2).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\measure_cpu.ps1 -Seconds 300
#>
param(
    [int]$Seconds = 300
)

$ErrorActionPreference = "Stop"

function Get-AppProcesses {
    $all = Get-CimInstance Win32_Process
    $roots = $all | Where-Object {
        $_.Name -like "CursorUsage*" -or
        ($_.CommandLine -and $_.CommandLine -match "cursor_usage_app|run\.py")
    }
    $ids = New-Object System.Collections.Generic.HashSet[int]
    foreach ($r in $roots) { [void]$ids.Add([int]$r.ProcessId) }
    do {
        $added = $false
        foreach ($p in $all) {
            if ($ids.Contains([int]$p.ParentProcessId) -and $ids.Add([int]$p.ProcessId)) {
                $added = $true
            }
        }
    } while ($added)
    $all | Where-Object { $ids.Contains([int]$_.ProcessId) }
}

function Get-Label($proc) {
    $cmd = [string]$proc.CommandLine
    if ($cmd -match "--dock|taskbar_widget") { return "taskbar-widget" }
    if ($cmd -match "--ball|ball_tk") { return "floating-ball" }
    if ($proc.Name -like "msedgewebview2*") { return "webview2" }
    return "main"
}

function Get-Snapshot {
    $snap = @{}
    foreach ($p in Get-AppProcesses) {
        $cpu = ([double]$p.KernelModeTime + [double]$p.UserModeTime) / 1e7
        $snap[[int]$p.ProcessId] = [pscustomobject]@{
            Label  = Get-Label $p
            Cpu    = $cpu
            Writes = [double]$p.WriteOperationCount
            Bytes  = [double]$p.WriteTransferCount
        }
    }
    $snap
}

$before = Get-Snapshot
if ($before.Count -eq 0) {
    Write-Host "Cursor Usage is not running." -ForegroundColor Yellow
    exit 1
}
Write-Host "Sampling $($before.Count) processes for $Seconds s ..."
Start-Sleep -Seconds $Seconds
$after = Get-Snapshot

$cores = [Environment]::ProcessorCount
$rows = foreach ($id in $after.Keys) {
    if (-not $before.ContainsKey($id)) { continue }
    $a = $after[$id]; $b = $before[$id]
    $cpu = $a.Cpu - $b.Cpu
    [pscustomobject]@{
        Label        = $a.Label
        PID          = $id
        "CPU s"      = [math]::Round($cpu, 2)
        "CPU %"      = [math]::Round($cpu / $Seconds / $cores * 100, 3)
        "Writes/min" = [math]::Round(($a.Writes - $b.Writes) / $Seconds * 60, 1)
        "KB written" = [math]::Round(($a.Bytes - $b.Bytes) / 1KB, 1)
    }
}

$groups = $rows | Group-Object Label | ForEach-Object {
    [pscustomobject]@{
        Component    = $_.Name
        Processes    = $_.Count
        "CPU s"      = [math]::Round(($_.Group | Measure-Object "CPU s" -Sum).Sum, 2)
        "CPU %"      = [math]::Round(($_.Group | Measure-Object "CPU %" -Sum).Sum, 3)
        "Writes/min" = [math]::Round(($_.Group | Measure-Object "Writes/min" -Sum).Sum, 1)
        "KB written" = [math]::Round(($_.Group | Measure-Object "KB written" -Sum).Sum, 1)
    }
}
$groups | Sort-Object "CPU s" -Descending | Format-Table -AutoSize
$total = ($rows | Measure-Object "CPU %" -Sum).Sum
Write-Host ("Total CPU (share of all {0} cores): {1:N3}%" -f $cores, $total)
