[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$PlanOnly = $true,
    [switch]$ExecuteProductionApply,
    [string]$Ack = "",
    [string]$DeployLockPath = ".deploy/deploy.lock",
    [string]$TargetColor = "",
    [string]$ActiveColor = "",
    [switch]$RequireLockValidation = $true,
    [switch]$MigrationCompatibilityConfirmed,
    [switch]$SchedulerSingletonConfirmed,
    [switch]$SharedMediaStaticStorageConfirmed,
    [switch]$RollbackCommandConfirmed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$DraftReadinessApprovalPhrase = "I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW"
$ActiveProductionApprovalPhrase = "<none - real production apply approval is not active in this phase>"
$FinalRuntimeApprovalPhrase = "I_APPROVE_ENABLE_BLUE_GREEN_RUNTIME_COMMANDS_AFTER_FINAL_REVIEW"
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DeployDirectory = [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath ".deploy"))
$DeployLockHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "deploy_lock.ps1"
$FinalRuntimeApprovalPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md"
$ProductionPreflightPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_PREFLIGHT.md"
$ProductionReadinessPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_APPLY_READINESS.md"
$ProductionCommandReviewPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md"
$ProductionRuntimeDetailsPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md"
$ProductionSwitchRollbackReviewPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md"
$RuntimeCommandHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "blue_green_runtime_commands.ps1"

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

function Get-MissingConfirmationGates {
    $missing = New-Object System.Collections.Generic.List[string]

    if (-not [bool]$MigrationCompatibilityConfirmed) {
        $missing.Add("MigrationCompatibilityConfirmed")
    }

    if (-not [bool]$SchedulerSingletonConfirmed) {
        $missing.Add("SchedulerSingletonConfirmed")
    }

    if (-not [bool]$SharedMediaStaticStorageConfirmed) {
        $missing.Add("SharedMediaStaticStorageConfirmed")
    }

    if (-not [bool]$RollbackCommandConfirmed) {
        $missing.Add("RollbackCommandConfirmed")
    }

    return $missing.ToArray()
}

function Show-PlanHeader {
    param([string]$ResolvedLockPath)

    Write-Step "Blue-green production apply skeleton"
    Write-Host "Script path: scripts\blue_green_production_apply.ps1"
    Write-Host "Runtime command helper path: scripts\blue_green_runtime_commands.ps1"
    Write-Host "Runtime command helper exists: $(Test-Path -LiteralPath $RuntimeCommandHelperPath -PathType Leaf)"
    Write-Host "Runtime command helper mode: plan-only / no-action"
    Write-Host "Final runtime approval doc exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
    Write-Host "Final runtime approval doc path: docs\BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md"
    Write-Host "Runtime execution remains disabled."
    Write-Host "Final runtime approval phrase documented but inactive: $FinalRuntimeApprovalPhrase"
    Write-Host "Mode: skeleton only / no-action"
    Write-Host "DryRun: $([bool]$DryRun)"
    Write-Host "PlanOnly: $([bool]$PlanOnly)"
    Write-Host "ExecuteProductionApply requested: $([bool]$ExecuteProductionApply)"
    Write-Host "RequireLockValidation: $([bool]$RequireLockValidation)"
    Write-Host "Active production approval phrase: $ActiveProductionApprovalPhrase"
    Write-Host "Draft readiness approval phrase: $DraftReadinessApprovalPhrase (NOT ACTIVE for real apply; accepted only to prove blocking behavior)"
    Write-Host "TargetColor: $(if ([string]::IsNullOrWhiteSpace($TargetColor)) { '<not provided>' } else { $TargetColor })"
    Write-Host "ActiveColor: $(if ([string]::IsNullOrWhiteSpace($ActiveColor)) { '<not provided>' } else { $ActiveColor })"
    Write-Host "Deployment lock path: $(Get-RelativeProjectPath -Path $ResolvedLockPath)"
    Write-Host "Resolved deployment lock path: $ResolvedLockPath"
    Write-Host "Deployment lock helper exists: $(Test-Path -LiteralPath $DeployLockHelperPath -PathType Leaf)"
    Write-Host "Production command review document exists: $(Test-Path -LiteralPath $ProductionCommandReviewPath -PathType Leaf)"
    Write-Host "Production runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath -PathType Leaf)"
    Write-Host "Production switch/rollback review document exists: $(Test-Path -LiteralPath $ProductionSwitchRollbackReviewPath -PathType Leaf)"
    Write-Host "Migration compatibility confirmation: $([bool]$MigrationCompatibilityConfirmed)"
    Write-Host "Scheduler singleton confirmation: $([bool]$SchedulerSingletonConfirmed)"
    Write-Host "Media/static shared storage confirmation: $([bool]$SharedMediaStaticStorageConfirmed)"
    Write-Host "Rollback command confirmation: $([bool]$RollbackCommandConfirmed)"
}

