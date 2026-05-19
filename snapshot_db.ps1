# Daily DB snapshot — invoked by the "Superstars DB Snapshot" scheduled task.
# Edit the schedule via Task Scheduler GUI or:
#   schtasks /Query /TN "Superstars DB Snapshot" /V /FO LIST
$src = "C:\Users\SSC-Admin\Superstars\dashboard\superstars.db"
$dstDir = "C:\Users\SSC-Admin\Superstars\dashboard\data_room\db_backups"
if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Force $dstDir | Out-Null }
$dst = Join-Path $dstDir ("superstars-daily-" + (Get-Date -Format yyyy-MM-dd) + ".db")
Copy-Item $src $dst -Force
