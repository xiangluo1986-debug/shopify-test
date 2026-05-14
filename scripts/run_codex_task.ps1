[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TaskFile,

    [string]$ProjectRoot = (Get-Location).Path,

    [string]$Sandbox = "workspace-write",

    [string]$CodexCmd = "C:\Users\xiang\AppData\Roaming\npm\codex.cmd",

    [string]$Model = "",

    [switch]$DryRun,

    [switch]$Notify
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-RequiredPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name not found: $Path"
    }

    return (Resolve-Path -LiteralPath $Path).ProviderPath
}

function Resolve-TaskPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$BasePath
    )

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return Resolve-RequiredPath -Path $Path -Name "TaskFile"
    }

    $projectRelative = Join-Path -Path $BasePath -ChildPath $Path
    if (Test-Path -LiteralPath $projectRelative) {
        return Resolve-RequiredPath -Path $projectRelative -Name "TaskFile"
    }

    return Resolve-RequiredPath -Path $Path -Name "TaskFile"
}

function Invoke-GitLines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & git -C $Root @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $joinedOutput = ($output | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
        throw "git $($Arguments -join ' ') failed:$([Environment]::NewLine)$joinedOutput"
    }

    if ($null -eq $output) {
        return @()
    }

    return @($output | ForEach-Object { $_.ToString() })
}

function Get-SafeCount {
    param(
        [AllowNull()]
        [object]$Value
    )

    if ($null -eq $Value) {
        return 0
    }

    return @($Value).Count
}

function Save-Lines {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [AllowNull()]
        [object[]]$Lines
    )

    if ((Get-SafeCount -Value $Lines) -eq 0) {
        Set-Content -LiteralPath $Path -Value "" -Encoding UTF8
        return
    }

    Set-Content -LiteralPath $Path -Value @($Lines) -Encoding UTF8
}

function Get-SafeRunTaskName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TaskFilePath
    )

    try {
        $stem = [System.IO.Path]::GetFileNameWithoutExtension($TaskFilePath)
        if ([string]::IsNullOrWhiteSpace($stem)) {
            return ""
        }

        $safeName = $stem.Trim()
        $safeName = $safeName -replace '[^A-Za-z0-9._-]', '_'
        $safeName = $safeName -replace '_+', '_'
        $safeName = $safeName.Trim("._-".ToCharArray())

        if ($safeName.Length -gt 80) {
            $safeName = $safeName.Substring(0, 80).Trim("._-".ToCharArray())
        }

        if ([string]::IsNullOrWhiteSpace($safeName)) {
            return ""
        }

        if ($safeName -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])$') {
            return ""
        }

        return $safeName
    } catch {
        return ""
    }
}

function Write-RunOutputCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RunDirectory
    )

    Write-Host ""
    Write-Host "Run output command:"
    Write-Host ('$run = "{0}"' -f $RunDirectory)
    Write-Host 'Get-Content "$run\last_message.txt" -Raw'
    Write-Host 'Get-Content "$run\safety_warnings.txt" -Raw'
    Write-Host 'Get-Content "$run\changed_files_after.txt" -Raw'
    Write-Host 'Get-Content "$run\staged_files_after.txt" -Raw'
    Write-Host 'git status --short --branch'
    Write-Host 'git diff --cached --name-only'
}

function Test-TextFileHasContent {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }

    $content = [System.IO.File]::ReadAllText($Path)
    return -not [string]::IsNullOrWhiteSpace($content)
}

function Write-LastMessageFallback {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$FullOutputPath,

        [Parameter(Mandatory = $true)]
        [int]$ExitCode
    )

    $fallback = @(
        "codex exec did not create a non-empty final report.",
        "Exit code: $ExitCode",
        "Review full output: $FullOutputPath",
        "Review git status and safety warning files in the same run directory."
    )

    Set-Content -LiteralPath $Path -Value $fallback -Encoding UTF8
}

function Invoke-CompletionSound {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Warning
    )

    if (-not $Notify) {
        return
    }

    try {
        if ($Warning) {
            [console]::beep(392, 160)
            [console]::beep(330, 220)
            return
        }

        [console]::beep(523, 100)
        [console]::beep(659, 100)
        [console]::beep(784, 140)
    } catch {
        Write-Verbose "Completion sound could not be played: $($_.Exception.Message)"
    }
}

