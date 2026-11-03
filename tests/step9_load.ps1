# PLAN step 9: drive one Locust load point against the Tier 2 ALB
# (ARCHITECTURE.md 8.4 experiments E0 / E5a / E5b, method in 5.3.3-5.3.4).
#
# What it does
#   1. Builds the Locust command for the chosen experiment and run id.
#   2. Runs locust headless at a fixed total rate (users x LOCUST_RPS_PER_USER),
#      writing its CSV + HTML into results/<experiment>/<run_id>/.
#   3. Writes meta.json (git SHA, image tag, rate, host, network, HC settings)
#      and records the per-instance tally the locustfile emits (served_by.json).
#   4. Prints the follow-up fetch_metrics.py command so the ALB/ASG server-side
#      metrics are pulled for the same window (the numbers the report quotes).
#
# This script does NOT change capacity or scaling. Set the ASG desired count and
# turn scaling off/on in AWS first (ARCHITECTURE.md 5.3.3), e.g. Jeel runs:
#   E0  : min=desired=max=1, scaling policy removed/suspended
#   E5a : min=max=desired=N (N=1, then N=2), scaling suspended
#   E5b : min 1 / desired 1 / max 2, scaling policy ACTIVE; this script just
#         steps the load, the policy does the 1 -> 2
#
# Preconditions (not checked here)
#   - envs/tier2 is applied by Jeel; he shares `terraform output -raw alb_dns_name`
#     and asg_name (HANDOFF.md 3, infra/envs/tier2/README.md).
#   - R_max from E0 is known before E5a/E5b, so you can set the rates (5.3.4).
#   - python with tests/requirements.txt installed (locust==2.47.0); laptop on
#     wired or a quiet Wi-Fi, VPN/backups/updates off (5.3.4 validity checks).
#
# Usage
#   # E0 calibration ramp on one instance, 10 -> target over the run:
#   .\tests\step9_load.ps1 -Experiment e0 -RunNumber 1 -RunLabel ramp `
#       -AlbDns <alb-dns> -ImageTag <sha> -Users 40 -RpsPerUser 10 `
#       -SpawnRate 0.5 -RunTime 10m -Network wired
#
#   # E5a fixed-capacity point at N=2 instances, 0.9 x R_max:
#   .\tests\step9_load.ps1 -Experiment e5a -RunNumber 2 -RunLabel n2 `
#       -AlbDns <alb-dns> -ImageTag <sha> -Users 18 -RpsPerUser 10 -RunTime 5m
#
#   # E5b autoscaling step (step the rate up; hold; then rerun lower to scale in):
#   .\tests\step9_load.ps1 -Experiment e5b -RunNumber 1 -RunLabel step-up `
#       -AlbDns <alb-dns> -ImageTag <sha> -Users 16 -RpsPerUser 10 -RunTime 10m

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('e0', 'e5a', 'e5b')]
    [string] $Experiment,

    [Parameter(Mandatory = $true)][ValidateRange(1, 99)]
    [int] $RunNumber,

    # Free-form target label for the run id, e.g. 'n1', 'n2', 'ramp', 'step-up'.
    # The run id becomes <experiment>-r<NN>-<RunLabel> (CONTRIBUTING.md).
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]*$')]
    [string] $RunLabel,

    [Parameter(Mandatory = $true)]
    [string] $AlbDns,

    [Parameter(Mandatory = $true)]
    [string] $ImageTag,

    # Load shape. Total target rate = Users x RpsPerUser (ARCHITECTURE.md 5.3.4).
    [Parameter(Mandatory = $true)][ValidateRange(1, 5000)]
    [int] $Users,

    [double] $RpsPerUser = 10.0,

    # Users spawned per second. For a step (E5b) keep this high so the step is
    # sharp; for a slow ramp (E0) use a fraction, e.g. 0.5 users/s.
    [double] $SpawnRate = 0,

    [Parameter(Mandatory = $true)]
    [string] $RunTime,

    [string] $Endpoint = '/api/v1/authenticate',
    [ValidateSet('otp', 'demo')][string] $Factor = 'otp',

    [string] $ClientLocation = '',
    [ValidateSet('wired', 'wifi', 'other')][string] $Network = 'other'
)

$ErrorActionPreference = 'Stop'

$runId = ('{0}-r{1:d2}-{2}' -f $Experiment, $RunNumber, $RunLabel)
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$locustfile = Join-Path $PSScriptRoot 'locustfile.py'
$resultsDir = Join-Path $repoRoot 'results'
$runDir = Join-Path $resultsDir (Join-Path $Experiment $runId)
$albUrl = ('http://{0}' -f $AlbDns)          # no trailing slash; endpoint carries it
$targetRate = [math]::Round($Users * $RpsPerUser, 2)

