[CmdletBinding()]
param(
    [ValidateSet("status", "validate-state", "plan-switch", "plan-rollback", "plan-cleanup")]
    [string]$Action = "status",
    [string]$ActiveColor = "",
    [string]$TargetColor = "",
    [string]$PreviousColor = "",
    [string]$DeployId = "",
    [string]$ProxyConfigPath = "",
    [string]$ActiveColorStatePath = ".deploy/active-color.json",
    [string]$DeployLockPath = ".deploy/deploy.lock",
    [string]$Ack = "",
    [switch]$Execute,
    [switch]$Apply,
    [switch]$RealRun,
    [switch]$ExecuteRuntimeCommands,
    [switch]$AllowRuntimeAction,
    [switch]$AllowProxyReload,
    [switch]$AllowTrafficSwitch,
    [switch]$AllowStateWrite,
    [switch]$ReloadProxy,
    [switch]$SwitchTraffic,
    [switch]$WriteActiveColorState
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RuntimeApprovalPhrase = "I_APPROVE_ENABLE_BLUE_GREEN_RUNTIME_COMMANDS_AFTER_FINAL_REVIEW"
$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DeployDirectory = [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath ".deploy"))
$RuntimeHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "blue_green_runtime_commands.ps1"
$ProductionApplyPath = Join-Path -Path $PSScriptRoot -ChildPath "blue_green_production_apply.ps1"
$DeployLockHelperPath = Join-Path -Path $PSScriptRoot -ChildPath "deploy_lock.ps1"
$FinalRuntimeApprovalPath = Join-Path -Path $ProjectRoot -ChildPath "docs\BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md"
$Script:InitialBoundParameters = @{}
foreach ($key in $PSBoundParameters.Keys) {
    $Script:InitialBoundParameters[$key] = $PSBoundParameters[$key]
}

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

function Get-RelativeProjectPath {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath.StartsWith($ProjectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $fullPath.Substring($ProjectRoot.Length).TrimStart("\", "/")
    }

    return $fullPath
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

function Resolve-ProjectPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "Path value is required."
    }

    $candidate = $Path
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path -Path $ProjectRoot -ChildPath $candidate
    }

    return [System.IO.Path]::GetFullPath($candidate)
}

function Resolve-ActiveColorStatePath {
    param([string]$Path)

    $fullPath = Resolve-ProjectPath -Path $Path
    $fileName = [System.IO.Path]::GetFileName($fullPath)
    if ([string]::IsNullOrWhiteSpace($fileName)) {
        throw "ActiveColorStatePath must point to a file under .deploy/."
    }

    if (-not (Test-PathInsideDirectory -Path $fullPath -Directory $DeployDirectory)) {
        throw "ActiveColorStatePath must stay inside the project .deploy directory."
    }

    return $fullPath
}

function Resolve-DeployLockPath {
    param([string]$Path)

    $fullPath = Resolve-ProjectPath -Path $Path
    $fileName = [System.IO.Path]::GetFileName($fullPath)
    if ([string]::IsNullOrWhiteSpace($fileName)) {
        throw "DeployLockPath must point to a lock file under .deploy/."
    }

    if (-not (Test-PathInsideDirectory -Path $fullPath -Directory $DeployDirectory)) {
        throw "DeployLockPath must stay inside the project .deploy directory."
    }

    return $fullPath
}

function Test-ColorValue {
    param(
        [string]$Name,
        [string]$Value,
        [bool]$Required
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        if ($Required) {
            throw "$Name is required and must be blue or green."
        }

        return ""
    }

    $normalized = $Value.Trim().ToLowerInvariant()
    if (($normalized -ne "blue") -and ($normalized -ne "green")) {
        throw "$Name must be blue or green."
    }

    return $normalized
}

