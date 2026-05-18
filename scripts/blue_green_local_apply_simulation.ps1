[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$ExecuteLocalSimulation,
    [string]$Ack = "",
    [string]$HealthUrl = "http://127.0.0.1:8000/healthz/",
    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RequiredApprovalPhrase = "I_APPROVE_LOCAL_ONLY_BLUE_GREEN_SIMULATION_NO_PRODUCTION_TRAFFIC"

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

    if ($ExecuteLocalSimulation) {
        Write-Warn "Local simulation execution was requested."
        Write-Warn "Real local simulation execution is not implemented in this phase."
    } else {
        Write-Ok "No local simulation execution was requested."
    }

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
            Label = "Active Compose file"
            Path = ".\docker-compose.yml"
        },
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
            Label = "Manual decision package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_DECISIONS.md"
        },
        [pscustomobject]@{
            Label = "Local dry-run review package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md"
        },
        [pscustomobject]@{
            Label = "Local simulation approval package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md"
        },
        [pscustomobject]@{
            Label = "Local simulation preview script"
            Path = ".\scripts\blue_green_local_apply_simulation_preview.ps1"
        },
        [pscustomobject]@{
            Label = "Blue-green dry-run planner"
            Path = ".\scripts\blue_green_deploy_dry_run.ps1"
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
    Write-Host "A future separately approved phase may run this read-only validation if the example Compose file is confirmed not to expose private environment values:"
    Write-Host "  # NOT RUN IN THIS TASK"
    Write-Host "  docker compose -f docker-compose.bluegreen.example.yml config"
}

function Show-BlockedActionPlan {
    Write-Step "Future local simulation plan"

    Write-Host "The steps below are documentation only and are NOT RUN by this script in this phase."
    Write-Host ""

    $steps = @(
        "Review git status and local readiness files.",
        "Confirm active docker-compose.yml remains unchanged.",
        "Confirm current web service still owns host port 8000.",
        "Validate example Compose/proxy config without starting containers.",
        "Start only the inactive color on a reviewed local-only test port.",
        "Run Django checks against the inactive color only.",
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
}

function Test-ExecutionGate {
    Write-Step "Execution gate"

    if (-not $ExecuteLocalSimulation) {
        Write-Ok "No execution requested. Printed the dry-run plan only."
        Write-Warn "Production remains NO-GO."
        return 0
    }

    if ([string]::IsNullOrWhiteSpace($Ack)) {
        Write-Warn "Blocked: -ExecuteLocalSimulation was provided, but -Ack is missing."
        Write-Warn "Required approval phrase: $RequiredApprovalPhrase"
        Write-Warn "No local simulation was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    if ($Ack -ne $RequiredApprovalPhrase) {
        Write-Warn "Blocked: -Ack does not match the required approval phrase."
        Write-Warn "The provided value was not printed."
        Write-Warn "No local simulation was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    Write-Ok "Approval phrase matched."
    Write-Warn "Real local simulation execution is not implemented in this phase."
    Write-Warn "No containers were started, stopped, restarted, or built."
    Write-Warn "No migration, collectstatic, proxy switch, file edit, Shopify call, Gmail call, or email send was performed."
    Write-Warn "Production remains NO-GO."
    return 3
}

Show-Mode
Show-GitStatus
Show-ReadinessFiles
Test-HealthUrl -Url $HealthUrl
Show-SafeConfigNote
Show-BlockedActionPlan

$exitCode = Test-ExecutionGate

Write-Step "Result"
if ($exitCode -eq 0) {
    Write-Ok "Local blue-green simulation runner completed in dry-run / no-action mode."
} else {
    Write-Warn "Local blue-green simulation runner blocked execution."
}
Write-Ok "Runtime behavior changed: no."
Write-Ok "Deploy, restart, build, migration, collectstatic, traffic switch, Shopify/Gmail/API write: no."

exit $exitCode
