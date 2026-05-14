[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Name,

    [string]$ProjectRoot = (Get-Location).Path,

    [string]$Sandbox = "workspace-write",

    [switch]$Notify,

    [switch]$DryRun,

    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$minimumClipboardLength = 200
$previewLineCount = 5

function Get-ClipboardPreview {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text,

        [Parameter(Mandatory = $true)]
        [int]$Count
    )

    $lines = @($Text -split "`r?`n")
    return @($lines | Select-Object -First $Count)
}

function Format-PreviewLine {
    param(
        [AllowNull()]
        [string]$Line
    )

    if ($null -eq $Line) {
        return "<blank>"
    }

    $display = $Line -replace "`t", "    "
    if ([string]::IsNullOrWhiteSpace($display)) {
        return "<blank>"
    }

    if ($display -match '(?i)(secret|token|api[_-]?key|password|credential|authorization|cloudflared).{0,40}[:=]') {
        return "[redacted secret-like preview line]"
    }

    if ($display.Length -gt 160) {
        return $display.Substring(0, 160) + "... [truncated]"
    }

    return $display
}

function Get-FirstNonEmptyLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    foreach ($line in @($Text -split "`r?`n")) {
        if (-not [string]::IsNullOrWhiteSpace($line)) {
            return $line.Trim()
        }
    }

    return ""
}

function Test-CommandLikeClipboardStart {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $firstLine = Get-FirstNonEmptyLine -Text $Text
    if ([string]::IsNullOrWhiteSpace($firstLine)) {
        return $false
    }

    $blockedStartPatterns = @(
        '(?i)^cd(\s|$)',
        '(?i)^chdir(\s|$)',
        '(?i)^set-location(\s|$)',
        '(?i)^powershell(\.exe)?(\s|$)',
        '(?i)^pwsh(\.exe)?(\s|$)',
        '(?i)^git(\s|$)',
        '(?i)^get-clipboard(\s|$)',
        '^\$taskPath(\s|=|$)',
        '^\$clipboardText(\s|=|$)'
    )

    foreach ($pattern in $blockedStartPatterns) {
        if ($firstLine -match $pattern) {
            return $true
        }
    }

    return $false
}

function Get-MissingStructureKeywords {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Text
    )

    $keywords = @("Goal", "Allowed", "Validation", "Final response")
    $missing = New-Object System.Collections.Generic.List[string]

    foreach ($keyword in $keywords) {
        if ($Text -notmatch [regex]::Escape($keyword)) {
            $missing.Add($keyword)
        }
    }

    return @($missing.ToArray())
}

if ($Name -notmatch '^[A-Za-z0-9._-]+$') {
    throw "Name may contain only letters, numbers, dash, underscore, and dot."
}

$clipboardText = Get-Clipboard -Raw
if ($null -eq $clipboardText) {
    $clipboardText = ""
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "ProjectRoot not found: $ProjectRoot"
}

$resolvedProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).ProviderPath
$tasksDir = Join-Path -Path $resolvedProjectRoot -ChildPath "ai_project_manager\tasks"
$taskFile = Join-Path -Path $tasksDir -ChildPath "$Name.md"
$relativeTaskPath = "ai_project_manager/tasks/$Name.md"
$runnerPath = Join-Path -Path $PSScriptRoot -ChildPath "run_codex_task.ps1"

if (-not (Test-Path -LiteralPath $runnerPath)) {
    throw "Runner script not found: $runnerPath"
}

if ((Split-Path -Path $taskFile -Leaf) -cne "$Name.md") {
    throw "Task file name must exactly match -Name with .md extension."
}

$previewLines = @(Get-ClipboardPreview -Text $clipboardText -Count $previewLineCount)
$missingKeywords = @(Get-MissingStructureKeywords -Text $clipboardText)

Write-Host "Clipboard runner preflight"
Write-Host "Name: $Name"
Write-Host "Clipboard length: $($clipboardText.Length)"
Write-Host "Task save path: $taskFile"
Write-Host "Runner path: $runnerPath"
Write-Host "Sandbox: $Sandbox"
Write-Host "Notify: $($Notify.IsPresent)"
Write-Host "DryRun: $($DryRun.IsPresent)"
Write-Host "Force: $($Force.IsPresent)"
Write-Host "Clipboard preview (first $previewLineCount lines):"
for ($i = 0; $i -lt $previewLines.Count; $i += 1) {
    $lineNumber = $i + 1
    Write-Host ("{0}: {1}" -f $lineNumber, (Format-PreviewLine -Line $previewLines[$i]))
}

if ([string]::IsNullOrWhiteSpace($clipboardText)) {
    throw "Clipboard task text must be non-empty."
}

if (Test-CommandLikeClipboardStart -Text $clipboardText) {
    throw "Clipboard appears to start with a PowerShell or Git command. Copy the task body, not the command used to launch the runner."
}

if ($clipboardText.Trim().Length -lt $minimumClipboardLength) {
    throw "Clipboard task text must be at least $minimumClipboardLength characters after trimming."
}

if ($missingKeywords.Count -gt 0) {
    Write-Warning "Clipboard task is missing recommended structure keywords: $($missingKeywords -join ', ')"
}

Write-Host "Would save task file: $taskFile"
Write-Host "Would run task through: $runnerPath"

if ($DryRun) {
    Write-Host "Dry run only. No task file was saved and the Codex runner was not called."
    return
}

if (-not $Force) {
    $confirmation = Read-Host "Proceed with this clipboard task? Type Y to continue"
    if ($confirmation -cnotin @("Y", "YES", "y", "yes")) {
        Write-Host "Cancelled. No task file saved and runner was not called."
        return
    }
} else {
    Write-Host "Force supplied; skipping manual YES confirmation after safety checks."
}

$taskFileText = @"
<!--
Clipboard runner source:
Name: $Name
Task file: $relativeTaskPath
Saved by: scripts/run_codex_clipboard_task.ps1
-->

$($clipboardText.TrimEnd())
"@

New-Item -ItemType Directory -Force -Path $tasksDir | Out-Null
Set-Content -LiteralPath $taskFile -Value $taskFileText -Encoding UTF8

Write-Host "Saved task file: $taskFile"
Write-Host "Task name: $Name"
Write-Host "Use the exact run directory printed by the runner for output review, especially when multiple tasks run."

$runnerParams = @{
    TaskFile = $taskFile
    ProjectRoot = $resolvedProjectRoot
    Sandbox = $Sandbox
}

if ($Notify) {
    $runnerParams["Notify"] = $true
}

& $runnerPath @runnerParams

Write-Host "Clipboard runner finished for task: $Name"
Write-Host "Saved task file: $taskFile"
Write-Host "Use the exact run directory from the runner's Run output command above."
