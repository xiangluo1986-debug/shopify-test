[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$ExecuteInactiveStartup,
    [string]$Ack = "",
    [int]$TestPort = 18080,
    [string]$InactiveService = "web_green_test",
    [string]$HealthUrl = "http://127.0.0.1:8000/healthz/",
    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RequiredApprovalPhrase = "I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC"
$CurrentActiveServiceName = "web"

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

function Show-Mode {
    Write-Step "Mode"

    if (-not $DryRun) {
        Write-Warn "DryRun was set to false, but this phase still forces dry-run / no-action behavior."
    } else {
        Write-Ok "Dry-run / no-action mode is active."
    }

    if ($ExecuteInactiveStartup) {
        Write-Warn "Inactive startup execution was requested."
    } else {
        Write-Ok "No inactive startup execution was requested."
    }

    Write-Warn "Inactive startup remains blocked by default."
    Write-Warn "Production remains NO-GO."
}

function Show-GitStatus {
    Write-Step "Git status"

    $status = Invoke-CaptureCommand -Command @("git", "status", "--short", "--branch")
    if ($status.ExitCode -ne 0) {
        Write-Warn "Could not read git status."
        $status.Output | ForEach-Object { Write-Warn "  $_" }
        return
    }

    $status.Output | ForEach-Object { Write-Host $_ }
}

function Show-ReadinessFiles {
    Write-Step "Readiness files"

    $items = @(
        [pscustomobject]@{
            Label = "Example blue-green Compose draft"
            Path = ".\docker-compose.bluegreen.example.yml"
        },
        [pscustomobject]@{
            Label = "Example nginx proxy draft"
            Path = ".\nginx\bluegreen.example.conf"
        },
        [pscustomobject]@{
            Label = "Blue-green plan"
            Path = ".\docs\BLUE_GREEN_DEPLOY_PLAN.md"
        },
        [pscustomobject]@{
            Label = "Local simulation approval package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md"
        },
        [pscustomobject]@{
            Label = "Local inactive startup plan"
            Path = ".\docs\BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md"
        },
        [pscustomobject]@{
            Label = "Apply checklist"
            Path = ".\docs\BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md"
        }
    )

    foreach ($item in $items) {
        if (Test-Path -LiteralPath $item.Path) {
            Write-Ok "$($item.Label) exists: $($item.Path)"
        } else {
            Write-Warn "$($item.Label) is missing: $($item.Path)"
        }
    }
}

function Test-StartupTarget {
    Write-Step "Startup target gate"

    Write-Host "Requested inactive service: $InactiveService"
    Write-Host "Requested test port: $TestPort"
    Write-Host "Current active service name: $CurrentActiveServiceName"

    if ($TestPort -eq 8000) {
        Write-Warn "Blocked: TestPort 8000 is forbidden."
        Write-Warn "The current web service must keep host port 8000."
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    if ([string]::IsNullOrWhiteSpace($InactiveService)) {
        Write-Warn "Blocked: InactiveService must be a non-empty service name."
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    if ($InactiveService -eq $CurrentActiveServiceName) {
        Write-Warn "Blocked: InactiveService must not equal the current active service name web."
        Write-Warn "The current web service must remain untouched."
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    Write-Ok "Target gate passed for dry-run planning: test port is not 8000 and inactive service is not web."
    return 0
}

function Test-HealthUrl {
    param([string]$Url)

    Write-Step "Current health endpoint"

    if ($SkipHealthCheck) {
        Write-Warn "Skipping health check because -SkipHealthCheck was set."
        return
    }

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-Ok "Current health check returned HTTP 200."
        } else {
            Write-Warn "Current health check returned HTTP $($response.StatusCode)."
        }
    } catch {
        Write-Warn "Current health check was not reachable: $($_.Exception.Message)"
    }
}

function Show-SafeConfigNote {
    Write-Step "Example Compose config validation"

    Write-Host "No Docker command is run by this runner in this phase."
    Write-Host "A future separately approved phase may run this read-only validation after confirming it will not expose private environment values:"
    Write-Host "  # NOT RUN IN THIS TASK"
    Write-Host "  docker compose -f docker-compose.bluegreen.example.yml config"
}

function Show-BlockedStartupPlan {
    Write-Step "Future local inactive startup plan"

    Write-Host "The steps below are documentation only and are NOT RUN by this script in this phase."
    Write-Host ""
    Write-Host "Script path:"
    Write-Host "  .\scripts\blue_green_local_inactive_startup.ps1"
    Write-Host ""
    Write-Host "Required approval phrase:"
    Write-Host "  $RequiredApprovalPhrase"
    Write-Host ""

    $steps = @(
        "Review git status and local readiness files.",
        "Confirm active docker-compose.yml remains unchanged.",
        "Confirm current web service still owns host port 8000.",
        "Confirm inactive service is not web.",
        "Confirm inactive test port is not 8000.",
        "Validate example Compose/proxy config without starting containers.",
        "Start only one inactive test service on the reviewed non-8000 local test port.",
        "Health-check the inactive color directly through /healthz/.",
        "Stop only the inactive local test color after validation.",
        "Leave current web, Cloudflare/domain routing, and production traffic unchanged."
    )

    foreach ($step in $steps) {
        Write-Host "  - $step"
    }

    Write-Host ""
    Write-Host "Blocked commands in this phase:"
    Write-Host "  docker compose up"
    Write-Host "  docker compose down"
    Write-Host "  docker compose restart"
    Write-Host "  docker compose build"
    Write-Host "  python manage.py migrate"
    Write-Host "  python manage.py collectstatic"
    Write-Host "  proxy reload or traffic switch"
    Write-Host ""
    Write-Host "Current phase status:"
    Write-Host "  - inactive startup runner exists"
    Write-Host "  - inactive startup remains blocked by default"
    Write-Host "  - test port must not be 8000"
    Write-Host "  - inactive service must not be web"
    Write-Host "  - production remains NO-GO"
}

function Test-ExecutionGate {
    Write-Step "Execution gate"

    if (-not $ExecuteInactiveStartup) {
        Write-Ok "No execution requested. Printed the dry-run plan only."
        Write-Warn "Inactive startup remains blocked by default."
        Write-Warn "Production remains NO-GO."
        return 0
    }

    if ([string]::IsNullOrWhiteSpace($Ack)) {
        Write-Warn "Blocked: -ExecuteInactiveStartup was provided, but -Ack is missing."
        Write-Warn "Required approval phrase: $RequiredApprovalPhrase"
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    if ($Ack -ne $RequiredApprovalPhrase) {
        Write-Warn "Blocked: -Ack does not match the required approval phrase."
        Write-Warn "The provided value was not printed."
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    Write-Ok "Approval phrase matched."
    Write-Warn "Real inactive startup execution is not implemented in this phase."
    Write-Warn "No containers were started, stopped, restarted, or built."
    Write-Warn "No migration, collectstatic, proxy switch, file edit, Shopify call, Gmail call, or email send was performed."
    Write-Warn "Production remains NO-GO."
    return 3
}

Show-Mode
Show-GitStatus
Show-ReadinessFiles

$targetGateExitCode = Test-StartupTarget
if ($targetGateExitCode -ne 0) {
    Write-Step "Result"
    Write-Warn "Local inactive-color startup runner blocked execution."
    Write-Ok "Runtime behavior changed: no."
    Write-Ok "Deploy, restart, build, migration, collectstatic, traffic switch, Shopify/Gmail/API write: no."
    exit $targetGateExitCode
}

Test-HealthUrl -Url $HealthUrl
Show-SafeConfigNote
Show-BlockedStartupPlan

$exitCode = Test-ExecutionGate

Write-Step "Result"
if ($exitCode -eq 0) {
    Write-Ok "Local inactive-color startup runner completed in dry-run / no-action mode."
} else {
    Write-Warn "Local inactive-color startup runner blocked execution."
}
Write-Ok "Runtime behavior changed: no."
Write-Ok "Deploy, restart, build, migration, collectstatic, traffic switch, Shopify/Gmail/API write: no."

exit $exitCode