function Test-FutureExecutionFlags {
    $blockedNames = @(
        "Execute",
        "Apply",
        "RealRun",
        "ExecuteRuntimeCommands",
        "AllowRuntimeAction",
        "AllowProxyReload",
        "AllowTrafficSwitch",
        "AllowStateWrite",
        "ReloadProxy",
        "SwitchTraffic",
        "WriteActiveColorState"
    )

    foreach ($name in $blockedNames) {
        if ($Script:InitialBoundParameters.ContainsKey($name)) {
            $value = $Script:InitialBoundParameters[$name]
            if (($value -is [System.Management.Automation.SwitchParameter] -and $value.IsPresent) -or ($value -eq $true)) {
                throw "Future execution parameter -$name is blocked. This helper is plan-only and no runtime execution is enabled."
            }
        }
    }
}

function Format-OptionalValue {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "<not provided>"
    }

    return $Value
}

function Get-SafeStateValue {
    param(
        [string]$Name,
        [object]$Value
    )

    if ($null -eq $Value) {
        return "<null>"
    }

    $text = ""
    if ($Value -is [string]) {
        $text = $Value
    } elseif ($Value -is [int] -or $Value -is [long] -or $Value -is [bool] -or $Value -is [datetime]) {
        $text = [string]$Value
    } else {
        $text = "<non-scalar value omitted>"
    }

    if ($Name -match "(?i)(secret|token|key|password|credential|private)" -or $text -match "(?i)(secret|token|password|credential|BEGIN [A-Z ]*PRIVATE KEY)") {
        return "<redacted>"
    }

    if ($text.Length -gt 160) {
        return $text.Substring(0, 160) + "...<truncated>"
    }

    return $text
}

function Show-SanitizedActiveColorState {
    param([string]$ResolvedStatePath)

    Write-Step "Active-color state"
    Write-Host "Active-color state path: $(Get-RelativeProjectPath -Path $ResolvedStatePath)"
    Write-Host "Resolved active-color state path: $ResolvedStatePath"
    Write-Host "State file exists: $(Test-Path -LiteralPath $ResolvedStatePath -PathType Leaf)"

    if (-not (Test-Path -LiteralPath $ResolvedStatePath -PathType Leaf)) {
        Write-Host "Sanitized state content: <state file not present>"
        return
    }

    $raw = Get-Content -LiteralPath $ResolvedStatePath -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Write-Host "Sanitized state content: <empty file>"
        return
    }

    try {
        $state = $raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-Warn "State file is present but is not valid JSON. Raw content was not printed."
        return
    }

    $allowedKeys = @(
        "active_color",
        "previous_color",
        "updated_at",
        "updated_by",
        "deploy_id",
        "proxy_config_version",
        "notes"
    )

    $properties = @($state.PSObject.Properties)
    if ($properties.Count -eq 0) {
        Write-Host "Sanitized state content: <no properties>"
        return
    }

    Write-Host "Sanitized state content:"
    foreach ($property in $properties) {
        if ($allowedKeys -contains $property.Name) {
            Write-Host ("  {0}: {1}" -f $property.Name, (Get-SafeStateValue -Name $property.Name -Value $property.Value))
        } else {
            Write-Host ("  {0}: <redacted or ignored future field>" -f $property.Name)
        }
    }
}

function Show-AvailableActions {
    Write-Step "Available future command plans"
    Write-Host "This helper is blocked/no-action by default. These actions only print status or plans:"
    Write-Host "  -Action status"
    Write-Host "  -Action validate-state"
    Write-Host "  -Action plan-switch"
    Write-Host "  -Action plan-rollback"
    Write-Host "  -Action plan-cleanup"
    Write-Host "Final runtime approval doc exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
    Write-Host "Future approval phrase documented but inactive: $RuntimeApprovalPhrase"
    Write-Host "Ack supplied: $(-not [string]::IsNullOrWhiteSpace($Ack))"
    Write-Host "Ack matches inactive future phrase: $($Ack -eq $RuntimeApprovalPhrase)"
    Write-Host "Runtime execution remains disabled."
    Write-Host "Even a matching Ack does not enable proxy reload, traffic switch, rollback execution, or active-color state writes in this phase."
}

