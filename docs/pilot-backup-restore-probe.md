# Pilot Database Backup Restore Probe

Created backup:

- `/home/michael/.codex/memories/pilot_dump_20260312_103754.sql.gz`
- remote copy: `~/cube-dev/pilot_dump_20260312_103754.sql.gz` on `felt-1.rootvg.net` (port `22051`)

## Quick remote integrity check

```bash
ssh -p 22051 michael@felt-1.rootvg.net 'gzip -t ~/cube-dev/pilot_dump_20260312_103754.sql.gz'
```

## Non-destructive restore probe

This verifies restoreability without touching production data. Replace `PGPASSWORD` as needed.

```bash
export PGPASSWORD=Wp3N6MmDjpiaOK6Q2sEPqVnS8LyaYa
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
PROBE_DB="cube_db_restore_probe_${TIMESTAMP}"

createdb -h 127.0.0.1 -U cube_user "$PROBE_DB"

gzip -dc /home/michael/.codex/memories/pilot_dump_20260312_103754.sql.gz \
  | pg_restore --clean --if-exists --no-owner --no-privileges -h 127.0.0.1 -U cube_user -d "$PROBE_DB"

pg_restore --list /home/michael/.codex/memories/pilot_dump_20260312_103754.sql.gz >/tmp/pilot_dump_manifest.txt
wc -l /tmp/pilot_dump_manifest.txt
psql -h 127.0.0.1 -U cube_user -d "$PROBE_DB" -c 'SELECT count(*) FROM pg_class WHERE relkind = '"'"'r'"'"' AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = '"'"'public'"'"');'

dropdb -h 127.0.0.1 -U cube_user "$PROBE_DB"
```

## Remote restore probe

```bash
ssh -p 22051 michael@felt-1.rootvg.net '
  export PGPASSWORD=...
  export PROBE_DB=cube_db_restore_probe
  createdb -h 127.0.0.1 -U cube_user "$PROBE_DB"
  gzip -dc ~/cube-dev/pilot_dump_20260312_103754.sql.gz \
    | pg_restore --clean --if-exists --no-owner --no-privileges -h 127.0.0.1 -U cube_user -d "$PROBE_DB"
  dropdb -h 127.0.0.1 -U cube_user "$PROBE_DB"
'
```
