param(
    [string]$EnvFile = "$PSScriptRoot\..\.env.local"
)

if (-not (Test-Path $EnvFile)) {
    Write-Error "Env file not found: $EnvFile"
    Write-Host "Copy .env.local.example to .env.local and fill the values."
    exit 1
}

Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) {
        return
    }
    [System.Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}

Write-Host "Loaded environment variables from $EnvFile"
