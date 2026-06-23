# Superstars Dashboard — continuous-run launcher (task #54, Path A)
#
# Used by the "SSC Dashboard Server" Windows scheduled task. Starts the
# Flask app under waitress (production-grade WSGI on Windows) bound to
# 127.0.0.1:5050. Falls back to Flask's dev server if waitress isn't
# installed.
#
# PATH A: no `op run`. ANTHROPIC_API_KEY is NOT injected — the server
# boots without it; cert-card AI extraction returns a clean 503
# "AI disabled" signal so the UI degrades gracefully (manual entry still
# works for cert data; everything else — DCR, sign-ins, labor, photos,
# PDF — works untouched).
#
# Bind contract: 127.0.0.1 ONLY. Tailscale serve proxies external traffic
# to the loopback. NEVER 0.0.0.0 — that would expose the dashboard to
# the LAN. Both the waitress and dev-server paths enforce this.

$ErrorActionPreference = 'Continue'

# Absolute paths — Task Scheduler does not honor relative cwd reliably.
$DashboardDir = 'C:\Users\SSC-Admin\Superstars\dashboard'
$VenvPython   = Join-Path $DashboardDir 'venv\Scripts\python.exe'
$LogDir       = Join-Path $DashboardDir 'data_room\server_logs'
$LogFile      = Join-Path $LogDir ('server-' + (Get-Date -Format 'yyyy-MM-dd') + '.log')

# Bind config — change here ONLY if Tailscale serve is re-configured
# AND you've verified the new bind is still loopback-only.
$BindHost = '127.0.0.1'
$BindPort = 5050

# Set working directory; venv python expects to find superstars.db, schema
# files, the data_room tree, and the worker_records tree relative to here.
Set-Location -Path $DashboardDir

# Ensure log dir exists (first-run case).
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

# Single log line at boot so the operator can confirm the task ran.
$bootStamp = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [launcher] cwd=$DashboardDir  bind=${BindHost}:${BindPort}"
Add-Content -Path $LogFile -Value $bootStamp

# Load runtime secrets from the gitignored .env (KEY=VALUE per line) into the process
# environment, so the app (os.environ) picks them up — e.g. GOOGLE_OAUTH_* for the
# "Sign in with Google" flow (#261). The .env is NEVER committed (gitignored). Values
# are NEVER written to the log — only the count of keys loaded. Lines starting with #
# and blank lines are ignored; surrounding single/double quotes on a value are stripped.
$EnvFile = Join-Path $DashboardDir '.env'
if (Test-Path $EnvFile) {
    $loaded = 0
    foreach ($raw in Get-Content -Path $EnvFile) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
        $i = $line.IndexOf('=')
        $k = $line.Substring(0, $i).Trim()
        $v = $line.Substring($i + 1).Trim()
        if ($v.Length -ge 2 -and (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'")))) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        if ($k) { Set-Item -Path ("Env:" + $k) -Value $v; $loaded++ }
    }
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [launcher] loaded $loaded env key(s) from .env (values not logged)"
}

# Detect waitress in the venv. If present, run via waitress-serve. If
# missing (clean install, or removed), fall back to Flask's dev server.
# Both paths bind to $BindHost / $BindPort and redirect stdout/stderr
# into the log file.
$waitressCheck = & $VenvPython -c "import waitress" 2>&1
if ($LASTEXITCODE -eq 0) {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [launcher] waitress detected -> running under waitress"
    & $VenvPython -m waitress --host=$BindHost --port=$BindPort --threads=8 server:app `
        *>> $LogFile
} else {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [launcher] waitress NOT installed -> Flask dev server (still 127.0.0.1)"
    # server.py's __main__ block honors FLASK_RUN_HOST/FLASK_RUN_PORT if set,
    # but its default already binds to 127.0.0.1:5050. Pass through to be
    # explicit even if defaults change.
    $env:FLASK_RUN_HOST = $BindHost
    $env:FLASK_RUN_PORT = "$BindPort"
    & $VenvPython server.py *>> $LogFile
}

Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  [launcher] server exited with code $LASTEXITCODE"