function Show-NoActionBoundary {
    Write-Step "No-action boundary"
    Write-Host "Real production blue-green apply command path is implemented as a skeleton only and remains blocked in this phase."
    Write-Host "This skeleton does not deploy."
    Write-Host "This skeleton does not start, stop, restart, or build containers."
    Write-Host "This skeleton does not run migrations."
    Write-Host "This skeleton does not run collectstatic."
    Write-Host "This skeleton does not switch traffic."
    Write-Host "This skeleton does not modify active docker-compose.yml."
    Write-Host "This skeleton does not change production nginx/proxy config."
    Write-Host "This skeleton does not call the runtime helper to reload proxy, switch traffic, write active-color state, or execute rollback."
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
    Write-Host "Final runtime approval document exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
    Write-Host "Required final runtime approval document: docs\BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md."
    Write-Host "Production apply readiness document exists: $(Test-Path -LiteralPath $ProductionReadinessPath -PathType Leaf)"
    Write-Host "Required readiness document: docs\BLUE_GREEN_PRODUCTION_APPLY_READINESS.md."
    Write-Host "Production command review document exists: $(Test-Path -LiteralPath $ProductionCommandReviewPath -PathType Leaf)"
    Write-Host "Required command review document: docs\BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md."
    Write-Host "Production runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath -PathType Leaf)"
    Write-Host "Required runtime details document: docs\BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md."
    Write-Host "Production switch/rollback review document exists: $(Test-Path -LiteralPath $ProductionSwitchRollbackReviewPath -PathType Leaf)"
    Write-Host "Required switch/rollback review document: docs\BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md."
    Write-Host "Production preflight document status: READY after review."
    Write-Host "Production apply readiness package status: READY after review."
    Write-Host "Production command review document status: READY after review if present."
    Write-Host "Production runtime details document status: READY after review if present."
    Write-Host "Production switch/rollback review document status: READY after review if present."
    Write-Host "Production command path skeleton: implemented but blocked."
    Write-Host "Runtime command helper: scripts\blue_green_runtime_commands.ps1 exists if reported above and remains plan-only."
    Write-Host "Proxy switch/reload command remains not active."
    Write-Host "Active-color state write remains not active."
    Write-Host "Rollback command remains not active."
    Write-Host "Final runtime approval phrase is documented but inactive: $FinalRuntimeApprovalPhrase."
    Write-Host "Runtime command execution remains disabled."
    Write-Host "Exact runtime command implementation is still not enabled."
    Write-Host "Conservative defaults now exist for production proxy, colors, active-color state, rollback, observation, migration policy, scheduler singleton, and media/static expectations."
    Write-Host "Production implementation remains NOT READY until exact proxy config path, switch/reload command, state update behavior, rollback command, and cleanup commands are reviewed."
    Write-Host "Draft readiness approval phrase is not active for real apply: $DraftReadinessApprovalPhrase."
    Write-Host "Real production apply remains blocked."
    Write-Host "Production apply still remains NO-GO."
    Write-Host "Exact production apply commands are not approved in this skeleton."
    Write-Host "Migration, scheduler singleton, media/static/uploads, proxy/port ownership, active/target color, health check, rollback, observation, cleanup, and data safety checks must pass first."
}

