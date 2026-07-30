"""Read-only, metadata-first PostgreSQL connector normalizer.

This module never connects to a database. An operator (or a future bounded
runner) executes the documented catalog SQL below with a dedicated read-only
identity and saves the result as a JSON catalog snapshot. This module then
deterministically normalizes that snapshot into the repository's
source-profile, evidence-index, and snapshot artifact shapes with SHA-256
content hashes, exactly like the committed ``profiles/<source>`` fixtures.

Fail-closed policy: the catalog snapshot may carry schema, table, column,
constraint, and row-estimate metadata only. Any key that could smuggle sampled
values or row content is rejected, as is any unknown key anywhere in the
document.

CLI::

    python -m ontology_appliance_gateway.connectors.postgres \
        data/synthetic/postgres-catalog.json profiles/postgres-demo \
        --catalog-locator data/synthetic/postgres-catalog.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping

EXTRACTOR_NAME = "ontology-appliance-postgres-metadata-profiler"
EXTRACTOR_VERSION = "1.0.0"
CATALOG_SCHEMA_VERSION = "1.0"
PROFILE_SCHEMA_VERSION = "1.0"

#: Connection options the adapter always applies. The session cannot write and
#: cannot hold a statement open past the governed timeout.
READ_ONLY_CONNECTION_OPTIONS: dict[str, str] = {
    "default_transaction_read_only": "on",
    "statement_timeout": "30000",
    "idle_in_transaction_session_timeout": "30000",
}

# --- Documented catalog extraction SQL -------------------------------------
# Read-only, parameter-free statements against information_schema/pg_catalog.
# They return metadata only; no user table is ever selected from.

SCHEMAS_SQL = """\
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name NOT IN ('pg_catalog', 'information_schema')
  AND schema_name NOT LIKE 'pg\\_%'
ORDER BY schema_name;
"""

TABLES_SQL = """\
SELECT t.table_schema,
       t.table_name,
       t.table_type,
       GREATEST(c.reltuples, 0)::bigint AS row_estimate
FROM information_schema.tables AS t
JOIN pg_catalog.pg_namespace AS n ON n.nspname = t.table_schema
JOIN pg_catalog.pg_class AS c
  ON c.relnamespace = n.oid AND c.relname = t.table_name
WHERE t.table_type IN ('BASE TABLE', 'VIEW')
  AND t.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND t.table_schema NOT LIKE 'pg\\_%'
ORDER BY t.table_schema, t.table_name;
"""

COLUMNS_SQL = """\
SELECT c.table_schema,
       c.table_name,
       c.column_name,
       c.ordinal_position,
       c.data_type,
       c.is_nullable
FROM information_schema.columns AS c
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND c.table_schema NOT LIKE 'pg\\_%'
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
"""

PRIMARY_KEYS_SQL = """\
SELECT tc.table_schema,
       tc.table_name,
       tc.constraint_name,
       array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS column_names
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON kcu.constraint_schema = tc.constraint_schema
 AND kcu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'PRIMARY KEY'
  AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND tc.table_schema NOT LIKE 'pg\\_%'
GROUP BY tc.table_schema, tc.table_name, tc.constraint_name
ORDER BY tc.table_schema, tc.table_name, tc.constraint_name;
"""

FOREIGN_KEYS_SQL = """\
SELECT tc.table_schema,
       tc.table_name,
       tc.constraint_name,
       array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS column_names,
       ccu.table_schema AS referenced_schema,
       ccu.table_name AS referenced_table,
       array_agg(ccu.column_name ORDER BY kcu.ordinal_position) AS referenced_columns
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON kcu.constraint_schema = tc.constraint_schema
 AND kcu.constraint_name = tc.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_schema = tc.constraint_schema
 AND ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
  AND tc.table_schema NOT LIKE 'pg\\_%'
GROUP BY tc.table_schema, tc.table_name, tc.constraint_name,
         ccu.table_schema, ccu.table_name
