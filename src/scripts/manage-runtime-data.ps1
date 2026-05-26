param(
    [Parameter(Mandatory = $false, Position = 0)]
    [ValidateSet('inspect', 'backup', 'restore', 'migrate')]
    [string]$Command = 'inspect',

    [Parameter(Mandatory = $false)]
    [ValidateSet('desktop', 'dev-legacy', 'dev')]
    [string]$SourceStack = 'desktop',

    [Parameter(Mandatory = $false)]
    [ValidateSet('desktop', 'dev-legacy', 'dev')]
    [string]$TargetStack = 'desktop',

    [Parameter(Mandatory = $false)]
    [string]$BackupPath = '',

    [Parameter(Mandatory = $false)]
    [string]$BackupRoot = '',

    [Parameter(Mandatory = $false)]
    [string]$ReportRoot = '',

    [Parameter(Mandatory = $false)]
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$defaultBackupRoot = Join-Path $repoRoot 'data\backups\manual'
$defaultReportRoot = Join-Path $repoRoot 'tmp\runtime-data-reports'

$stackPresets = @{
    'desktop' = @{
        AuthVolume = 'cga-desktop_auth_db_data'
        FalkorVolume = 'cga-desktop_falkordb_data'
        Containers = @('cga-desktop-api', 'cga-desktop-falkordb')
    }
    'dev-legacy' = @{
        AuthVolume = 'contextgraph_auth_db_dev_data'
        FalkorVolume = 'contextgraph_falkordb_dev_data'
        Containers = @('contextgraph-api-dev', 'contextgraph-falkordb-dev')
    }
    'dev' = @{
        AuthVolume = 'contextgraphadmin_auth_db_dev_data'
        FalkorVolume = 'contextgraphadmin_falkordb_dev_data'
        Containers = @('cga-api-dev', 'cga-falkordb-dev')
    }
}

function Invoke-Docker {
    param(
        [string[]]$DockerArguments
    )

    & docker @DockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker failed with exit code $LASTEXITCODE"
    }
}

function Invoke-DockerCapture {
    param(
        [string[]]$DockerArguments,
        [switch]$AllowFailure
    )

    $output = & docker @DockerArguments 2>&1
    if (-not $AllowFailure -and $LASTEXITCODE -ne 0) {
        throw (($output | Out-String).Trim())
    }
    return (($output | Out-String).Trim())
}

function Get-StackPreset {
    param(
        [string]$StackName
    )

    if (-not $stackPresets.ContainsKey($StackName)) {
        throw "Unknown stack preset: $StackName"
    }

    return $stackPresets[$StackName]
}

