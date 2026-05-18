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
        target_environment = $TargetValue
        expected_max_age = "PT2H"
        current_phase = "<acquiring|building|checking|switching|cleanup|releasing>"
    }

    foreach ($key in $record.Keys) {
        Write-Host ("  {0}: {1}" -f $key, $record[$key])
    }
}

function Show-ImplementationPlan {
    Write-Step "Future enforcement plan"
    Write-Host "1. Add an atomic acquire helper before deploy/build/restart/switch/cleanup actions."
    Write-Host "2. Block and exit non-zero when .deploy/deploy.lock already exists."
    Write-Host "3. Print sanitized owner metadata for the existing lock."
    Write-Host "4. Never auto-remove another active lock."
    Write-Host "5. Require explicit manual stale-lock review before removal."
    Write-Host "6. Release only the lock owned by the current process in a finally/cleanup block."
    Write-Host "7. Keep production apply blocked until safe_deploy and future blue-green switch paths enforce the lock."
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LockDirectory = Join-Path -Path $ProjectRoot -ChildPath ".deploy"
$LockPath = Join-Path -Path $LockDirectory -ChildPath "deploy.lock"
$RelativeLockPath = ".deploy\deploy.lock"

Write-Step "Deployment lock dry-run"
Write-Host "Purpose: $Purpose"
Write-Host "Target: $Target"
Write-Host "Proposed lock path: $RelativeLockPath"
Write-Host "Resolved lock path: $LockPath"
Write-Host "Design document: docs\DEPLOYMENT_LOCK.md"
Write-Host "This helper is read-only. It does not create, delete, or modify lock files."

Write-Step "Current lock path state"
$lockDirectoryExists = Test-Path -LiteralPath $LockDirectory -PathType Container
$lockExists = Test-Path -LiteralPath $LockPath -PathType Leaf
Write-Host "Lock directory exists: $lockDirectoryExists"
Write-Host "Lock file exists: $lockExists"

if ($lockExists) {
    Show-LockFileContents -Path $LockPath
}

Show-DryRunPlan -Path $RelativeLockPath -Exists $lockExists

if ($ShowPlan) {
    Show-FutureLockRecord -PurposeValue $Purpose -TargetValue $Target
    Show-ImplementationPlan
}

Write-Step "Result"
Write-Ok "Deployment lock dry-run completed. No file or runtime change was performed."
Write-Ok "Active deploy scripts do not enforce the lock yet; production apply remains blocked until enforcement is implemented."