function Get-StatusPaths {
    param(
        [AllowNull()]
        [string[]]$StatusLines
    )

    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($line in @($StatusLines)) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.Length -lt 4) {
            continue
        }

        $path = $line.Substring(3).Trim()
        if ($path -like "* -> *") {
            $path = ($path -split " -> ")[-1].Trim()
        }

        $path = $path.Trim('"')
        if (-not [string]::IsNullOrWhiteSpace($path)) {
            $paths.Add($path)
        }
    }

    return @($paths)
}

function New-SafetyWarnings {
    param(
        [AllowNull()]
        [string[]]$ChangedFiles,

        [AllowNull()]
        [string[]]$StagedFiles
    )

    $warnings = New-Object System.Collections.Generic.List[string]

    if ((Get-SafeCount -Value $StagedFiles) -gt 0) {
        $warnings.Add("WARNING: staged area is not empty. Review staged_files_after.txt before continuing.")
    }

    foreach ($path in @($ChangedFiles)) {
        if ([string]::IsNullOrWhiteSpace($path)) {
            continue
        }

        $normalized = ($path -replace "\\", "/").Trim()
        $leaf = Split-Path -Path $normalized -Leaf

        if ($normalized -eq "logs" -or $normalized -eq "logs/" -or ($normalized -like "logs/*" -and $normalized -notlike "logs/codex_runs/*")) {
            $warnings.Add("WARNING: changed path is under logs/ outside logs/codex_runs/: $normalized")
        }

        if ($leaf -eq ".env" -or $leaf -like ".env.*") {
            $warnings.Add("WARNING: changed path looks like an environment file: $normalized")
        }

        if ($normalized -eq ".codex/config.toml") {
            $warnings.Add("WARNING: changed path is forbidden config: $normalized")
        }

        if ($normalized -like "backend/logs/*") {
            $warnings.Add("WARNING: changed path is under backend/logs/: $normalized")
        }

        if ($normalized -like "backend/reviews/*") {
            $warnings.Add("WARNING: changed path is under backend/reviews/: $normalized")
        }

        if ($normalized -match "(?i)(secret|token|credential|key)") {
            $warnings.Add("WARNING: changed path contains a secret-risk word: $normalized")
        }
    }

    if ((Get-SafeCount -Value $warnings) -eq 0) {
        $warnings.Add("No safety warnings detected.")
    }

    return @($warnings)
}

function Format-CommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $parts = @($Executable) + $Arguments
    return (($parts | ForEach-Object {
        if ($_ -match '\s') {
            '"' + ($_ -replace '"', '\"') + '"'
        } else {
            $_
        }
    }) -join " ")
}

function ConvertTo-ProcessArgument {
    param(
        [AllowNull()]
        [string]$Argument
    )

    if ($null -eq $Argument -or $Argument.Length -eq 0) {
        return '""'
    }

    if ($Argument -notmatch '[\s"&|<>()^]') {
        return $Argument
    }

    $builder = New-Object System.Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0

    foreach ($char in $Argument.ToCharArray()) {
        if ($char -eq [char]92) {
            $backslashes += 1
            continue
        }

        if ($char -eq [char]34) {
            if ($backslashes -gt 0) {
                [void]$builder.Append(('\' * ($backslashes * 2)))
                $backslashes = 0
            }

            [void]$builder.Append('\"')
            continue
        }

        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }

        [void]$builder.Append($char)
    }

    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }

    [void]$builder.Append('"')
    return $builder.ToString()
}

function Join-ProcessArguments {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    return (($Arguments | ForEach-Object { ConvertTo-ProcessArgument -Argument $_ }) -join " ")
}