ORDER BY tc.table_schema, tc.table_name, tc.constraint_name;
"""

CATALOG_SQL: dict[str, str] = {
    "schemas": SCHEMAS_SQL,
    "tables": TABLES_SQL,
    "columns": COLUMNS_SQL,
    "primary_keys": PRIMARY_KEYS_SQL,
    "foreign_keys": FOREIGN_KEYS_SQL,
}

# --- Fail-closed catalog validation -----------------------------------------

#: Keys that could carry sampled values or row content. Their presence
#: anywhere in a catalog snapshot rejects the whole document.
FORBIDDEN_VALUE_KEYS: frozenset[str] = frozenset(
    {
        "data",
        "example",
        "examples",
        "histogram_bounds",
        "most_common_vals",
        "preview",
        "record",
        "records",
        "row",
        "rows",
        "sample",
        "sample_rows",
        "sample_values",
        "samples",
        "tuple",
        "tuples",
        "value",
        "values",
    }
)

_TOP_LEVEL_KEYS = {
    "catalog_schema_version",
    "database",
    "server_version",
    "collected_at",
    "schemas",
    "tables",
    "columns",
    "primary_keys",
    "foreign_keys",
}
_SCHEMA_KEYS = {"schema_name"}
_TABLE_KEYS = {"table_schema", "table_name", "table_type", "row_estimate"}
_COLUMN_KEYS = {
    "table_schema",
    "table_name",
    "column_name",
    "ordinal_position",
    "data_type",
    "is_nullable",
}
_PRIMARY_KEY_KEYS = {"table_schema", "table_name", "constraint_name", "column_names"}
_FOREIGN_KEY_KEYS = {
    "table_schema",
    "table_name",
    "constraint_name",
    "column_names",
    "referenced_schema",
    "referenced_table",
    "referenced_columns",
}
_TABLE_TYPES = {"BASE TABLE", "VIEW"}

#: PostgreSQL ``data_type`` values mapped onto the connector logical types.
LOGICAL_TYPE_MAP: dict[str, str] = {
    "array": "array",
    "bigint": "integer",
    "boolean": "boolean",
    "bytea": "binary",
    "character": "string",
    "character varying": "string",
    "date": "date",
    "double precision": "number",
    "integer": "integer",
    "json": "object",
    "jsonb": "object",
    "numeric": "number",
    "real": "number",
    "smallint": "integer",
    "text": "string",
    "time without time zone": "string",
    "timestamp with time zone": "datetime",
    "timestamp without time zone": "datetime",
    "uuid": "string",
}
_FALLBACK_LOGICAL_TYPE = "string"


class CatalogPolicyError(ValueError):
    """The catalog snapshot violates the metadata-only, fail-closed policy."""


@dataclass(frozen=True)
class CatalogLimits:
    """Bounded metadata intake; exceeding any bound refuses the snapshot."""

    maximum_schemas: int = 16
    maximum_tables: int = 200
    maximum_columns: int = 2000


DEFAULT_LIMITS = CatalogLimits()


def _walk_keys(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield f"{path}.{key}", str(key)
            yield from _walk_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{path}[{index}]")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CatalogPolicyError(message)


def _require_entries(catalog: Mapping[str, Any], key: str, allowed: set[str]) -> list[dict]:
    entries = catalog.get(key)
    _require(isinstance(entries, list), f"catalog {key} must be an array")
    validated: list[dict] = []
    for index, entry in enumerate(entries):
        label = f"{key}[{index}]"
        _require(isinstance(entry, Mapping), f"{label} must be an object")
        unknown = set(entry) - allowed
        _require(not unknown, f"{label} has unsupported keys: {sorted(unknown)}")
        missing = allowed - set(entry)
        _require(not missing, f"{label} is missing keys: {sorted(missing)}")
        validated.append(dict(entry))
    return validated


def _require_string(entry: Mapping[str, Any], key: str, label: str) -> str:
    value = entry.get(key)
    _require(isinstance(value, str) and bool(value.strip()), f"{label}.{key} must be a string")
    return value


def _require_name_list(entry: Mapping[str, Any], key: str, label: str) -> list[str]:
    value = entry.get(key)
    _require(
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value),
        f"{label}.{key} must be a non-empty array of identifier strings",
    )
    return list(value)


def validate_catalog(
    catalog: Mapping[str, Any], *, limits: CatalogLimits = DEFAULT_LIMITS
) -> dict[str, Any]:
    """Validate a catalog snapshot, refusing anything beyond bounded metadata."""

    _require(isinstance(catalog, Mapping), "catalog snapshot must be a JSON object")
    for path, key in _walk_keys(catalog):
        if key.lower() in FORBIDDEN_VALUE_KEYS:
            raise CatalogPolicyError(
                f"value-bearing key {key!r} at {path} is refused: the PostgreSQL "
                "connector is metadata-only and value sampling is disabled"
            )
    unknown = set(catalog) - _TOP_LEVEL_KEYS
    _require(not unknown, f"catalog has unsupported top-level keys: {sorted(unknown)}")
    missing = _TOP_LEVEL_KEYS - set(catalog)
    _require(not missing, f"catalog is missing top-level keys: {sorted(missing)}")
    _require(
        catalog["catalog_schema_version"] == CATALOG_SCHEMA_VERSION,
        f"catalog_schema_version must be {CATALOG_SCHEMA_VERSION!r}",
    )
    _require_string(catalog, "database", "catalog")
    _require_string(catalog, "server_version", "catalog")
    _require_string(catalog, "collected_at", "catalog")

    schemas = _require_entries(catalog, "schemas", _SCHEMA_KEYS)
    schema_names = {_require_string(entry, "schema_name", "schemas[]") for entry in schemas}
    _require(len(schema_names) == len(schemas), "schema names must be unique")
    _require(
        len(schemas) <= limits.maximum_schemas,
        f"catalog exceeds the {limits.maximum_schemas} schema limit",
    )

    tables = _require_entries(catalog, "tables", _TABLE_KEYS)
    _require(
        len(tables) <= limits.maximum_tables,
        f"catalog exceeds the {limits.maximum_tables} table limit",
    )
    table_names: set[tuple[str, str]] = set()
    for entry in tables:
        schema = _require_string(entry, "table_schema", "tables[]")
        name = _require_string(entry, "table_name", "tables[]")
        _require(schema in schema_names, f"table {schema}.{name} references an unlisted schema")
        _require(
            entry["table_type"] in _TABLE_TYPES,
            f"tables[].table_type must be one of {sorted(_TABLE_TYPES)}",
        )
        estimate = entry["row_estimate"]
        _require(
            isinstance(estimate, int) and not isinstance(estimate, bool) and estimate >= 0,
            "tables[].row_estimate must be a non-negative integer",
        )
        _require((schema, name) not in table_names, f"duplicate table {schema}.{name}")
        table_names.add((schema, name))

    columns = _require_entries(catalog, "columns", _COLUMN_KEYS)
    _require(
        len(columns) <= limits.maximum_columns,
        f"catalog exceeds the {limits.maximum_columns} column limit",
    )
    column_names: set[tuple[str, str, str]] = set()
    for entry in columns:
        schema = _require_string(entry, "table_schema", "columns[]")
        table = _require_string(entry, "table_name", "columns[]")
        column = _require_string(entry, "column_name", "columns[]")
        _require(
            (schema, table) in table_names,
            f"column {schema}.{table}.{column} references an unlisted table",
        )
        position = entry["ordinal_position"]
        _require(
            isinstance(position, int) and not isinstance(position, bool) and position >= 1,
            "columns[].ordinal_position must be a positive integer",
        )
        _require_string(entry, "data_type", "columns[]")
        _require(
            entry["is_nullable"] in {"YES", "NO"},
            "columns[].is_nullable must be 'YES' or 'NO'",
        )
        key = (schema, table, column)
        _require(key not in column_names, f"duplicate column {schema}.{table}.{column}")
        column_names.add(key)

    for entry in _require_entries(catalog, "primary_keys", _PRIMARY_KEY_KEYS):
        schema = _require_string(entry, "table_schema", "primary_keys[]")
        table = _require_string(entry, "table_name", "primary_keys[]")
        _require_string(entry, "constraint_name", "primary_keys[]")
        for column in _require_name_list(entry, "column_names", "primary_keys[]"):
            _require(
                (schema, table, column) in column_names,
                f"primary key references unlisted column {schema}.{table}.{column}",
            )

    for entry in _require_entries(catalog, "foreign_keys", _FOREIGN_KEY_KEYS):
        schema = _require_string(entry, "table_schema", "foreign_keys[]")
        table = _require_string(entry, "table_name", "foreign_keys[]")
        _require_string(entry, "constraint_name", "foreign_keys[]")
        referenced_schema = _require_string(entry, "referenced_schema", "foreign_keys[]")
        referenced_table = _require_string(entry, "referenced_table", "foreign_keys[]")
        local = _require_name_list(entry, "column_names", "foreign_keys[]")
        referenced = _require_name_list(entry, "referenced_columns", "foreign_keys[]")
        _require(
            len(local) == len(referenced),
            "foreign_keys[] column_names and referenced_columns must align",
        )
        for column in local:
            _require(
                (schema, table, column) in column_names,
                f"foreign key references unlisted column {schema}.{table}.{column}",
            )
        for column in referenced:
            _require(
                (referenced_schema, referenced_table, column) in column_names,
                "foreign key references unlisted column "
                f"{referenced_schema}.{referenced_table}.{column}",
            )
    return dict(catalog)


# --- Deterministic normalization ---------------------------------------------


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def compact_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _logical_type(data_type: str) -> str:
    if data_type.upper().endswith("[]") or data_type.upper() == "ARRAY":
        return "array"
    return LOGICAL_TYPE_MAP.get(data_type.lower(), _FALLBACK_LOGICAL_TYPE)


def _table_locator(database: str, schema: str, table: str) -> str:
    return f"postgres://{database}/{schema}/{table}"


def _evidence_id(source_id: str, snapshot_id: str, locator: str, pointer: str) -> str:
    digest = sha256_hex(f"{snapshot_id}|{locator}|{pointer}".encode("utf-8"))[:16]
    return f"evidence-{source_id}-{digest}"


def normalize_catalog(
    catalog: Mapping[str, Any],
    *,
    catalog_locator: str,
    catalog_sha256: str,
    catalog_byte_count: int,
    source_id: str = "postgres-demo",
    tenant_id: str = "demo-bank",
    profile_prefix: str = "profiles/postgres-demo",
    limits: CatalogLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Normalize a validated catalog snapshot into profile artifacts.

    Returns a mapping of artifact file name to JSON-serializable content:
    ``profile.json``, ``evidence-index.json``, and ``snapshot.json``.
    """

    validated = validate_catalog(catalog, limits=limits)
    database = validated["database"]
    observed_at = validated["collected_at"]
    snapshot_id = f"{source_id}@sha256:{catalog_sha256}"

    tables: dict[str, dict[str, Any]] = {}
    for entry in sorted(
        validated["tables"], key=lambda item: (item["table_schema"], item["table_name"])
    ):
        qualified = f"{entry['table_schema']}.{entry['table_name']}"
        tables[qualified] = {
            "schema": entry["table_schema"],
            "name": entry["table_name"],
            "tableType": entry["table_type"],
            "rowEstimate": entry["row_estimate"],
            "sourceLocator": _table_locator(database, entry["table_schema"], entry["table_name"]),
            "primaryKey": None,
            "foreignKeys": [],
            "columns": {},
        }

    for entry in sorted(
        validated["columns"],
        key=lambda item: (item["table_schema"], item["table_name"], item["ordinal_position"]),
    ):
        qualified = f"{entry['table_schema']}.{entry['table_name']}"
        locator = (
            f"{_table_locator(database, entry['table_schema'], entry['table_name'])}"
            f"#column={entry['column_name']}"
        )
        tables[qualified]["columns"][entry["column_name"]] = {
            "ordinalPosition": entry["ordinal_position"],
            "dataType": entry["data_type"],
            "logicalType": _logical_type(entry["data_type"]),
            "nullable": entry["is_nullable"] == "YES",
            "sourceLocator": locator,
        }

    for entry in sorted(
        validated["primary_keys"],
        key=lambda item: (item["table_schema"], item["table_name"], item["constraint_name"]),
    ):
        qualified = f"{entry['table_schema']}.{entry['table_name']}"
        tables[qualified]["primaryKey"] = {
            "constraintName": entry["constraint_name"],
            "columns": list(entry["column_names"]),
        }

    for entry in sorted(
        validated["foreign_keys"],
        key=lambda item: (item["table_schema"], item["table_name"], item["constraint_name"]),
    ):
        qualified = f"{entry['table_schema']}.{entry['table_name']}"
        tables[qualified]["foreignKeys"].append(
            {
                "constraintName": entry["constraint_name"],
                "columns": list(entry["column_names"]),
                "referencedTable": f"{entry['referenced_schema']}.{entry['referenced_table']}",
                "referencedColumns": list(entry["referenced_columns"]),
            }
        )

    statistics = {
        "schemaCount": len(validated["schemas"]),
        "tableCount": len(validated["tables"]),
        "columnCount": len(validated["columns"]),
        "primaryKeyCount": len(validated["primary_keys"]),
        "foreignKeyCount": len(validated["foreign_keys"]),
    }
    profile = {
        "schemaVersion": PROFILE_SCHEMA_VERSION,
        "sourceId": source_id,
        "tenantId": tenant_id,
        "snapshotId": snapshot_id,
        "sourceContentSha256": catalog_sha256,
        "sourceLocator": catalog_locator,
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "database": database,
        "serverVersion": validated["server_version"],
        "valueSampling": "disabled",
        "readOnlyEnforcement": dict(READ_ONLY_CONNECTION_OPTIONS),
        "bounds": {
            "maximumSchemas": limits.maximum_schemas,
            "maximumTables": limits.maximum_tables,
            "maximumColumns": limits.maximum_columns,
            "observedSchemas": statistics["schemaCount"],
            "observedTables": statistics["tableCount"],
            "observedColumns": statistics["columnCount"],
        },
        "statistics": statistics,
        "schemas": sorted(entry["schema_name"] for entry in validated["schemas"]),
        "tables": tables,
    }

    def evidence_entry(
        *, claim: dict[str, Any], locator: str, coordinates: dict[str, Any],
        policy_tags: list[str], content_sha256: str | None = None,
    ) -> dict[str, Any]:
        pointer = str(coordinates.get("profilePointer", coordinates.get("artifact", "")))
        return {
            "evidenceId": _evidence_id(source_id, snapshot_id, locator, pointer),
            "tenantId": tenant_id,
            "sourceId": source_id,
            "snapshotId": snapshot_id,
            "locator": locator,
            "claim": claim,
            "classification": "INTERNAL",
            "contentSha256": content_sha256 or sha256_hex(compact_json_bytes(claim)),
            "normalizedCoordinates": coordinates,
            "observedAt": observed_at,
            "extractorName": EXTRACTOR_NAME,
            "extractorVersion": EXTRACTOR_VERSION,
            "policyTags": policy_tags,
        }

    evidence: list[dict[str, Any]] = [
        evidence_entry(
            claim={
                "byteCount": catalog_byte_count,
                "schemaCount": statistics["schemaCount"],
                "tableCount": statistics["tableCount"],
                "columnCount": statistics["columnCount"],
            },
            locator=catalog_locator,
            coordinates={"artifact": "catalog-snapshot"},
            policy_tags=["metadata-only", "read-only", "snapshot"],
            content_sha256=catalog_sha256,
        ),
        evidence_entry(
            claim={"profileStatistics": statistics},
            locator=f"{profile_prefix}/profile.json#/statistics",
            coordinates={"profilePointer": "/statistics"},
            policy_tags=["bounded-profile", "metadata-only", "read-only"],
        ),
    ]
    for qualified, table in tables.items():
        claim = {
            "tableMetadata": {
                "tableType": table["tableType"],
                "rowEstimate": table["rowEstimate"],
                "columnCount": len(table["columns"]),
                "primaryKey": table["primaryKey"],
            }
        }
        evidence.append(
            evidence_entry(
                claim=claim,
                locator=table["sourceLocator"],
                coordinates={
                    "table": qualified,
                    "profilePointer": f"/tables/{qualified}",
                },
                policy_tags=["metadata-only", "read-only"],
            )
        )
        for foreign_key in table["foreignKeys"]:
            evidence.append(
                evidence_entry(
                    claim={"relationshipEvidence": foreign_key},
                    locator=(
                        f"{table['sourceLocator']}"
                        f"#constraint={foreign_key['constraintName']}"
                    ),
                    coordinates={
                        "constraint": foreign_key["constraintName"],
                        "profilePointer": f"/tables/{qualified}/foreignKeys",
                    },
                    policy_tags=["metadata-only", "read-only", "relationship-profile"],
                )
            )

    evidence_index = {
        "schemaVersion": PROFILE_SCHEMA_VERSION,
        "sourceId": source_id,
        "tenantId": tenant_id,
        "snapshotId": snapshot_id,
        "sourceContentSha256": catalog_sha256,
        "sourceLocator": catalog_locator,
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "evidence": evidence,
    }

    snapshot = {
        "schemaVersion": PROFILE_SCHEMA_VERSION,
        "accessMode": "read_only",
        "sourceId": source_id,
        "tenantId": tenant_id,
        "snapshotId": snapshot_id,
        "sourceLocator": catalog_locator,
        "profileLocator": f"{profile_prefix}/profile.json",
        "extractorName": EXTRACTOR_NAME,
        "extractorVersion": EXTRACTOR_VERSION,
        "observedAt": observed_at,
        "valueSampling": "disabled",
        "readOnlyEnforcement": dict(READ_ONLY_CONNECTION_OPTIONS),
        "content": {
            "byteCount": catalog_byte_count,
            "sha256": catalog_sha256,
            "schemaCount": statistics["schemaCount"],
            "tableCount": statistics["tableCount"],
            "columnCount": statistics["columnCount"],
            "sourceAssets": [
                {
                    "path": catalog_locator,
                    "mediaType": "application/json",
                    "byteCount": catalog_byte_count,
                    "sha256": catalog_sha256,
                }
            ],
        },
    }

    return {
        "profile.json": profile,
        "evidence-index.json": evidence_index,
        "snapshot.json": snapshot,
    }


