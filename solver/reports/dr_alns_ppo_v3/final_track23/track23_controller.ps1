$ErrorActionPreference = "Stop"

$Repo = "D:\ReSETP"
$Runner = "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe"
$Worker = "C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
$OutputDir = Join-Path $Repo "solver\reports\dr_alns_ppo_v3\final_track23"
$ControllerLog = Join-Path $OutputDir "track23_controller.log"
$ControllerStatus = Join-Path $OutputDir "track23_controller_status.json"
$StatePath = Join-Path $OutputDir "track23_state.json"
$FinalReportJson = Join-Path $OutputDir "track23_final_report.json"
$HandoffPath = Join-Path $Repo "HANDOFF.md"
$MaxSeconds = 26 * 3600
$Stages = @("A", "A2", "B", "C", "D", "E")
$Started = Get-Date

function Write-ControllerLog {
    param([string] $Message)
    $line = "{0}`t{1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $ControllerLog -Value $line -Encoding UTF8
}

function Read-JsonOrNull {
    param([string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Write-Json {
    param([string] $Path, [object] $Payload)
    $json = $Payload | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText($Path, $json + "`n", [System.Text.UTF8Encoding]::new($false))
}

function Get-ElapsedSeconds {
    return [int]((Get-Date) - $Started).TotalSeconds
}

function Get-StageStatus {
    param([string] $Stage, [object] $State)
    if ($null -eq $State) {
        return "NO_STATE"
    }
    $key = switch ($Stage) {
        "A" { "stage_a" }
        "A2" { "stage_a2" }
        "B" { "stage_b" }
        "C" { "stage_c" }
        "D" { "stage_d" }
        "E" { "final_status" }
        default { "" }
    }
    if ($Stage -eq "E") {
        if ($null -eq $State.final_status) {
            return "UNKNOWN"
        }
        return [string]$State.final_status
    }
    $stageObject = $State.PSObject.Properties[$key]
    if ($null -eq $stageObject -or $null -eq $stageObject.Value) {
        return "NOT_RUN"
    }
    if ($null -eq $stageObject.Value.status) {
        return "UNKNOWN"
    }
    return [string]$stageObject.Value.status
}

function Add-ExistingArtifacts {
    $items = New-Object System.Collections.Generic.List[string]
    $controller = Join-Path $OutputDir "track23_controller.ps1"
    if (Test-Path -LiteralPath $controller) {
        $items.Add($controller)
    }
    foreach ($pattern in @("*.csv", "*.json", "*.md")) {
        Get-ChildItem -LiteralPath $OutputDir -Filter $pattern -File -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_.Name -notmatch "\.log$|\.pid$") {
                $items.Add($_.FullName)
            }
        }
    }
    foreach ($dir in @("stage_d_track18")) {
        $path = Join-Path $OutputDir $dir
        if (Test-Path -LiteralPath $path) {
            Get-ChildItem -LiteralPath $path -Include *.csv,*.json,*.md -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
                $items.Add($_.FullName)
            }
        }
    }
    Get-ChildItem -LiteralPath $OutputDir -Directory -Filter "stage_d_track20_*" -ErrorAction SilentlyContinue | ForEach-Object {
        Get-ChildItem -LiteralPath $_.FullName -Include *.csv,*.json,*.md -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object {
            $items.Add($_.FullName)
        }
    }
    if ($items.Count -gt 0) {
        & git add -f -- $items.ToArray()
    }
}

function Commit-Artifacts {
    param([string] $Message)
    & git diff --check
    if ($LASTEXITCODE -ne 0) {
        throw "git diff --check failed"
    }
    Add-ExistingArtifacts
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-ControllerLog "No staged artifact changes for commit: $Message"
        return
    }
    & git commit -m $Message
    if ($LASTEXITCODE -ne 0) {
        throw "git commit failed for $Message"
    }
}

