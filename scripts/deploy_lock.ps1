[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("acquire", "release", "status", "validate")]
    [string]$Action,

    [string]$Purpose = "",
    [string]$Target = "",
    [string]$LockPath = ".deploy/deploy.lock",
    [string]$LockId = "",
    [int]$MaxAgeMinutes = 120,
    [switch]$ForceStaleRelease
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$DeployDirectory = [System.IO.Path]::GetFullPath((Join-Path -Path $ProjectRoot -ChildPath ".deploy"))

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

function Write-Blocked {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Protect-SensitiveText {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) {
        return ""
    }

    $sanitized = $Text
    $sanitized = $sanitized -replace '(?i)("(?:[^"]*(secret|token|api[_-]?key|password|passwd|pwd|credential|authorization)[^"]*)"\s*:\s*)("[^"]*"|[^,\s}]+)', '$1"<redacted>"'
    $sanitized = $sanitized -replace '(?i)(secret|token|api[_-]?key|password|passwd|pwd|credential|authorization|bearer)(\s*[:=]\s*)("?)\S+("?)', '$1$2$3<redacted>$4'
    $sanitized = $sanitized -replace '(?i)(--(?:secret|token|api-key|password|credential|authorization)\s+)\S+', '$1<redacted>'
    $sanitized = $sanitized -replace '(?i)(SHOPIFY|GMAIL|TRUSTPILOT|KUDOSI|ALI[_-]?REVIEWS|CLOUDFLARED|DATABASE|DJANGO_SECRET_KEY)([A-Z0-9_ -]*)(\s*[:=]\s*)("?)\S+("?)', '$1$2$3$4<redacted>$5'
    $sanitized = $sanitized -replace '(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', '$1 <redacted>'

    if ($sanitized.Length -gt 300) {
        $sanitized = $sanitized.Substring(0, 300) + " ... <truncated>"
    }

    return $sanitized
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

function Resolve-SafeLockPath {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "LockPath is required."
    }

    $candidate = $Path
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path -Path $ProjectRoot -ChildPath $candidate
    }

    $fullPath = [System.IO.Path]::GetFullPath($candidate)
    $fileName = [System.IO.Path]::GetFileName($fullPath)
    if ([string]::IsNullOrWhiteSpace($fileName)) {
        throw "LockPath must point to a lock file, not a directory."
    }

    if (-not (Test-PathInsideDirectory -Path $fullPath -Directory $DeployDirectory)) {
        throw "LockPath must stay inside the project .deploy directory."
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

function Get-MetadataValue {
    param(
        [object]$Metadata,
        [string]$Name
    )

    if ($null -eq $Metadata) {
        return ""
    }

    $property = $Metadata.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value) {
        return ""
    }

    return [string]$property.Value
}

function ConvertFrom-LockJson {
    param([string]$Json)

    if ([string]::IsNullOrWhiteSpace($Json)) {
        throw "Lock file is empty."
    }

    try {
        return ($Json | ConvertFrom-Json -ErrorAction Stop)
    } catch {
        throw "Lock file is not valid JSON: $($_.Exception.Message)"
    }
}

function Read-LockMetadata {
    param([string]$Path)

    $json = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    return ConvertFrom-LockJson -Json $json
}