if ($SpawnRate -le 0) { $SpawnRate = $Users }   # default: all users at once (a step)

# Raw results are never overwritten (CONTRIBUTING.md).
if (Test-Path (Join-Path $runDir 'locust_stats.csv')) {
    throw "locust_stats.csv already exists under $runDir. Pick a new -RunNumber."
}
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

if (-not (Get-Command locust -ErrorAction SilentlyContinue)) {
    throw "locust not on PATH. Activate the tests venv and 'pip install -r tests/requirements.txt'."
}

$csvPrefix = Join-Path $runDir 'locust'
$htmlPath = Join-Path $runDir 'locust.html'
$tallyPath = Join-Path $runDir 'served_by.json'

$startUtc = [DateTime]::UtcNow

Write-Host ''
Write-Host "step 9 load run: $runId" -ForegroundColor Cyan
Write-Host "  host      : $albUrl$Endpoint  (factor $Factor)"
Write-Host "  users     : $Users at $RpsPerUser req/s each  => target $targetRate req/s"
Write-Host "  spawn rate: $SpawnRate users/s"
Write-Host "  run time  : $RunTime"
Write-Host "  out       : $runDir"
Write-Host ''
Write-Host "Reminder: set ASG capacity / scaling for $Experiment in AWS first (5.3.3)." -ForegroundColor Yellow
Write-Host ''

# The locustfile reads these from the environment.
$env:LOCUST_RPS_PER_USER = "$RpsPerUser"
$env:LOCUST_ENDPOINT = $Endpoint
$env:LOCUST_FACTOR = $Factor
$env:LOCUST_TALLY_OUT = $tallyPath

$locustArgs = @(
    '-f', $locustfile,
    '--headless',
    '--host', $albUrl,
    '--users', $Users,
    '--spawn-rate', $SpawnRate,
    '--run-time', $RunTime,
    '--csv', $csvPrefix,
    '--csv-full-history',
    '--html', $htmlPath,
    '--only-summary'
)

Push-Location $repoRoot
try {
    & locust @locustArgs
    $locustExit = $LASTEXITCODE
}
finally {
    Pop-Location
    Remove-Item Env:\LOCUST_TALLY_OUT -ErrorAction SilentlyContinue
}

$endUtc = [DateTime]::UtcNow

# meta.json, same spirit as the prober's (tests/README.md). Times in UTC ms so
# fetch_metrics.py can read the window straight out of it.
$meta = [ordered]@{
    run_id            = $runId
    experiment        = $Experiment
    tool              = 'locust'
    host              = $albUrl
    endpoint          = $Endpoint
    factor            = $Factor
    users             = $Users
    rps_per_user      = $RpsPerUser
    target_rate_per_s = $targetRate
    spawn_rate        = $SpawnRate
    run_time          = $RunTime
    image_tag         = $ImageTag
    client_location   = $ClientLocation
    client_network    = $Network
    git_sha           = (& git -C $repoRoot rev-parse --short HEAD 2>$null)
    locust_version    = ((& locust --version 2>$null) -join ' ')
    locust_exit_code  = $locustExit
    started_utc_ms    = [long]([DateTimeOffset]$startUtc).ToUnixTimeMilliseconds()
    ended_utc_ms      = [long]([DateTimeOffset]$endUtc).ToUnixTimeMilliseconds()
    written_utc       = $endUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
    note              = 'Set ASG capacity/scaling in AWS before the run (5.3.3). Validity: achieved rate within 5% of target, no Locust CPU warnings (5.3.4).'
}
$metaPath = Join-Path $runDir 'meta.json'
($meta | ConvertTo-Json -Depth 5) | Out-File -FilePath $metaPath -Encoding utf8

Write-Host ''
if ($locustExit -ne 0) {
    Write-Warning "locust exited $locustExit. Check the summary above; the run may be invalid."
}
Write-Host 'Done. Validity checks (ARCHITECTURE.md 5.3.4):' -ForegroundColor Green
Write-Host '  - achieved req/s in locust_stats.csv within 5% of ' -NoNewline
Write-Host "$targetRate"
Write-Host '  - no Locust CPU-bound warnings above'
Write-Host "  - served_by.json shows the expected number of instances"
Write-Host ''
Write-Host 'Now pull the server-side metrics for this window (needs Tier 2 ARNs):' -ForegroundColor Green
Write-Host ('  python tests\fetch_metrics.py --run-dir "{0}" --region ap-south-1 `' -f $runDir)
Write-Host '      --alb app/aadhaar-tier2-alb/<id> --target-group targetgroup/aadhaar-tier2-tg/<id> `'
Write-Host '      --asg <asg_name>'
Write-Host ''
Write-Host 'When all points for an experiment are in, build the charts:'
Write-Host '  python analysis\analyze_load.py --experiment ' -NoNewline
Write-Host "$Experiment"