function Test-DockerVolumeExists {
    param(
        [string]$VolumeName
    )

    $null = & docker volume inspect $VolumeName 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Get-ExistingContainers {
    $raw = Invoke-DockerCapture -DockerArguments @('ps', '-a', '--format', '{{.Names}}')
    if (-not $raw) {
        return @()
    }
    return @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-RunningContainers {
    $raw = Invoke-DockerCapture -DockerArguments @('ps', '--format', '{{.Names}}')
    if (-not $raw) {
        return @()
    }
    return @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Stop-Containers {
    param(
        [string[]]$ContainerNames
    )

    $existing = Get-ExistingContainers
    $running = Get-RunningContainers
    $toStop = @($ContainerNames | Where-Object { $_ -in $existing -and $_ -in $running } | Select-Object -Unique)
    if ($toStop.Count -gt 0) {
        Write-Host "Stopping containers: $($toStop -join ', ')"
        Invoke-Docker -DockerArguments @('stop') + $toStop
    }
    return $toStop
}

function Start-Containers {
    param(
        [string[]]$ContainerNames
    )

    $existing = Get-ExistingContainers
    $toStart = @($ContainerNames | Where-Object { $_ -in $existing } | Select-Object -Unique)
    if ($toStart.Count -gt 0) {
        Write-Host "Starting containers: $($toStart -join ', ')"
        Invoke-Docker -DockerArguments @('start') + $toStart
    }
}

function Get-BackupRootPath {
    if ($BackupRoot) {
        return (Resolve-Path -LiteralPath $BackupRoot -ErrorAction SilentlyContinue) ?? $BackupRoot
    }
    return $defaultBackupRoot
}

function Get-ReportRootPath {
    if ($ReportRoot) {
        return (Resolve-Path -LiteralPath $ReportRoot -ErrorAction SilentlyContinue) ?? $ReportRoot
    }
    return $defaultReportRoot
}

function New-BackupDirectory {
    param(
        [string]$BaseRoot,
        [string]$NamePrefix
    )

    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $path = Join-Path $BaseRoot "$NamePrefix-$timestamp"
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    return $path
}

function Save-BackupMetadata {
    param(
        [string]$DestinationPath,
        [hashtable]$Metadata
    )

    $Metadata | ConvertTo-Json -Depth 10 | Set-Content -Path (Join-Path $DestinationPath 'metadata.json') -Encoding UTF8
}

function Write-OperationReport {
    param(
        [string]$OperationName,
        [hashtable]$ReportData
    )

    $reportRootPath = Get-ReportRootPath
    New-Item -ItemType Directory -Force -Path $reportRootPath | Out-Null
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $reportPath = Join-Path $reportRootPath "$OperationName-$timestamp.json"
    $ReportData | ConvertTo-Json -Depth 12 | Set-Content -Path $reportPath -Encoding UTF8
    return $reportPath
}

function Get-SqliteSummaryPythonScript {
    param(
        [string]$DbPath
    )

    return @"
from pathlib import Path
import json
import sqlite3

db = Path(r'$DbPath')
summary = {
    "exists": db.exists(),
    "file_size": db.stat().st_size if db.exists() else 0,
    "tables": [],
    "counts": {},
    "issues": [],
}

if not db.exists():
    summary["issues"].append("missing auth.db")
else:
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    summary["tables"] = [row[0] for row in cur.execute("select name from sqlite_master where type='table' order by name")]
    for table in ("projects", "users", "audit_logs"):
        try:
            summary["counts"][table] = cur.execute(f"select count(1) from {table}").fetchone()[0]
        except Exception as exc:
            summary["issues"].append(f"required table {table}: {exc}")
    if "work_activities" in summary["tables"]:
        try:
            summary["counts"]["work_activities"] = cur.execute("select count(1) from work_activities").fetchone()[0]
        except Exception as exc:
            summary["issues"].append(f"optional table work_activities: {exc}")

print(json.dumps(summary))
"@
}

function Get-SqliteSummaryObjectFromMount {
    param(
        [string[]]$MountArguments,
        [string]$DbPath
    )

    $pythonScript = Get-SqliteSummaryPythonScript -DbPath $DbPath
    $raw = Invoke-DockerCapture -DockerArguments (@('run', '--rm') + $MountArguments + @('python:3.12-slim', 'python', '-c', $pythonScript)) -AllowFailure
    if (-not $raw) {
        return @{
            exists = $false
            file_size = 0
            tables = @()
            counts = @{}
            issues = @('no output from sqlite summary probe')
        }
    }
    return ($raw | ConvertFrom-Json -AsHashtable)
}

function Get-VolumeAuthSummaryObject {
    param(
        [string]$VolumeName
    )

    if (-not (Test-DockerVolumeExists -VolumeName $VolumeName)) {
        return @{
            exists = $false
            file_size = 0
            tables = @()
            counts = @{}
            issues = @('missing auth volume')
        }
    }

    return Get-SqliteSummaryObjectFromMount -MountArguments @('-v', "${VolumeName}:/source:ro") -DbPath '/source/auth.db'
}

function Get-BackupAuthSummaryObject {
    param(
        [string]$AuthBackupFile
    )

    $resolvedAuthFile = (Resolve-Path -LiteralPath $AuthBackupFile).Path
    return Get-SqliteSummaryObjectFromMount -MountArguments @('-v', "${resolvedAuthFile}:/backup/auth.db:ro") -DbPath '/backup/auth.db'
}

function Get-FalkorArchiveSummaryObject {
    param(
        [string]$FalkorBackupFile
    )

    $resolvedArchive = (Resolve-Path -LiteralPath $FalkorBackupFile).Path
    $summary = @{
        exists = (Test-Path -LiteralPath $resolvedArchive)
        file_size = 0
        sha256 = $null
        archive_ok = $false
        entry_count = 0
        issues = @()
    }

    if (-not $summary.exists) {
        $summary.issues += 'missing falkordb-data.tgz'
        return $summary
    }

    $fileInfo = Get-Item -LiteralPath $resolvedArchive
    $summary.file_size = $fileInfo.Length
    $summary.sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedArchive).Hash.ToLowerInvariant()

    try {
        $entryCountRaw = Invoke-DockerCapture -DockerArguments @(
            'run', '--rm',
            '-v', "${resolvedArchive}:/backup/falkordb-data.tgz:ro",
            'alpine:3.20',
            'sh', '-c',
            'set -eu; tar -tzf /backup/falkordb-data.tgz | wc -l | tr -d " "'
        )
        $summary.archive_ok = $true
        $summary.entry_count = [int]($entryCountRaw.Trim())
    }
    catch {
        $summary.issues += $_.Exception.Message
    }

    return $summary
}

function Get-BackupValidationSummary {
    param(
        [hashtable]$Artifacts
    )

    $authSummary = Get-BackupAuthSummaryObject -AuthBackupFile $Artifacts.Auth
    $falkorSummary = Get-FalkorArchiveSummaryObject -FalkorBackupFile $Artifacts.Falkor
    $issues = @()

    if (-not $authSummary.exists) {
        $issues += 'auth backup is missing'
    }
    foreach ($requiredTable in @('projects', 'users', 'audit_logs')) {
        if (-not ($authSummary.tables -contains $requiredTable)) {
            $issues += "auth backup missing required table: $requiredTable"
        }
    }
    if ($authSummary.issues) {
        $issues += @($authSummary.issues)
    }
    if (-not $falkorSummary.archive_ok) {
        $issues += 'falkordb archive could not be read'
    }
    if ($falkorSummary.issues) {
        $issues += @($falkorSummary.issues)
    }

    return @{
        is_valid = ($issues.Count -eq 0)
        auth = $authSummary
        falkor = $falkorSummary
        issues = $issues
    }
}

function Get-StackGraphNames {
    param(
        [hashtable]$Preset
    )

    $running = Get-RunningContainers
    $graphContainer = $Preset.Containers | Select-Object -Last 1
    if (-not ($graphContainer -in $running)) {
        return @()
    }

    $graphs = Invoke-DockerCapture -DockerArguments @('exec', $graphContainer, 'redis-cli', 'GRAPH.LIST') -AllowFailure
    if (-not $graphs) {
        return @()
    }
    return @($graphs -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Get-StackInspectionObject {
    param(
        [string]$StackName
    )

    $preset = Get-StackPreset -StackName $StackName
    $running = Get-RunningContainers
    return @{
        stack = $StackName
        auth_volume = $preset.AuthVolume
        falkor_volume = $preset.FalkorVolume
        containers = @($preset.Containers)
        running_containers = @($preset.Containers | Where-Object { $_ -in $running })
        auth = Get-VolumeAuthSummaryObject -VolumeName $preset.AuthVolume
        graph_names = Get-StackGraphNames -Preset $preset
    }
}

function Compare-AuthCounts {
    param(
        [hashtable]$ReferenceCounts,
        [hashtable]$CandidateCounts
    )

    $comparison = @{}
    $keys = @($ReferenceCounts.Keys + $CandidateCounts.Keys | Sort-Object -Unique)
    foreach ($key in $keys) {
        $expected = $ReferenceCounts[$key]
        $actual = $CandidateCounts[$key]
        $comparison[$key] = @{
            expected = $expected
            actual = $actual
            matches = ($expected -eq $actual)
        }
    }
    return $comparison
}

function Compare-StringCollections {
    param(
        [string[]]$ReferenceValues,
        [string[]]$CandidateValues
    )

    $expected = @($ReferenceValues | Sort-Object -Unique)
    $actual = @($CandidateValues | Sort-Object -Unique)
    return @{
        expected = $expected
        actual = $actual
        matches = (($expected -join '|') -eq ($actual -join '|'))
    }
}

function Backup-AuthVolume {
    param(
        [string]$VolumeName,
        [string]$DestinationPath
    )

    $resolvedDestination = (Resolve-Path -LiteralPath $DestinationPath).Path
    $pythonScript = @'
from pathlib import Path
import shutil

src = Path('/source/auth.db')
dst = Path('/backup/auth.db')
if not src.exists():
    raise SystemExit('auth.db not found in source volume')

shutil.copy2(src, dst)
'@
    Invoke-Docker -DockerArguments @(
        'run', '--rm',
        '-v', "${VolumeName}:/source:ro",
        '-v', "${resolvedDestination}:/backup",
        'python:3.12-slim',
        'python', '-c',
        $pythonScript
    )
}

function Backup-FalkorVolume {
    param(
        [string]$VolumeName,
        [string]$DestinationPath
    )

    $resolvedDestination = (Resolve-Path -LiteralPath $DestinationPath).Path
    Invoke-Docker -DockerArguments @(
        'run', '--rm',
        '-v', "${VolumeName}:/source:ro",
        '-v', "${resolvedDestination}:/backup",
        'alpine:3.20',
        'sh', '-c',
        'set -eu; tar -czf /backup/falkordb-data.tgz -C /source .'
    )
}

function Invoke-BackupForStack {
    param(
        [string]$StackName,
        [string]$DestinationPath
    )

    $preset = Get-StackPreset -StackName $StackName
    if (-not (Test-DockerVolumeExists -VolumeName $preset.AuthVolume)) {
        throw "Auth volume not found for stack '$StackName': $($preset.AuthVolume)"
    }
    if (-not (Test-DockerVolumeExists -VolumeName $preset.FalkorVolume)) {
        throw "Falkor volume not found for stack '$StackName': $($preset.FalkorVolume)"
    }

    New-Item -ItemType Directory -Force -Path $DestinationPath | Out-Null
    Backup-AuthVolume -VolumeName $preset.AuthVolume -DestinationPath $DestinationPath
    Backup-FalkorVolume -VolumeName $preset.FalkorVolume -DestinationPath $DestinationPath
    $artifacts = Resolve-BackupArtifacts -BackupSourcePath $DestinationPath
    $validation = Get-BackupValidationSummary -Artifacts $artifacts
    Save-BackupMetadata -DestinationPath $DestinationPath -Metadata @{
        stack = $StackName
        authVolume = $preset.AuthVolume
        falkorVolume = $preset.FalkorVolume
        createdAt = (Get-Date).ToString('s')
        validation = $validation
    }
    if (-not $validation.is_valid) {
        throw "Backup validation failed for stack '$StackName': $($validation.issues -join '; ')"
    }
    Write-Host "Backup created: $DestinationPath"
    return @{
        path = $DestinationPath
        artifacts = $artifacts
        validation = $validation
    }
}

function Resolve-BackupArtifacts {
    param(
        [string]$BackupSourcePath
    )

    $resolved = (Resolve-Path -LiteralPath $BackupSourcePath).Path
    $manualAuth = Join-Path $resolved 'auth.db'
    $manualFalkor = Join-Path $resolved 'falkordb-data.tgz'
    if ((Test-Path -LiteralPath $manualAuth) -and (Test-Path -LiteralPath $manualFalkor)) {
        return @{
            Root = $resolved
            Auth = $manualAuth
            Falkor = $manualFalkor
        }
    }

    $scheduledAuth = Join-Path $resolved 'auth\auth-latest.db'
    $scheduledFalkor = Join-Path $resolved 'falkordb\falkordb-latest.tgz'
    if ((Test-Path -LiteralPath $scheduledAuth) -and (Test-Path -LiteralPath $scheduledFalkor)) {
        return @{
            Root = $resolved
            Auth = $scheduledAuth
            Falkor = $scheduledFalkor
        }
    }

    throw "Backup path does not contain auth/falkor artifacts: $BackupSourcePath"
}

function Restore-AuthVolume {
    param(
        [string]$VolumeName,
        [string]$AuthBackupFile
    )

    $resolvedAuthFile = (Resolve-Path -LiteralPath $AuthBackupFile).Path
    $pythonScript = @'
from pathlib import Path
import shutil

src = Path('/backup/auth.db')
dst = Path('/target/auth.db')
shutil.copy2(src, dst)
'@
    Invoke-Docker -DockerArguments @(
        'run', '--rm',
        '-v', "${VolumeName}:/target",
        '-v', "${resolvedAuthFile}:/backup/auth.db:ro",
        'python:3.12-slim',
        'python', '-c',
        $pythonScript
    )
}

function Restore-FalkorVolume {
    param(
        [string]$VolumeName,
        [string]$FalkorBackupFile
    )

    $resolvedArchive = (Resolve-Path -LiteralPath $FalkorBackupFile).Path
    Invoke-Docker -DockerArguments @(
        'run', '--rm',
        '-v', "${VolumeName}:/target",
        '-v', "${resolvedArchive}:/backup/falkordb-data.tgz:ro",
        'alpine:3.20',
        'sh', '-c',
        'set -eu; find /target -mindepth 1 -delete; tar -xzf /backup/falkordb-data.tgz -C /target'
    )
}

function Get-AuthStats {
    param(
        [string]$VolumeName
    )

    $summary = Get-VolumeAuthSummaryObject -VolumeName $VolumeName
    $lines = @(
        "exists=$($summary.exists)",
        "file_size=$($summary.file_size)"
    )
    foreach ($key in @($summary.counts.Keys | Sort-Object)) {
        $lines += "$key=$($summary.counts[$key])"
    }
    foreach ($issue in @($summary.issues)) {
        $lines += "issue=$issue"
    }
    return ($lines -join "`n")
}

function Get-StackGraphInfo {
    param(
        [hashtable]$Preset
    )

    $graphs = Get-StackGraphNames -Preset $Preset
    if ($graphs.Count -eq 0) {
        return 'graph list unavailable (container not running)'
    }
    return ($graphs -join "`n")
}

function Show-StackInspection {
    param(
        [string]$StackName
    )

    $inspection = Get-StackInspectionObject -StackName $StackName
    Write-Host "Stack: $StackName"
    Write-Host "- auth volume: $($inspection.auth_volume) (exists=$([bool](Test-DockerVolumeExists -VolumeName $inspection.auth_volume)))"
    Write-Host "- falkor volume: $($inspection.falkor_volume) (exists=$([bool](Test-DockerVolumeExists -VolumeName $inspection.falkor_volume)))"
    Write-Host "- containers: $($inspection.containers -join ', ')"
    Write-Host "- running: $($inspection.running_containers -join ', ')"
    Write-Host "- auth stats:"
    (Get-AuthStats -VolumeName $inspection.auth_volume) -split "`r?`n" | ForEach-Object { if ($_){ Write-Host "  $_" } }
    Write-Host "- graphs:"
    if ($inspection.graph_names.Count -eq 0) {
        Write-Host '  graph list unavailable (container not running)'
    }
    else {
        $inspection.graph_names | ForEach-Object { Write-Host "  $_" }
    }
    Write-Host ''
}

Set-Location $repoRoot

switch ($Command) {
    'inspect' {
        Show-StackInspection -StackName $SourceStack
        if ($TargetStack -ne $SourceStack) {
            Show-StackInspection -StackName $TargetStack
        }
    }
    'backup' {
        $baseRoot = Get-BackupRootPath
        New-Item -ItemType Directory -Force -Path $baseRoot | Out-Null
        $destination = if ($BackupPath) {
            New-Item -ItemType Directory -Force -Path $BackupPath | Out-Null
            (Resolve-Path -LiteralPath $BackupPath).Path
        }
        else {
            New-BackupDirectory -BaseRoot $baseRoot -NamePrefix "backup-$SourceStack"
        }
        $backupResult = Invoke-BackupForStack -StackName $SourceStack -DestinationPath $destination
        Write-Host "Backup validation: succeeded=$($backupResult.validation.is_valid)"
    }
    'restore' {
        if (-not $Force) {
            throw 'restore overwrites target volumes. Re-run with -Force.'
        }
        if (-not $BackupPath) {
            throw 'restore requires -BackupPath.'
        }
        $targetPreset = Get-StackPreset -StackName $TargetStack
        $report = @{
            operation = 'restore'
            targetStack = $TargetStack
            startedAt = (Get-Date).ToString('s')
            requestedBackupPath = $BackupPath
            targetBefore = Get-StackInspectionObject -StackName $TargetStack
        }
        $operationError = $null
        $stopped = @()
        try {
            $artifacts = Resolve-BackupArtifacts -BackupSourcePath $BackupPath
            $report.resolvedBackup = $artifacts
            $report.inputValidation = Get-BackupValidationSummary -Artifacts $artifacts
            if (-not $report.inputValidation.is_valid) {
                throw "Backup validation failed: $($report.inputValidation.issues -join '; ')"
            }
            $baseRoot = Get-BackupRootPath
            New-Item -ItemType Directory -Force -Path $baseRoot | Out-Null
            $safetyBackup = New-BackupDirectory -BaseRoot $baseRoot -NamePrefix "safety-restore-$TargetStack"
            $report.safetyBackup = Invoke-BackupForStack -StackName $TargetStack -DestinationPath $safetyBackup
            $stopped = Stop-Containers -ContainerNames $targetPreset.Containers
            Restore-AuthVolume -VolumeName $targetPreset.AuthVolume -AuthBackupFile $artifacts.Auth
            Restore-FalkorVolume -VolumeName $targetPreset.FalkorVolume -FalkorBackupFile $artifacts.Falkor
        }
        catch {
            $operationError = $_
        }
        finally {
            Start-Containers -ContainerNames $stopped
            $report.completedAt = (Get-Date).ToString('s')
            $report.status = if ($operationError) { 'failed' } else { 'succeeded' }
            if ($operationError) {
                $report.error = $operationError.Exception.Message
            }
            $report.targetAfter = Get-StackInspectionObject -StackName $TargetStack
            if ($report.ContainsKey('inputValidation')) {
                $report.authCountComparison = Compare-AuthCounts -ReferenceCounts $report.inputValidation.auth.counts -CandidateCounts $report.targetAfter.auth.counts
            }
            $reportPath = Write-OperationReport -OperationName "restore-$TargetStack" -ReportData $report
            Write-Host "Restore report: $reportPath"
        }
        if ($operationError) {
            throw $operationError
        }
        Write-Host "Restore completed for stack '$TargetStack'. Safety backup: $($report.safetyBackup.path)"
    }
    'migrate' {
        if (-not $Force) {
            throw 'migrate overwrites target volumes. Re-run with -Force.'
        }
        if ($SourceStack -eq $TargetStack) {
            throw 'SourceStack and TargetStack must differ for migrate.'
        }
        $sourcePreset = Get-StackPreset -StackName $SourceStack
        $targetPreset = Get-StackPreset -StackName $TargetStack
        $baseRoot = Get-BackupRootPath
        New-Item -ItemType Directory -Force -Path $baseRoot | Out-Null
        $report = @{
            operation = 'migrate'
            sourceStack = $SourceStack
            targetStack = $TargetStack
            startedAt = (Get-Date).ToString('s')
            sourceBefore = Get-StackInspectionObject -StackName $SourceStack
            targetBefore = Get-StackInspectionObject -StackName $TargetStack
        }
        $operationError = $null
        $sourceStopped = @()
        $targetStopped = @()
        try {
            $safetyBackup = New-BackupDirectory -BaseRoot $baseRoot -NamePrefix "safety-migrate-$TargetStack"
            $report.safetyBackup = Invoke-BackupForStack -StackName $TargetStack -DestinationPath $safetyBackup
            $sourceSnapshot = New-BackupDirectory -BaseRoot $baseRoot -NamePrefix "source-migrate-$SourceStack"
            $report.sourceSnapshot = Invoke-BackupForStack -StackName $SourceStack -DestinationPath $sourceSnapshot
            $sourceStopped = Stop-Containers -ContainerNames $sourcePreset.Containers
            $targetStopped = Stop-Containers -ContainerNames $targetPreset.Containers
            Invoke-Docker -DockerArguments @(
                'run', '--rm',
                '-v', "$($sourcePreset.AuthVolume):/from:ro",
                '-v', "$($targetPreset.AuthVolume):/to",
                'alpine:3.20',
                'sh', '-c',
                'set -eu; cp -a /from/. /to/'
            )
            Invoke-Docker -DockerArguments @(
                'run', '--rm',
                '-v', "$($sourcePreset.FalkorVolume):/from:ro",
                '-v', "$($targetPreset.FalkorVolume):/to",
                'alpine:3.20',
                'sh', '-c',
                'set -eu; find /to -mindepth 1 -delete; cp -a /from/. /to/'
            )
        }
        catch {
            $operationError = $_
        }
        finally {
            Start-Containers -ContainerNames $sourceStopped
            Start-Containers -ContainerNames $targetStopped
            $report.completedAt = (Get-Date).ToString('s')
            $report.status = if ($operationError) { 'failed' } else { 'succeeded' }
            if ($operationError) {
                $report.error = $operationError.Exception.Message
            }
            $report.targetAfter = Get-StackInspectionObject -StackName $TargetStack
            $report.authCountComparison = Compare-AuthCounts -ReferenceCounts $report.sourceBefore.auth.counts -CandidateCounts $report.targetAfter.auth.counts
            $report.graphComparison = Compare-StringCollections -ReferenceValues $report.sourceBefore.graph_names -CandidateValues $report.targetAfter.graph_names
            $reportPath = Write-OperationReport -OperationName "migrate-$SourceStack-to-$TargetStack" -ReportData $report
            Write-Host "Migration report: $reportPath"
        }
        if ($operationError) {
            throw $operationError
        }
        Write-Host "Migration completed: $SourceStack -> $TargetStack. Safety backup: $($report.safetyBackup.path)"
    }
}