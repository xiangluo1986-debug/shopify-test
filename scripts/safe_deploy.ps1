[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$CheckDeployLock,
    [switch]$ValidateDeployLockOnly,
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
$DeployLockAcquired = $false
$DeployLockId = ""
$ScriptExitCode = 0

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
    Write-Host "Dry run does not acquire or release the deployment lock."
    Write-Host "Real safe deploy acquires the deployment lock before build/check/migrate/collectstatic/restart/health check."
    Write-Host "Real safe deploy releases only the matching lock_id in cleanup/finally handling."

    if ($status.LockExists) {
        Write-Warn "Dry run: real safe deploy would be blocked until the deployment lock is released."
    } else {
        Write-Ok "Dry run: no deployment lock currently blocks a future real safe deploy."
    }
    Write-Ok "Real safe_deploy lock enforcement is active in non-dry-run mode."
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
        Show-DeployLockHelperStatus
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

function Write-CapturedOutput {
    param([object[]]$Output)

    if ($null -eq $Output) {
        return
    }

    foreach ($line in $Output) {
        if ($null -ne $line) {
            Write-Host ("  " + ([string]$line))
        }
    }
}

function Invoke-DeployLockHelper {
    param(
        [string]$Action,
        [AllowNull()]$Arguments
    )

    if (-not (Test-Path -LiteralPath $DeployLockHelperPath -PathType Leaf)) {
        throw "Deployment lock helper was not found: $(Get-RelativeProjectPath -Path $DeployLockHelperPath)"
    }

    $resolvedLockPath = Resolve-DeployLockPath -Path $DeployLockPath
    $command = @(
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $DeployLockHelperPath,
        "-Action",
        $Action,
        "-LockPath",
        $resolvedLockPath
    )

    if ($null -ne $Arguments) {
        foreach ($key in $Arguments.Keys) {
            $value = $Arguments[$key]
            if ($null -eq $value) {
                continue
            }

            $command += "-$key"
            $command += [string]$value
        }
    }

    return (Invoke-CaptureCommand -Command $command)
}

function Show-DeployLockHelperStatus {
    try {
        $statusResult = Invoke-DeployLockHelper -Action "status" -Arguments $null
        Write-CapturedOutput -Output $statusResult.Output
        if ($statusResult.ExitCode -ne 0) {
            Write-Warn "Deployment lock status helper exited with code $($statusResult.ExitCode)."
        }
    } catch {
        Write-Warn "Could not print deployment lock helper status: $($_.Exception.Message)"
    }
}

function Acquire-DeploymentLock {
    param(
        [string]$Purpose = "safe-deploy",
        [string]$Target = "web"
    )

    if ($script:DeployLockAcquired) {
        return
    }

    Write-Step "Acquire deployment lock"
    $newLockId = [guid]::NewGuid().ToString()
    $result = Invoke-DeployLockHelper -Action "acquire" -Arguments ([ordered]@{
        Purpose = $Purpose
        Target = $Target
        LockId = $newLockId
    })
    Write-CapturedOutput -Output $result.Output

    if ($result.ExitCode -ne 0) {
        throw "Deployment lock acquisition failed with exit code $($result.ExitCode). Safe deploy blocked before deploy commands."
    }

    $script:DeployLockId = $newLockId
    $script:DeployLockAcquired = $true
}

function Release-DeploymentLock {
    if (-not $script:DeployLockAcquired) {
        return $true
    }

    Write-Step "Release deployment lock"
    $result = Invoke-DeployLockHelper -Action "release" -Arguments ([ordered]@{
        LockId = $script:DeployLockId
    })
    Write-CapturedOutput -Output $result.Output

    if ($result.ExitCode -ne 0) {
        Write-Fail "Deployment lock release failed with exit code $($result.ExitCode). Review the lock before rerunning deployment."
        return $false
    }

    $script:DeployLockAcquired = $false
    $script:DeployLockId = ""
    return $true
}

function Invoke-ValidateDeployLockOnly {
    Write-Step "Deployment lock acquire/release validation only"
    Write-Host "This validation may create and release the selected lock file, but it runs no Docker, migration, collectstatic, restart, health-check, or traffic-switch command."
    Write-Host "Deployment lock path: $(Get-RelativeProjectPath -Path (Resolve-DeployLockPath -Path $DeployLockPath))"

    Acquire-DeploymentLock -Purpose "safe-deploy-validate-lock-only" -Target "local-validation"
    Write-Ok "Deployment lock acquire path validated. Cleanup/finally release will run before exit."
    return 0
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
    if ($CheckDeployLock -and $ValidateDeployLockOnly) {
        throw "Use only one of -CheckDeployLock or -ValidateDeployLockOnly."
    }

    if ($DryRun -and $ValidateDeployLockOnly) {
        throw "Use -DryRun for read-only command previews or -ValidateDeployLockOnly for real test-lock acquire/release validation, not both."
    }

    if ($CheckDeployLock) {
        $ScriptExitCode = Invoke-CheckDeployLock
    } elseif ($ValidateDeployLockOnly) {
        $ScriptExitCode = Invoke-ValidateDeployLockOnly
    } else {
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

        if (-not $DryRun) {
            Acquire-DeploymentLock -Purpose "safe-deploy" -Target "web"
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
            $ScriptExitCode = 0
        } else {
            $healthy = Wait-HealthCheck -Url $HealthUrl -TimeoutSeconds $HealthTimeoutSeconds
            if (-not $healthy) {
                Write-Fail "Web service did not become healthy. Recent web logs:"
                & docker compose logs --tail=100 web
                $ScriptExitCode = 1
            } else {
                Write-Ok "Safe deploy completed successfully."
                $ScriptExitCode = 0
            }
        }
    }
} catch {
    Write-Fail $_.Exception.Message
    Write-Fail "Safe deploy stopped before success."
    $ScriptExitCode = 1
} finally {
    if ($DeployLockAcquired) {
        if (-not (Release-DeploymentLock)) {
            $ScriptExitCode = 1
        }
    }
}

exit $ScriptExitCode
