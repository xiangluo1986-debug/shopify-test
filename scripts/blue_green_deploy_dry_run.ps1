[CmdletBinding()]
param(
    [string]$ComposeFile = ".\docker-compose.yml",
    [string]$HealthUrl = "http://127.0.0.1:8000/healthz/",
    [switch]$SkipHealthCheck
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

function Get-ComposeServiceNames {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Warn "Compose file was not found: $Path"
        return @()
    }

    $services = New-Object System.Collections.Generic.List[string]
    $inServices = $false

    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^services:\s*$') {
            $inServices = $true
            continue
        }

        if ($inServices -and $line -match '^[A-Za-z0-9_.-]+:\s*(?:#.*)?$') {
            break
        }

        if ($inServices -and $line -match '^\s{2}([A-Za-z0-9_.-]+):\s*(?:#.*)?$') {
            $services.Add($Matches[1])
        }
    }

    return $services.ToArray()
}

function Show-ComposeSummary {
    param([string]$Path)

    Write-Step "Compose service summary"
    Write-Host "Reading service names from $Path without printing environment values."

    $services = @(Get-ComposeServiceNames -Path $Path)
    if ($services.Count -eq 0) {
        Write-Warn "No services were detected. Review the compose file manually."
        return
    }

    Write-Host ("Services: " + ($services -join ", "))

    $proxyServices = @($services | Where-Object { $_ -match '^(nginx|proxy|caddy|traefik|haproxy)$' })
    if ($proxyServices.Count -eq 0) {
        Write-Warn "No local reverse proxy service was detected in Compose."
    } else {
        Write-Ok ("Proxy-like service detected: " + ($proxyServices -join ", "))
    }

    $webServices = @($services | Where-Object { $_ -match '^web' })
    if ($webServices.Count -le 1) {
        Write-Warn "Only one web-like service was detected. Blue-green is not active in the current Compose file."
    } else {
        Write-Ok ("Multiple web-like services detected: " + ($webServices -join ", "))
    }
}

function Show-ActiveComposeShape {
    param([string]$Path)

    Write-Step "Active Compose runtime shape"
    Write-Host "Checking whether the active Compose file still appears compatible with the current single-web workflow."

    $services = @(Get-ComposeServiceNames -Path $Path)
    if ($services.Count -eq 0) {
        Write-Warn "Could not confirm active Compose shape because no services were detected."
        return
    }

    $hasCurrentWeb = $services -contains "web"
    $webServices = @($services | Where-Object { $_ -match '^web' })
    $colorServices = @($services | Where-Object { $_ -match '^web_(blue|green)$' })
    $proxyServices = @($services | Where-Object { $_ -match '^(bluegreen_proxy|nginx|proxy|caddy|traefik|haproxy)$' })

    if ($hasCurrentWeb -and $webServices.Count -eq 1 -and $colorServices.Count -eq 0 -and $proxyServices.Count -eq 0) {
        Write-Ok "Current active Compose still appears single-web: service 'web' is present, and no active blue/green/proxy service was detected."
        return
    }

    Write-Warn "Active Compose no longer looks like the original single-web shape. Review before relying on this planner."
    Write-Host ("Detected services: " + ($services -join ", "))
}

function Show-DraftArtifactSummary {
    Write-Step "Non-active blue-green draft artifacts"

    $artifacts = @(
        [pscustomobject]@{
            Label = "Blue-green example compose"
            Path = ".\docker-compose.bluegreen.example.yml"
        },
        [pscustomobject]@{
            Label = "Proxy example config"
            Path = ".\nginx\bluegreen.example.conf"
        },
        [pscustomobject]@{
            Label = "Apply checklist"
            Path = ".\docs\BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md"
        },
        [pscustomobject]@{
            Label = "Manual decision review package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_DECISIONS.md"
        },
        [pscustomobject]@{
            Label = "Local apply dry-run review package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_DRY_RUN_REVIEW.md"
        },
        [pscustomobject]@{
            Label = "Local apply simulation approval package"
            Path = ".\docs\BLUE_GREEN_DEPLOY_LOCAL_APPLY_SIMULATION_APPROVAL.md"
        },
        [pscustomobject]@{
            Label = "Local inactive startup plan"
            Path = ".\docs\BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md"
        },
        [pscustomobject]@{
            Label = "Local apply simulation read-only preview"
            Path = ".\scripts\blue_green_local_apply_simulation_preview.ps1"
        },
        [pscustomobject]@{
            Label = "Gated local apply simulation runner"
            Path = ".\scripts\blue_green_local_apply_simulation.ps1"
        }
    )

    foreach ($artifact in $artifacts) {
        if (Test-Path -LiteralPath $artifact.Path) {
            Write-Ok "$($artifact.Label) exists: $($artifact.Path)"
        } else {
            Write-Warn "$($artifact.Label) is missing: $($artifact.Path)"
        }
    }

    Write-Host "These files are examples/checklists only. They are not loaded by the current docker compose command unless explicitly passed with -f."
}

