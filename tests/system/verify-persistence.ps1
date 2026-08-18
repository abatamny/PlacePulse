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

$databaseUser = [Environment]::GetEnvironmentVariable('PLACEPULSE_POSTGRES_USER')
if ([string]::IsNullOrWhiteSpace($databaseUser)) {
    $databaseUser = 'placepulse'
}
$databaseName = [Environment]::GetEnvironmentVariable('PLACEPULSE_POSTGRES_DB')
if ([string]::IsNullOrWhiteSpace($databaseName)) {
    $databaseName = 'placepulse'
}
$placeCountQuery = "SELECT count(*) FROM places WHERE osm_type = 'way' AND osm_id = 66098525"
$redisUser = [Environment]::GetEnvironmentVariable('PLACEPULSE_REDIS_USER')
if ([string]::IsNullOrWhiteSpace($redisUser)) {
    $redisUser = 'placepulse'
}
$redisAuthentication = "REDISCLI_AUTH=$([Environment]::GetEnvironmentVariable('PLACEPULSE_REDIS_PASSWORD'))"

$compose = @(
    'compose', '-p', $ProjectName,
    '-f', 'deploy/compose.yml',
    '-f', 'deploy/compose.test.yml'
)

function Invoke-Compose {
    $commandArguments = @($args)
    & docker @compose @commandArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose command failed.'
    }
}

function Read-ComposeValue {
    $commandArguments = @($args)
    $output = & docker @compose @commandArguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Docker Compose query failed.'
    }
    return ($output | Out-String).Trim()
}

try {
    Invoke-Compose up -d --wait postgres redis
    Invoke-Compose up --no-deps bootstrap

    $placeCountBefore = Read-ComposeValue exec -T postgres psql -U $databaseUser -d $databaseName -tAc $placeCountQuery
    if ($placeCountBefore -ne '1') {
        throw "Expected one seeded campus row before restart; found $placeCountBefore."
    }

    $redisSet = Read-ComposeValue exec -T -e $redisAuthentication redis redis-cli --user $redisUser SET placepulse:test:persistence survived
    if ($redisSet -ne 'OK') {
        throw 'Could not create the Redis persistence probe.'
    }

    Invoke-Compose restart postgres redis
    Invoke-Compose up -d --wait postgres redis

    $placeCountAfter = Read-ComposeValue exec -T postgres psql -U $databaseUser -d $databaseName -tAc $placeCountQuery
    $redisAfter = Read-ComposeValue exec -T -e $redisAuthentication redis redis-cli --user $redisUser GET placepulse:test:persistence

    if ($placeCountAfter -ne '1' -or $redisAfter -ne 'survived') {
        throw 'PostgreSQL or Redis data did not survive a normal restart.'
    }

    Read-ComposeValue exec -T -e $redisAuthentication redis redis-cli --user $redisUser DEL placepulse:test:persistence | Out-Null
    Write-Output 'PostgreSQL and Redis persistence checks passed.'
}
finally {
    if ($Cleanup) {
        Invoke-Compose down --volumes --remove-orphans
    }
}