def normalize_catalog_bytes(
    catalog_bytes: bytes,
    *,
    catalog_locator: str,
    source_id: str = "postgres-demo",
    tenant_id: str = "demo-bank",
    profile_prefix: str = "profiles/postgres-demo",
    limits: CatalogLimits = DEFAULT_LIMITS,
) -> dict[str, Any]:
    """Parse and normalize raw catalog snapshot bytes (content-hash pinned)."""

    try:
        catalog = json.loads(catalog_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CatalogPolicyError(f"catalog snapshot is not valid UTF-8 JSON: {error}") from error
    return normalize_catalog(
        catalog,
        catalog_locator=catalog_locator,
        catalog_sha256=sha256_hex(catalog_bytes),
        catalog_byte_count=len(catalog_bytes),
        source_id=source_id,
        tenant_id=tenant_id,
        profile_prefix=profile_prefix,
        limits=limits,
    )


def write_profile_bundle(artifacts: Mapping[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in sorted(artifacts):
        path = output_dir / name
        path.write_bytes(json_bytes(artifacts[name]))
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ontology_appliance_gateway.connectors.postgres",
        description=(
            "Normalize a PostgreSQL catalog snapshot (JSON produced by the documented "
            "read-only information_schema/pg_catalog SQL) into deterministic profile, "
            "evidence-index, and snapshot artifacts. No database connection is opened."
        ),
    )
    parser.add_argument("catalog", type=Path, help="catalog snapshot JSON file")
    parser.add_argument("output", type=Path, help="output profile directory")
    parser.add_argument("--source-id", default="postgres-demo")
    parser.add_argument("--tenant-id", default="demo-bank")
    parser.add_argument(
        "--catalog-locator",
        default=None,
        help="stable evidence locator for the catalog snapshot (defaults to the input path)",
    )
    parser.add_argument(
        "--profile-prefix",
        default=None,
        help="locator prefix for profile artifacts (defaults to profiles/<output name>)",
    )
    args = parser.parse_args(argv)

    catalog_bytes = args.catalog.read_bytes()
    artifacts = normalize_catalog_bytes(
        catalog_bytes,
        catalog_locator=args.catalog_locator or args.catalog.as_posix(),
        source_id=args.source_id,
        tenant_id=args.tenant_id,
        profile_prefix=args.profile_prefix or f"profiles/{args.output.name}",
    )
    for path in write_profile_bundle(artifacts, args.output):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
