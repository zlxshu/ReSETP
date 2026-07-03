$ErrorActionPreference = "Stop"

$Repo = "D:\ReSETP"
$Runner = "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe"
$Worker = "C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
$OutputDir = Join-Path $Repo "solver\reports\dr_alns_ppo_v3\final_track23"
$ControllerLog = Join-Path $OutputDir "track23_controller_d2.log"
$ControllerStatus = Join-Path $OutputDir "track23_controller_d2_status.json"
$StatePath = Join-Path $OutputDir "track23_state.json"
$FinalReportJson = Join-Path $OutputDir "track23_final_report.json"
$HandoffPath = Join-Path $Repo "HANDOFF.md"
$Stages = @("B", "C", "D", "E")
$MaxSeconds = 26 * 3600
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
    $json = ($Payload | ConvertTo-Json -Depth 20) -replace "`r`n", "`n"
    [System.IO.File]::WriteAllText($Path, $json + "`n", [System.Text.UTF8Encoding]::new($false))
}

function Get-StageStatus {
    param([string] $Stage, [object] $State)
    if ($null -eq $State) {
        return "NO_STATE"
    }
    $key = switch ($Stage) {
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
    $prop = $State.PSObject.Properties[$key]
    if ($null -eq $prop -or $null -eq $prop.Value) {
        return "NOT_RUN"
    }
    if ($null -eq $prop.Value.status) {
        return "UNKNOWN"
    }
    return [string]$prop.Value.status
}

function Normalize-TextArtifacts {
    $files = @()
    $files += Get-ChildItem -LiteralPath $OutputDir -File -Include *.csv,*.json,*.md,*.ps1 -ErrorAction SilentlyContinue
    foreach ($dir in @("stage_c_train24", "stage_d_track18")) {
        $path = Join-Path $OutputDir $dir
        if (Test-Path -LiteralPath $path) {
            $files += Get-ChildItem -LiteralPath $path -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue
        }
    }
    $files += Get-ChildItem -LiteralPath $OutputDir -Directory -Filter "stage_d_track20_*" -ErrorAction SilentlyContinue | ForEach-Object {
        Get-ChildItem -LiteralPath $_.FullName -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue
    }
    foreach ($file in ($files | Sort-Object FullName -Unique)) {
        $text = [System.IO.File]::ReadAllText($file.FullName)
        $text = $text -replace "`r`n", "`n"
        $text = $text -replace "`r", "`n"
        $lines = $text -split "`n", -1
        $lines = $lines | ForEach-Object { $_ -replace '[ \t]+$', '' }
        $text = ($lines -join "`n")
        if (-not $text.EndsWith("`n")) {
            $text += "`n"
        }
        [System.IO.File]::WriteAllText($file.FullName, $text, [System.Text.UTF8Encoding]::new($false))
    }
}

function Add-Artifacts {
    param([switch] $IncludeHandoff)
    $files = @()
    $files += Get-ChildItem -LiteralPath $OutputDir -File -Include *.csv,*.json,*.md,*.ps1 -ErrorAction SilentlyContinue
    foreach ($dir in @("stage_c_train24", "stage_d_track18")) {
        $path = Join-Path $OutputDir $dir
        if (Test-Path -LiteralPath $path) {
            $files += Get-ChildItem -LiteralPath $path -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue
        }
    }
    $bestVal = Join-Path $OutputDir "stage_c_train24\best_val_async_block_ppo.pt"
    if (Test-Path -LiteralPath $bestVal) {
        $files += Get-Item -LiteralPath $bestVal
    }
    $files += Get-ChildItem -LiteralPath $OutputDir -Directory -Filter "stage_d_track20_*" -ErrorAction SilentlyContinue | ForEach-Object {
        Get-ChildItem -LiteralPath $_.FullName -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue
    }
    if ($IncludeHandoff) {
        $files += Get-Item -LiteralPath $HandoffPath
    }
    $rel = @($files | Sort-Object FullName -Unique | ForEach-Object { Resolve-Path -LiteralPath $_.FullName -Relative })
    if ($rel.Count -gt 0) {
        & git add -f -- $rel
    }
}

function Commit-Artifacts {
    param([string] $Message, [switch] $IncludeHandoff)
    Normalize-TextArtifacts
    & git diff --check
    if ($LASTEXITCODE -ne 0) {
        throw "git diff --check failed"
    }
    Add-Artifacts -IncludeHandoff:$IncludeHandoff
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
    $stageB = if ($null -ne $state -and $null -ne $state.stage_b) { [string]$state.stage_b.status } else { "NOT_RUN" }
    $stageC = if ($null -ne $state -and $null -ne $state.stage_c) { [string]$state.stage_c.status } else { "NOT_RUN" }
    $stageD = if ($null -ne $state -and $null -ne $state.stage_d) { [string]$state.stage_d.status } else { "NOT_RUN" }
    $pillars = if ($null -ne $state -and $null -ne $state.pillar_summary) {
        "QUALITY=$($state.pillar_summary.DR_PILLAR_QUALITY), EFFICIENCY=$($state.pillar_summary.DR_PILLAR_EFFICIENCY), DYNAMIC=$($state.pillar_summary.DR_PILLAR_DYNAMIC)"
    } else {
        "QUALITY=UNKNOWN, EFFICIENCY=UNKNOWN, DYNAMIC=UNKNOWN"
    }
    $head = (& git rev-parse --short HEAD).Trim()
    $marker = "[x86/Track23-D2 resume closeout]"
    $entry = @(
        "- $(Get-Date -Format 'yyyy-MM-dd') $marker Final status `$status`: $reason",
        "  - Stage status: B `$stageB`; C `$stageC`; D `$stageD`; E `$status`.",
        "  - Pillars: $pillars.",
        "  - Evidence dir: `solver/reports/dr_alns_ppo_v3/final_track23/`; key files `stage_b_carbon_scenario_knobs.csv`, `stage_c24_no_tuning_parity_rows.csv`, `stage_d_dynamic_summary.json`, `final_report.md`, `track23_final_report.json`.",
        "  - HEAD when appending this run log: `$head`; no push/rebase/prune."
    ) -join "`n"
    $old = [System.IO.File]::ReadAllText($HandoffPath)
    if ($old.Contains($marker)) {
        Write-ControllerLog "HANDOFF already contains Track23-D2 run log marker; skip append"
        return
    }
    [System.IO.File]::WriteAllText($HandoffPath, $old.TrimEnd() + "`n" + $entry + "`n", [System.Text.UTF8Encoding]::new($false))
}

Set-Location -LiteralPath $Repo
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$env:PYTHONPATH = "$Repo\solver\src;$Repo\models\src;$Repo\solver\rl"
$env:SETP_WORKER_PYTHON = $Worker
Write-ControllerLog "Track23-D2 controller start repo=$Repo runner=$Runner worker=$Worker"

$records = @()
$stopReason = ""
foreach ($stage in $Stages) {
    $elapsed = [int]((Get-Date) - $Started).TotalSeconds
    if ($elapsed -ge $MaxSeconds) {
        $stopReason = "HALT_TRACK23_D2_CONTROLLER_WALLTIME before stage $stage elapsed=$elapsed max=$MaxSeconds"
        Write-ControllerLog $stopReason
        break
    }
    Write-ControllerLog "START stage=$stage elapsed=$elapsed"
    $stageStdout = Join-Path $OutputDir ("track23_d2_stage_{0}.stdout.log" -f $stage)
    $stageStderr = Join-Path $OutputDir ("track23_d2_stage_{0}.stderr.log" -f $stage)
    $stageStart = Get-Date
    $stdout = & $Runner -m dr_alns_ppo.track23_standing run --stages $stage --worker-python $Worker 2> $stageStderr
    $exitCode = $LASTEXITCODE
    $stdout | Out-File -LiteralPath $stageStdout -Encoding UTF8
    $duration = [int]((Get-Date) - $stageStart).TotalSeconds
    $state = Read-JsonOrNull $StatePath
    $stageStatus = Get-StageStatus -Stage $stage -State $state
    Write-ControllerLog "END stage=$stage exit=$exitCode duration=$duration status=$stageStatus"
    $records += [pscustomobject]([ordered]@{
        stage = $stage
        exit_code = $exitCode
        duration_seconds = $duration
        status = $stageStatus
        elapsed_seconds = [int]((Get-Date) - $Started).TotalSeconds
    })
    Write-Json $ControllerStatus ([ordered]@{
        started = $Started.ToString("o")
        updated = (Get-Date).ToString("o")
        max_seconds = $MaxSeconds
        records = $records
        stop_reason = $stopReason
    })
    Commit-Artifacts "[x86/DR] Track23-D2 Stage $stage results"
    if ($exitCode -ne 0) {
        $final = Read-JsonOrNull $FinalReportJson
        $finalStatus = if ($null -ne $final -and $null -ne $final.final_status) { [string]$final.final_status } else { "NO_FINAL_STATUS" }
        $stopReason = "HALT after stage $stage exit=$exitCode final_status=$finalStatus"
        Write-ControllerLog $stopReason
        break
    }
}

Write-Json $ControllerStatus ([ordered]@{
    started = $Started.ToString("o")
    updated = (Get-Date).ToString("o")
    max_seconds = $MaxSeconds
    records = $records
    stop_reason = $stopReason
})
Append-HandoffRunLog
Commit-Artifacts "[x86/DR] Finalize Track23-D2 standing report" -IncludeHandoff
Write-ControllerLog "Track23-D2 controller finish stop_reason=$stopReason"