function Show-DecisionStatus {
    Write-Step "Blue-green decision status"

    $decisionPath = ".\docs\BLUE_GREEN_DEPLOY_DECISIONS.md"
    if (-not (Test-Path -LiteralPath $decisionPath)) {
        Write-Warn "Decision document is missing: $decisionPath"
        return
    }

    Write-Ok "Decision document exists: $decisionPath"

    $content = Get-Content -LiteralPath $decisionPath -Raw
    $checks = @(
        [pscustomobject]@{
            Label = "Local-only planning approval marker"
            Needle = "Local-only planning status: approved"
        },
        [pscustomobject]@{
            Label = "Production apply remains NO-GO"
            Needle = "Production apply status: NO-GO."
        },
        [pscustomobject]@{
            Label = "nginx example-only default"
            Needle = "nginx, example-only"
        },
        [pscustomobject]@{
            Label = "Host port 8000 stays with current web service"
            Needle = 'Keep the current `web` service owning host port `8000`'
        },
        [pscustomobject]@{
            Label = "No Cloudflare or external routing change for local-only phase"
            Needle = "Make no Cloudflare, domain, tunnel, or external routing change"
        },
        [pscustomobject]@{
            Label = "File-based active color marker remains draft/example only"
            Needle = "Do not create an active runtime state file in this task."
        },
        [pscustomobject]@{
            Label = "Backward-compatible migration default"
            Needle = "Migrations must be backward-compatible"
        },
        [pscustomobject]@{
            Label = "Shared media remains unchanged"
            Needle = "Keep the current shared media volume behavior unchanged."
        },
        [pscustomobject]@{
            Label = "Scheduler remains singleton"
            Needle = "Scheduler remains singleton."
        },
        [pscustomobject]@{
            Label = "10-minute local/test observation minimum"
            Needle = "Minimum observation window: 10 minutes for local/test."
        },
        [pscustomobject]@{
            Label = "First apply scope is local-only dry-run planning"
            Needle = "First apply scope is local-only apply dry-run planning."
        }
    )

    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($check in $checks) {
        if ($content.Contains($check.Needle)) {
            Write-Ok "$($check.Label): present"
        } else {
            Write-Warn "$($check.Label): missing"
            $missing.Add($check.Label)
        }
    }

    if ($missing.Count -eq 0) {
        Write-Ok "Local-only defaults appear filled, and production apply remains NO-GO."
    } else {
        Write-Warn "Decision defaults may be incomplete. Review missing markers before relying on local-only planning status."
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
            Write-Ok "Health check returned HTTP 200."
        } else {
            Write-Warn "Health check returned HTTP $($response.StatusCode)."
        }
    } catch {
        Write-Warn "Health check was not reachable: $($_.Exception.Message)"
    }
}

function Show-FuturePlan {
    Write-Step "Future blue-green flow"

    Write-Host "NOT RUN IN THIS TASK: build or start the inactive color."
    Write-Host "NOT RUN IN THIS TASK: run Django checks inside the inactive color."
    Write-Host "NOT RUN IN THIS TASK: probe inactive-color /healthz/."
    Write-Host "NOT RUN IN THIS TASK: switch proxy traffic."
    Write-Host "NOT RUN IN THIS TASK: stop the previous color."
    Write-Host ""
    Write-Host "Local simulation runner status: dry-run / no-action only."
    Write-Host "Real local simulation execution is not implemented in this phase."
    Write-Host "Local inactive-color startup plan status: reviewed document only; startup remains NO-GO."
    Write-Host "Any future inactive startup must use one inactive test service on a non-8000 local port and leave current web untouched."
    Write-Host "Production remains NO-GO."
    Write-Host ""
    Write-Host "This script does not call docker compose up, down, restart, build, run, exec, or migrate."
    Write-Host "This script does not modify files, switch traffic, call Shopify APIs, call Gmail APIs, or send email."
}

Show-GitStatus
Show-ComposeSummary -Path $ComposeFile
Show-ActiveComposeShape -Path $ComposeFile
Show-DraftArtifactSummary
Show-DecisionStatus
Test-HealthUrl -Url $HealthUrl
Show-FuturePlan

Write-Step "Result"
Write-Ok "Blue-green dry-run planner completed. No deploy action was performed."
Write-Ok "No runtime behavior was changed by this read-only planner."
Write-Ok "Simulation runner status: dry-run / no-action only; production remains NO-GO."
