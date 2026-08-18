param(
    [ValidatePattern('^[a-z0-9][a-z0-9_-]*-test$')]
    [string]$ProjectName = 'placepulse-persistence-test',
    [switch]$Cleanup
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

foreach ($secretName in @(
    'PLACEPULSE_POSTGRES_PASSWORD',
    'PLACEPULSE_REDIS_PASSWORD',
    'PLACEPULSE_SEED_PASSWORD'
)) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($secretName))) {
        throw "Set $secretName before running this isolated persistence check."
    }
}

$compose = @(
    'compose', '-p', $ProjectName,
    '-f', 'deploy/compose.yml',
    '-f', 'deploy/compose.test.yml'
)

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & docker @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed: $($Arguments -join ' ')"
    }
}

function Read-ComposeValue {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $output = & docker @compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose query failed: $($Arguments -join ' ')"
    }
    return ($output | Out-String).Trim()
}

try {
    Invoke-Compose up -d --wait postgres redis
    Invoke-Compose up --no-deps bootstrap

    $placeCountBefore = Read-ComposeValue exec -T postgres sh -ec 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM places WHERE osm_type = ''way'' AND osm_id = 66098525"'
    if ($placeCountBefore -ne '1') {
        throw "Expected one seeded campus row before restart; found $placeCountBefore."
    }

    $redisSet = Read-ComposeValue exec -T redis sh -ec 'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; redis-cli --user "$PLACEPULSE_REDIS_USER" SET placepulse:test:persistence survived'
    if ($redisSet -ne 'OK') {
        throw 'Could not create the Redis persistence probe.'
    }

    Invoke-Compose restart postgres redis
    Invoke-Compose up -d --wait postgres redis

    $placeCountAfter = Read-ComposeValue exec -T postgres sh -ec 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM places WHERE osm_type = ''way'' AND osm_id = 66098525"'
    $redisAfter = Read-ComposeValue exec -T redis sh -ec 'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; redis-cli --user "$PLACEPULSE_REDIS_USER" GET placepulse:test:persistence'

    if ($placeCountAfter -ne '1' -or $redisAfter -ne 'survived') {
        throw 'PostgreSQL or Redis data did not survive a normal restart.'
    }

    Read-ComposeValue exec -T redis sh -ec 'export REDISCLI_AUTH="$(cat /run/secrets/redis_password)"; redis-cli --user "$PLACEPULSE_REDIS_USER" DEL placepulse:test:persistence' | Out-Null
    Write-Output 'PostgreSQL and Redis persistence checks passed.'
}
finally {
    if ($Cleanup) {
        Invoke-Compose down --volumes --remove-orphans
    }
}