function Show-FinalRuntimeApprovalStatus {
    Write-Step "Final runtime approval status"
    Write-Host "Final runtime approval doc exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
    Write-Host "Final runtime approval doc path: docs\BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md"
    Write-Host "Runtime command execution: NOT ENABLED"
    Write-Host "Future approval phrase documented but inactive: $RuntimeApprovalPhrase"
    Write-Host "Production apply remains: NO-GO"
}

function Show-Status {
    param(
        [string]$ResolvedStatePath,
        [string]$ResolvedDeployLockPath
    )

    Write-Step "Blue-green runtime command helper status"
    Write-Host "Script path: scripts\blue_green_runtime_commands.ps1"
    Write-Host "Mode: plan-only / no-action"
    Write-Host "Action: $Action"
    Write-Host "Runtime helper exists: $(Test-Path -LiteralPath $RuntimeHelperPath -PathType Leaf)"
    Write-Host "Production apply skeleton exists: $(Test-Path -LiteralPath $ProductionApplyPath -PathType Leaf)"
    Write-Host "Deployment lock helper exists: $(Test-Path -LiteralPath $DeployLockHelperPath -PathType Leaf)"
    Write-Host "Deploy lock path: $(Get-RelativeProjectPath -Path $ResolvedDeployLockPath)"
    Write-Host "Resolved deploy lock path: $ResolvedDeployLockPath"
    Write-Host "Proxy config path: $(Format-OptionalValue -Value $ProxyConfigPath)"
    Write-Host "Production apply remains: NO-GO"
    Write-Host "Proxy switch execution: NOT ENABLED"
    Write-Host "Proxy reload execution: NOT ENABLED"
    Write-Host "Active-color state write: NOT ENABLED"
    Write-Host "Rollback execution: NOT ENABLED"
    Write-Host "Container start/stop/restart/build: NOT ENABLED"
    Write-Host "Migration/collectstatic: NOT ENABLED"
    Write-Host "Final runtime approval doc exists: $(Test-Path -LiteralPath $FinalRuntimeApprovalPath -PathType Leaf)"
    Write-Host "Future approval phrase documented but inactive: $RuntimeApprovalPhrase"

    Write-Step "Document status"
    $docs = @(
        "docs\BLUE_GREEN_FINAL_RUNTIME_APPROVAL.md",
        "docs\BLUE_GREEN_PRODUCTION_SWITCH_ROLLBACK_REVIEW.md",
        "docs\BLUE_GREEN_PRODUCTION_RUNTIME_DETAILS.md",
        "docs\BLUE_GREEN_PRODUCTION_COMMAND_REVIEW.md",
        "docs\BLUE_GREEN_PRODUCTION_APPLY_READINESS.md",
        "docs\BLUE_GREEN_PRODUCTION_PREFLIGHT.md",
        "docs\BLUE_GREEN_DEPLOY_PLAN.md",
        "docs\BLUE_GREEN_DEPLOY_APPLY_CHECKLIST.md",
        "docs\DEPLOYMENT_LOCK.md",
        "docs\SAFE_DEPLOY.md"
    )

    foreach ($doc in $docs) {
        $path = Join-Path -Path $ProjectRoot -ChildPath $doc
        Write-Host "$doc exists: $(Test-Path -LiteralPath $path -PathType Leaf)"
    }

    Show-SanitizedActiveColorState -ResolvedStatePath $ResolvedStatePath
    Show-AvailableActions
}

