$ErrorActionPreference = "Stop"
$bashCandidates = @(
    (Join-Path $env:ProgramFiles "Git\bin\bash.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Git\bin\bash.exe")
)
$bash = $bashCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $bash) {
    throw "Git Bash не найден. Установите Git for Windows или запустите scripts/check.sh в другом Bash. WSL для этого не нужен."
}

$scriptPath = (Join-Path $PSScriptRoot "check.sh").Replace("\", "/")
& $bash $scriptPath
exit $LASTEXITCODE

