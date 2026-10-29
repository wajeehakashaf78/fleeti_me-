<#
One-time setup of pgvector for FLEETI RAG on the local PostgreSQL 18 (Windows).

Run in PowerShell **as Administrator**, from this folder:
    powershell -ExecutionPolicy Bypass -File .\setup_pgvector.ps1

What it does:
  1. Copies pgvector 0.8.1 (built from source for PostgreSQL 18 x64) into the Postgres folder.
  2. Creates a login role + database "fleeti_rag" (owned by that role) with a random password.
  3. Enables the "vector" extension in that database.
  4. Writes FLEETI_PG_DSN=... into the project's .env.
You are asked once for the existing "postgres" superuser password; it is not stored anywhere.
#>
#Requires -RunAsAdministrator
param(
    [string]$PgRoot = "C:\Program Files\PostgreSQL\18",
    [int]$Port = 0,   # 0 = read "port" from this PostgreSQL's postgresql.conf
    [string]$Database = "fleeti_rag",
    [string]$Role = "fleeti_rag"
)
$ErrorActionPreference = "Stop"
if ($Port -eq 0) {
    $conf = Join-Path $PgRoot "data\postgresql.conf"
    $m = Select-String -Path $conf -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    $Port = if ($m) { [int]$m.Matches[0].Groups[1].Value } else { 5432 }
}
Write-Host "Using PostgreSQL at $PgRoot on port $Port"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$envFile = Join-Path (Split-Path -Parent (Split-Path -Parent $here)) ".env"
$psql = Join-Path $PgRoot "bin\psql.exe"

Write-Host "1/4 Installing pgvector files into $PgRoot"
Copy-Item (Join-Path $here "vector.dll") (Join-Path $PgRoot "lib") -Force
Copy-Item (Join-Path $here "vector.control") (Join-Path $PgRoot "share\extension") -Force
Copy-Item (Join-Path $here "sql\vector--*.sql") (Join-Path $PgRoot "share\extension") -Force

$secure = Read-Host "Password of the 'postgres' user" -AsSecureString
$env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

function Invoke-Psql([string]$db, [string]$sql) {
    $out = & $psql -h localhost -p $Port -U postgres -d $db -v ON_ERROR_STOP=1 -tAc $sql
    if ($LASTEXITCODE -ne 0) { throw "psql failed: $sql" }
    return $out
}

try {
    Write-Host "2/4 Creating role '$Role' and database '$Database'"
    $rolePassword = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 28 | ForEach-Object { [char]$_ })
    if (Invoke-Psql "postgres" "SELECT 1 FROM pg_roles WHERE rolname = '$Role'") {
        Invoke-Psql "postgres" "ALTER ROLE $Role WITH LOGIN PASSWORD '$rolePassword'" | Out-Null
    } else {
        Invoke-Psql "postgres" "CREATE ROLE $Role LOGIN PASSWORD '$rolePassword'" | Out-Null
    }
    if (-not (Invoke-Psql "postgres" "SELECT 1 FROM pg_database WHERE datname = '$Database'")) {
        Invoke-Psql "postgres" "CREATE DATABASE $Database OWNER $Role" | Out-Null
    }

    Write-Host "3/4 Enabling the vector extension"
    Invoke-Psql $Database "CREATE EXTENSION IF NOT EXISTS vector" | Out-Null
    $version = Invoke-Psql $Database "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    Write-Host "    pgvector version: $version"
}
finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host "4/4 Writing FLEETI_PG_DSN to $envFile"
$dsn = "FLEETI_PG_DSN=postgresql://${Role}:${rolePassword}@localhost:${Port}/${Database}"
$lines = @()
if (Test-Path $envFile) { $lines = @(Get-Content $envFile | Where-Object { $_ -notmatch '^FLEETI_PG_DSN=' }) }
$lines += $dsn
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding $false))

Write-Host ""
Write-Host "Done. Next, build the RAG index from the project folder:"
Write-Host "    ..\venv\Scripts\python.exe -m FleetDbSummarizer.rag.build_index"
