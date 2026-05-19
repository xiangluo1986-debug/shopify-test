[CmdletBinding()]
param(
    [string]$ComposeFile = ".\docker-compose.yml",
    [string]$HealthUrl = "http://127.0.0.1:8000/healthz/",
    [switch]$SkipHealthCheck
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$InactiveStartupApprovalPhrase = "I_APPROVE_LOCAL_INACTIVE_COLOR_STARTUP_NO_8000_NO_PRODUCTION_TRAFFIC"
$NonProductionValidationApprovalPhrase = "I_APPROVE_NON_PRODUCTION_BLUE_GREEN_RUNTIME_VALIDATION_NO_PRODUCTION_TRAFFIC"
$NonProductionValidationLockPath = ".deploy/bluegreen-nonprod-validation.lock"
$NonProductionInactiveRuntimeValidationStatus = "PASSED"
$ProxyValidationApprovalPhrase = "I_APPROVE_LOCAL_PROXY_ROUTING_VALIDATION_NO_PRODUCTION_TRAFFIC"
$ProxyValidationLockPath = ".deploy/bluegreen-proxy-validation.lock"
$ProxyValidationComposeProjectName = "aftersales-bluegreen-proxy-validation"
$ProxyValidationInactivePort = "18080"
$ProxyValidationProxyPort = "19080"
$ProxyValidationTargetService = "web_green_test"
$ProxyValidationProxyService = "bluegreen_proxy_test"
$ProxyValidationUnifiedComposePath = ".\docker-compose.bluegreen.proxy-validation.example.yml"
$ProxyValidationStatus = "PASSED"
$ProxyValidationHoldOpenStatus = "completed for 2026-05-19 validation"
$ProductionApplyStatus = "NO-GO"
$NextBlueGreenStep = "use production runtime defaults for future exact implementation review"
$ProductionPreflightPath = ".\docs\BLUE_GREEN_PRODUCTION_PREFLIGHT.md"
$ProductionPreflightStatus = "READY after review"
$ProductionReadinessPath = ".\docs\BLUE_GREEN_PRODUCTION_APPLY_READINESS.md"
$ProductionApplyReadinessStatus = "READY after review"
$ProductionCommandReviewPath = ".\docs\BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md"
$ProductionCommandReviewStatus = "READY after review"
$ProductionRuntimeDetailsPath = ".\docs\BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md"
$ProductionRuntimeDetailsStatus = "READY after review"
$ProductionCommandPathSkeletonStatus = "implemented but blocked"
$ProductionCommandImplementationStatus = "NOT READY"

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
            Label = "Local-test inactive Compose example"
            Path = ".\docker-compose.bluegreen.local-test.example.yml"
        },
        [pscustomobject]@{
            Label = "Unified local-test proxy validation Compose example"
            Path = ".\docker-compose.bluegreen.proxy-validation.example.yml"
        },
        [pscustomobject]@{
            Label = "Local-test proxy-only Compose example"
            Path = ".\docker-compose.bluegreen.proxy-test.example.yml"
        },
        [pscustomobject]@{
            Label = "Proxy example config"
            Path = ".\nginx\bluegreen.example.conf"
        },
        [pscustomobject]@{
            Label = "Local-test proxy example config"
            Path = ".\nginx\bluegreen.local-test.example.conf"
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
            Label = "Deployment lock design"
            Path = ".\docs\DEPLOYMENT_LOCK.md"
        },
        [pscustomobject]@{
            Label = "Deployment lock dry-run helper"
            Path = ".\scripts\deploy_lock_dry_run.ps1"
        },
        [pscustomobject]@{
            Label = "Deployment lock real helper"
            Path = ".\scripts\deploy_lock.ps1"
        },
        [pscustomobject]@{
            Label = "Local inactive startup plan"
            Path = ".\docs\BLUE_GREEN_LOCAL_INACTIVE_STARTUP_PLAN.md"
        },
        [pscustomobject]@{
            Label = "Non-production runtime validation plan"
            Path = ".\docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION.md"
        },
        [pscustomobject]@{
            Label = "Non-production runtime validation approval package"
            Path = ".\docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md"
        },
        [pscustomobject]@{
            Label = "Local proxy routing validation approval package"
            Path = ".\docs\BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md"
        },
        [pscustomobject]@{
            Label = "Production preflight readiness review"
            Path = $ProductionPreflightPath
        },
        [pscustomobject]@{
            Label = "Production apply readiness checklist / exact command review"
            Path = $ProductionReadinessPath
        },
        [pscustomobject]@{
            Label = "Production runtime command review"
            Path = $ProductionCommandReviewPath
        },
        [pscustomobject]@{
            Label = "Production runtime details"
            Path = $ProductionRuntimeDetailsPath
        },
        [pscustomobject]@{
            Label = "Local apply simulation read-only preview"
            Path = ".\scripts\blue_green_local_apply_simulation_preview.ps1"
        },
        [pscustomobject]@{
            Label = "Gated local apply simulation runner"
            Path = ".\scripts\blue_green_local_apply_simulation.ps1"
        },
        [pscustomobject]@{
            Label = "Gated local inactive startup runner"
            Path = ".\scripts\blue_green_local_inactive_startup.ps1"
        },
        [pscustomobject]@{
            Label = "No-action production apply skeleton"
            Path = ".\scripts\blue_green_production_apply.ps1"
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

function Show-DeploymentLockStatus {
    Write-Step "Deployment lock status"

    $lockDocPath = ".\docs\DEPLOYMENT_LOCK.md"
    $lockDryRunPath = ".\scripts\deploy_lock_dry_run.ps1"
    $lockHelperPath = ".\scripts\deploy_lock.ps1"
    $safeDeployPath = ".\scripts\safe_deploy.ps1"
    $productionApplyPath = ".\scripts\blue_green_production_apply.ps1"
    $nonProductionValidationPath = ".\docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION.md"
    $nonProductionApprovalPath = ".\docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md"
    $proxyValidationApprovalPath = ".\docs\BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md"
    $productionPreflightPath = $ProductionPreflightPath
    $productionReadinessPath = $ProductionReadinessPath
    $productionCommandReviewPath = $ProductionCommandReviewPath
    $productionRuntimeDetailsPath = $ProductionRuntimeDetailsPath
    $proxyUnifiedComposePath = $ProxyValidationUnifiedComposePath
    $proxyComposePath = ".\docker-compose.bluegreen.proxy-test.example.yml"
    $proxyConfigPath = ".\nginx\bluegreen.local-test.example.conf"

    if (Test-Path -LiteralPath $lockDocPath) {
        Write-Ok "Deployment lock design doc exists: $lockDocPath"
    } else {
        Write-Warn "Deployment lock design doc is missing: $lockDocPath"
    }

    if (Test-Path -LiteralPath $lockDryRunPath) {
        Write-Ok "Deploy lock dry-run helper exists: $lockDryRunPath"
    } else {
        Write-Warn "Deploy lock dry-run helper is missing: $lockDryRunPath"
    }

    if (Test-Path -LiteralPath $lockHelperPath) {
        Write-Ok "Deploy lock real helper exists: $lockHelperPath"
    } else {
        Write-Warn "Deploy lock real helper is missing: $lockHelperPath"
    }

    if (Test-Path -LiteralPath $safeDeployPath) {
        $safeDeployText = Get-Content -LiteralPath $safeDeployPath -Raw
        $safeDeployLockEnforcementExists = ($safeDeployText -match "CheckDeployLock") -and ($safeDeployText -match "ValidateDeployLockOnly") -and ($safeDeployText -match "Acquire-DeploymentLock") -and ($safeDeployText -match "Release-DeploymentLock")
        Write-Host "safe_deploy real-mode lock enforcement exists: $safeDeployLockEnforcementExists"
    } else {
        Write-Warn "safe_deploy script is missing: $safeDeployPath"
    }

    if (Test-Path -LiteralPath $productionApplyPath) {
        $productionApplyText = Get-Content -LiteralPath $productionApplyPath -Raw
        $productionApplySkeletonExists = ($productionApplyText -match "I_APPROVE_PRODUCTION_BLUE_GREEN_APPLY_AFTER_PREFLIGHT_REVIEW") -and ($productionApplyText -match "Real production blue-green apply command path is implemented as a skeleton only and remains blocked in this phase")
        Write-Ok "Blue-green production apply skeleton exists: $productionApplyPath"
        Write-Host "Blue-green production apply skeleton no-action gate present: $productionApplySkeletonExists"
    } else {
        Write-Warn "Blue-green production apply skeleton is missing: $productionApplyPath"
    }

    if (Test-Path -LiteralPath $nonProductionValidationPath) {
        Write-Ok "Non-production validation plan exists: $nonProductionValidationPath"
    } else {
        Write-Warn "Non-production validation plan is missing: $nonProductionValidationPath"
    }

    if (Test-Path -LiteralPath $nonProductionApprovalPath) {
        Write-Ok "Non-production validation approval package exists: $nonProductionApprovalPath"
    } else {
        Write-Warn "Non-production validation approval package is missing: $nonProductionApprovalPath"
    }

    if (Test-Path -LiteralPath $proxyValidationApprovalPath) {
        Write-Ok "Local proxy routing validation approval package exists: $proxyValidationApprovalPath"
    } else {
        Write-Warn "Local proxy routing validation approval package is missing: $proxyValidationApprovalPath"
    }

    if (Test-Path -LiteralPath $productionPreflightPath) {
        Write-Ok "Production preflight document exists: $productionPreflightPath"
    } else {
        Write-Warn "Production preflight document is missing: $productionPreflightPath"
    }

    if (Test-Path -LiteralPath $productionReadinessPath) {
        Write-Ok "Production apply readiness package exists: $productionReadinessPath"
    } else {
        Write-Warn "Production apply readiness package is missing: $productionReadinessPath"
    }

    if (Test-Path -LiteralPath $productionCommandReviewPath) {
        Write-Ok "Production command review document exists: $productionCommandReviewPath"
    } else {
        Write-Warn "Production command review document is missing: $productionCommandReviewPath"
    }

    if (Test-Path -LiteralPath $productionRuntimeDetailsPath) {
        Write-Ok "Production runtime details document exists: $productionRuntimeDetailsPath"
    } else {
        Write-Warn "Production runtime details document is missing: $productionRuntimeDetailsPath"
    }

    if (Test-Path -LiteralPath $proxyUnifiedComposePath) {
        Write-Ok "Unified local proxy routing compose example exists: $proxyUnifiedComposePath"
        $proxyUnifiedText = Get-Content -LiteralPath $proxyUnifiedComposePath -Raw
        $proxyNetworkFixReady = ($proxyUnifiedText -match "web_green_test") -and ($proxyUnifiedText -match "bluegreen_proxy_test") -and ($proxyUnifiedText -match "local_validation_net") -and ($proxyUnifiedText -match "18080:8000") -and ($proxyUnifiedText -match "19080:80")
        Write-Host "Proxy validation network fix ready: $proxyNetworkFixReady"
    } else {
        Write-Warn "Unified local proxy routing compose example is missing: $proxyUnifiedComposePath"
        Write-Host "Proxy validation network fix ready: False"
    }

    if (Test-Path -LiteralPath $proxyComposePath) {
        Write-Ok "Proxy-only local routing compose example exists: $proxyComposePath"
    } else {
        Write-Warn "Proxy-only local routing compose example is missing: $proxyComposePath"
    }

    if (Test-Path -LiteralPath $proxyConfigPath) {
        Write-Ok "Local proxy routing nginx example exists: $proxyConfigPath"
    } else {
        Write-Warn "Local proxy routing nginx example is missing: $proxyConfigPath"
    }

    Write-Ok "safe_deploy lock enforcement is active in real non-dry-run mode."
    Write-Warn "Blue-green production real apply remains NO-GO. The command path skeleton is implemented but blocked and still performs no runtime action."
    Write-Host "Non-production inactive runtime validation: $NonProductionInactiveRuntimeValidationStatus."
    Write-Host "Local/test proxy routing validation: $ProxyValidationStatus."
    Write-Host "Non-production validation chain: PASSED for inactive runtime plus local/test proxy routing."
    Write-Host "Production preflight: $ProductionPreflightStatus."
    Write-Host "Production preflight document exists: $(Test-Path -LiteralPath $ProductionPreflightPath)."
    Write-Host "Production apply readiness: $ProductionApplyReadinessStatus."
    Write-Host "Production apply readiness package exists: $(Test-Path -LiteralPath $ProductionReadinessPath)."
    Write-Host "Production command review: $ProductionCommandReviewStatus."
    Write-Host "Production command review document exists: $(Test-Path -LiteralPath $ProductionCommandReviewPath)."
    Write-Host "Production runtime details: $ProductionRuntimeDetailsStatus."
    Write-Host "Production runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath)."
    Write-Host "Production proxy/active-color/rollback details: conservative defaults documented."
    Write-Host "Conservative defaults: nginx proxy candidate; current web owns port 8000 until final approval; web_blue/web_green/bluegreen_proxy service names; .deploy/active-color.json state; rollback to previous_color; at least 10 minutes of observation."
    Write-Host "Active-color state under .deploy must not be committed and must not contain secrets."
    Write-Host "Production command path skeleton: $ProductionCommandPathSkeletonStatus."
    Write-Host "Production implementation: $ProductionCommandImplementationStatus."
    Write-Host "Proxy validation hold-open mode: $ProxyValidationHoldOpenStatus in scripts/blue_green_local_inactive_startup.ps1."
    Write-Host "Production apply: $ProductionApplyStatus."
    Write-Host "Next step: $NextBlueGreenStep."
    Write-Host "Production apply remains blocked until exact runtime commands based on the documented defaults are implemented, reviewed, approved, and covered by manual production approval."
    Write-Host "Local inactive startup has separate local-only gates; production switch still requires the deployment lock."
    Write-Host "Non-production validation approval phrase required for future runtime validation: $NonProductionValidationApprovalPhrase"
    Write-Host "Non-production validation lock path for the future run: $NonProductionValidationLockPath"
    Write-Host "Local proxy routing validation approval phrase required for any future rerun: $ProxyValidationApprovalPhrase"
    Write-Host "Local proxy routing validation lock path used / required for future rerun: $ProxyValidationLockPath"
    Write-Host "Local proxy routing validation fixed parameters: project=$ProxyValidationComposeProjectName compose=$ProxyValidationUnifiedComposePath inactive_port=$ProxyValidationInactivePort proxy_port=$ProxyValidationProxyPort target=$ProxyValidationTargetService proxy=$ProxyValidationProxyService production_port_8000=not-used."
    Write-Host "Deployment lock is required for non-production runtime validation and any future runtime-changing production apply."
    Write-Host "Runtime-changing paths requiring the lock: container start, container stop, container restart, image build, migration, collectstatic, proxy switch, traffic switch, cleanup, production apply, and rollback."
    Write-Host "If a second deploy task sees an existing lock, it must block and exit non-zero. It must not auto-queue."
    Write-Host "Future runtime-changing scripts must release only the matching lock_id in cleanup/finally handling."
    Write-Host "Stale locks require manual review. Normal non-deploy tasks are not blocked."
    Write-Host "Proposed lock path: .deploy/deploy.lock"
    Write-Host "Current status: helper exists if listed above; safe_deploy dry-run reports lock state without acquiring it, -CheckDeployLock is read-only, real safe_deploy acquires/releases the lock, and production apply skeleton remains no-action."
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
    Write-Host "Local inactive-color startup plan status: reviewed local-only startup path; startup remains NO-GO by default."
    Write-Host "Local inactive-color startup runner status: exists if listed above; future executable path is gated and blocked by default."
    Write-Host "Required inactive startup approval phrase: $InactiveStartupApprovalPhrase"
    Write-Host "Future real local inactive startup also requires -AllowContainerAction."
    Write-Host "Local-test compose example: docker-compose.bluegreen.local-test.example.yml."
    Write-Host "Local inactive startup reuses the existing aftersales-web image and intentionally does not build images."
    Write-Host "If aftersales-web is missing, run a separate explicit image build/preparation task before startup."
    Write-Host "Any future inactive startup must use one inactive test service on a non-8000 local port and leave current web untouched."
    Write-Host "The future inactive service must not be the current active service name web."
    Write-Host "Production/runtime-changing blue-green scripts must acquire the deployment lock before any future container, build, migration, collectstatic, proxy switch, traffic switch, cleanup, apply, or rollback action."
    Write-Host "Future non-production runtime validation must also acquire the deployment lock before test-only runtime actions."
    Write-Host "Future non-production validation approval package path: .\docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION_APPROVAL.md."
    Write-Host "Non-production inactive runtime validation: $NonProductionInactiveRuntimeValidationStatus."
    Write-Host "Local/test proxy routing validation: $ProxyValidationStatus."
    Write-Host "Non-production validation chain: PASSED for inactive runtime plus local/test proxy routing."
    Write-Host "Production preflight: $ProductionPreflightStatus."
    Write-Host "Production preflight document exists: $(Test-Path -LiteralPath $ProductionPreflightPath)."
    Write-Host "Production apply readiness: $ProductionApplyReadinessStatus."
    Write-Host "Production apply readiness package exists: $(Test-Path -LiteralPath $ProductionReadinessPath)."
    Write-Host "Production command review: $ProductionCommandReviewStatus."
    Write-Host "Production command review document exists: $(Test-Path -LiteralPath $ProductionCommandReviewPath)."
    Write-Host "Production runtime details: $ProductionRuntimeDetailsStatus."
    Write-Host "Production runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath)."
    Write-Host "Production proxy/active-color/rollback details: conservative defaults documented."
    Write-Host "Production implementation: $ProductionCommandImplementationStatus."
    Write-Host "Production command path skeleton: $ProductionCommandPathSkeletonStatus."
    Write-Host "Production apply: $ProductionApplyStatus."
    Write-Host "Next step: $NextBlueGreenStep."
    Write-Host "Future non-production validation requires explicit approval phrase: $NonProductionValidationApprovalPhrase"
    Write-Host "Future non-production validation lock path: $NonProductionValidationLockPath"
    Write-Host "Future local proxy routing validation approval package path: .\docs\BLUE_GREEN_PROXY_LOCAL_VALIDATION_APPROVAL.md."
    Write-Host "Future local proxy routing validation rerun requires explicit approval phrase: $ProxyValidationApprovalPhrase"
    Write-Host "Future local proxy routing validation rerun lock path: $ProxyValidationLockPath"
    Write-Host "Completed local proxy routing validation used project $ProxyValidationComposeProjectName, compose $ProxyValidationUnifiedComposePath, target $ProxyValidationTargetService on $ProxyValidationInactivePort, and proxy $ProxyValidationProxyService on $ProxyValidationProxyPort."
    Write-Host "Completed local proxy routing validation used hold-open startup so $ProxyValidationTargetService remained available on $ProxyValidationInactivePort."
    Write-Host "After proxy validation, cleanup stopped only $ProxyValidationProxyService and $ProxyValidationTargetService."
    Write-Host "Production port 8000 was not used by the proxy validation."
    Write-Host "The unified proxy validation compose example kept $ProxyValidationProxyService and $ProxyValidationTargetService on the same Docker network for service discovery."
    Write-Host "An existing deployment lock must block the second deploy task; no automatic queue is allowed."
    Write-Host "Production command path skeleton path: .\scripts\blue_green_production_apply.ps1."
    Write-Host "Production command path skeleton: $ProductionCommandPathSkeletonStatus."
    Write-Host "Production command review document path: $ProductionCommandReviewPath."
    Write-Host "Non-production validation plan path: .\docs\BLUE_GREEN_NON_PRODUCTION_VALIDATION.md."
    Write-Host "Production preflight document path: $ProductionPreflightPath."
    Write-Host "Production apply readiness package path: $ProductionReadinessPath."
    Write-Host "Production apply remains blocked until exact runtime commands based on the documented defaults are implemented, reviewed, approved, and covered by manual approval."
    Write-Host "Production remains NO-GO."
    Write-Host ""
    Write-Host "This script does not call docker compose up, down, restart, build, run, exec, or migrate."
    Write-Host "This script does not modify files, switch traffic, call Shopify APIs, call Gmail APIs, or send email."
}

Show-GitStatus
Show-ComposeSummary -Path $ComposeFile
Show-ActiveComposeShape -Path $ComposeFile
Show-DraftArtifactSummary
Show-DeploymentLockStatus
Show-DecisionStatus
Test-HealthUrl -Url $HealthUrl
Show-FuturePlan

Write-Step "Result"
Write-Ok "Blue-green dry-run planner completed. No deploy action was performed."
Write-Ok "No runtime behavior was changed by this read-only planner."
Write-Ok "Deployment lock status: helper/doc/safe_deploy enforcement are checked above; dry-run still acquires no lock."
Write-Ok "Production command path skeleton: $ProductionCommandPathSkeletonStatus."
Write-Ok "Non-production inactive runtime validation: PASSED."
Write-Ok "Local/test proxy routing validation: PASSED."
Write-Ok "Non-production validation chain: PASSED for inactive runtime plus local/test proxy routing."
Write-Ok "Production preflight: $ProductionPreflightStatus."
Write-Ok "Production preflight document exists: $(Test-Path -LiteralPath $ProductionPreflightPath)."
Write-Ok "Production apply readiness: $ProductionApplyReadinessStatus."
Write-Ok "Production apply readiness package exists: $(Test-Path -LiteralPath $ProductionReadinessPath)."
Write-Ok "Production command review: $ProductionCommandReviewStatus."
Write-Ok "Production command review document exists: $(Test-Path -LiteralPath $ProductionCommandReviewPath)."
Write-Ok "Production runtime details: $ProductionRuntimeDetailsStatus."
Write-Ok "Production runtime details document exists: $(Test-Path -LiteralPath $ProductionRuntimeDetailsPath)."
Write-Ok "Production proxy/active-color/rollback details have conservative defaults."
Write-Ok "Production command path skeleton: $ProductionCommandPathSkeletonStatus."
Write-Ok "Production implementation: $ProductionCommandImplementationStatus."
Write-Ok "Proxy validation network fix: unified compose example was used for the passed local/test validation."
Write-Ok "Proxy validation hold-open mode: completed for the passed local/test validation."
Write-Ok "Local proxy routing validation approval package status: exists if reported above; passed result recorded and future reruns require explicit approval phrase and deployment lock."
Write-Ok "Production apply: NO-GO."
Write-Ok "Next step: $NextBlueGreenStep."
Write-Ok "Non-production validation approval package status: exists if reported above; future runtime validation requires explicit approval phrase and deployment lock."
Write-Ok "Production blue-green real apply remains NO-GO until a separate future phase approves exact runtime commands behind deployment lock gates."
Write-Ok "Inactive startup runner status: dry-run / no-action by default; future execution requires Ack plus -AllowContainerAction; test port 8000 and service web are blocked; production remains NO-GO."
Write-Ok "Simulation runner status: dry-run / no-action only; production remains NO-GO."
