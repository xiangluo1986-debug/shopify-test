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
    Write-Host "This script does not call docker compose up, down, restart, build, run, exec, or migrate."
    Write-Host "This script does not modify files, switch traffic, call Shopify APIs, call Gmail APIs, or send email."
}

Show-GitStatus
Show-ComposeSummary -Path $ComposeFile
Test-HealthUrl -Url $HealthUrl
Show-FuturePlan

Write-Step "Result"
Write-Ok "Blue-green dry-run planner completed. No deploy action was performed."
