[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$CheckDeployLock,
    [switch]$SkipPull,
    [switch]$SkipMigrate,
    [switch]$SkipCollectstatic,
    [string]$DeployLockPath = ".deploy/deploy.lock",
    [string]$HealthUrl = "http://127.0.0.1:8000/healthz/",
    [int]$HealthTimeoutSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DeployDirectory = [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath ".deploy"))
$DeployLockHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "deploy_lock.ps1"

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

function Format-Command {
    param([string[]]$Command)

    return (($Command | ForEach-Object {
        if ($_ -match "\s") {
            '"' + ($_ -replace '"', '\"') + '"'
        } else {
            $_
        }
    }) -join " ")
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

function Get-DeployLockStatus {
    $resolvedLockPath = Resolve-DeployLockPath -Path $DeployLockPath

    return [pscustomobject]@{
        LockPath = (Get-RelativeProjectPath -Path $resolvedLockPath)
        ResolvedLockPath = $resolvedLockPath
        LockHelperPath = (Get-RelativeProjectPath -Path $DeployLockHelperPath)
        LockHelperExists = (Test-Path -LiteralPath $DeployLockHelperPath -PathType Leaf)
        LockExists = (Test-Path -LiteralPath $resolvedLockPath -PathType Leaf)
    }
}

function Show-DeployLockAwareness {
    Write-Step "Deployment lock awareness"

    $status = Get-DeployLockStatus
    Write-Host "Deployment lock path: $($status.LockPath)"
    Write-Host "Resolved deployment lock path: $($status.ResolvedLockPath)"
    Write-Host "Lock helper path: $($status.LockHelperPath)"
    Write-Host "Lock helper exists: $($status.LockHelperExists)"
    Write-Host "Deployment lock currently exists: $($status.LockExists)"
    Write-Host "Future real safe deploy must acquire the deployment lock before build/check/migrate/collectstatic/restart."
    Write-Host "Future real safe deploy must release the deployment lock in cleanup/finally handling."

    if ($status.LockExists) {
        Write-Warn "Dry run: real safe deploy would be blocked until the deployment lock is released."
    } else {
        Write-Ok "Dry run: no deployment lock currently blocks a future real safe deploy."
    }

    Write-Warn "Real safe_deploy lock enforcement is still pending; non-dry-run behavior is unchanged in this phase."
}

function Invoke-CheckDeployLock {
    Write-Step "Deployment lock check"

    $status = Get-DeployLockStatus
    Write-Host "Deployment lock path: $($status.LockPath)"
    Write-Host "Resolved deployment lock path: $($status.ResolvedLockPath)"
    Write-Host "Lock helper path: $($status.LockHelperPath)"
    Write-Host "Lock helper exists: $($status.LockHelperExists)"
    Write-Host "Deployment lock currently exists: $($status.LockExists)"
    Write-Host "This check does not create, delete, acquire, release, or deploy."

    if ($status.LockExists) {
        Write-Fail "Deployment lock exists. A real safe deploy should stop and require a manual rerun after the lock is released."
        return 2
    }

    Write-Ok "No deployment lock exists."
    return 0
}

function Invoke-CaptureCommand {
    param([string[]]$Command)

    $exe = $Command[0]
    $commandArgs = @()
    if ($Command.Count -gt 1) {
        $commandArgs = $Command[1..($Command.Count - 1)]
    }

    $output = & $exe @commandArgs 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output = $output
    }
}

function Invoke-DeployCommand {
    param(
        [string]$Description,
        [string[]]$Command
    )

    Write-Step $Description
    Write-Host ("  " + (Format-Command -Command $Command))

    if ($DryRun) {
        Write-Warn "Dry run: command was not executed."
        return
    }

    $exe = $Command[0]
    $commandArgs = @()
    if ($Command.Count -gt 1) {
        $commandArgs = $Command[1..($Command.Count - 1)]
    }

    & $exe @commandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $(Format-Command -Command $Command)"
    }
}

