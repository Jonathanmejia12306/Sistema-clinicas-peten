#!/usr/bin/env python3
"""Migrate the SQLite database used by the clinic app to PostgreSQL.

Usage examples:
    python migrate_sqlite_to_postgres.py --sqlite-db clinica.db --postgres-url postgresql://USER:PASSWORD@HOST:5432/clinica --dry-run
    python migrate_sqlite_to_postgres.py --sqlite-db clinica.db --postgres-url postgresql://USER:PASSWORD@HOST:5432/clinica
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

try:
    import psycopg2
    from psycopg2 import sql as pg_sql
    from psycopg2.extras import execute_values
except ImportError:  # pragma: no cover
    psycopg2 = None
    pg_sql = None
    execute_values = None


DEFAULT_SQLITE_DB = Path(__file__).resolve().parent / "clinica.db"
DEFAULT_POSTGRES_URL = os.getenv("DATABASE_URL")


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sqlite_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row[0] for row in rows]


def sqlite_table_order(conn: sqlite3.Connection) -> List[str]:
    tables = sqlite_tables(conn)
    if not tables:
        return []

    children = {table: set() for table in tables}
    indegree = {table: 0 for table in tables}

    for table in tables:
        fk_rows = conn.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        refs = {row[2] for row in fk_rows if row[2] in children}
        for ref in sorted(refs):
            if ref == table:
                continue
            if table not in children[ref]:
                children[ref].add(table)
                indegree[table] += 1

    queue = [table for table in tables if indegree[table] == 0]
    ordered = []
    while queue:
        table = queue.pop(0)
        ordered.append(table)
        for child in sorted(children[table]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)

    if len(ordered) != len(tables):
        remaining = [table for table in tables if table not in ordered]
        ordered.extend(remaining)

    return ordered


def column_type_sqlite_to_postgres(sqlite_type: str) -> str:
    t = (sqlite_type or "TEXT").upper()
    if t.startswith("INTEGER") or t.startswith("INT"):
        return "BIGINT"
    if "REAL" in t or "FLOAT" in t or "DOUBLE" in t:
        return "DOUBLE PRECISION"
    if "BOOL" in t:
        return "BOOLEAN"
    if t == "DATE":
        return "DATE"
    if t == "TIME":
        return "TIME"
    if "DATETIME" in t or "TIMESTAMP" in t:
        return "TIMESTAMP"
    return "TEXT"


def normalize_default(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.upper() in {"CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME"}:
        return value.upper()
    if value.startswith("'") and value.endswith("'"):
        return value
    if value.startswith('"') and value.endswith('"'):
        return "'" + value[1:-1].replace("'", "''") + "'"
    try:
        int(value)
        return value
    except ValueError:
        pass
    try:
        float(value)
        return value
    except ValueError:
        pass
    return "'" + value.replace("'", "''") + "'"


def build_create_table_sqlite(conn: sqlite3.Connection, table_name: str) -> str:
    info_rows = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    if not info_rows:
        raise ValueError(f"Table does not exist or has no columns: {table_name}")

    columns_sql = []
    pk_columns = []
    for col in info_rows:
        cid, name, data_type, notnull, default_value, pk = col
        postgres_type = column_type_sqlite_to_postgres(data_type or "TEXT")
        col_name = quote_ident(name)

        if pk:
            pk_columns.append(name)

        if pk and data_type and data_type.upper().startswith("INTEGER"):
            # SQLite integer primary keys become identity columns in PostgreSQL.
            definition = f"{col_name} BIGSERIAL"
        else:
            definition = f"{col_name} {postgres_type}"

        if notnull and not pk:
            definition += " NOT NULL"

        if default_value is not None and default_value != "":
            normalized = normalize_default(default_value)
            if normalized is not None:
                definition += f" DEFAULT {normalized}"

        columns_sql.append(definition)

    index_rows = conn.execute(f'PRAGMA index_list("{table_name}")').fetchall()
    for index in index_rows:
        index_name, is_unique = index[1], index[2]
        origin = index[3] if len(index) > 3 else ""
        is_partial = bool(index[4]) if len(index) > 4 else False
        if not is_unique or origin == "pk":
            continue
        escaped_index = index_name.replace('"', '""')
        index_columns = conn.execute(f'PRAGMA index_info("{escaped_index}")').fetchall()
        if is_partial or any(row[1] is None or row[1] < 0 for row in index_columns):
            raise ValueError(f"Cannot safely migrate partial or expression-based unique index: {index_name}")
        columns_sql.append(
            "UNIQUE (" + ", ".join(quote_ident(row[2]) for row in index_columns) + ")"
        )

    fk_rows = conn.execute(f'PRAGMA foreign_key_list("{table_name}")').fetchall()
    fk_sql = []
    seen = set()
    for fk in fk_rows:
        id_, seq, table, from_col, to_col, on_update, on_delete, match = fk
        key = (table, from_col, to_col)
        if key in seen:
            continue
        seen.add(key)
        constraint = f"FOREIGN KEY ({quote_ident(from_col)}) REFERENCES {quote_ident(table)} ({quote_ident(to_col)})"
        if on_update and on_update.upper() != "NO ACTION":
            constraint += f" ON UPDATE {on_update.upper()}"
        if on_delete and on_delete.upper() != "NO ACTION":
            constraint += f" ON DELETE {on_delete.upper()}"
        fk_sql.append(constraint)

    if pk_columns:
        pk_sql = f"PRIMARY KEY ({', '.join(quote_ident(col) for col in pk_columns)})"
        columns_sql.append(pk_sql)

    if fk_sql:
        columns_sql.extend(fk_sql)

    return f"CREATE TABLE IF NOT EXISTS {quote_ident(table_name)} (\n  " + ",\n  ".join(columns_sql) + "\n);"


def sqlite_data_types(conn: sqlite3.Connection, table_name: str):
    cols = conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [row[1] for row in cols], [row[2] for row in cols]


def migrate_sqlite_to_postgres(sqlite_path: str, postgres_url: str, dry_run: bool = False, schema_only: bool = False) -> None:
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required. Install it with: pip install psycopg2-binary")
    if not postgres_url and not dry_run:
        raise ValueError("A PostgreSQL URL is required unless using --dry-run.")

    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    tables = sqlite_table_order(sqlite_conn)
    if not tables:
        raise RuntimeError(f"No tables found in SQLite database: {sqlite_path}")

    print(f"Found tables in dependency order: {', '.join(tables)}")

    if dry_run:
        print("\nDRY RUN MODE: SQL statements prepared but not executed against PostgreSQL.\n")
        for table in tables:
            print(build_create_table_sqlite(sqlite_conn, table))
        sqlite_conn.close()
        return

    pg_conn = psycopg2.connect(postgres_url)
    try:
        pg_cur = pg_conn.cursor()
        try:
            pg_cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' LIMIT 1"
            )
            if pg_cur.fetchone():
                raise RuntimeError(
                    "The PostgreSQL destination schema is not empty; migration refused to protect existing data. "
                    "Choose a new empty database/schema before migrating."
                )

            for table in tables:
                ddl = build_create_table_sqlite(sqlite_conn, table)
                print(f"Creating PostgreSQL table: {table}")
                pg_cur.execute(ddl)

                if schema_only:
                    continue

                column_names, column_types = sqlite_data_types(sqlite_conn, table)
                rows = sqlite_conn.execute(f'SELECT * FROM "{table}"').fetchall()
                if not rows:
                    print(f"No rows to insert into {table}.\n")
                    continue

                cols = [quote_ident(col) for col in column_names]
                columns_sql = ', '.join(cols)

                normalized_rows = []
                for row in rows:
                    clean_row = []
                    for value, sqlite_type in zip(row, column_types):
                        if value is None:
                            clean_row.append(None)
                        elif (
                            isinstance(value, str)
                            and value.strip() == ''
                            and any(token in (sqlite_type or '').upper() for token in (
                                'INT', 'REAL', 'FLOAT', 'DOUBLE', 'NUMERIC', 'DECIMAL', 'DATE', 'TIME', 'BOOL'
                            ))
                        ):
                            clean_row.append(None)
                        else:
                            clean_row.append(value)
                    normalized_rows.append(tuple(clean_row))

                insert_sql = f"INSERT INTO {quote_ident(table)} ({columns_sql}) VALUES %s"
                execute_values(pg_cur, insert_sql, normalized_rows)
                print(f"Inserted {len(normalized_rows)} rows into {table}.")

            if not schema_only:
                for table in tables:
                    info_rows = sqlite_conn.execute(f'PRAGMA table_info("{table}")').fetchall()
                    for _, column, data_type, _, _, is_primary_key in info_rows:
                        if not is_primary_key or not (data_type or '').upper().startswith('INTEGER'):
                            continue
                        pg_cur.execute("SELECT pg_get_serial_sequence(%s, %s)", (quote_ident(table), column))
                        sequence = pg_cur.fetchone()[0]
                        if sequence:
                            pg_cur.execute(
                                f"SELECT setval(%s, COALESCE(MAX({quote_ident(column)}), 1), "
                                f"MAX({quote_ident(column)}) IS NOT NULL) FROM {quote_ident(table)}",
                                (sequence,),
                            )
            pg_conn.commit()
        except Exception:
            pg_conn.rollback()
            raise
        finally:
            pg_cur.close()
    finally:
        pg_conn.close()
        sqlite_conn.close()

    print("\nMigration finished successfully.")


def sequence_needs_advance(last_value: int, is_called: bool, max_id: int | None) -> bool:
    if max_id is None:
        return False
    next_id = last_value + 1 if is_called else last_value
    return next_id <= max_id


def synchronize_postgres_sequences(postgres_url: str) -> List[str]:
    if psycopg2 is None or pg_sql is None:
        raise RuntimeError("psycopg2 is required. Install it with: pip install psycopg2-binary")
    if not postgres_url:
        raise ValueError("A PostgreSQL URL is required to synchronize sequences.")

    connection = psycopg2.connect(postgres_url)
    synchronized = []
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND column_default LIKE 'nextval(%' "
                "ORDER BY table_name, ordinal_position"
            )
            serial_columns = cursor.fetchall()
            for table, column in serial_columns:
                cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)",
                    (quote_ident(table), column),
                )
                row = cursor.fetchone()
                sequence = row[0] if row else None
                if not sequence:
                    continue

                sequence_parts = sequence.split('.', 1)
                if len(sequence_parts) == 2:
                    schema_name, sequence_name = (part.strip('"') for part in sequence_parts)
                else:
                    schema_name, sequence_name = 'public', sequence_parts[0].strip('"')
                cursor.execute(
                    pg_sql.SQL("SELECT last_value, is_called FROM {} ").format(
                        pg_sql.Identifier(schema_name, sequence_name)
                    )
                )
                last_value, is_called = cursor.fetchone()
                cursor.execute(
                    pg_sql.SQL("SELECT MAX({}) FROM {} ").format(
                        pg_sql.Identifier(column), pg_sql.Identifier(table)
                    )
                )
                max_id = cursor.fetchone()[0]
                if sequence_needs_advance(last_value, is_called, max_id):
                    cursor.execute(
                        "SELECT setval(%s::regclass, %s, true)",
                        (sequence, max_id),
                    )
                    synchronized.append(f"{table}.{column}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
    finally:
        connection.close()
    return synchronized


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite database to PostgreSQL")
    parser.add_argument("--sqlite-db", default=str(DEFAULT_SQLITE_DB), help="Path to the SQLite DB file")
    parser.add_argument("--postgres-url", default=DEFAULT_POSTGRES_URL, help="PostgreSQL connection URL (or set DATABASE_URL)")
    parser.add_argument("--dry-run", action="store_true", help="Show the generated SQL without connecting to PostgreSQL")
    parser.add_argument("--schema-only", action="store_true", help="Create schema only, without copying rows")
    parser.add_argument("--sync-sequences-only", action="store_true", help="Advance PostgreSQL serial sequences to the existing maximum IDs without changing rows")
    args = parser.parse_args()

    if args.sync_sequences_only and (args.dry_run or args.schema_only):
        parser.error("--sync-sequences-only cannot be combined with --dry-run or --schema-only.")
    if not args.postgres_url and (args.sync_sequences_only or not args.dry_run):
        parser.error("Provide --postgres-url or set DATABASE_URL.")

    try:
        if args.sync_sequences_only:
            synchronized = synchronize_postgres_sequences(args.postgres_url)
            print(f"Advanced {len(synchronized)} serial sequence(s).")
        else:
            migrate_sqlite_to_postgres(args.sqlite_db, args.postgres_url, dry_run=args.dry_run, schema_only=args.schema_only)
        return 0
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
