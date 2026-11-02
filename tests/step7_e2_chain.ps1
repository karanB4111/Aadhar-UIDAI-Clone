# Step 7 E2 chain: waits for BOTH ALB targets to be healthy before each run.
# Replaces the fixed-sleep chain used for E1 — an EC2 stop/start cycle takes
# 90-120 s plus ~60 s of user-data, longer than any safe fixed sleep.
#
# Each run: 240 s probe, inject at 30 s, restore at 150 s. Then poll ALB
# target health until both targets are `healthy` (up to 10 min) before the
# next run.

[CmdletBinding()]
param(
    [string] $AlbDns = 'aadhaar-tier1-alb-1335660658.ap-south-1.elb.amazonaws.com',
    [string] $ImageTag = '6cc656f',
    [string] $Region = 'ap-south-1',
    [string] $AzA = 'i-09e04fbc68955b460',
    [string] $AzB = 'i-010438766fd85a857',
    [int[]] $Runs = @(2, 3, 4, 5),       # r01 is already in; override to redo
    [int] $MaxWaitSeconds = 600,
    [int] $PollSeconds = 15
)

$ErrorActionPreference = 'Stop'
$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..')

if (-not $env:AWS_PROFILE) { throw 'Set $env:AWS_PROFILE first.' }

function Get-TargetHealth {
    param([string] $Region)
    $tgArn = aws elbv2 describe-target-groups --region $Region --query "TargetGroups[?contains(TargetGroupName,'aadhaar-tier1')].TargetGroupArn | [0]" --output text
    if (-not $tgArn -or $tgArn -eq 'None') { throw 'target group not found' }
    $raw = aws elbv2 describe-target-health --region $Region --target-group-arn $tgArn --query "TargetHealthDescriptions[].{Id:Target.Id,State:TargetHealth.State}" --output json
    return $raw | ConvertFrom-Json
}

function Wait-BothHealthy {
    param([int] $MaxWait, [int] $Poll, [string] $Region)
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $MaxWait) {
        try {
            $th = Get-TargetHealth -Region $Region
            $states = $th | ForEach-Object { "$($_.Id)=$($_.State)" }
            Write-Host ("    [{0,4:n0}s] {1}" -f ((Get-Date) - $t0).TotalSeconds, ($states -join ', '))
            $allHealthy = ($th.Count -ge 2) -and (-not ($th | Where-Object { $_.State -ne 'healthy' }))
            if ($allHealthy) { return $true }
        } catch {
            Write-Host "    (poll error: $_)"
        }
        Start-Sleep -Seconds $Poll
    }
    return $false
}

function Start-Container {
    # SSM `docker start aadhaar-mock` on both instances. user_data runs only
    # on the first boot, so after an E2 stop/start cycle the container is
    # not auto-launched.
    param([string] $Region, [string[]] $Ids)
    $json = Join-Path ([System.IO.Path]::GetTempPath()) 'ssm-docker-start.json'
    '{"commands":["docker start aadhaar-mock >/dev/null 2>&1 || true"]}' | Set-Content -Encoding ascii $json
    foreach ($id in $Ids) {
        # Retry up to ~2 min: SSM only accepts commands once the agent has
        # re-registered after the boot.
        $deadline = (Get-Date).AddSeconds(150)
        while ((Get-Date) -lt $deadline) {
            $cmd = aws ssm send-command --region $Region --document-name AWS-RunShellScript --instance-ids $id --parameters "file://$json" --query Command.CommandId --output text 2>$null
            if ($LASTEXITCODE -eq 0 -and $cmd) {
                Write-Host "    sent docker-start to $id ($cmd)"
                break
            }
            Start-Sleep -Seconds 5
        }
    }
}

Set-Location $repoRoot

# alternating pattern starting from r02 (b, a, b, a); if $Runs is overridden,
# derive AZ from run number parity (even -> b, odd -> a).
foreach ($r in $Runs) {
    $az = if ($r % 2 -eq 0) { 'b' } else { 'a' }
    $id = if ($az -eq 'a') { $AzA } else { $AzB }
    $runId = ('e2-r{0:d2}-az-{1}' -f $r, $az)

    # Before every run: make sure the container is up on both instances
    # (previous restore may have left it down because user_data doesn't
    # re-run), then wait for the ALB to confirm both targets healthy.
    Write-Host ''
    Write-Host "==== ${runId}: pre-run container start + health wait ====" -ForegroundColor Cyan
    Start-Container -Region $Region -Ids @($AzA, $AzB)
    if (-not (Wait-BothHealthy -MaxWait $MaxWaitSeconds -Poll $PollSeconds -Region $Region)) {
        Write-Error "Both targets did not become healthy within $MaxWaitSeconds s before ${runId}. Aborting chain."
        return
    }
    # 60 s extra buffer so the newly-healthy instance has settled.
    Start-Sleep -Seconds 60

    .\tests\step7_run.ps1 -Experiment e2 -RunNumber $r -TargetAz $az -InstanceId $id -AlbDns $AlbDns -ImageTag $ImageTag -Network wifi -ClientLocation "home, Gandhinagar" -Duration 240 -RestoreAt 150
}

# Final cleanup: once the chain finishes, bring the container back on the
# instance that was stopped by the last run, so the stack is left healthy.
Write-Host ''
Write-Host '==== post-chain: bringing containers back up ====' -ForegroundColor Cyan
Start-Container -Region $Region -Ids @($AzA, $AzB)
Wait-BothHealthy -MaxWait $MaxWaitSeconds -Poll $PollSeconds -Region $Region | Out-Null

Write-Host ''
Write-Host 'E2 chain finished. Run:' -ForegroundColor Green
Write-Host '  python analysis\analyze.py --experiment e2'
