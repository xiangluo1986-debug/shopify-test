[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$PlanOnly = $true,
    [switch]$ExecuteProductionApply,
    [string]$Ack = "",
    [string]$DeployLockPath = ".deploy/deploy.lock",
    [string]$TargetColor = "",
    [string]$ActiveColor = "",
    [switch]$RequireLockValidation = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RequiredApprovalPhrase = "I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_WITH_DEPLOYMENT_LOCK"
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DeployDirectory = [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath ".deploy"))
$DeployLockHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "deploy_lock.ps1"
$ProductionPreflightPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_PREFLIGHT.md"
$ProductionReadinessPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_APPLY_READINESS.md"
$DraftReadinessApprovalPhrase = "I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Test-PathInsideDirectory {
    param(
        [string]$Path,
        [string]$Directory
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullDirectory = [System.IO.Path]::GetFullPath($Directory).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $directoryPrefix = $fullDirectory + [System.IO.Path]::DirectorySeparatorChar

    return $fullPath.StartsWith($directoryPrefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Resolve-DeployLockPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "DeployLockPath is required."
    }

    $candidate = $Path
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path -Path $ProjectRoot -ChildPath $candidate
    }

    $fullPath = [System.IO.Path]::GetFullPath($candidate)
    $fileName = [System.IO.Path]::GetFileName($fullPath)
    if ([string]::IsNullOrWhiteSpace($fileName)) {
        throw "DeployLockPath must point to a lock file, not a directory."
    }

    if (-not (Test-PathInsideDirectory -Path $fullPath -Directory $DeployDirectory)) {
        throw "DeployLockPath must stay inside the project .deploy directory."
    }

    return $fullPath
}

