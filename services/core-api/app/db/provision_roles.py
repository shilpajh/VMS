"""Apply app/db/roles.sql (the vms_app / vms_migrator role provisioning) to a
target database.

Must be run by a superuser-equivalent role (able to CREATE ROLE and GRANT on
schema public) — locally this is the `vms` role from docker-compose. Never
invoked by the running application; this is dev/CI/ops tooling only.

Usage:
    python -m app.db.provision_roles postgresql://vms:...@localhost:5432/vms
    python -m app.db.provision_roles postgresql://vms:...@localhost:5432/vms_test
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

ROLES_SQL_PATH = Path(__file__).parent / "roles.sql"


def provision_roles(dsn: str) -> None:
    """Idempotently create vms_app / vms_migrator on the database `dsn` points at."""
    sql = ROLES_SQL_PATH.read_text()
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    provision_roles(sys.argv[1])