function Show-ProductionRuntimeDefaults {
    Write-Step "Production runtime details (documented defaults / NOT RUN)"
    Write-Host "Runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath -PathType Leaf)"
    Write-Host "Switch/rollback review doc exists: $(Test-Path -LiteralPath $ProductionSwitchRollbackReviewPath -PathType Leaf)"
    Write-Host "Runtime command helper exists: $(Test-Path -LiteralPath $RuntimeCommandHelperPath -PathType Leaf)"
    Write-Host "NOT RUN: runtime helper status/plan commands are documentation-only in this phase."
    Write-Host "NOT RUN: use nginx as the production blue-green proxy candidate."
    Write-Host "NOT RUN: current production web keeps host port 8000 until explicit final approval."
    Write-Host "NOT RUN: future service names are web_blue, web_green, and bluegreen_proxy."
    Write-Host "NOT RUN: active-color state design exists for .deploy\active-color.json with active_color, previous_color, updated_at, updated_by, deploy_id, proxy_config_version, and notes."
    Write-Host "NOT RUN: active-color state under .deploy must not be committed and must not contain secrets."
    Write-Host "NOT RUN: active-color state writes must be atomic and occur only after switch or rollback health passes."
    Write-Host "NOT RUN: future switch would update only a controlled local proxy include/symlink/state file after target health passes."
    Write-Host "NOT RUN: rollback would switch proxy back to previous_color and use the deployment lock."
    Write-Host "NOT RUN: first production apply observation would be at least 10 minutes before cleanup."
    Write-Host "NOT RUN: migration policy allows only backward-compatible migrations during blue-green apply."
    Write-Host "NOT RUN: scheduler remains singleton; no blue/green scheduler is allowed."
    Write-Host "NOT RUN: media/uploads must be shared and static handling must be reviewed before production proxy switch."
    Write-Host "Proxy switch/reload command still not active."
    Write-Host "Active-color state write still not active."
    Write-Host "Rollback command still not active."
}

function Show-ConfirmationGatePlan {
    Write-Step "Required safety confirmations"
    Write-Host "NOT RUN: migration compatibility confirmation gate. Supplied: $([bool]$MigrationCompatibilityConfirmed)"
    Write-Host "NOT RUN: scheduler singleton confirmation gate. Supplied: $([bool]$SchedulerSingletonConfirmed)"
    Write-Host "NOT RUN: media/static shared storage confirmation gate. Supplied: $([bool]$SharedMediaStaticStorageConfirmed)"
    Write-Host "NOT RUN: rollback command confirmation gate. Supplied: $([bool]$RollbackCommandConfirmed)"
    Write-Host "Missing confirmations block execution requests. Even complete confirmations do not enable runtime action in this phase."
}

