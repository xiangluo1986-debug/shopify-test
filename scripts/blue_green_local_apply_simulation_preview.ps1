[CmdletBinding()]
param(
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

function Show-FileStatus {
    Write-Step "Required docs and example files"

    $items = @(
        [pscustomobject]@{
            Label = "Local simulation approval package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md"
        },
        [pscustomobject]@{
            Label = "Local inactive startup plan"
            Path = ".\docs\BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md"
        },
        [pscustomobject]@{
            Label = "Local dry-run review package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md"
        },
        [pscustomobject]@{
            Label = "Apply checklist"
            Path = ".\docs\BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md"
        },
        [pscustomobject]@{
            Label = "Blue-green plan"
            Path = ".\docs\BLUE_GREEN_DEPLOY_PLAN.md"
        },
        [pscustomobject]@{
            Label = "Example compose draft"
            Path = ".\docker-compose.bluegreen.example.yml"
        },
        [pscustomobject]@{
            Label = "Example proxy draft"
            Path = ".\nginx\bluegreen.example.conf"
        },
        [pscustomobject]@{
            Label = "Read-only dry-run planner"
            Path = ".\scripts\blue_green_deploy_dry_run.ps1"
        },
        [pscustomobject]@{
            Label = "Gated local simulation runner"
            Path = ".\scripts\blue_green_local_apply_simulation.ps1"
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

function Show-RunnerStatus {
    Write-Step "Local simulation runner status"

    $runnerPath = ".\scripts\blue_green_local_apply_simulation.ps1"
    if (Test-Path -LiteralPath $runnerPath) {
        Write-Ok "Simulation runner exists: $runnerPath"
    } else {
        Write-Warn "Simulation runner is missing: $runnerPath"
    }

    Write-Warn "Current status is dry-run / no-action only."
    Write-Warn "Real local simulation execution is not implemented in this phase."
    Write-Warn "Local inactive-color startup remains NO-GO until separate approval."
    Write-Warn "Any future inactive startup must use a non-8000 test port and leave current web untouched."
    Write-Warn "Production remains NO-GO."
}

function Show-ApprovalStatus {
    Write-Step "Approval phrase status"

    $ack = [Environment]::GetEnvironmentVariable("BLUE_GREEN_LOCAL_SIMULATION_ACK", "Process")
    if ([string]::IsNullOrEmpty($ack)) {
        Write-Warn "BLUE_GREEN_LOCAL_SIMULATION_ACK is not set."
        Write-Warn "Local simulation remains NO-GO."
        return
    }

    if ($ack -eq $RequiredApprovalPhrase) {
        Write-Ok "BLUE_GREEN_LOCAL_SIMULATION_ACK is present and matches the required phrase."
        Write-Warn "This preview still does not run the simulation or any dangerous command."
        return
    }

    Write-Warn "BLUE_GREEN_LOCAL_SIMULATION_ACK is present but does not match the required phrase."
    Write-Warn "The value was not printed. Local simulation remains NO-GO."
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

function Show-FutureCommandPlan {
    Write-Step "Future local simulation command plan"

    Write-Host "Every command below is documentation only and is NOT RUN IN THIS TASK."
    Write-Host ""

    $groups = @(
        [pscustomobject]@{
            Label = "Preflight checks"
            Commands = @(
                "git status --short --branch",
                "docker compose ps",
                "Invoke-WebRequest -Uri `"http://127.0.0.1:8000/healthz/`" -UseBasicParsing -TimeoutSec 5",
                "docker compose exec -T web python manage.py check"
            )
        },
        [pscustomobject]@{
            Label = "Example compose config validation"
            Commands = @(
                "docker compose -f docker-compose.bluegreen.example.yml config",
                "docker run --rm -v `"`${PWD}\nginx\bluegreen.example.conf:/etc/nginx/conf.d/default.conf:ro`" nginx:1.27-alpine nginx -t"
            )
        },
        [pscustomobject]@{
            Label = "Inactive color startup on test-only port"
            Commands = @(
                "# Future requirement: use one inactive test service only on a non-8000 port such as 18080 or 18081.",
                "docker compose -f <local-simulation-compose-file> up -d web_green"
            )
        },
        [pscustomobject]@{
            Label = "Health check"
            Commands = @(
                "Invoke-WebRequest -Uri `"http://127.0.0.1:<inactive-test-port>/healthz/`" -UseBasicParsing -TimeoutSec 5",
                "docker compose -f <local-simulation-compose-file> exec -T web_green python manage.py check"
            )
        },
        [pscustomobject]@{
            Label = "Logs inspection"
            Commands = @(
                "docker compose -f <local-simulation-compose-file> logs --tail=100 web_green"
            )
        },
        [pscustomobject]@{
            Label = "Cleanup inactive test color"
            Commands = @(
                "docker compose -f <local-simulation-compose-file> stop web_green"
            )
        },
        [pscustomobject]@{
            Label = "Rollback / no-switch behavior"
            Commands = @(
                "Leave current web running, keep port 8000 unchanged, do not change proxy or Cloudflare routing."
            )
        }
    )

    foreach ($group in $groups) {
        Write-Host $group.Label -ForegroundColor Cyan
        foreach ($command in $group.Commands) {
            Write-Host "  # NOT RUN IN THIS TASK"
            Write-Host "  $command"
        }
        Write-Host ""
    }
}

Show-GitStatus
Show-FileStatus
Show-RunnerStatus
Show-ApprovalStatus
Test-HealthUrl -Url $HealthUrl
Show-FutureCommandPlan

Write-Step "Result"
Write-Ok "Local blue-green apply simulation preview completed."
Write-Ok "No runtime behavior was changed."
Write-Ok "Inactive startup plan status: exists if listed above; local inactive startup remains NO-GO."
Write-Ok "Simulation runner status: dry-run / no-action only; production remains NO-GO."
Write-Ok "No docker compose up/down/restart/build, migrate, collectstatic, traffic switch, file modification, Shopify call, Gmail call, or email send was performed."
