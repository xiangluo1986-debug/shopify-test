[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$ExecuteInactiveStartup,
    [string]$Ack = "",
    [int]$TestPort = 18080,
    [string]$InactiveService = "web_green_test",
    [string]$ComposeFile = ".\docker-compose.bluegreen.local-test.example.yml",
    [switch]$AllowContainerAction,
    [string]$HealthUrl = "http://127.0.0.1:8000/healthz/",
    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RequiredApprovalPhrase = "I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC"
$CurrentActiveServiceName = "web"
$ForbiddenHostPort = 8000

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
        Write-Warn "DryRun was set to false. Real local startup still requires -ExecuteInactiveStartup, the exact -Ack, and -AllowContainerAction."
    } else {
        Write-Ok "Dry-run / no-action mode is active unless every execution gate is supplied."
    }

    if ($ExecuteInactiveStartup) {
        Write-Warn "Inactive startup execution was requested."
    } else {
        Write-Ok "No inactive startup execution was requested."
    }

    if ($AllowContainerAction) {
        Write-Warn "AllowContainerAction was supplied. Container actions can run only after all other gates pass."
    } else {
        Write-Ok "AllowContainerAction is not supplied."
    }

    Write-Host "Compose file: $ComposeFile"
    Write-Host "Inactive service: $InactiveService"
    Write-Host "Test port: $TestPort"
    Write-Warn "Inactive startup remains blocked by default and requires a separate explicit execution request."
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
            Label = "Local-test inactive Compose example"
            Path = ".\docker-compose.bluegreen.local-test.example.yml"
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
    Write-Host "Requested compose file: $ComposeFile"
    Write-Host "Current active service name: $CurrentActiveServiceName"

    if ($TestPort -lt 1 -or $TestPort -gt 65535) {
        Write-Warn "Blocked: TestPort must be between 1 and 65535."
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    if ($TestPort -eq $ForbiddenHostPort) {
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

    if ([string]::IsNullOrWhiteSpace($ComposeFile)) {
        Write-Warn "Blocked: ComposeFile must be a non-empty path."
        Write-Warn "No inactive startup was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    $composeLeaf = Split-Path -Leaf $ComposeFile
    if ($composeLeaf -eq "docker-compose.yml") {
        Write-Warn "Blocked: active docker-compose.yml must not be used for the local inactive startup runner."
        Write-Warn "Use the reviewed local-test example compose file instead."
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

    Write-Host "No Docker command is run unless -ExecuteInactiveStartup, the exact -Ack, and -AllowContainerAction are all supplied."
    Write-Host "A future execution path validates the local-test compose file before any startup:"
    Write-Host "  docker compose -f $ComposeFile config --quiet"
    Write-Host "The separate validation command requested for this task is config-only and does not start containers:"
    Write-Host "  docker compose -f docker-compose.bluegreen.local-test.example.yml config"
}

function Show-BlockedStartupPlan {
    Write-Step "Future local inactive startup plan"

    Write-Host "The steps below are documentation only during dry-run and are NOT RUN unless every execution gate is supplied."
    Write-Host ""
    Write-Host "Script path:"
    Write-Host "  .\scripts\blue_green_local_inactive_startup.ps1"
    Write-Host "Local-test Compose example:"
    Write-Host "  .\docker-compose.bluegreen.local-test.example.yml"
    Write-Host ""
    Write-Host "Required approval phrase:"
    Write-Host "  $RequiredApprovalPhrase"
    Write-Host "Required container-action gate:"
    Write-Host "  -AllowContainerAction"
    Write-Host ""

    $steps = @(
        "Review git status and local readiness files.",
        "Confirm active docker-compose.yml remains unchanged.",
        "Confirm current web service still owns host port 8000.",
        "Confirm inactive service is not web.",
        "Confirm inactive test port is not 8000.",
        "Validate the local-test Compose file before startup.",
        "Start only one inactive test service on the reviewed non-8000 local test port.",
        "Health-check the inactive color directly through /healthz/.",
        "Print inactive service logs if health check fails.",
        "Stop only the inactive local test color after validation.",
        "Leave current web, Cloudflare/domain routing, and production traffic unchanged."
    )

    foreach ($step in $steps) {
        Write-Host "  - $step"
    }

    Write-Host ""
    Write-Host "Blocked unless all execution gates are supplied; not run during this task validation:"
    Write-Host "  docker compose up"
    Write-Host "  docker compose down"
    Write-Host "  docker compose restart"
    Write-Host "  docker compose build"
    Write-Host "  python manage.py migrate"
    Write-Host "  python manage.py collectstatic"
    Write-Host "  proxy reload or traffic switch"
    Write-Host ""
    Write-Host "Future executable path:"
    Write-Host "  - validate compose config with --quiet"
    Write-Host "  - docker compose -f $ComposeFile up -d --no-deps --no-build $InactiveService"
    Write-Host "  - Invoke-WebRequest http://127.0.0.1:$TestPort/healthz/"
    Write-Host "  - docker compose -f $ComposeFile logs --tail=100 $InactiveService only if health fails"
    Write-Host "  - docker compose -f $ComposeFile stop $InactiveService during cleanup"
    Write-Host ""
    Write-Host "Current phase status:"
    Write-Host "  - inactive startup runner exists"
    Write-Host "  - local-only executable path exists behind strict gates"
    Write-Host "  - -AllowContainerAction is required for future real local startup"
    Write-Host "  - test port must not be 8000"
    Write-Host "  - inactive service must not be web"
    Write-Host "  - production remains NO-GO"
}

function Show-CleanupPlan {
    Write-Step "Future cleanup plan"

    Write-Host "Cleanup for a future approved local startup is limited to the inactive test service:"
    Write-Host "  docker compose -f $ComposeFile stop $InactiveService"
    Write-Host ""
    Write-Host "Cleanup must not:"
    Write-Host "  - stop current web"
    Write-Host "  - run docker compose down for the whole project"
    Write-Host "  - remove db or media volumes"
    Write-Host "  - prune Docker resources"
    Write-Host "  - change proxy, Cloudflare, domain routing, or production traffic"
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

    if (-not $AllowContainerAction) {
        Write-Warn "Blocked: real local inactive startup also requires -AllowContainerAction."
        Write-Warn "No Docker container action was run."
        Write-Warn "No containers were started, stopped, restarted, or built."
        Write-Warn "No migration, collectstatic, proxy switch, file edit, Shopify call, Gmail call, or email send was performed."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    Write-Warn "All local execution gates are present."
    Write-Warn "This path is local-test only and must not use port 8000, current web, production proxy, or production traffic."
    return 10
}

function Test-InactiveHealth {
    param([string]$Url)

    Write-Step "Inactive service health check"
    Write-Host "Health URL: $Url"

    for ($attempt = 1; $attempt -le 12; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                Write-Ok "Inactive service health check returned HTTP 200."
                return $true
            }

            Write-Warn "Inactive service health attempt $attempt returned HTTP $($response.StatusCode)."
        } catch {
            Write-Warn "Inactive service health attempt $attempt failed: $($_.Exception.Message)"
        }

        if ($attempt -lt 12) {
            Start-Sleep -Seconds 5
        }
    }

    return $false
}

function Invoke-InactiveStartup {
    Write-Step "Local inactive startup execution"

    if (-not (Test-Path -LiteralPath $ComposeFile)) {
        Write-Warn "Blocked: Compose file was not found: $ComposeFile"
        Write-Warn "No Docker container action was run."
        Write-Warn "Production remains NO-GO."
        return 2
    }

    $inactiveHealthUrl = "http://127.0.0.1:$TestPort/healthz/"
    $startedInactiveService = $false
    $exitCode = 0
    $previousLocalTestPort = [Environment]::GetEnvironmentVariable("BLUE_GREEN_LOCAL_TEST_PORT", "Process")

    try {
        [Environment]::SetEnvironmentVariable("BLUE_GREEN_LOCAL_TEST_PORT", [string]$TestPort, "Process")

        Write-Step "Validate local-test Compose config"
        Write-Host "Running config validation without printing expanded config."
        $config = Invoke-CaptureCommand -Command @("docker", "compose", "-f", $ComposeFile, "config", "--quiet")
        if ($config.ExitCode -ne 0) {
            Write-Warn "Blocked: docker compose config validation failed for $ComposeFile."
            Write-Warn "No inactive service was started."
            Write-Warn "Production remains NO-GO."
            return 2
        }
        Write-Ok "Compose config validation passed."

        Write-Step "Start inactive test service only"
        Write-Host "Starting only inactive service '$InactiveService' from '$ComposeFile'."
        Write-Host "Command uses --no-deps and --no-build."
        $start = Invoke-CaptureCommand -Command @("docker", "compose", "-f", $ComposeFile, "up", "-d", "--no-deps", "--no-build", $InactiveService)
        if ($start.ExitCode -ne 0) {
            Write-Warn "Blocked: inactive service startup failed."
            Write-Warn "No current web, scheduler, proxy, traffic, migration, collectstatic, or production action was requested by this runner."
            return 2
        }
        $startedInactiveService = $true
        Write-Ok "Inactive test service startup command completed."

        if (-not (Test-InactiveHealth -Url $inactiveHealthUrl)) {
            Write-Warn "Inactive service health check failed. Printing inactive service logs only."
            $logs = Invoke-CaptureCommand -Command @("docker", "compose", "-f", $ComposeFile, "logs", "--tail=100", $InactiveService)
            if ($logs.Output) {
                $logs.Output | ForEach-Object { Write-Host $_ }
            }
            $exitCode = 2
        } else {
            Write-Ok "Inactive local startup validation passed."
        }
    } finally {
        if ($startedInactiveService) {
            Write-Step "Cleanup inactive test service only"
            Write-Host "Stopping only inactive service '$InactiveService'."
            $stop = Invoke-CaptureCommand -Command @("docker", "compose", "-f", $ComposeFile, "stop", $InactiveService)
            if ($stop.ExitCode -ne 0) {
                Write-Warn "Inactive service stop command failed. Review the inactive test service manually."
                $exitCode = 2
            } else {
                Write-Ok "Inactive test service stop command completed."
            }
        }

        [Environment]::SetEnvironmentVariable("BLUE_GREEN_LOCAL_TEST_PORT", $previousLocalTestPort, "Process")
    }

    Write-Warn "Current web was not targeted."
    Write-Warn "Port 8000 was not targeted."
    Write-Warn "No migration, collectstatic, proxy switch, Shopify call, Gmail call, or email send was requested."
    Write-Warn "Production remains NO-GO."
    return $exitCode
}

Show-Mode
Show-GitStatus
Show-ReadinessFiles

$targetGateExitCode = Test-StartupTarget
if ($targetGateExitCode -ne 0) {
    Write-Step "Result"
    Write-Warn "Local inactive-color startup runner blocked execution."
    Write-Ok "Runtime behavior changed: no."
    Write-Ok "Container start/stop/restart/build: no."
    Write-Ok "Deploy, migration, collectstatic, traffic switch, Shopify/Gmail/API write: no."
    exit $targetGateExitCode
}

Test-HealthUrl -Url $HealthUrl
Show-SafeConfigNote
Show-BlockedStartupPlan
Show-CleanupPlan

$exitCode = Test-ExecutionGate
if ($exitCode -eq 10) {
    $exitCode = Invoke-InactiveStartup
}

Write-Step "Result"
if ($exitCode -eq 0) {
    if ($ExecuteInactiveStartup -and $AllowContainerAction -and $Ack -eq $RequiredApprovalPhrase) {
        Write-Ok "Local inactive-color startup runner completed the gated local execution path."
    } else {
        Write-Ok "Local inactive-color startup runner completed in dry-run / no-action mode."
    }
} else {
    Write-Warn "Local inactive-color startup runner blocked execution."
}
Write-Ok "Runtime behavior changed: no."
if ($ExecuteInactiveStartup -and $AllowContainerAction -and $Ack -eq $RequiredApprovalPhrase) {
    Write-Warn "Container action gate was supplied; review execution sections above for inactive-service start/stop results."
} else {
    Write-Ok "Container start/stop/restart/build: no."
}
Write-Ok "Deploy, migration, collectstatic, traffic switch, Shopify/Gmail/API write: no."

exit $exitCode
