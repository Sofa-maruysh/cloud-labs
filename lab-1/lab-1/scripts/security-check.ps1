$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$evidenceDir = Join-Path $root "evidence"
$resultFile = Join-Path $evidenceDir "security-check-run.txt"
$wordlistFile = Join-Path $root "security\wordlist.txt"
$lines = New-Object 'System.Collections.Generic.List[string]'
$findings = 0

function Add-ReportLine {
    param([string]$Text = "")
    Write-Host $Text
    $script:lines.Add($Text)
}

function Invoke-LocalRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$HostHeader = "localhost",
        [string]$Method = "GET",
        [switch]$PathAsIs
    )

    $headersFile = [System.IO.Path]::GetTempFileName()
    $bodyFile = [System.IO.Path]::GetTempFileName()
    $errorFile = [System.IO.Path]::GetTempFileName()

    try {
        $arguments = @(
            "-k", "-sS", "--noproxy", "*",
            "--connect-timeout", "3", "--max-time", "10",
            "-D", $headersFile, "-o", $bodyFile,
            "-w", "%{http_code}",
            "-X", $Method,
            "-H", "Host: $HostHeader"
        )
        if ($PathAsIs) {
            $arguments += "--path-as-is"
        }
        $arguments += "https://127.0.0.1$Path"

        $statusOutput = (& curl.exe @arguments 2> $errorFile | Out-String).Trim()
        $curlExitCode = $LASTEXITCODE
        $headers = Get-Content -LiteralPath $headersFile -Raw -ErrorAction SilentlyContinue
        $body = Get-Content -LiteralPath $bodyFile -Raw -ErrorAction SilentlyContinue
        $curlError = Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue

        $statusCode = 0
        if ($statusOutput -match '(\d{3})$') {
            $statusCode = [int]$Matches[1]
        }

        return [pscustomobject]@{
            Status = $statusCode
            Headers = [string]$headers
            Body = [string]$body
            ExitCode = $curlExitCode
            Error = [string]$curlError
        }
    }
    finally {
        Remove-Item -LiteralPath $headersFile, $bodyFile, $errorFile -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    throw "curl.exe was not found. It is included with current Windows versions."
}

New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null

Add-ReportLine "Authorized local nginx security check"
Add-ReportLine "Target: https://127.0.0.1 (Host: localhost)"
Add-ReportLine "The script refuses external targets and does not perform DDoS or password guessing."
Add-ReportLine "Started: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"
Add-ReportLine

$probe = Invoke-LocalRequest -Path "/api/healthz"
if ($probe.ExitCode -ne 0 -or $probe.Status -eq 0) {
    throw "The local HTTPS site is unavailable. Run: docker compose up -d --build --wait"
}

Add-ReportLine "=== 1. Path traversal ==="
$traversalPaths = @(
    "/docs/../nginx/nginx.conf",
    "/docs/%2e%2e/nginx/nginx.conf",
    "/%2e%2e/%2e%2e/etc/passwd"
)
$traversalExposed = $false
foreach ($path in $traversalPaths) {
    $response = Invoke-LocalRequest -Path $path -PathAsIs
    $sensitiveContent = $response.Body -match 'worker_processes|root:x:'
    Add-ReportLine ("{0,-42} HTTP {1}; sensitive content={2}" -f $path, $response.Status, $sensitiveContent)
    if ($response.Status -eq 200 -and $sensitiveContent) {
        $traversalExposed = $true
    }
}
if ($traversalExposed) {
    Add-ReportLine "[FOUND] Path traversal exposed a local file."
    $findings++
} else {
    Add-ReportLine "[BLOCKED] No local file was exposed through path traversal."
}
Add-ReportLine

