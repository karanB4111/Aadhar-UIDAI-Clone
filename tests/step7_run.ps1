# PLAN step 7: drive one failover run against the Tier 1 ALB
# (ARCHITECTURE.md 8.4 experiments E1 / E1b / E2 and the method in 8.5).
#
# What it does
#   1. Reads the ALB DNS and target instance id (passed in).
#   2. Writes SSM parameter JSON files into the run dir (needed because PS /
#      cmd.exe both strip inner double quotes from --parameters inline).
#   3. Starts tests/prober.py at 20 req/s on the schedule below.
#   4. At t = $InjectAt injects:
#      - E1 / E1b : aws ssm send-command ... docker stop aadhaar-mock
#      - E2       : aws ec2 stop-instances
#   5. At t = $RestoreAt restores (docker start / ec2 start).
#   6. Prober stops at t = $Duration and writes CSVs + meta.json to
#      results/<experiment>/<run_id>/ (CONTRIBUTING.md).
#
# Preconditions (not checked here; the prober fails fast otherwise)
#   - envs/tier1 is applied (fast health-checks for E1/E2, or with
#     terraform.tfvars.e1b for E1b). Jeel runs these; see HANDOFF.md 4.
#   - $env:AWS_PROFILE is set to a profile that can SSM / EC2 the Tier 1
#     instances (HANDOFF.md 2).
#   - aws, python on PATH; laptop clock NTP-synced (ARCHITECTURE.md 8.3).
#
# Usage
#   $env:AWS_PROFILE = 'aadhaar'
#   .\tests\step7_run.ps1 `
#       -Experiment e1 -RunNumber 1 -TargetAz a `
#       -InstanceId i-0abc... -AlbDns <alb-dns> -ImageTag <sha>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('e1', 'e1b', 'e2')]
    [string] $Experiment,

    [Parameter(Mandatory = $true)][ValidateRange(1, 99)]
    [int] $RunNumber,

    [Parameter(Mandatory = $true)][ValidateSet('a', 'b')]
    [string] $TargetAz,

    [Parameter(Mandatory = $true)]
    [string] $InstanceId,

    [Parameter(Mandatory = $true)]
    [string] $AlbDns,

    [Parameter(Mandatory = $true)]
    [string] $ImageTag,

    # Experiment timing. Defaults match ARCHITECTURE.md 8.4 / 8.5.
    # E1b needs a longer window (detection 30-60 s); pass -Duration 300
    # -RestoreAt 180.
    [int] $Duration = 180,
    [int] $InjectAt = 30,
    [int] $RestoreAt = 120,
    [double] $Rate = 20.0,

    [string] $Region = 'ap-south-1',
    [string] $ClientLocation = '',
    [ValidateSet('wired', 'wifi', 'other')][string] $Network = 'other'
)

$ErrorActionPreference = 'Stop'

$runId = ('{0}-r{1:d2}-az-{2}' -f $Experiment, $RunNumber, $TargetAz)
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$prober = Join-Path $PSScriptRoot 'prober.py'
$resultsDir = Join-Path $repoRoot 'results'
$runDir = Join-Path $resultsDir (Join-Path $Experiment $runId)
$albUrl = ('http://{0}/' -f $AlbDns)

if (Test-Path (Join-Path $runDir 'prober.csv')) {
    throw "prober.csv already exists under $runDir. Pick a new -RunNumber."
}

# Ensure the run dir exists so we can drop the SSM parameter files into it;
# the prober will create it too, but we need it a step earlier.
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

if (-not $env:AWS_PROFILE -or $env:AWS_PROFILE -eq '') {
    Write-Warning 'AWS_PROFILE is not set; the aws CLI will use its default profile.'
}

# Build inject / restore commands. For SSM we materialise the --parameters
# JSON into a file next to prober.csv and reference it as file:// — inline
# JSON gets mangled by PowerShell / cmd.exe quoting on Windows.
function Write-SsmParams($Path, $Shell) {
    $json = '{"commands":["' + $Shell + '"]}'
    [System.IO.File]::WriteAllText($Path, $json, [System.Text.Encoding]::ASCII)
}

