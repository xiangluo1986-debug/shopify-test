<#
.SYNOPSIS
Safely stages approved project files and creates a local Git commit.

.DESCRIPTION
This helper is intentionally narrow. It only runs git status, git add,
git commit, and git log. It never pushes, resets, rebases, cleans,
checks out, restores files, deletes lock files, runs Shopify tasks, runs
migrations, or modifies any database.

Generated logs, review outputs, JSON/HTML reports, database files, and
migrations are blocked from staging.

.EXAMPLE
.\scripts\git_safe_commit.ps1 -Message "Add Shopify apply execution preview task"

.EXAMPLE
.\scripts\git_safe_commit.ps1 -Message "Add Shopify apply execution preview task" -PreviewOnly

.EXAMPLE
.\scripts\git_safe_commit.ps1 -Message "Add Shopify apply execution preview task" -DryRun
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Message,

    [Alias("PreviewOnly")]
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$GitDir = Join-Path $RepoRoot ".git"

if (-not (Test-Path -LiteralPath $GitDir)) {
    throw "This script must be run from inside the aftersales Git repository."
}

Set-Location -LiteralPath $RepoRoot

$AllowedGitVerbs = @("status", "add", "commit", "log")

function Invoke-SafeGit {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    if ($Arguments.Count -eq 0) {
        throw "No Git command was provided."
    }

    $Verb = $Arguments[0]
    if ($AllowedGitVerbs -notcontains $Verb) {
        throw "Blocked Git command: git $Verb"
    }

    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
}

function Get-GitStatusLines {
    $Output = & git status --porcelain=v1 --untracked-files=all
    if ($LASTEXITCODE -ne 0) {
        throw "Git status failed."
    }

    return @($Output)
}

function Normalize-GitPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return ($Path.Trim() -replace "\\", "/")
}

function Get-ChangedItems {
    $Items = @()

    foreach ($Line in Get-GitStatusLines) {
        if ([string]::IsNullOrWhiteSpace($Line)) {
            continue
        }

        if ($Line.Length -lt 4) {
            throw "Unexpected git status output: $Line"
        }

        $Status = $Line.Substring(0, 2)
        $PathText = $Line.Substring(3)
        $IsRenameOrCopy = $false

        if ($PathText -match " -> ") {
            $IsRenameOrCopy = $true
            $PathParts = $PathText -split " -> ", 2
            $PathText = $PathParts[1]
        }

        $Items += [PSCustomObject]@{
            Status = $Status
            IndexStatus = $Status.Substring(0, 1)
            WorktreeStatus = $Status.Substring(1, 1)
            Path = Normalize-GitPath -Path $PathText
            IsRenameOrCopy = $IsRenameOrCopy
        }
    }

    return $Items
}

function Test-AllowedProjectPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $AllowedExactPaths = @(
        "AGENTS.md",
        "remote_approval_runner.py",
        ".codex/skills/local-approval-runner/SKILL.md",
        ".codex/skills/shopify-product-translation/SKILL.md",
        "backend/shopify_sync/management/commands/translate_shopify_product.py",
        "backend/shopify_sync/translation_glossary_de.json",
        "backend/shopify_sync/translation_glossary_es.json",
        "backend/shopify_sync/translation_glossary_fr.json",
        "backend/shopify_sync/translation_glossary_it.json",
        "backend/shopify_sync/translation_glossary_ja.json",
        "scripts/git_safe_commit.ps1"
    )

    if ($AllowedExactPaths -contains $Path) {
        return $true
    }

    $AllowedPatterns = @(
        "^remote_approval/[^/]+\.(md|py)$",
        "^remote_approval/tasks/[^/]+\.py$"
    )

    foreach ($Pattern in $AllowedPatterns) {
        if ($Path -match $Pattern) {
            return $true
        }
    }

    return $false
}