function Append-HandoffRunLog {
    $state = Read-JsonOrNull $FinalReportJson
    $status = "UNKNOWN"
    $reason = ""
    if ($null -ne $state) {
        if ($null -ne $state.final_status) {
            $status = [string]$state.final_status
        }
        if ($null -ne $state.final_reason) {
            $reason = [string]$state.final_reason
        }
    }
    $stageA = if ($null -ne $state -and $null -ne $state.stage_a) { [string]$state.stage_a.status } else { "NOT_RUN" }
    $stageA2 = if ($null -ne $state -and $null -ne $state.stage_a2) { [string]$state.stage_a2.status } else { "NOT_RUN" }
    $stageB = if ($null -ne $state -and $null -ne $state.stage_b) { [string]$state.stage_b.status } else { "NOT_RUN" }
    $stageC = if ($null -ne $state -and $null -ne $state.stage_c) { [string]$state.stage_c.status } else { "NOT_RUN" }
    $stageD = if ($null -ne $state -and $null -ne $state.stage_d) { [string]$state.stage_d.status } else { "NOT_RUN" }
    $pillars = if ($null -ne $state -and $null -ne $state.pillar_summary) {
        "QUALITY=$($state.pillar_summary.DR_PILLAR_QUALITY), EFFICIENCY=$($state.pillar_summary.DR_PILLAR_EFFICIENCY), DYNAMIC=$($state.pillar_summary.DR_PILLAR_DYNAMIC)"
    } else {
        "QUALITY=未判, EFFICIENCY=未判, DYNAMIC=未判"
    }
    $head = (& git rev-parse --short HEAD).Trim()
    $entry = @(
        "- 🧾 $(Get-Date -Format 'yyyy-MM-dd') [x86/Track23 正式 Stage A-E 执行收口] **Final status `$status`**：$reason",
        "  - Stage 状态：A `$stageA`；A2 `$stageA2`；B `$stageB`；C `$stageC`；D `$stageD`。",
        "  - 三支柱：$pillars。",
        "  - 证据目录：`solver/reports/dr_alns_ppo_v3/final_track23/`；核心文件 `final_report.md`、`track23_final_report.json`、`track23_state.json`。",
        "  - 本地收口 commit 起点/过程最新：`$head`；未 push/rebase/prune。"
    ) -join "`n"
    $old = [System.IO.File]::ReadAllText($HandoffPath)
    if ($old.Contains("[x86/Track23 正式 Stage A-E 执行收口]")) {
        Write-ControllerLog "HANDOFF already contains Track23 run log marker; skip append"
        return
    }
    [System.IO.File]::WriteAllText($HandoffPath, $old.TrimEnd() + "`n" + $entry + "`n", [System.Text.UTF8Encoding]::new($false))
}

Set-Location -LiteralPath $Repo
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$env:PYTHONPATH = "$Repo\solver\src;$Repo\models\src;$Repo\solver\rl"
$env:SETP_WORKER_PYTHON = $Worker
Write-ControllerLog "Track23 controller start repo=$Repo runner=$Runner worker=$Worker"

$stageRecords = @()
$stopReason = ""
foreach ($stage in $Stages) {
    $elapsed = Get-ElapsedSeconds
    if ($elapsed -ge $MaxSeconds) {
        $stopReason = "HALT_TRACK23_CONTROLLER_WALLTIME before stage $stage elapsed=$elapsed max=$MaxSeconds"
        Write-ControllerLog $stopReason
        break
    }

    Write-ControllerLog "START stage=$stage elapsed=$elapsed"
    $stageStdout = Join-Path $OutputDir ("track23_stage_{0}.stdout.log" -f $stage)
    $stageStderr = Join-Path $OutputDir ("track23_stage_{0}.stderr.log" -f $stage)
    $stageStart = Get-Date
    $args = @("-m", "dr_alns_ppo.track23_standing", "run", "--stages", $stage, "--worker-python", $Worker)
    $stdout = & $Runner @args 2> $stageStderr
    $exitCode = $LASTEXITCODE
    $stdout | Out-File -LiteralPath $stageStdout -Encoding UTF8
    $duration = [int]((Get-Date) - $stageStart).TotalSeconds
    $state = Read-JsonOrNull $StatePath
    $stageStatus = Get-StageStatus -Stage $stage -State $state
    Write-ControllerLog "END stage=$stage exit=$exitCode duration=$duration status=$stageStatus"

    $record = [ordered]@{
        stage = $stage
        exit_code = $exitCode
        duration_seconds = $duration
        status = $stageStatus
        elapsed_seconds = Get-ElapsedSeconds
    }
    $stageRecords += [pscustomobject]$record
    Write-Json $ControllerStatus ([ordered]@{
        started = $Started.ToString("o")
        updated = (Get-Date).ToString("o")
        max_seconds = $MaxSeconds
        records = $stageRecords
        stop_reason = $stopReason
    })

    Commit-Artifacts "[x86/DR] Track23 Stage $stage results"

    if ($exitCode -ne 0) {
        $final = Read-JsonOrNull $FinalReportJson
        $finalStatus = ""
        if ($null -ne $final -and $null -ne $final.final_status) {
            $finalStatus = [string]$final.final_status
        }
        $stopReason = "HALT after stage $stage exit=$exitCode final_status=$finalStatus"
        Write-ControllerLog $stopReason
        break
    }
}

Write-Json $ControllerStatus ([ordered]@{
    started = $Started.ToString("o")
    updated = (Get-Date).ToString("o")
    max_seconds = $MaxSeconds
    records = $stageRecords
    stop_reason = $stopReason
})

Append-HandoffRunLog
& git add -- $HandoffPath
& git add -f -- $ControllerStatus
Add-ExistingArtifacts
& git diff --check
if ($LASTEXITCODE -ne 0) {
    throw "git diff --check failed before final commit"
}
& git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    & git commit -m "[x86/DR] Finalize Track23 standing report"
    if ($LASTEXITCODE -ne 0) {
        throw "final Track23 commit failed"
    }
}
Write-ControllerLog "Track23 controller finish stop_reason=$stopReason"