function Show-GitState {
    Write-Step "Current git branch"
    $branch = Invoke-CaptureCommand -Command @("git", "branch", "--show-current")
    if ($branch.ExitCode -eq 0) {
        $branchName = (($branch.Output | Out-String).Trim())
        if ([string]::IsNullOrWhiteSpace($branchName)) {
            $branchName = "<detached or unknown>"
        }
        Write-Host "Branch: $branchName"
    } else {
        Write-Warn "Could not read git branch."
        $branch.Output | ForEach-Object { Write-Warn "  $_" }
    }

    Write-Step "Git status"
    $status = Invoke-CaptureCommand -Command @("git", "status", "--short")
    if ($status.ExitCode -ne 0) {
        Write-Warn "Could not read git status."
        $status.Output | ForEach-Object { Write-Warn "  $_" }
        return
    }

    $statusText = (($status.Output | Out-String).Trim())
    if ([string]::IsNullOrWhiteSpace($statusText)) {
        Write-Ok "Working tree is clean."
    } else {
        Write-Warn "Working tree is dirty. Review these files before deploying:"
        $status.Output | ForEach-Object { Write-Warn "  $_" }
    }
}

function Wait-HealthCheck {
    param(
        [string]$Url,
        [int]$TimeoutSeconds
    )

    Write-Step "Health check"
    Write-Host "Polling $Url for up to $TimeoutSeconds seconds."

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Write-Ok "Health check passed: HTTP 200"
                return $true
            }
            $lastError = "HTTP $($response.StatusCode)"
        } catch {
            $lastError = $_.Exception.Message
        }

        Start-Sleep -Seconds 3
    }

    Write-Fail "Health check failed after $TimeoutSeconds seconds."
    if ($lastError) {
        Write-Fail "Last health check error: $lastError"
    }
    return $false
}

try {
    if ($CheckDeployLock) {
        exit (Invoke-CheckDeployLock)
    }

    Show-GitState
    if ($DryRun) {
        Show-DeployLockAwareness
    }

    if ($SkipPull) {
        Write-Warn "-SkipPull set. This script does not run git pull by default."
    } else {
        Write-Host ""
        Write-Host "No git pull is run by this script. Update code through your approved workflow before deploying."
    }

    Invoke-DeployCommand -Description "Build Docker image before restart" -Command @("docker", "compose", "build", "web")
    Invoke-DeployCommand -Description "Run Django system checks" -Command @("docker", "compose", "run", "--rm", "web", "python", "manage.py", "check")

    if ($SkipMigrate) {
        Write-Warn "Skipping migrations because -SkipMigrate was set."
    } else {
        Invoke-DeployCommand -Description "Run database migrations" -Command @("docker", "compose", "run", "--rm", "web", "python", "manage.py", "migrate")
    }

    if ($SkipCollectstatic) {
        Write-Warn "Skipping collectstatic because -SkipCollectstatic was set."
    } else {
        try {
            Invoke-DeployCommand -Description "Collect static files" -Command @("docker", "compose", "run", "--rm", "web", "python", "manage.py", "collectstatic", "--noinput")
        } catch {
            Write-Fail "collectstatic failed. If staticfiles is intentionally not configured for this project, rerun with -SkipCollectstatic after documenting that choice."
            throw
        }
    }

    Invoke-DeployCommand -Description "Restart web service" -Command @("docker", "compose", "up", "-d", "web")

    if ($DryRun) {
        Write-Step "Health check"
        Write-Warn "Dry run: health check was not called."
        Write-Ok "Dry run completed. No deploy commands were executed."
        exit 0
    }

    $healthy = Wait-HealthCheck -Url $HealthUrl -TimeoutSeconds $HealthTimeoutSeconds
    if (-not $healthy) {
        Write-Fail "Web service did not become healthy. Recent web logs:"
        & docker compose logs --tail=100 web
        exit 1
    }

    Write-Ok "Safe deploy completed successfully."
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    Write-Fail "Safe deploy stopped before success."
    exit 1
}