function Read-LockMetadataExclusive {
    param([string]$Path)

    $stream = $null
    $reader = $null

    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
        $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
        $json = $reader.ReadToEnd()
        return ConvertFrom-LockJson -Json $json
    } finally {
        if ($null -ne $reader) {
            $reader.Dispose()
        } elseif ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Show-LockMetadata {
    param([object]$Metadata)

    $keys = @(
        "lock_id",
        "created_at",
        "user",
        "host",
        "process_id",
        "purpose",
        "target",
        "command",
        "max_age_minutes",
        "project_path"
    )

    foreach ($key in $keys) {
        $value = Get-MetadataValue -Metadata $Metadata -Name $key
        if ($value -ne "") {
            Write-Host ("  {0}: {1}" -f $key, (Protect-SensitiveText -Text $value))
        }
    }
}

function Show-StaleStatus {
    param(
        [object]$Metadata,
        [int]$ThresholdMinutes
    )

    $createdAt = Get-MetadataValue -Metadata $Metadata -Name "created_at"
    if ([string]::IsNullOrWhiteSpace($createdAt)) {
        Write-Warn "Stale check: lock has no created_at value."
        return
    }

    try {
        $created = [System.DateTimeOffset]::Parse($createdAt, [System.Globalization.CultureInfo]::InvariantCulture)
        $age = [System.DateTimeOffset]::UtcNow - $created.ToUniversalTime()
        $ageMinutes = [math]::Round($age.TotalMinutes, 1)
        Write-Host "Lock age minutes: $ageMinutes"

        if ($age.TotalMinutes -gt $ThresholdMinutes) {
            Write-Warn "Stale candidate: lock age is greater than MaxAgeMinutes ($ThresholdMinutes)."
            Write-Warn "This helper does not auto-delete stale locks. Review manually before any release."
        } else {
            Write-Ok "Stale check: lock is within MaxAgeMinutes ($ThresholdMinutes)."
        }
    } catch {
        Write-Warn "Stale check could not parse created_at: $($_.Exception.Message)"
    }
}

function New-LockMetadata {
    param(
        [string]$NewLockId,
        [string]$PurposeValue,
        [string]$TargetValue,
        [int]$MaxAge,
        [string]$ResolvedLockPath
    )

    return [ordered]@{
        lock_id = $NewLockId
        created_at = ([System.DateTimeOffset]::UtcNow.ToString("o"))
        user = (Protect-SensitiveText -Text ([System.Environment]::UserName))
        host = (Protect-SensitiveText -Text ([System.Environment]::MachineName))
        process_id = $PID
        purpose = (Protect-SensitiveText -Text $PurposeValue)
        target = (Protect-SensitiveText -Text $TargetValue)
        command = (Protect-SensitiveText -Text ([System.Environment]::CommandLine))
        max_age_minutes = $MaxAge
        project_path = (Protect-SensitiveText -Text $ProjectRoot)
        lock_path = (Get-RelativeProjectPath -Path $ResolvedLockPath)
    }
}

function Write-LockFileAtomic {
    param(
        [string]$Path,
        [object]$Metadata
    )

    $stream = $null
    $writer = $null
    $json = $Metadata | ConvertTo-Json -Depth 5
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)

    try {
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        $writer = New-Object System.IO.StreamWriter($stream, $utf8NoBom)
        $writer.WriteLine($json)
    } finally {
        if ($null -ne $writer) {
            $writer.Dispose()
        } elseif ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Invoke-Status {
    param([string]$ResolvedLockPath)

    Write-Step "Deployment lock status"
    Write-Host "Lock path: $(Get-RelativeProjectPath -Path $ResolvedLockPath)"
    Write-Host "Resolved lock path: $ResolvedLockPath"

    if (-not (Test-Path -LiteralPath $ResolvedLockPath -PathType Leaf)) {
        Write-Ok "Lock exists: false"
        return 0
    }

    Write-Warn "Lock exists: true"

    try {
        $metadata = Read-LockMetadata -Path $ResolvedLockPath
        Show-LockMetadata -Metadata $metadata
        Show-StaleStatus -Metadata $metadata -ThresholdMinutes $MaxAgeMinutes
    } catch {
        Write-Warn "Could not parse lock metadata: $($_.Exception.Message)"
    }

    return 0
}

function Invoke-Validate {
    param([string]$ResolvedLockPath)

    Write-Step "Deployment lock validation"
    Write-Host "Project path: $ProjectRoot"
    Write-Host "Allowed lock directory: $DeployDirectory"
    Write-Host "Lock path: $(Get-RelativeProjectPath -Path $ResolvedLockPath)"
    Write-Host "Resolved lock path: $ResolvedLockPath"

    if ($MaxAgeMinutes -le 0) {
        Write-Blocked "MaxAgeMinutes must be greater than zero."
        return 1
    }

    if (-not (Test-PathInsideDirectory -Path $ResolvedLockPath -Directory $DeployDirectory)) {
        Write-Blocked "Lock path is outside .deploy."
        return 1
    }

    Write-Ok "Lock directory safety check passed."

    if (-not (Test-Path -LiteralPath $ResolvedLockPath -PathType Leaf)) {
        Write-Ok "No existing lock file to parse."
        return 0
    }

    try {
        $metadata = Read-LockMetadata -Path $ResolvedLockPath
        Write-Ok "Existing lock JSON parsed successfully."
        Show-LockMetadata -Metadata $metadata
        Show-StaleStatus -Metadata $metadata -ThresholdMinutes $MaxAgeMinutes
        return 0
    } catch {
        Write-Blocked "Existing lock validation failed: $($_.Exception.Message)"
        return 1
    }
}

function Invoke-Acquire {
    param([string]$ResolvedLockPath)

    Write-Step "Acquire deployment lock"
    Write-Host "Lock path: $(Get-RelativeProjectPath -Path $ResolvedLockPath)"

    if ($ForceStaleRelease) {
        Write-Warn "ForceStaleRelease was supplied, but this helper does not delete stale locks."
        Write-Warn "Acquire will still block if the lock already exists."
    }

    $parentDirectory = [System.IO.Path]::GetDirectoryName($ResolvedLockPath)
    [System.IO.Directory]::CreateDirectory($parentDirectory) | Out-Null

    $newLockId = $LockId
    if ([string]::IsNullOrWhiteSpace($newLockId)) {
        $newLockId = [guid]::NewGuid().ToString()
    }

    $metadata = New-LockMetadata -NewLockId $newLockId -PurposeValue $Purpose -TargetValue $Target -MaxAge $MaxAgeMinutes -ResolvedLockPath $ResolvedLockPath

    try {
        Write-LockFileAtomic -Path $ResolvedLockPath -Metadata $metadata
        Write-Ok "Lock acquired."
        Write-Host "lock_id: $newLockId"
        Write-Host "Release command requires this exact LockId."
        return 0
    } catch [System.IO.IOException] {
        if (Test-Path -LiteralPath $ResolvedLockPath -PathType Leaf) {
            Write-Blocked "Lock acquisition blocked because the lock file already exists."
            try {
                $existing = Read-LockMetadata -Path $ResolvedLockPath
                Show-LockMetadata -Metadata $existing
                Show-StaleStatus -Metadata $existing -ThresholdMinutes $MaxAgeMinutes
            } catch {
                Write-Warn "Existing lock metadata could not be parsed: $($_.Exception.Message)"
            }
            return 2
        }

        Write-Blocked "Lock acquisition failed: $($_.Exception.Message)"
        return 1
    } catch {
        Write-Blocked "Lock acquisition failed: $($_.Exception.Message)"
        return 1
    }
}

function Invoke-Release {
    param([string]$ResolvedLockPath)

    Write-Step "Release deployment lock"
    Write-Host "Lock path: $(Get-RelativeProjectPath -Path $ResolvedLockPath)"

    if ($ForceStaleRelease) {
        Write-Warn "ForceStaleRelease was supplied, but stale deletion is not implemented in this helper."
        Write-Warn "Release still requires an exact LockId match."
    }

    if ([string]::IsNullOrWhiteSpace($LockId)) {
        Write-Blocked "Release blocked because -LockId is required."
        return 2
    }

    if (-not (Test-Path -LiteralPath $ResolvedLockPath -PathType Leaf)) {
        Write-Blocked "Release blocked because no lock file exists."
        return 2
    }

    try {
        $metadata = Read-LockMetadataExclusive -Path $ResolvedLockPath
        $currentLockId = Get-MetadataValue -Metadata $metadata -Name "lock_id"

        if ($currentLockId -ne $LockId) {
            Write-Blocked "Release blocked because LockId does not match the current lock."
            Write-Host "Current lock metadata:"
            Show-LockMetadata -Metadata $metadata
            return 2
        }
    } catch {
        Write-Blocked "Release blocked because the lock could not be read safely: $($_.Exception.Message)"
        return 2
    }

    Remove-Item -LiteralPath $ResolvedLockPath -Force
    Write-Ok "Lock released."
    return 0
}

try {
    $ResolvedLockPath = Resolve-SafeLockPath -Path $LockPath
} catch {
    Write-Blocked "Invalid lock path: $($_.Exception.Message)"
    exit 1
}

if ($ForceStaleRelease -and $Action -notin @("acquire", "release", "status", "validate")) {
    Write-Warn "ForceStaleRelease is accepted only for recognized actions."
}

switch ($Action) {
    "acquire" { exit (Invoke-Acquire -ResolvedLockPath $ResolvedLockPath) }
    "release" { exit (Invoke-Release -ResolvedLockPath $ResolvedLockPath) }
    "status" { exit (Invoke-Status -ResolvedLockPath $ResolvedLockPath) }
    "validate" { exit (Invoke-Validate -ResolvedLockPath $ResolvedLockPath) }
    default {
        Write-Blocked "Unknown action: $Action"
        exit 1
    }
}