function Invoke-CodexProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,

        [Parameter(Mandatory = $true)]
        [string]$InputText,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $extension = [System.IO.Path]::GetExtension($Executable)

    if ($extension -in @(".bat", ".cmd")) {
        if ([string]::IsNullOrWhiteSpace($env:ComSpec)) {
            $startInfo.FileName = "cmd.exe"
        } else {
            $startInfo.FileName = $env:ComSpec
        }

        $startInfo.Arguments = "/d /c " + (Join-ProcessArguments -Arguments (@($Executable) + $Arguments))
    } else {
        $startInfo.FileName = $Executable
        $startInfo.Arguments = Join-ProcessArguments -Arguments $Arguments
    }

    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $startInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $startInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    $inputError = $null

    try {
        [void]$process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()

        try {
            $inputBytes = [System.Text.Encoding]::UTF8.GetBytes($InputText)
            $process.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
            $process.StandardInput.BaseStream.Flush()
        } catch {
            $inputError = $_.Exception
        } finally {
            $process.StandardInput.Close()
        }

        $process.WaitForExit()
        $stdout = $stdoutTask.Result
        $stderr = $stderrTask.Result

        $outputParts = New-Object System.Collections.Generic.List[string]
        if (-not [string]::IsNullOrEmpty($stdout)) {
            $outputParts.Add($stdout.TrimEnd())
        }

        if (-not [string]::IsNullOrEmpty($stderr)) {
            $outputParts.Add($stderr.TrimEnd())
        }

        if ($null -ne $inputError) {
            $outputParts.Add("ERROR: failed to write prompt to codex stdin: $($inputError.Message)")
        }

        $combinedOutput = ($outputParts.ToArray() -join [Environment]::NewLine)
        if ($combinedOutput.Length -gt 0) {
            $combinedOutput += [Environment]::NewLine
        }

        [System.IO.File]::WriteAllText($OutputPath, $combinedOutput, [System.Text.Encoding]::UTF8)

        if (-not [string]::IsNullOrWhiteSpace($stdout)) {
            Write-Host $stdout.TrimEnd()
        }

        if (-not [string]::IsNullOrWhiteSpace($stderr)) {
            Write-Host $stderr.TrimEnd()
        }

        if ($null -ne $inputError -and $process.ExitCode -eq 0) {
            return 1
        }

        return $process.ExitCode
    } finally {
        $process.Dispose()
    }
}

$resolvedProjectRoot = Resolve-RequiredPath -Path $ProjectRoot -Name "ProjectRoot"
$resolvedTaskFile = Resolve-TaskPath -Path $TaskFile -BasePath $resolvedProjectRoot
$resolvedCodexCmd = Resolve-RequiredPath -Path $CodexCmd -Name "CodexCmd"
$safetyRulesPath = Resolve-RequiredPath -Path (Join-Path -Path $resolvedProjectRoot -ChildPath "ai_project_manager\SAFETY_RULES.md") -Name "SAFETY_RULES.md"

$footer = @"
Before your final response, inspect the current git status and any relevant validation output.
Your final response must list changed files, validation commands and results, staged files status, and confirmation that no commit or push was run.
Do not stage, commit, push, restore, reset, or delete unrelated files.
"@

$codexArgs = @(
    "exec",
    "--cd",
    $resolvedProjectRoot,
    "--sandbox",
    $Sandbox,
    "-o",
    "<run-dir>\last_message.txt"
)

if (-not [string]::IsNullOrWhiteSpace($Model)) {
    $codexArgs += @("--model", $Model)
}