function Get-RelativeProjectPath {
    param([string]$Path)

    if ($Path.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $Path.Substring($ProjectRoot.Length).TrimStart("\", "/")
    }

    return $Path
}

function Test-ColorValue {
    param(
        [string]$Name,
        [string]$Value,
        [bool]$Required
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        if ($Required) {
            throw "$Name is required and must be blue or green."
        }

        return ""
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    if (($normalized -ne "blue") -and ($normalized -ne "green")) {
        throw "$Name must be blue or green."
    }

    return $normalized
}

function Show-PlanHeader {
    param([string]$ResolvedLockPath)

    Write-Step "Blue-green production apply skeleton"
    Write-Host "Script path: scripts\blue_green_production_apply.ps1"
    Write-Host "Mode: skeleton only / no-action"
    Write-Host "DryRun: $([bool]$DryRun)"
    Write-Host "PlanOnly: $([bool]$PlanOnly)"
    Write-Host "ExecuteProductionApply requested: $([bool]$ExecuteProductionApply)"
    Write-Host "RequireLockValidation: $([bool]$RequireLockValidation)"
    Write-Host "Required approval phrase: $RequiredApprovalPhrase"
    Write-Host "Draft readiness approval phrase: $DraftReadinessApprovalPhrase (not active; not accepted by current scripts)"
    Write-Host "TargetColor: $(if ([string]::IsNullOrWhiteSpace($TargetColor)) { '<not provided>' } else { $TargetColor })"
    Write-Host "ActiveColor: $(if ([string]::IsNullOrWhiteSpace($ActiveColor)) { '<not provided>' } else { $ActiveColor })"
    Write-Host "Deployment lock path: $(Get-RelativeProjectPath -Path $ResolvedLockPath)"
    Write-Host "Resolved deployment lock path: $ResolvedLockPath"
    Write-Host "Deployment lock helper exists: $(Test-Path -LiteralPath $DeployLockHelperPath -PathType Leaf)"
}

function Show-NoActionBoundary {
    Write-Step "No-action boundary"
    Write-Host "This skeleton does not deploy."
    Write-Host "This skeleton does not start, stop, restart, or build containers."
    Write-Host "This skeleton does not run migrations."
    Write-Host "This skeleton does not run collectstatic."
    Write-Host "This skeleton does not switch traffic."
    Write-Host "This skeleton does not modify active docker-compose.yml."
    Write-Host "This skeleton does not change production nginx/proxy config."
    Write-Host "This skeleton does not call Shopify APIs, Gmail APIs, review tools, or external write paths."
    Write-Host "This skeleton does not acquire, create, release, delete, or modify the production deployment lock."
}

function Show-NonProductionGate {
    Write-Step "Required non-production validation gate"
    Write-Host "Production apply requires successful non-production blue-green runtime validation first."
    Write-Host "Required validation document: docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION.md."
    Write-Host "Production remains NO-GO until that validation passes and manual production approval is given."
    Write-Host "This skeleton still performs no runtime action."
}

function Show-ProductionPreflightGate {
    Write-Step "Required production preflight gate"
    Write-Host "Production preflight document exists: $(Test-Path -LiteralPath $ProductionPreflightPath -PathType Leaf)"
    Write-Host "Required preflight document: docs\BLUE_GREEN_PRODUCTION_PREFLIGHT.md."
    Write-Host "Production apply readiness document exists: $(Test-Path -LiteralPath $ProductionReadinessPath -PathType Leaf)"
    Write-Host "Required readiness document: docs\BLUE_GREEN_PRODUCTION_APPLY_READINESS.md."
    Write-Host "Production preflight document status: READY after review."
    Write-Host "Production apply readiness package status: READY after review."
    Write-Host "Exact production command review is required."
    Write-Host "Production apply command implementation: NOT READY / not yet implemented."
    Write-Host "Draft readiness approval phrase is not active yet: $DraftReadinessApprovalPhrase."
    Write-Host "Production apply still remains NO-GO."
    Write-Host "Exact production apply command is not implemented in this skeleton."
    Write-Host "Migration, scheduler singleton, media/static/uploads, proxy/port ownership, active/target color, health check, rollback, observation, cleanup, and data safety checks must pass first."
}

function Show-LockFlow {
    Write-Step "Future required deployment lock flow"
    Write-Host "NOT RUN: acquire deployment lock before any build/start/migrate/collectstatic/proxy switch/cleanup."
    Write-Host "NOT RUN: block immediately if the lock exists; do not queue behind it."
    Write-Host "NOT RUN: store a generated lock_id in the lock record for the owning deploy flow."
    Write-Host "NOT RUN: release only the matching lock_id in finally/cleanup handling."
    Write-Host "NOT RUN: print sanitized lock owner metadata for manual review when blocked."
    Write-Host "NOT RUN: stale lock review must be manual."
    Write-Host "NOT RUN: no automatic stale lock deletion."
    Write-Host "Normal non-deploy tasks are not blocked by this deployment lock."
    Write-Host "Current skeleton lock validation is path and plan validation only; no lock is acquired."
}

function Show-FutureSteps {
    Write-Step "Future production apply phases"
    Write-Host "NOT RUN: exact production apply command review."
    Write-Host "NOT RUN: preflight git status."
    Write-Host "NOT RUN: current active health check."
    Write-Host "NOT RUN: validate target inactive color."
    Write-Host "NOT RUN: prepare image."
    Write-Host "NOT RUN: start target inactive color."
    Write-Host "NOT RUN: health check target color."
    Write-Host "NOT RUN: optional migration only if policy approved."
    Write-Host "NOT RUN: proxy switch only after health pass."
    Write-Host "NOT RUN: observe."
    Write-Host "NOT RUN: rollback path."
    Write-Host "NOT RUN: cleanup old color only after observation."
}

function Show-BlockingResult {
    param(
        [string]$Message,
        [int]$Code
    )

    Write-Step "Result"
    Write-Fail $Message
    Write-Fail "Production blue-green apply remains blocked. No runtime action was performed."
    exit $Code
}

$resolvedLockPath = ""
try {
    $resolvedLockPath = Resolve-DeployLockPath -Path $DeployLockPath
} catch {
    Write-Step "Deployment lock path validation"
    Write-Fail $_.Exception.Message
    Write-Fail "No runtime action was performed."
    exit 4
}

try {
    $normalizedTargetColor = Test-ColorValue -Name "TargetColor" -Value $TargetColor -Required:$false
    $normalizedActiveColor = Test-ColorValue -Name "ActiveColor" -Value $ActiveColor -Required:$false
} catch {
    Show-PlanHeader -ResolvedLockPath $resolvedLockPath
    Show-NoActionBoundary
    Show-NonProductionGate
    Show-ProductionPreflightGate
    Show-BlockingResult -Message $_.Exception.Message -Code 5
}

Show-PlanHeader -ResolvedLockPath $resolvedLockPath
Show-NoActionBoundary
Show-NonProductionGate
Show-ProductionPreflightGate
Show-LockFlow
Show-FutureSteps

if ((-not [string]::IsNullOrWhiteSpace($normalizedTargetColor)) -and
    (-not [string]::IsNullOrWhiteSpace($normalizedActiveColor)) -and
    ($normalizedTargetColor -eq $normalizedActiveColor)) {
    Show-BlockingResult -Message "TargetColor must be different from ActiveColor." -Code 6
}

if (-not $ExecuteProductionApply) {
    Write-Step "Result"
    Write-Ok "Plan-only production apply skeleton completed. No runtime action was performed."
    Write-Ok "Successful non-production validation and manual approval are required before production apply."
    Write-Ok "Production readiness document exists if reported above; exact command review is required."
    Write-Ok "Production apply command is still not implemented."
    Write-Ok "Draft readiness approval phrase is not active yet and is not accepted by current scripts."
    Write-Ok "Production real apply remains NO-GO."
    exit 0
}

if ($Ack -ne $RequiredApprovalPhrase) {
    Show-BlockingResult -Message "ExecuteProductionApply requires the exact approval phrase." -Code 2
}

try {
    $normalizedTargetColor = Test-ColorValue -Name "TargetColor" -Value $TargetColor -Required:$true
    $normalizedActiveColor = Test-ColorValue -Name "ActiveColor" -Value $ActiveColor -Required:$true
} catch {
    Show-BlockingResult -Message $_.Exception.Message -Code 3
}

if ($normalizedTargetColor -eq $normalizedActiveColor) {
    Show-BlockingResult -Message "TargetColor must be different from ActiveColor." -Code 6
}

if (-not $RequireLockValidation) {
    Show-BlockingResult -Message "RequireLockValidation must remain enabled before any future runtime-changing apply." -Code 7
}

Write-Step "Approved execution request"
Write-Warn "The approval phrase matched, target color differs from active color, and the lock path is constrained to .deploy/."
Write-Fail "Real production blue-green apply is not implemented in this phase."
Write-Fail "No docker compose up/down/restart/build was run."
Write-Fail "No proxy switch, migration, collectstatic, traffic switch, or cleanup was run."
Write-Fail "No deployment lock was acquired because this skeleton has no real production apply implementation."
Write-Fail "Exact production apply command is not implemented; migration, scheduler, media/static, proxy, rollback, observation, cleanup, and data safety checks must pass first."
Write-Fail "Draft readiness approval phrase is not active yet; production apply remains NO-GO."

Write-Step "Result"
Write-Fail "Production blue-green apply remains blocked by the skeleton."
exit 20