function Show-ProductionCommandPathSkeleton {
    Write-Step "Phase 1 - Preflight (planned / NOT RUN)"
    Write-Host "NOT RUN: git status."
    Write-Host "NOT RUN: deployment lock status."
    Write-Host "NOT RUN: current 8000 /healthz/ check."
    Write-Host "NOT RUN: active color / target color validation."
    Write-Host "NOT RUN: migration compatibility gate."
    Write-Host "NOT RUN: scheduler singleton gate."
    Write-Host "NOT RUN: media/static shared storage gate."
    Write-Host "NOT RUN: rollback command gate."

    Write-Step "Phase 2 - Lock (planned / NOT RUN)"
    Write-Host "NOT RUN: acquire deployment lock before any build/start/migrate/collectstatic/proxy switch/cleanup."
    Write-Host "NOT RUN: block immediately and exit non-zero if the lock exists."
    Write-Host "NOT RUN: do not auto-queue behind an existing lock."
    Write-Host "NOT RUN: store a generated lock_id in the lock record for the owning deploy flow."
    Write-Host "NOT RUN: release only the matching lock_id in finally/cleanup handling."
    Write-Host "NOT RUN: print sanitized lock owner metadata for manual review when blocked."
    Write-Host "NOT RUN: stale lock review must be manual; no automatic stale lock deletion."
    Write-Host "Normal non-deploy tasks are not blocked by this deployment lock."
    Write-Host "Current skeleton lock validation is path and plan validation only; no lock is acquired."

    Write-Step "Phase 3 - Prepare target color (planned / NOT RUN)"
    Write-Host "NOT RUN: future image/build preparation."
    Write-Host "NOT RUN: future target color start."
    Write-Host "NOT RUN: future target color health check."

    Write-Step "Phase 4 - Switch (planned / NOT RUN)"
    Write-Host "NOT RUN: future proxy config validation."
    Write-Host "NOT RUN: future proxy switch."
    Write-Host "NOT RUN: future post-switch health check."

    Write-Step "Phase 5 - Observe (planned / NOT RUN)"
    Write-Host "NOT RUN: future observation window."
    Write-Host "NOT RUN: future log checks."
    Write-Host "NOT RUN: future health checks."

    Write-Step "Phase 6 - Rollback (planned / NOT RUN)"
    Write-Host "NOT RUN: future rollback to previous color."
    Write-Host "NOT RUN: old color retained during observation."
    Write-Host "NOT RUN: no automatic database rollback."

    Write-Step "Phase 7 - Cleanup (planned / NOT RUN)"
    Write-Host "NOT RUN: future cleanup only after observation."
    Write-Host "NOT RUN: no database, media, static, upload, or secret-bearing volume removal."
    Write-Host "NOT RUN: no scheduler duplication."
    Write-Host "NOT RUN: no cleanup of previous color until rollback is no longer immediately needed."
}

