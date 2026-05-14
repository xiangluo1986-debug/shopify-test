[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Name,

    [string]$ProjectRoot = (Get-Location).Path,

    [string]$Sandbox = "workspace-write",

    [switch]$Notify,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($Name -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Name may contain only letters, numbers, dash, underscore, and dot."
}

$clipboardText = Get-Clipboard -Raw
if ([string]::IsNullOrWhiteSpace($clipboardText) -or $clipboardText.Trim().Length -le 20) {
    throw "Clipboard task text must be non-empty and longer than 20 characters."
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "ProjectRoot not found: $ProjectRoot"
}

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$tasksDir = Join-Path -Path $resolvedProjectRoot -ChildPath "ai_project_manager\tasks"
$taskFile = Join-Path -Path $tasksDir -ChildPath "$Name.md"
$runnerPath = Join-Path -Path $PSScriptRoot -ChildPath "run_codex_task.ps1"

if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "Runner script not found: $runnerPath"
}

New-Item -ItemType Directory -Force -Path $tasksDir | Out-Null
Set-Content -LiteralPath $taskFile -Value $clipboardText -Encoding UTF8

Write-Host "Saved task file: $taskFile"
Write-Host "Sandbox: $Sandbox"
Write-Host "Notify: $($Notify.IsPresent)"
Write-Host "DryRun: $($DryRun.IsPresent)"

$runnerParams = @{
    TaskFile = $taskFile
    ProjectRoot = $resolvedProjectRoot
    Sandbox = $Sandbox
}

if ($Notify) {
    $runnerParams["Notify"] = $true
}

if ($DryRun) {
    $runnerParams["DryRun"] = $true
}

& $runnerPath @runnerParams
