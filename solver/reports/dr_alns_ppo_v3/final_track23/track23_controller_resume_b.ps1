$ErrorActionPreference = "Stop"
$Repo = "D:\ReSETP"
$Runner = "C:\Users\zlxshu\.venvs\resetp-ppo-cu124-py312\Scripts\python.exe"
$Worker = "C:\Users\zlxshu\.venvs\resetp-solver-py313\Scripts\python.exe"
$env:PYTHONPATH = "D:\ReSETP\solver\src;D:\ReSETP\models\src;D:\ReSETP\solver\rl"
$env:SETP_WORKER_PYTHON = $Worker
$OutputDir = Join-Path $Repo "solver\reports\dr_alns_ppo_v3\final_track23"
$Progress = Join-Path $OutputDir "track23_progress.log"
$ControllerLog = Join-Path $OutputDir "track23_controller_resume_b.log"
$ControllerStatus = Join-Path $OutputDir "track23_controller_resume_b_status.json"
$StatePath = Join-Path $OutputDir "track23_state.json"
$FinalReportJson = Join-Path $OutputDir "track23_final_report.json"
$Stages = @("B", "C", "D", "E")
$MaxSeconds = 26 * 3600
$Started = Get-Date
Set-Location -LiteralPath $Repo
function Write-ControllerLog { param([string] $Message) Add-Content -LiteralPath $ControllerLog -Value (("{0}`t{1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message)) -Encoding UTF8 }
function Read-JsonOrNull { param([string] $Path) if (-not (Test-Path -LiteralPath $Path)) { return $null }; return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
function Write-Json { param([string] $Path, [object] $Payload) $json = ($Payload | ConvertTo-Json -Depth 20) -replace "`r`n", "`n"; [System.IO.File]::WriteAllText($Path, $json + "`n", [System.Text.UTF8Encoding]::new($false)) }
function Get-StageStatus { param([string] $Stage, [object] $State)
    if ($null -eq $State) { return "NO_STATE" }
    $key = switch ($Stage) { "B" { "stage_b" } "C" { "stage_c" } "D" { "stage_d" } "E" { "final_status" } default { "" } }
    if ($Stage -eq "E") { if ($null -eq $State.final_status) { return "UNKNOWN" }; return [string]$State.final_status }
    $prop = $State.PSObject.Properties[$key]
    if ($null -eq $prop -or $null -eq $prop.Value) { return "NOT_RUN" }
    if ($null -eq $prop.Value.status) { return "UNKNOWN" }
    return [string]$prop.Value.status
}
function Normalize-TextArtifacts {
    $files = @()
    $files += Get-ChildItem -LiteralPath $OutputDir -File -Include *.csv,*.json,*.md,*.ps1 -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath (Join-Path $OutputDir "stage_d_track18")) { $files += Get-ChildItem -LiteralPath (Join-Path $OutputDir "stage_d_track18") -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue }
    $files += Get-ChildItem -LiteralPath $OutputDir -Directory -Filter "stage_d_track20_*" -ErrorAction SilentlyContinue | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue }
    foreach ($file in $files) { $text = [System.IO.File]::ReadAllText($file.FullName); $text = $text -replace "`r`n", "`n"; $text = $text -replace "`r", "`n"; $lines = $text -split "`n", -1; $lines = $lines | ForEach-Object { $_ -replace '[ \t]+$', '' }; $text = ($lines -join "`n"); if (-not $text.EndsWith("`n")) { $text += "`n" }; [System.IO.File]::WriteAllText($file.FullName, $text, [System.Text.UTF8Encoding]::new($false)) }
}
function Add-Artifacts {
    $files = @()
    $files += Get-ChildItem -LiteralPath $OutputDir -File -Include *.csv,*.json,*.md,*.ps1 -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath (Join-Path $OutputDir "stage_d_track18")) { $files += Get-ChildItem -LiteralPath (Join-Path $OutputDir "stage_d_track18") -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue }
    $files += Get-ChildItem -LiteralPath $OutputDir -Directory -Filter "stage_d_track20_*" -ErrorAction SilentlyContinue | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File -Include *.csv,*.json,*.md -ErrorAction SilentlyContinue }
    $rel = @($files | Sort-Object FullName -Unique | ForEach-Object { Resolve-Path -LiteralPath $_.FullName -Relative })
    if ($rel.Count -gt 0) { & git add -f -- $rel }
}
function Commit-Artifacts { param([string] $Message)
    Normalize-TextArtifacts
    & git diff --check
    if ($LASTEXITCODE -ne 0) { throw "git diff --check failed" }
    Add-Artifacts
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) { Write-ControllerLog "No staged artifact changes for commit: $Message"; return }
    & git commit -m $Message
    if ($LASTEXITCODE -ne 0) { throw "git commit failed for $Message" }
}
$records = @()
$stopReason = ""
Write-ControllerLog "Track23 resume-B controller start"
foreach ($stage in $Stages) {
    $elapsed = [int]((Get-Date) - $Started).TotalSeconds
    if ($elapsed -ge $MaxSeconds) { $stopReason = "HALT_TRACK23_RESUME_CONTROLLER_WALLTIME before stage $stage elapsed=$elapsed max=$MaxSeconds"; Write-ControllerLog $stopReason; break }
    Write-ControllerLog "START stage=$stage elapsed=$elapsed"
    $stageStdout = Join-Path $OutputDir ("track23_stage_{0}.stdout.log" -f $stage)
    $stageStderr = Join-Path $OutputDir ("track23_stage_{0}.stderr.log" -f $stage)
    $stageStart = Get-Date
    $stdout = & $Runner -m dr_alns_ppo.track23_standing run --stages $stage --worker-python $Worker 2> $stageStderr
    $exitCode = $LASTEXITCODE
    $stdout | Out-File -LiteralPath $stageStdout -Encoding UTF8
    $duration = [int]((Get-Date) - $stageStart).TotalSeconds
    $state = Read-JsonOrNull $StatePath
    $stageStatus = Get-StageStatus -Stage $stage -State $state
    Write-ControllerLog "END stage=$stage exit=$exitCode duration=$duration status=$stageStatus"
    $records += [pscustomobject]([ordered]@{ stage=$stage; exit_code=$exitCode; duration_seconds=$duration; status=$stageStatus; elapsed_seconds=[int]((Get-Date)-$Started).TotalSeconds })
    Write-Json $ControllerStatus ([ordered]@{ started=$Started.ToString("o"); updated=(Get-Date).ToString("o"); max_seconds=$MaxSeconds; records=$records; stop_reason=$stopReason })
    Commit-Artifacts "[x86/DR] Track23 Stage $stage results"
    if ($exitCode -ne 0) { $final = Read-JsonOrNull $FinalReportJson; $finalStatus = if ($null -ne $final -and $null -ne $final.final_status) { [string]$final.final_status } else { "NO_FINAL_STATUS" }; $stopReason = "HALT after stage $stage exit=$exitCode final_status=$finalStatus"; Write-ControllerLog $stopReason; break }
}
Write-Json $ControllerStatus ([ordered]@{ started=$Started.ToString("o"); updated=(Get-Date).ToString("o"); max_seconds=$MaxSeconds; records=$records; stop_reason=$stopReason })
Commit-Artifacts "[x86/DR] Finalize Track23 standing report"
Write-ControllerLog "Track23 resume-B controller finish stop_reason=$stopReason"