# Dev-preview launcher — runs the Flask dev server against an ISOLATED DB copy so
# browser verification NEVER touches the live superstars.db (CLAUDE.md isolation rule).
# PORT comes from the preview harness (launch.json autoPort); SSC_DB_URL may be
# pre-set by the caller. Otherwise the gitignored .dev_db_url marker is the single
# source — server.py applies it at the TOP of the file (before the import-time boot
# ensures), so we leave the env unset and let it. The pin below is the last-resort
# fallback ONLY for when the marker file is missing: the ps1 path must never fall
# through to live.
if (-not $env:SSC_DB_URL) {
  $marker = Join-Path $PSScriptRoot ".dev_db_url"
  if (-not (Test-Path $marker)) {
    $env:SSC_DB_URL = "sqlite:///C:/Users/SSC-Admin/Superstars/snapshots/ssc_dev_278.db"
  }
}
Set-Location $PSScriptRoot
& "$PSScriptRoot\venv\Scripts\python.exe" server.py
