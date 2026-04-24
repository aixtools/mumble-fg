# Pilot Backup Restore Probe

Verified: `mumble-fg` `main` version `0.3.7.dev1` on `2026-04-24`.

This document is a generic restoreability check for a host-side `PILOT_DBMS`
backup. It is intentionally written without environment-specific secrets or
hostnames.

Use it to answer one narrow question:

- can a captured pilot-data backup be restored cleanly into a disposable probe DB?

## Preconditions

- you have a recent backup artifact
- you have credentials that can create and drop a disposable probe DB
- you are not pointing at production data

## Local Non-Destructive Restore Probe

Replace the placeholders for your environment:

```bash
export PGPASSWORD='<db_password>'
BACKUP_FILE='/path/to/pilot_dump.sql.gz'
PROBE_DB="pilot_dbms_restore_probe_$(date +%Y%m%d_%H%M%S)"

createdb -h 127.0.0.1 -U <db_user> "$PROBE_DB"

gzip -dc "$BACKUP_FILE" \
  | psql -h 127.0.0.1 -U <db_user> -d "$PROBE_DB"

gzip -dc "$BACKUP_FILE" > /tmp/pilot_dbms_restore_probe.sql
wc -l /tmp/pilot_dbms_restore_probe.sql
psql -h 127.0.0.1 -U <db_user> -d "$PROBE_DB" -c '\dt'

dropdb -h 127.0.0.1 -U <db_user> "$PROBE_DB"
rm -f /tmp/pilot_dbms_restore_probe.sql
```

## What To Check

- backup stream decompresses cleanly
- `psql` import completes without schema/object errors
- expected tables exist in the probe DB
- the probe DB can be dropped cleanly afterward

## Notes

- use a disposable DB name every time
- do not run this against the live `PILOT_DBMS`
- if the host app depends on extensions or roles, verify those separately before
  treating the probe as a real disaster-recovery test