switch ($Experiment) {
    { $_ -eq 'e1' -or $_ -eq 'e1b' } {
        $injectParams = Join-Path $runDir 'ssm-inject.json'
        $restoreParams = Join-Path $runDir 'ssm-restore.json'
        Write-SsmParams $injectParams 'docker stop aadhaar-mock'
        Write-SsmParams $restoreParams 'docker start aadhaar-mock'
        $injectCmd = ('aws ssm send-command --region {0} --document-name AWS-RunShellScript --instance-ids {1} --parameters file://{2} --query Command.CommandId --output text' -f $Region, $InstanceId, $injectParams.Replace('\','/'))
        $restoreCmd = ('aws ssm send-command --region {0} --document-name AWS-RunShellScript --instance-ids {1} --parameters file://{2} --query Command.CommandId --output text' -f $Region, $InstanceId, $restoreParams.Replace('\','/'))
    }
    'e2' {
        # Instance stop/start cycle. user_data runs only on first boot, so
        # after start-instances the container does NOT auto-restart. The
        # chain driver (tests/step7_e2_chain.ps1) issues
        # `docker start aadhaar-mock` via SSM after the health gate, so the
        # restore here just fires the start API; the recorded restore
        # timestamp is close to the API accept, which is good enough for
        # the error-window measurement that matters for E2.
        $injectCmd = ('aws ec2 stop-instances --region {0} --instance-ids {1} --query StoppingInstances[0].CurrentState.Name --output text' -f $Region, $InstanceId)
        $restoreCmd = ('aws ec2 start-instances --region {0} --instance-ids {1} --query StartingInstances[0].CurrentState.Name --output text' -f $Region, $InstanceId)
    }
}

switch ($Experiment) {
    'e1b' {
        $hcInterval = 30; $hcTimeout = 5; $hcHealthy = 5; $hcUnhealthy = 2
    }
    default {
        $hcInterval = 5; $hcTimeout = 2; $hcHealthy = 2; $hcUnhealthy = 2
    }
}

Write-Host ''
Write-Host "step 7 run: $runId" -ForegroundColor Cyan
Write-Host "  ALB     : $albUrl"
Write-Host "  target  : $InstanceId (az $TargetAz, $Region)"
Write-Host "  rate    : $Rate req/s"
Write-Host "  schedule: inject at ${InjectAt}s, restore at ${RestoreAt}s, stop at ${Duration}s"
Write-Host "  hc      : interval=$hcInterval s, timeout=$hcTimeout s, healthy=$hcHealthy, unhealthy=$hcUnhealthy"
Write-Host "  out     : $runDir"
Write-Host ''

$proberArgs = @(
    $prober,
    $albUrl,
    '--run-id', $runId,
    '--rate', $Rate,
    '--duration', $Duration,
    '--image-tag', $ImageTag,
    '--network', $Network,
    '--meta', ('hc_interval_s=' + $hcInterval),
    '--meta', ('hc_timeout_s=' + $hcTimeout),
    '--meta', ('hc_healthy_threshold=' + $hcHealthy),
    '--meta', ('hc_unhealthy_threshold=' + $hcUnhealthy),
    '--meta', 'instance_type=t3.micro',
    '--meta', ('target_instance_id=' + $InstanceId),
    '--meta', ('target_az=' + $TargetAz),
    '--meta', ('experiment=' + $Experiment),
    '--action', $InjectAt, 'inject_start', $injectCmd,
    '--action', $RestoreAt, 'restore', $restoreCmd
)
if ($ClientLocation -ne '') {
    $proberArgs += @('--client-location', $ClientLocation)
}

Push-Location $repoRoot
try {
    & python @proberArgs
    if ($LASTEXITCODE -ne 0) {
        throw "prober exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host ''
Write-Host 'Done. Verify:' -ForegroundColor Green
Write-Host ('  python analysis\analyze.py --run-dir "{0}"' -f $runDir)
Write-Host ''
Write-Host 'When all 5 (E1/E2) or 3 (E1b) runs are in, commit the raw files and run'
Write-Host 'the full analyze step to produce summary.csv, aggregate.csv and charts/.'
