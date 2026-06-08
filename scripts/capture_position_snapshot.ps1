# input: D:\freqtrade 的 show_recent_positions.py、.venv Python、artifact results 与 Git 远端。
# output: snapshots\YYYY-MM-DD 下的控制台输出、仓位 JSON、收益 JSON、run_meta.json，并可提交推送。
# pos: Windows 计划任务调用的每日仓位审计入口；一旦我被更新，务必更新开头注释以及 scripts\FOLDER_README.md。

param(
    [int]$Days = 8,
    [string]$FreqtradeRoot = 'D:\freqtrade',
    [string]$PythonExe = 'D:\freqtrade\.venv\Scripts\python.exe',
    [string]$ShowScript = 'D:\freqtrade\user_func\strategies\research\str_etf_v1\live\show_recent_positions.py',
    [string]$RepoRoot = '',
    [string]$RemoteName = 'origin',
    [string]$Branch = 'main',
    [switch]$DryRun,
    [switch]$NoPush
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

function Resolve-RepoRoot {
    param([string]$ExplicitRepoRoot)
    if ($ExplicitRepoRoot -and $ExplicitRepoRoot.Trim()) {
        return (Resolve-Path -LiteralPath $ExplicitRepoRoot).Path
    }
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
}

function Find-LatestResultFile {
    param(
        [string]$ArtifactRoot,
        [string]$Filter,
        [datetime]$RunStartedUtc
    )
    if (-not (Test-Path -LiteralPath $ArtifactRoot)) {
        throw "artifact root not found: $ArtifactRoot"
    }
    $file = Get-ChildItem -LiteralPath $ArtifactRoot -Recurse -File -Filter $Filter |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $file) {
        throw "result file not found: $Filter under $ArtifactRoot"
    }
    if ($file.LastWriteTimeUtc -lt $RunStartedUtc.AddMinutes(-10)) {
        Write-Warning "latest $Filter is older than this run: $($file.FullName)"
    }
    return $file
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Data
    )
    $Data | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Path -Encoding UTF8
}

$repoRoot = Resolve-RepoRoot -ExplicitRepoRoot $RepoRoot
$runStarted = Get-Date
$runStartedUtc = $runStarted.ToUniversalTime()
$snapshotDate = $runStarted.ToString('yyyy-MM-dd')
$snapshotDir = Join-Path $repoRoot (Join-Path 'snapshots' $snapshotDate)
New-Item -ItemType Directory -Force -Path $snapshotDir | Out-Null

$consolePath = Join-Path $snapshotDir 'show_recent_positions.txt'
$metaPath = Join-Path $snapshotDir 'run_meta.json'
$artifactRoot = Join-Path (Split-Path -Parent $ShowScript) 'artifacts'
$commandText = "`"$PythonExe`" `"$ShowScript`" --days $Days --save"

$exitCode = 0
$status = 'success'
$outputLines = @()
try {
    Push-Location -LiteralPath $FreqtradeRoot
    try {
        $outputLines = & $PythonExe $ShowScript --days $Days --save 2>&1
        $exitCode = if ($null -eq $LASTEXITCODE) { 0 } else { [int]$LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}
catch {
    $status = 'failure'
    $exitCode = if ($exitCode -ne 0) { $exitCode } else { 1 }
    $outputLines += $_.Exception.Message
}

$outputLines | Set-Content -LiteralPath $consolePath -Encoding UTF8
if ($exitCode -ne 0) {
    $status = 'failure'
}

$positionsSource = $null
$performanceSource = $null
$copyErrors = @()
if ($exitCode -eq 0) {
    try {
        $positionsSource = Find-LatestResultFile -ArtifactRoot $artifactRoot -Filter 'recent_positions_*.json' -RunStartedUtc $runStartedUtc
        $performanceSource = Find-LatestResultFile -ArtifactRoot $artifactRoot -Filter 'recent_performance_*.json' -RunStartedUtc $runStartedUtc
        Copy-Item -LiteralPath $positionsSource.FullName -Destination (Join-Path $snapshotDir $positionsSource.Name) -Force
        Copy-Item -LiteralPath $performanceSource.FullName -Destination (Join-Path $snapshotDir $performanceSource.Name) -Force
    }
    catch {
        $status = 'failure'
        $exitCode = 1
        $copyErrors += $_.Exception.Message
    }
}

$gitResult = [ordered]@{
    attempted = $false
    committed = $false
    pushed = $false
    message = $null
}

$meta = [ordered]@{
    status = $status
    captured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    captured_at_local = (Get-Date).ToString('s')
    snapshot_date = $snapshotDate
    command = $commandText
    days = $Days
    exit_code = $exitCode
    repo_root = $repoRoot
    freqtrade_root = $FreqtradeRoot
    console_output = $consolePath
    source_positions = if ($positionsSource) { $positionsSource.FullName } else { $null }
    source_performance = if ($performanceSource) { $performanceSource.FullName } else { $null }
    copy_errors = $copyErrors
    dry_run = [bool]$DryRun
    no_push = [bool]$NoPush
    git = $gitResult
}
Write-JsonFile -Path $metaPath -Data $meta

if (-not $DryRun) {
    Push-Location -LiteralPath $repoRoot
    try {
        $gitResult.attempted = $true
        $gitResult.message = if ($NoPush) { 'snapshot commit pending; push disabled' } else { 'snapshot commit and push pending' }
        $meta.git = $gitResult
        Write-JsonFile -Path $metaPath -Data $meta

        git add README.md FOLDER_README.md .gitignore scripts snapshots
        git diff --cached --quiet
        if ($LASTEXITCODE -eq 0) {
            $gitResult.message = 'no staged changes'
        }
        else {
            $commitMessage = "position snapshot $snapshotDate"
            git commit -m $commitMessage
            if ($LASTEXITCODE -ne 0) {
                throw 'git commit failed'
            }
            $gitResult.committed = $true
            if (-not $NoPush) {
                git push $RemoteName $Branch
                if ($LASTEXITCODE -ne 0) {
                    throw 'git push failed'
                }
                $gitResult.pushed = $true
                $gitResult.message = 'snapshot commit pushed'
            }
            else {
                $gitResult.message = 'snapshot commit created; push disabled'
            }
        }
    }
    catch {
        $status = 'failure'
        $exitCode = 1
        $gitResult.message = $_.Exception.Message
    }
    finally {
        $meta.status = $status
        $meta.exit_code = $exitCode
        $meta.git = $gitResult
        Write-JsonFile -Path $metaPath -Data $meta

        git add snapshots
        git diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            git commit -m "position snapshot $snapshotDate git result"
            if ($LASTEXITCODE -ne 0) {
                $status = 'failure'
                $exitCode = 1
            }
            elseif ((-not $NoPush) -and $gitResult.pushed) {
                git push $RemoteName $Branch
                if ($LASTEXITCODE -ne 0) {
                    $status = 'failure'
                    $exitCode = 1
                }
            }
        }
        Pop-Location
    }
}

if ($DryRun) {
    Write-Host "[dry-run] snapshot written: $snapshotDir"
}
else {
    Write-Host "[done] snapshot written: $snapshotDir"
    Write-Host "[done] git committed=$($gitResult.committed) pushed=$($gitResult.pushed)"
}

exit $exitCode