function Show-StateValidation {
    param(
        [string]$ResolvedStatePath,
        [string]$ResolvedDeployLockPath
    )

    $normalizedActiveColor = Test-ColorValue -Name "ActiveColor" -Value $ActiveColor -Required:$false
    $normalizedTargetColor = Test-ColorValue -Name "TargetColor" -Value $TargetColor -Required:$false
    $normalizedPreviousColor = Test-ColorValue -Name "PreviousColor" -Value $PreviousColor -Required:$false

    if ((-not [string]::IsNullOrWhiteSpace($normalizedActiveColor)) -and
        (-not [string]::IsNullOrWhiteSpace($normalizedTargetColor)) -and
        ($normalizedActiveColor -eq $normalizedTargetColor)) {
        throw "TargetColor must be different from ActiveColor."
    }

    Write-Step "State validation"
    Write-Ok "ActiveColorStatePath is constrained under .deploy/: $(Get-RelativeProjectPath -Path $ResolvedStatePath)"
    Write-Ok "DeployLockPath is constrained under .deploy/: $(Get-RelativeProjectPath -Path $ResolvedDeployLockPath)"
    Write-Host "ActiveColor: $(Format-OptionalValue -Value $normalizedActiveColor)"
    Write-Host "TargetColor: $(Format-OptionalValue -Value $normalizedTargetColor)"
    Write-Host "PreviousColor: $(Format-OptionalValue -Value $normalizedPreviousColor)"
    Write-Host "DeployId: $(Format-OptionalValue -Value $DeployId)"
    Write-Host "ProxyConfigPath: $(Format-OptionalValue -Value $ProxyConfigPath)"
    Write-Host "No files were modified."
    Write-Host "No proxy reload, traffic switch, rollback, container action, migration, collectstatic, or active-color state write was performed."
    Show-FinalRuntimeApprovalStatus
    Write-Host "Production apply remains NO-GO."
}

function Show-PlanSwitch {
    param(
        [string]$ResolvedStatePath,
        [string]$ResolvedDeployLockPath
    )

    Show-StateValidation -ResolvedStatePath $ResolvedStatePath -ResolvedDeployLockPath $ResolvedDeployLockPath

    Write-Step "Future proxy switch plan (NOT RUN)"
    Write-Host "NOT RUN: acquire deployment lock at $(Get-RelativeProjectPath -Path $ResolvedDeployLockPath)."
    Write-Host "NOT RUN: validate target health for TargetColor=$(Format-OptionalValue -Value $TargetColor)."
    Write-Host "NOT RUN: validate proxy config at ProxyConfigPath=$(Format-OptionalValue -Value $ProxyConfigPath)."
    Write-Host "NOT RUN: switch/reload proxy from ActiveColor=$(Format-OptionalValue -Value $ActiveColor) to TargetColor=$(Format-OptionalValue -Value $TargetColor)."
    Write-Host "NOT RUN: post-switch health check through the production routing path."
    Write-Host "NOT RUN: atomic active-color state write to $(Get-RelativeProjectPath -Path $ResolvedStatePath)."
    Write-Host "Proxy switch execution: NOT ENABLED."
    Write-Host "Proxy reload execution: NOT ENABLED."
    Write-Host "Active-color state write: NOT ENABLED."
    Write-Host "Runtime execution remains disabled."
    Write-Host "Final approval phrase documented but inactive: $RuntimeApprovalPhrase"
    Write-Host "Production apply remains NO-GO."
}

function Show-PlanRollback {
    param(
        [string]$ResolvedStatePath,
        [string]$ResolvedDeployLockPath
    )

    Show-StateValidation -ResolvedStatePath $ResolvedStatePath -ResolvedDeployLockPath $ResolvedDeployLockPath

    Write-Step "Future rollback plan (NOT RUN)"
    Write-Host "NOT RUN: acquire deployment lock at $(Get-RelativeProjectPath -Path $ResolvedDeployLockPath)."
    Write-Host "NOT RUN: switch proxy back to PreviousColor=$(Format-OptionalValue -Value $PreviousColor)."
    Write-Host "NOT RUN: post-rollback health check through the production routing path."
    Write-Host "NOT RUN: atomic active-color state write after rollback health passes to $(Get-RelativeProjectPath -Path $ResolvedStatePath)."
    Write-Host "Rollback execution: NOT ENABLED."
    Write-Host "Proxy reload execution: NOT ENABLED."
    Write-Host "Active-color state write: NOT ENABLED."
    Write-Host "No database rollback is enabled by this helper."
    Write-Host "Runtime execution remains disabled."
    Write-Host "Final approval phrase documented but inactive: $RuntimeApprovalPhrase"
    Write-Host "Production apply remains NO-GO."
}