if ($DryRun) {
    Write-Host "Dry run only. Validated inputs and did not create a run directory."
    Write-Host "ProjectRoot: $resolvedProjectRoot"
    Write-Host "TaskFile: $resolvedTaskFile"
    Write-Host "SafetyRules: $safetyRulesPath"
    Write-Host "Would run:"
    Write-Host (Format-CommandLine -Executable $resolvedCodexCmd -Arguments $codexArgs)
    Write-Host "Prompt would be provided on stdin from SAFETY_RULES.md, the task file, and the final-response footer."
    Invoke-CompletionSound -Warning $false
    return
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runRoot = Join-Path -Path $resolvedProjectRoot -ChildPath "logs\codex_runs"
$safeTaskName = Get-SafeRunTaskName -TaskFilePath $resolvedTaskFile
if ([string]::IsNullOrWhiteSpace($safeTaskName)) {
    $runDirectoryName = $timestamp
} else {
    $runDirectoryName = "{0}_{1}" -f $timestamp, $safeTaskName
}

$outputDir = Join-Path -Path $runRoot -ChildPath $runDirectoryName
$suffix = 1
while (Test-Path -LiteralPath $outputDir) {
    $outputDir = Join-Path -Path $runRoot -ChildPath ("{0}_{1}" -f $runDirectoryName, $suffix)
    $suffix += 1
}

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
Set-Content -LiteralPath (Join-Path -Path $runRoot -ChildPath "latest_run_path.txt") -Value $outputDir -Encoding UTF8

$taskUsedPath = Join-Path -Path $outputDir -ChildPath "task_used.md"
$fullOutputPath = Join-Path -Path $outputDir -ChildPath "full_output.txt"
$lastMessagePath = Join-Path -Path $outputDir -ChildPath "last_message.txt"
$gitBeforePath = Join-Path -Path $outputDir -ChildPath "git_status_before.txt"
$gitAfterPath = Join-Path -Path $outputDir -ChildPath "git_status_after.txt"
$changedFilesPath = Join-Path -Path $outputDir -ChildPath "changed_files_after.txt"
$stagedFilesPath = Join-Path -Path $outputDir -ChildPath "staged_files_after.txt"
$warningsPath = Join-Path -Path $outputDir -ChildPath "safety_warnings.txt"

$safetyText = Get-Content -LiteralPath $safetyRulesPath -Raw
$taskText = Get-Content -LiteralPath $resolvedTaskFile -Raw
$prompt = @"
$safetyText

# Task File

$taskText

# Required Final Response

$footer
"@

Set-Content -LiteralPath $taskUsedPath -Value $prompt -Encoding UTF8

$gitBefore = @(Invoke-GitLines -Root $resolvedProjectRoot -Arguments @("status", "--short", "--branch"))
Save-Lines -Path $gitBeforePath -Lines $gitBefore

Write-Host "Git status before:"
foreach ($line in $gitBefore) {
    Write-Host $line
}

$actualCodexArgs = @(
    "exec",
    "--cd",
    $resolvedProjectRoot,
    "--sandbox",
    $Sandbox,
    "-o",
    $lastMessagePath
)

if (-not [string]::IsNullOrWhiteSpace($Model)) {
    $actualCodexArgs += @("--model", $Model)
}

Write-Host "Run directory: $outputDir"
Write-Host "Running:"
Write-Host (Format-CommandLine -Executable $resolvedCodexCmd -Arguments $actualCodexArgs)

try {
    $codexExitCode = Invoke-CodexProcess -Executable $resolvedCodexCmd -Arguments $actualCodexArgs -InputText $prompt -OutputPath $fullOutputPath
} catch {
    $codexExitCode = 1
    $failureMessage = "ERROR: failed to invoke codex exec: $($_.Exception.Message)"
    if (Test-Path -LiteralPath $fullOutputPath) {
        Add-Content -LiteralPath $fullOutputPath -Value $failureMessage -Encoding UTF8
    } else {
        Set-Content -LiteralPath $fullOutputPath -Value $failureMessage -Encoding UTF8
    }

    Write-Warning $failureMessage
}

if (-not (Test-Path -LiteralPath $fullOutputPath)) {
    Set-Content -LiteralPath $fullOutputPath -Value "" -Encoding UTF8
}

$lastMessageFallbackUsed = $false
if (-not (Test-TextFileHasContent -Path $lastMessagePath)) {
    Write-LastMessageFallback -Path $lastMessagePath -FullOutputPath $fullOutputPath -ExitCode $codexExitCode
    $lastMessageFallbackUsed = $true
}

$gitAfter = @(Invoke-GitLines -Root $resolvedProjectRoot -Arguments @("status", "--short", "--branch"))
$changedStatus = @(Invoke-GitLines -Root $resolvedProjectRoot -Arguments @("status", "--short", "--untracked-files=all"))
$stagedFiles = @(Invoke-GitLines -Root $resolvedProjectRoot -Arguments @("diff", "--cached", "--name-only"))
$changedFiles = @(Get-StatusPaths -StatusLines $changedStatus)
$warnings = @(New-SafetyWarnings -ChangedFiles $changedFiles -StagedFiles $stagedFiles)
$runnerWarnings = New-Object System.Collections.Generic.List[string]
if ($lastMessageFallbackUsed) {
    $runnerWarnings.Add("WARNING: codex exec did not create a non-empty last_message.txt; fallback report was written.")
}
$allWarnings = @($runnerWarnings.ToArray()) + @($warnings)
$hasSafetyWarnings = @($warnings | Where-Object { $_ -like "WARNING:*" }).Count -gt 0
$hasRunnerWarnings = @($runnerWarnings | Where-Object { $_ -like "WARNING:*" }).Count -gt 0

Save-Lines -Path $gitAfterPath -Lines $gitAfter
Save-Lines -Path $changedFilesPath -Lines $changedStatus
Save-Lines -Path $stagedFilesPath -Lines $stagedFiles
Save-Lines -Path $warningsPath -Lines $allWarnings

Write-Host "Git status after written to: $gitAfterPath"
Write-Host "Safety warnings written to: $warningsPath"

if ($codexExitCode -ne 0) {
    Write-Warning "codex exec exited with code $codexExitCode. Review $fullOutputPath and $lastMessagePath."
    Write-RunOutputCommand -RunDirectory $outputDir
    Invoke-CompletionSound -Warning $true
    exit $codexExitCode
}

Write-Host "codex exec completed. Review $lastMessagePath and $fullOutputPath."
Write-RunOutputCommand -RunDirectory $outputDir
Invoke-CompletionSound -Warning ($hasSafetyWarnings -or $hasRunnerWarnings)