function Show-BlockingResult {
    param(
        [string]$Message,
        [int]$Code
    )

    Write-Step "Result"
    Write-Fail "Real production blue-green apply command path is implemented as a skeleton only and remains blocked in this phase."
    Write-Fail $Message
    Write-Fail "Exact runtime command implementation is still not enabled."
    Write-Fail "Conservative runtime defaults are documented, but exact proxy switch/reload and rollback commands are not implemented yet."
    Write-Fail "Switch/rollback review doc exists: $(Test-Path -LiteralPath $ProductionSwitchRollbackReviewPath -PathType Leaf)"
    Write-Fail "Runtime command helper exists: $(Test-Path -LiteralPath $RuntimeCommandHelperPath -PathType Leaf)"
    Write-Fail "Runtime command helper is plan-only and is not called here to perform any runtime action."
    Write-Fail "Final runtime approval doc exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
    Write-Fail "Final runtime approval phrase is documented but inactive: $FinalRuntimeApprovalPhrase"
    Write-Fail "Runtime command execution remains disabled."
    Write-Fail "Proxy switch/reload command still not active."
    Write-Fail "Active-color state write still not active."
    Write-Fail "Rollback command still not active."
    Write-Fail "Review docs\BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md, docs\BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md, and docs\BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md before any future implementation task."
    Write-Fail "Production blue-green apply remains blocked. No runtime action was performed."
    Write-Fail "Production apply remains NO-GO."
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
Show-ProductionRuntimeDefaults
Show-ConfirmationGatePlan
Show-ProductionCommandPathSkeleton

if ((-not [string]::IsNullOrWhiteSpace($normalizedTargetColor)) -and
    (-not [string]::IsNullOrWhiteSpace($normalizedActiveColor)) -and
    ($normalizedTargetColor -eq $normalizedActiveColor)) {
    Show-BlockingResult -Message "TargetColor must be different from ActiveColor." -Code 6
}

if (-not $ExecuteProductionApply) {
    Write-Step "Result"
    Write-Ok "Plan-only production apply skeleton completed. No runtime action was performed."
    Write-Ok "Successful non-production validation and manual approval are required before production apply."
    Write-Ok "Production readiness document exists if reported above; production command review is required and should exist if reported above."
    Write-Ok "Production command review document exists if reported above."
    Write-Ok "Production runtime details document exists if reported above."
    Write-Ok "Production switch/rollback review document exists if reported above."
    Write-Ok "Runtime command helper exists if reported above and remains plan-only / no-action."
    Write-Ok "Final runtime approval doc exists if reported above."
    Write-Ok "Runtime execution remains disabled."
    Write-Ok "Final runtime approval phrase is documented but inactive."
    Write-Ok "Conservative defaults exist for proxy, colors, active-color state, rollback, observation, migration policy, scheduler singleton, and media/static expectations."
    Write-Ok "Active-color state design exists and remains no-write in this skeleton."
    Write-Ok "Production command path skeleton is implemented but blocked."
    Write-Ok "Exact runtime command implementation is still not enabled."
    Write-Ok "Proxy switch/reload command still not active."
    Write-Ok "Active-color state write still not active."
    Write-Ok "Rollback command still not active."
    Write-Ok "Real production apply remains blocked."
    Write-Ok "Draft readiness approval phrase is not active for real apply."
    Write-Ok "Production real apply remains NO-GO."
    exit 0
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

if ($Ack -ne $DraftReadinessApprovalPhrase) {
    Show-BlockingResult -Message "ExecuteProductionApply requires the exact draft readiness phrase for skeleton validation. No active real-apply approval phrase exists in this phase." -Code 2
}

if (-not $RequireLockValidation) {
    Show-BlockingResult -Message "RequireLockValidation must remain enabled before any future runtime-changing apply." -Code 7
}

$missingConfirmations = @(Get-MissingConfirmationGates)
if ($missingConfirmations.Count -gt 0) {
    Show-BlockingResult -Message ("Missing required production safety confirmations: " + ($missingConfirmations -join ", ") + ".") -Code 8
}

Write-Step "Approved execution request"
Write-Warn "The draft readiness phrase matched, target color differs from active color, confirmation gates were supplied, and the lock path is constrained to .deploy/."
Write-Fail "Real production blue-green apply command path is implemented as a skeleton only and remains blocked in this phase."
Write-Fail "No docker compose up/down/restart/build was run."
Write-Fail "No proxy switch, migration, collectstatic, traffic switch, or cleanup was run."
Write-Fail "No deployment lock was acquired because this skeleton has no real production apply implementation."
Write-Fail "Exact production apply commands are not approved; migration, scheduler, media/static, proxy, rollback, observation, cleanup, and data safety checks must pass first."
Write-Fail "Production command review document exists: $(Test-Path -LiteralPath $ProductionCommandReviewPath -PathType Leaf)"
Write-Fail "Production runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath -PathType Leaf)"
Write-Fail "Production switch/rollback review document exists: $(Test-Path -LiteralPath $ProductionSwitchRollbackReviewPath -PathType Leaf)"
Write-Fail "Runtime command helper exists: $(Test-Path -LiteralPath $RuntimeCommandHelperPath -PathType Leaf)"
Write-Fail "Runtime command helper is plan-only and not active for proxy reload, traffic switch, active-color state write, or rollback execution."
Write-Fail "Final runtime approval doc exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
Write-Fail "Final runtime approval phrase is documented but inactive: $FinalRuntimeApprovalPhrase"
Write-Fail "Runtime command execution remains disabled."
Write-Fail "Exact runtime command implementation is still not enabled."
Write-Fail "Active-color state design exists and remains no-write in this skeleton."
Write-Fail "Conservative runtime defaults are documented; exact switch/reload and rollback commands are still not implemented."
Write-Fail "Draft readiness approval phrase is not active for real apply; production apply remains NO-GO."

Write-Step "Result"
Write-Fail "Production blue-green apply remains blocked by the skeleton."
exit 20