function Test-ForbiddenPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ($Path -match "(^|/)\.env($|\.)|\.env$") {
        return $true
    }

    if ($Path -match "^(logs|backend/logs|backend/reviews)/") {
        return $true
    }

    if ($Path -match "(^|/)(review|reviews)/") {
        return $true
    }

    if ($Path -match "(^|/)migrations/.*\.py$") {
        return $true
    }

    if ($Path -match "(^|/)db\.sqlite3(-journal)?$") {
        return $true
    }

    if ($Path -match "\.(log|jsonl|html)$") {
        return $true
    }

    if (($Path -match "\.json$") -and (-not (Test-AllowedProjectPath -Path $Path))) {
        return $true
    }

    if ($Path -match "(^|/).*_review\.(json|html)$") {
        return $true
    }

    return $false
}

Write-Host ""
Write-Host "Current Git status:"
Invoke-SafeGit -Arguments @("status", "--short")

$ChangedItems = @(Get-ChangedItems)

if ($ChangedItems.Count -eq 0) {
    if ($DryRun) {
        Write-Host ""
        Write-Host "Dry run complete. No changed files found. Nothing would be staged or committed."
        exit 0
    }

    throw "No changed files found. Nothing to commit."
}

$RenameOrCopyItems = @($ChangedItems | Where-Object { $_.IsRenameOrCopy })
if ($RenameOrCopyItems.Count -gt 0) {
    Write-Host ""
    Write-Host "Rename/copy changes require manual review. Nothing was staged:"
    $RenameOrCopyItems | ForEach-Object { Write-Host "  $($_.Status) $($_.Path)" }
    throw "Stopped before staging."
}

$ForbiddenItems = @($ChangedItems | Where-Object { Test-ForbiddenPath -Path $_.Path })
if ($ForbiddenItems.Count -gt 0) {
    Write-Host ""
    Write-Host "Forbidden files are present. Nothing was staged:"
    $ForbiddenItems | ForEach-Object { Write-Host "  $($_.Status) $($_.Path)" }
    throw "Stopped before staging."
}

$UnknownItems = @($ChangedItems | Where-Object { -not (Test-AllowedProjectPath -Path $_.Path) })
if ($UnknownItems.Count -gt 0) {
    Write-Host ""
    Write-Host "Unapproved project files are present. Nothing was staged:"
    $UnknownItems | ForEach-Object { Write-Host "  $($_.Status) $($_.Path)" }
    throw "Stopped before staging."
}

$FilesToStage = @($ChangedItems | ForEach-Object { $_.Path } | Sort-Object -Unique)
if ($FilesToStage.Count -eq 0) {
    throw "No approved files found. Nothing to commit."
}

Write-Host ""
Write-Host "Approved files to stage:"
$FilesToStage | ForEach-Object { Write-Host "  $_" }

if ($DryRun) {
    Write-Host ""
    Write-Host "Dry run complete. No files were staged or committed."
    exit 0
}

$AddArgs = @("add", "--") + $FilesToStage
Invoke-SafeGit -Arguments $AddArgs

Write-Host ""
Write-Host "Status after staging:"
Invoke-SafeGit -Arguments @("status", "--short")

$PostStageItems = @(Get-ChangedItems)
$BadStagedItems = @(
    $PostStageItems |
        Where-Object {
            ($_.IndexStatus -ne " " -and $_.IndexStatus -ne "?") -and
            ((Test-ForbiddenPath -Path $_.Path) -or (-not (Test-AllowedProjectPath -Path $_.Path)))
        }
)

if ($BadStagedItems.Count -gt 0) {
    Write-Host ""
    Write-Host "Unexpected staged files detected. Commit blocked:"
    $BadStagedItems | ForEach-Object { Write-Host "  $($_.Status) $($_.Path)" }
    throw "Stopped before commit."
}

$StagedItems = @(
    $PostStageItems |
        Where-Object { $_.IndexStatus -ne " " -and $_.IndexStatus -ne "?" }
)

if ($StagedItems.Count -eq 0) {
    throw "No staged files found. Nothing to commit."
}

Write-Host ""
Write-Host "Creating local commit..."
Invoke-SafeGit -Arguments @("commit", "-m", $Message)

Write-Host ""
Write-Host "Final Git status:"
Invoke-SafeGit -Arguments @("status", "--short")

Write-Host ""
Write-Host "Latest commit:"
Invoke-SafeGit -Arguments @("log", "-1", "--oneline", "--decorate")
