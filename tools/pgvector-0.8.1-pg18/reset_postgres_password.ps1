<#
Reset the password of the local PostgreSQL 18 "postgres" superuser, when it is forgotten.

Run in PowerShell **as Administrator**, from this folder:
    powershell -ExecutionPolicy Bypass -File .\reset_postgres_password.ps1

How it works:
  1. Backs up pg_hba.conf, then temporarily allows password-less logins from THIS machine only.
  2. Restarts PostgreSQL and sets the new password you type.
  3. Restores the original pg_hba.conf and restarts PostgreSQL again (also if a step fails).
Other programs using this PostgreSQL are disconnected for a few seconds during the restarts.
#>
#Requires -RunAsAdministrator
param(
    [string]$PgRoot = "C:\Program Files\PostgreSQL\18",
    [string]$Service = "postgresql-x64-18",
    [int]$Port = 0   # 0 = read "port" from this PostgreSQL's postgresql.conf
)
$ErrorActionPreference = "Stop"
if ($Port -eq 0) {
    $conf = Join-Path $PgRoot "data\postgresql.conf"
    $m = Select-String -Path $conf -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    $Port = if ($m) { [int]$m.Matches[0].Groups[1].Value } else { 5432 }
}
Write-Host "Using PostgreSQL at $PgRoot on port $Port"
$hba = Join-Path $PgRoot "data\pg_hba.conf"
$backup = "$hba.fleeti-backup"
$psql = Join-Path $PgRoot "bin\psql.exe"

$new1 = Read-Host "New password for 'postgres'" -AsSecureString
$new2 = Read-Host "Repeat the new password" -AsSecureString
$plain = { param($s) [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)) }
$pw = & $plain $new1
if ($pw -ne (& $plain $new2)) { throw "The two passwords do not match - nothing was changed." }
if ($pw.Length -lt 8) { throw "Use at least 8 characters - nothing was changed." }

Copy-Item $hba $backup -Force
try {
    Write-Host "1/3 Temporarily allowing local password-less login"
    $original = Get-Content $hba
    $trust = @("host all postgres 127.0.0.1/32 trust", "host all postgres ::1/128 trust")
    [IO.File]::WriteAllLines($hba, $trust + $original, (New-Object Text.ASCIIEncoding))
    Restart-Service $Service -Force

    Write-Host "2/3 Setting the new password"
    $escaped = $pw.Replace("'", "''")
    & $psql -h localhost -p $Port -U postgres -d postgres -v ON_ERROR_STOP=1 -c "ALTER USER postgres WITH PASSWORD '$escaped'" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not set the password." }
}
finally {
    Write-Host "3/3 Restoring the original login rules"
    Copy-Item $backup $hba -Force
    Remove-Item $backup -Force
    Restart-Service $Service -Force
}
Write-Host "Done. Now run setup_pgvector.ps1 again and use the new password."
