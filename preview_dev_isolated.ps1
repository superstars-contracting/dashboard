# Dev-preview launcher — runs the Flask dev server against an ISOLATED DB copy so
# browser verification NEVER touches the live superstars.db (CLAUDE.md isolation rule).
# PORT comes from the preview harness (launch.json autoPort); SSC_DB_URL may be
# pre-set by the caller — otherwise it pins to the standing dev copy in snapshots/.
if (-not $env:SSC_DB_URL) {
  $env:SSC_DB_URL = "sqlite:///C:/Users/SSC-Admin/Superstars/snapshots/ssc_dev_273.db"
}
Set-Location $PSScriptRoot
& "$PSScriptRoot\venv\Scripts\python.exe" server.py
