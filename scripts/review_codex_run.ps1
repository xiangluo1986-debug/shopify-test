[CmdletBinding()]
param(
    [string]$RunPath,

    [switch]$ShowFullOutput,

    [switch]$OpenFolder
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$expectedFiles = @(
    "last_message.txt",
    "safety_warnings.txt",
    "changed_files_after.txt",
    "staged_files_after.txt",
    "git_status_before.txt",
    "git_status_after.txt",
    "full_output.txt",
    "task_used.md"
)

function Write-Section {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title
    )

    Write-Host ""
    Write-Host "== $Title =="
}

function Get-FileText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Format-SafeLine {
    param(
        [AllowNull()]
        [string]$Line
    )

    if ($null -eq $Line) {
        return ""
    }

    if ($Line -match '(?i)(secret|token|api[_-]?key|password|credential|authorization|cloudflared|secret_key).{0,80}(:|=)') {
        return "[redacted secret-like line]"
    }

    return $Line
}

function Write-SafeText {
    param(
        [AllowNull()]
        [string]$Text
    )

    if ([string]::IsNullOrEmpty($Text)) {
        return
    }

    $lines = @($Text -split "`r?`n")
    foreach ($line in $lines) {
        Write-Host (Format-SafeLine -Line $line)
    }
}

function Write-TextFileSection {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunDirectory,

        [Parameter(Mandatory = $true)]
        [string]$FileName,

        [Parameter(Mandatory = $true)]
        [string]$MissingMessage
    )

    $path = Join-Path -Path $RunDirectory -ChildPath $FileName
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        Write-Host $MissingMessage
        return
    }

    $text = Get-FileText -Path $path
    if ([string]::IsNullOrWhiteSpace($text)) {
        Write-Host "(empty)"
        return
    }

    Write-SafeText -Text $text
}

function Invoke-GitLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & git -C $Root @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joinedOutput = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        throw "git $($Arguments -join ' ') failed:$([Environment]::NewLine)$joinedOutput"
    }

    if ($null -eq $output) {
        return @()
    }

    return @($output | ForEach-Object { $_.ToString() })
}

function Write-GitSection {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    try {
        $lines = @(Invoke-GitLines -Root $Root -Arguments $Arguments)
        if ($lines.Count -eq 0) {
            Write-Host "(none)"
            return
        }

        foreach ($line in $lines) {
            Write-Host $line
        }
    } catch {
        Write-Host "WARNING: $($_.Exception.Message)"
    }
}

function Test-FileHasNonWhitespaceContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    $text = Get-FileText -Path $Path
    return -not [string]::IsNullOrWhiteSpace($text)
}

if ([string]::IsNullOrWhiteSpace($RunPath)) {
    throw "RunPath is required. Pass -RunPath <completed runner output directory>."
}

if (-not (Test-Path -LiteralPath $RunPath)) {
    throw "Run path not found: $RunPath"
}

if (-not (Test-Path -LiteralPath $RunPath -PathType Container)) {
    throw "Run path is not a directory: $RunPath"
}

$resolvedRunPath = (Resolve-Path -LiteralPath $RunPath).ProviderPath
$projectRoot = (Resolve-Path -LiteralPath (Join-Path -Path $PSScriptRoot -ChildPath "..")).ProviderPath

$fileExists = @{}
foreach ($fileName in $expectedFiles) {
    $filePath = Join-Path -Path $resolvedRunPath -ChildPath $fileName
    $fileExists[$fileName] = Test-Path -LiteralPath $filePath -PathType Leaf
}

$safetyWarningsPath = Join-Path -Path $resolvedRunPath -ChildPath "safety_warnings.txt"
$changedFilesAfterPath = Join-Path -Path $resolvedRunPath -ChildPath "changed_files_after.txt"
$safetyWarningsNonEmpty = Test-FileHasNonWhitespaceContent -Path $safetyWarningsPath
$changedFilesRecorded = Test-FileHasNonWhitespaceContent -Path $changedFilesAfterPath

Write-Host "Codex run review"
Write-Host "Run path: $resolvedRunPath"
Write-Host "Current time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
Write-Host "Expected files:"
foreach ($fileName in $expectedFiles) {
    if ($fileExists[$fileName]) {
        Write-Host "  OK      $fileName"
    } else {
        Write-Host "  MISSING $fileName"
    }
}

Write-Section -Title "A. Last message"
Write-TextFileSection -RunDirectory $resolvedRunPath -FileName "last_message.txt" -MissingMessage "WARNING: last_message.txt missing."

Write-Section -Title "B. Safety warnings"
if (-not $fileExists["safety_warnings.txt"]) {
    Write-Host "WARNING: safety_warnings.txt missing."
} else {
    $safetyText = Get-FileText -Path $safetyWarningsPath
    if ([string]::IsNullOrWhiteSpace($safetyText)) {
        Write-Host "OK: no safety warnings recorded."
    } else {
        Write-Host "REVIEW REQUIRED: safety warnings exist."
        Write-SafeText -Text $safetyText
    }
}

Write-Section -Title "C. Changed files after"
Write-TextFileSection -RunDirectory $resolvedRunPath -FileName "changed_files_after.txt" -MissingMessage "WARNING: changed_files_after.txt missing."

Write-Section -Title "D. Staged files after"
Write-TextFileSection -RunDirectory $resolvedRunPath -FileName "staged_files_after.txt" -MissingMessage "WARNING: staged_files_after.txt missing."

Write-Section -Title "E. Git status after"
Write-TextFileSection -RunDirectory $resolvedRunPath -FileName "git_status_after.txt" -MissingMessage "WARNING: git_status_after.txt missing."

Write-Section -Title "F. Cached staged files now"
Write-GitSection -Root $projectRoot -Arguments @("diff", "--cached", "--name-only")

Write-Section -Title "G. Current git status now"
Write-GitSection -Root $projectRoot -Arguments @("status", "--short", "--branch")

Write-Section -Title "Review decision helper"
$currentStagedFiles = $null
try {
    $currentStagedFiles = @(Invoke-GitLines -Root $projectRoot -Arguments @("diff", "--cached", "--name-only"))
} catch {
    Write-Host "WARNING: unable to check current staged files: $($_.Exception.Message)"
}

if ($null -ne $currentStagedFiles) {
    if ($currentStagedFiles.Count -gt 0) {
        Write-Host "REVIEW REQUIRED: staged files exist."
    } else {
        Write-Host "OK: no staged files currently detected."
    }
}

if ($safetyWarningsNonEmpty) {
    Write-Host "REVIEW REQUIRED: safety warnings exist."
}

if ($changedFilesRecorded) {
    Write-Host "Check changed files against the task's Allowed files."
}

Write-Host "Manual git add/commit/push only after ChatGPT review."

if ($ShowFullOutput) {
    Write-Section -Title "Full output"
    Write-TextFileSection -RunDirectory $resolvedRunPath -FileName "full_output.txt" -MissingMessage "WARNING: full_output.txt missing."
}

if ($OpenFolder) {
    Invoke-Item -LiteralPath $resolvedRunPath
}