Add-ReportLine "=== 2. Content discovery with a small wordlist ==="
if (-not (Test-Path -LiteralPath $wordlistFile)) {
    throw "Wordlist not found: $wordlistFile"
}
$sensitivePaths = @('.env', '.git/config', 'nginx.conf', 'backup.zip')
$sensitiveExposed = $false
$words = Get-Content -LiteralPath $wordlistFile | Where-Object { $_ -and -not $_.StartsWith('#') }
foreach ($word in $words) {
    $path = "/" + $word.TrimStart('/')
    $response = Invoke-LocalRequest -Path $path -PathAsIs
    Add-ReportLine ("{0,-24} HTTP {1}" -f $path, $response.Status)
    if ($sensitivePaths -contains $word -and $response.Status -eq 200) {
        $sensitiveExposed = $true
    }
}
if ($sensitiveExposed) {
    Add-ReportLine "[FOUND] A sensitive candidate returned HTTP 200."
    $findings++
} else {
    Add-ReportLine "[BLOCKED] No sensitive candidate returned HTTP 200."
}
Add-ReportLine "Note: /admin/, /docs/ and /api/tasks are expected application routes."
Add-ReportLine

Add-ReportLine "=== 3. Basic Auth bypass attempts ==="
$authPaths = @('/admin/', '/admin', '/admin%2f', '/admin/..;/')
$authBypass = $false
foreach ($path in $authPaths) {
    $response = Invoke-LocalRequest -Path $path -PathAsIs
    $adminBody = $response.Body -match '<h1>/admin</h1>'
    Add-ReportLine ("{0,-24} HTTP {1}; protected page returned={2}" -f $path, $response.Status, $adminBody)
    if ($response.Status -eq 200 -and $adminBody) {
        $authBypass = $true
    }
}
if ($authBypass) {
    Add-ReportLine "[FOUND] The protected admin page was returned without credentials."
    $findings++
} else {
    Add-ReportLine "[BLOCKED] The protected admin page was not returned without credentials."
}
Add-ReportLine

Add-ReportLine "=== 4. Host header / virtual-host confusion ==="
$unknownHost = Invoke-LocalRequest -Path "/" -HostHeader "unknown.local"
$otherHost = Invoke-LocalRequest -Path "/" -HostHeader "other.local"
$unknownLeaksProject = $unknownHost.Body -match 'app\.js|about\.html'
$otherIsSeparate = $otherHost.Status -eq 200 -and $otherHost.Body -match 'about\.html' -and $otherHost.Body -notmatch 'app\.js'
Add-ReportLine ("unknown.local -> HTTP {0}; project content returned={1}" -f $unknownHost.Status, $unknownLeaksProject)
Add-ReportLine ("other.local   -> HTTP {0}; separate project={1}" -f $otherHost.Status, $otherIsSeparate)
if ($unknownHost.Status -eq 200 -or $unknownLeaksProject -or -not $otherIsSeparate) {
    Add-ReportLine "[FOUND] Virtual-host isolation did not behave as expected."
    $findings++
} else {
    Add-ReportLine "[BLOCKED] Unknown Host was rejected and the second host stayed isolated."
}
Add-ReportLine

Add-ReportLine "=== 5. HTTP method and information disclosure ==="
$trace = Invoke-LocalRequest -Path "/" -Method "TRACE"
$normal = Invoke-LocalRequest -Path "/"
$traceEnabled = $trace.Status -ge 200 -and $trace.Status -lt 300
$versionMatch = [regex]::Match($normal.Headers, '(?im)^Server:\s*nginx/([0-9.]+)')
Add-ReportLine ("TRACE / -> HTTP {0}" -f $trace.Status)
if ($traceEnabled) {
    Add-ReportLine "[FOUND] TRACE returned a successful status."
    $findings++
} else {
    Add-ReportLine "[BLOCKED] TRACE was not accepted."
}
if ($versionMatch.Success) {
    Add-ReportLine ("[FOUND] Server header discloses the exact nginx version: {0}" -f $versionMatch.Groups[1].Value)
    Add-ReportLine "Recommendation: add 'server_tokens off;' to the nginx http block."
    $findings++
} else {
    Add-ReportLine "[OK] The Server header does not disclose an exact nginx version."
}
Add-ReportLine

Add-ReportLine "=== Summary ==="
Add-ReportLine "Categories tested: 5"
Add-ReportLine "Confirmed findings: $findings"
Add-ReportLine "A zero or non-zero finding count is acceptable for the assignment: the attempts and analysis are documented."
Add-ReportLine "Finished: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"

$lines | Set-Content -LiteralPath $resultFile -Encoding UTF8
Write-Host ""
Write-Host "Saved: $resultFile"