function Show-PlanCleanup {
    param([string]$ResolvedDeployLockPath)

    Write-Step "Future cleanup plan (NOT RUN)"
    Write-Host "NOT RUN: cleanup only after the approved observation window passes."
    Write-Host "NOT RUN: acquire deployment lock at $(Get-RelativeProjectPath -Path $ResolvedDeployLockPath) before runtime-changing cleanup."
    Write-Host "NOT RUN: do not remove database volumes."
    Write-Host "NOT RUN: do not remove media or upload volumes."
    Write-Host "NOT RUN: do not stop scheduler unexpectedly."
    Write-Host "NOT RUN: do not remove rollback-required runtime state."
    Write-Host "Cleanup execution: NOT ENABLED."
    Write-Host "Container stop/removal execution: NOT ENABLED."
    Show-FinalRuntimeApprovalStatus
    Write-Host "Production apply remains NO-GO."
}

function Show-BlockedResult {
    param(
        [string]$Message,
        [int]$Code
    )

    Write-Step "Result"
    Write-Fail $Message
    Write-Fail "No runtime action was performed."
    Write-Fail "This helper is plan-only / no-action by default."
    Write-Fail "Proxy switch/reload execution is NOT ENABLED."
    Write-Fail "Active-color state write is NOT ENABLED."
    Write-Fail "Rollback execution is NOT ENABLED."
    Write-Fail "Production apply remains NO-GO."
    exit $Code
}

try {
    Test-FutureExecutionFlags
    $resolvedStatePath = Resolve-ActiveColorStatePath -Path $ActiveColorStatePath
    $resolvedDeployLockPath = Resolve-DeployLockPath -Path $DeployLockPath
    $globalActiveColor = Test-ColorValue -Name "ActiveColor" -Value $ActiveColor -Required:$false
    $globalTargetColor = Test-ColorValue -Name "TargetColor" -Value $TargetColor -Required:$false
    $null = Test-ColorValue -Name "PreviousColor" -Value $PreviousColor -Required:$false
    if ((-not [string]::IsNullOrWhiteSpace($globalActiveColor)) -and
        (-not [string]::IsNullOrWhiteSpace($globalTargetColor)) -and
        ($globalActiveColor -eq $globalTargetColor)) {
        throw "TargetColor must be different from ActiveColor."
    }

    switch ($Action) {
        "status" {
            Show-Status -ResolvedStatePath $resolvedStatePath -ResolvedDeployLockPath $resolvedDeployLockPath
        }
        "validate-state" {
            Show-StateValidation -ResolvedStatePath $resolvedStatePath -ResolvedDeployLockPath $resolvedDeployLockPath
        }
        "plan-switch" {
            Show-PlanSwitch -ResolvedStatePath $resolvedStatePath -ResolvedDeployLockPath $resolvedDeployLockPath
        }
        "plan-rollback" {
            Show-PlanRollback -ResolvedStatePath $resolvedStatePath -ResolvedDeployLockPath $resolvedDeployLockPath
        }
        "plan-cleanup" {
            Show-PlanCleanup -ResolvedDeployLockPath $resolvedDeployLockPath
        }
    }

    Write-Step "Result"
    Write-Ok "Runtime helper completed in plan-only mode. No runtime action was performed."
    Write-Ok "Production apply remains NO-GO."
    exit 0
} catch {
    Show-BlockedResult -Message $_.Exception.Message -Code 10
}
