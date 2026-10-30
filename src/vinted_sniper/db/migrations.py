"""Schema migrations.

Files in migrations/ are named NNNN_description.sql and applied in order. SQLite's
user_version pragma records how far we got. Each file and its version bump run in one
transaction, so a failure leaves the database at the last version that fully applied
rather than half-way through a file that cannot be re-run.

Foreign keys are switched off while a file runs and checked before it commits. That is
SQLite's documented procedure for rebuilding a table, which is the only way to change a
constraint: with them on, dropping the old copy of a parent table would cascade-delete
every child row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from vinted_sniper.db.connection import Database
from vinted_sniper.log import get_logger

log = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_FILENAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    path: Path

    @property
    def name(self) -> str:
        return self.path.name


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Return migrations in version order, refusing anything malformed or out of sequence."""
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if match is None:
            raise ValueError(f"Migration {path.name!r} does not match NNNN_lower_snake_case.sql")
        found.append(Migration(version=int(match.group(1)), path=path))

    for expected, migration in enumerate(found, start=1):
        if migration.version != expected:
            raise ValueError(
                f"Migration numbering has a gap or duplicate: expected {expected:04d}, "
                f"found {migration.name}"
            )
    return found


async def current_version(db: Database) -> int:
    version = await db.fetch_value("PRAGMA user_version")
    return int(version or 0)


async def apply_pending(db: Database, directory: Path = MIGRATIONS_DIR) -> int:
    """Apply every migration newer than the recorded version. Returns how many ran."""
    migrations = discover(directory)
    version = await current_version(db)

    if version > len(migrations):
        raise RuntimeError(
            f"Database is at schema version {version} but only {len(migrations)} migrations "
            "exist. This database was written by a newer release; upgrade rather than "
            "downgrade."
        )

    pending = [m for m in migrations if m.version > version]
    for migration in pending:
        await _apply(db, migration)
        log.info("migration.applied", version=migration.version, name=migration.name)

    return len(pending)


async def _apply(db: Database, migration: Migration) -> None:
    sql = migration.path.read_text(encoding="utf-8")
    # The pragma is a no-op inside a transaction, so it goes first, on its own.
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        async with db.transaction() as conn:
            # executescript commits whatever is open and then runs the script as written;
            # starting it with BEGIN is what keeps the whole file in one transaction.
            await conn.executescript(f"BEGIN;\n{sql}")
            async with conn.execute("PRAGMA foreign_key_check") as cursor:
                broken = list(await cursor.fetchall())
            if broken:
                raise RuntimeError(
                    f"Migration {migration.name} left {len(broken)} broken foreign key(s), "
                    f"first in table {broken[0][0]!r}"
                )
            await conn.execute(f"PRAGMA user_version = {migration.version}")
    finally:
        await db.execute("PRAGMA foreign_keys = ON")
