[CmdletBinding()]
param(
    [string]$Purpose = "dry-run",
    [string]$Target = "local",
    [switch]$ShowPlan
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Protect-SensitiveText {
    param([string]$Text)

    $sanitized = $Text

    $sanitized = $sanitized -replace '(?i)("(?:[^"]*(secret|token|api[_-]?key|password|passwd|pwd|credential|authorization)[^"]*)"\s*:\s*)("[^"]*"|[^,\s}]+)', '$1"<redacted>"'
    $sanitized = $sanitized -replace '(?i)(secret|token|api[_-]?key|password|passwd|pwd|credential|authorization|bearer)(\s*[:=]\s*)("?)\S+("?)', '$1$2$3<redacted>$4'
    $sanitized = $sanitized -replace '(?i)(--(?:secret|token|api-key|password|credential|authorization)\s+)\S+', '$1<redacted>'
    $sanitized = $sanitized -replace '(?i)(SHOPIFY|GMAIL|TRUSTPILOT|KUDOSI|ALI[_-]?REVIEWS|CLOUDFLARED|DATABASE|DJANGO_SECRET_KEY)([A-Z0-9_ -]*)(\s*[:=]\s*)("?)\S+("?)', '$1$2$3$4<redacted>$5'
    $sanitized = $sanitized -replace '(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', '$1 <redacted>'

    if ($sanitized.Length -gt 240) {
        $sanitized = $sanitized.Substring(0, 240) + " ... <truncated>"
    }

    return $sanitized
}

function Show-LockFileContents {
    param([string]$Path)

    Write-Step "Existing lock contents"
    Write-Host "Showing sanitized lock file text only. Secrets must not be stored in deployment locks."

    try {
        $lineNumber = 0
        foreach ($line in Get-Content -LiteralPath $Path -ErrorAction Stop) {
            $lineNumber += 1
            if ($lineNumber -gt 80) {
                Write-Warn "Output truncated after 80 lines."
                break
            }
            Write-Host ("  " + (Protect-SensitiveText -Text $line))
        }
    } catch {
        Write-Warn "Could not read lock file contents: $($_.Exception.Message)"
    }
}

function Show-DryRunPlan {
    param(
        [string]$Path,
        [bool]$Exists
    )

    Write-Step "Dry-run acquire/release behavior"

    if ($Exists) {
        Write-Warn "Would block acquisition and exit non-zero because a lock already exists."
        Write-Host "Would print sanitized owner metadata for manual review."
        Write-Host "Would not delete or overwrite the existing lock."
    } else {
        Write-Ok "Would allow acquisition in a future enforcing script."
        Write-Host "Would atomically create: $Path"
        Write-Host "Would release the lock in a finally/cleanup block after the protected action completes."
    }

    Write-Host "Dry-run mode created no lock file and deleted no lock file."
}

function Show-FutureLockRecord {
    param(
        [string]$PurposeValue,
        [string]$TargetValue
    )

    Write-Step "Future lock record shape"

    $record = [ordered]@{
        lock_id = "<generated-guid>"
        created_at = "<utc-iso8601>"
        user = "<current-user>"
        host = "<current-host>"
        process_id = "<process-id>"
        command = "<sanitized-command>"
        purpose = $PurposeValue
        target = $TargetValue
        max_age_minutes = 120
        project_path = "<project-root>"
    }

    foreach ($key in $record.Keys) {
        Write-Host ("  {0}: {1}" -f $key, $record[$key])
    }
}

function Show-ImplementationPlan {
    Write-Step "Current helper and safe_deploy enforcement plan"
    Write-Host "Real helper: scripts\deploy_lock.ps1"
    Write-Host "Safe deploy enforcement: scripts\safe_deploy.ps1 reports lock status in -DryRun, supports -CheckDeployLock, and enforces the lock in real mode."
    Write-Host "1. The helper can acquire, release, report status, and validate a local lock file."
    Write-Host "2. safe_deploy dry-run reports lock state without acquiring or releasing the real lock."
    Write-Host "3. safe_deploy -CheckDeployLock is read-only and blocks when a lock exists."
    Write-Host "4. Real safe_deploy acquires the lock before build/check/migrate/collectstatic/restart/health check."
    Write-Host "5. Real safe_deploy releases only the matching lock_id in cleanup/finally handling."
    Write-Host "6. Future blue-green runtime-changing paths must use the same lock before container start/stop/restart, image build, migration, collectstatic, proxy switch, traffic switch, cleanup, production apply, or rollback."
    Write-Host "7. If the lock exists, future runtime-changing scripts must block and exit non-zero; they must not auto-queue."
    Write-Host "8. Stale locks require manual review, and normal non-deploy tasks are not blocked."
    Write-Host "9. Production blue-green apply remains NO-GO until a separate apply task approves exact runtime commands."
}

function Show-RealHelperExamples {
    Write-Step "Real helper examples"
    Write-Host "Status:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action status"
    Write-Host "Acquire:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action acquire -Purpose `"safe-deploy`" -Target `"production`""
    Write-Host "Release requires the exact lock_id printed by acquire or status:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action release -LockId <lock_id>"
    Write-Host "Validate:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_lock.ps1 -Action validate"
    Write-Host "These examples are not run by this dry-run helper."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LockDirectory = Join-Path -Path $ProjectRoot -ChildPath ".deploy"
$LockPath = Join-Path -Path $LockDirectory -ChildPath "deploy.lock"
$LockHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "deploy_lock.ps1"
$SafeDeployPath = Join-Path -Path $PSScriptRoot -ChildPath "safe_deploy.ps1"
$RelativeLockPath = ".deploy\deploy.lock"
$safeDeployLockEnforcementExists = $false
if (Test-Path -LiteralPath $SafeDeployPath -PathType Leaf) {
    $safeDeployText = Get-Content -LiteralPath $SafeDeployPath -Raw
    $safeDeployLockEnforcementExists = ($safeDeployText -match "CheckDeployLock") -and ($safeDeployText -match "ValidateDeployLockOnly") -and ($safeDeployText -match "Acquire-DeploymentLock") -and ($safeDeployText -match "Release-DeploymentLock")
}

Write-Step "Deployment lock dry-run"
Write-Host "Purpose: $Purpose"
Write-Host "Target: $Target"
Write-Host "Proposed lock path: $RelativeLockPath"
Write-Host "Resolved lock path: $LockPath"
Write-Host "Real helper path: scripts\deploy_lock.ps1"
Write-Host "Safe deploy script path: scripts\safe_deploy.ps1"
Write-Host "Design document: docs\DEPLOYMENT_LOCK.md"
Write-Host "This helper is read-only. It does not create, delete, or modify lock files."

Write-Step "Current lock path state"
$lockDirectoryExists = Test-Path -LiteralPath $LockDirectory -PathType Container
$lockExists = Test-Path -LiteralPath $LockPath -PathType Leaf
Write-Host "Lock directory exists: $lockDirectoryExists"
Write-Host "Lock file exists: $lockExists"
Write-Host "Real helper exists: $(Test-Path -LiteralPath $LockHelperPath -PathType Leaf)"
Write-Host "safe_deploy real-mode lock enforcement exists: $safeDeployLockEnforcementExists"

if ($lockExists) {
    Show-LockFileContents -Path $LockPath
}

Show-DryRunPlan -Path $RelativeLockPath -Exists $lockExists

if ($ShowPlan) {
    Show-FutureLockRecord -PurposeValue $Purpose -TargetValue $Target
    Show-RealHelperExamples
    Show-ImplementationPlan
}

Write-Step "Result"
Write-Ok "Deployment lock dry-run completed. No file or runtime change was performed."
Write-Ok "safe_deploy lock enforcement exists if reported above; dry-run still acquires no lock."
Write-Ok "Production blue-green apply remains NO-GO until a separate apply task approves exact runtime commands."
