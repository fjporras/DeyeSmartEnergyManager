"""Optional InfluxDB price source (REE indicators bucket).

HA's influxdb config entry is export-only: it holds the connection
(URL/token/org/bucket) but creates no entities. This module reuses that
connection — never duplicating credentials — and runs read-only Flux
queries to fetch hourly import ("consumo") and export ("vertido")
prices.

Measurement/field names can be set explicitly in the options; when left
empty they are auto-discovered via ``influxdb/schema`` and cached.

Degrades gracefully: any failure returns ``None`` and the coordinator
falls back to PVPC + the fixed export price.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from .const import (
    CONF_INFLUX_BUCKET,
    CONF_INFLUX_EXPORT_FIELD,
    CONF_INFLUX_EXPORT_MEASUREMENT,
    CONF_INFLUX_EXPORT_TAG,
    CONF_INFLUX_IMPORT_FIELD,
    CONF_INFLUX_IMPORT_MEASUREMENT,
    CONF_INFLUX_IMPORT_TAG,
    CONF_INFLUX_ORG,
    CONF_INFLUX_TAG_KEY,
    CONF_INFLUX_TOKEN,
    CONF_INFLUX_URL,
    CONF_INFLUX_VERIFY_SSL,
    DEFAULT_INFLUX_BUCKET,
    DEFAULT_INFLUX_EXPORT_FIELD,
    DEFAULT_INFLUX_EXPORT_MEASUREMENT,
    DEFAULT_INFLUX_EXPORT_TAG,
    DEFAULT_INFLUX_IMPORT_FIELD,
    DEFAULT_INFLUX_IMPORT_MEASUREMENT,
    DEFAULT_INFLUX_IMPORT_TAG,
    DEFAULT_INFLUX_TAG_KEY,
)

_LOGGER = logging.getLogger(__name__)

INFLUX_DOMAIN = "influxdb"

# Name patterns for auto-discovery (measurement or field names).
# The REE ESIOS indicator codes (1001 = PVPC consumo, 1739 = vertido)
# are matched literally — the bucket may store them as measurement or
# field names.
_IMPORT_RE = re.compile(
    r"pvpc|precio.*consumo|price|omie|spot|consumo|import|compra|\b1001\b",
    re.I,
)
_EXPORT_RE = re.compile(
    r"vertido|export|feed.?in|compensa|excedent|venta|sell|\b1739\b",
    re.I,
)


@dataclass(frozen=True)
class InfluxSettings:
    """Connection + series mapping for the price bucket."""

    url: str
    token: str
    org: str
    bucket: str
    api_version: str | None = None
    entry_keys: tuple[str, ...] = ()
    verify_ssl: bool = True
    tag_key: str | None = None
    import_measurement: str | None = None
    import_field: str | None = None
    import_tag: str | None = None
    export_measurement: str | None = None
    export_field: str | None = None
    export_tag: str | None = None


def get_influx_settings(hass, options: dict) -> InfluxSettings | None:
    """Build settings from HA's own influxdb config entry + overrides.

    When no usable influxdb entry exists, falls back to explicit
    connection options (url/token/org) so the HA influxdb integration —
    which only *exports* — can be removed entirely.
    """
    base = None
    for entry in hass.config_entries.async_entries(INFLUX_DOMAIN):
        data = dict(entry.data)
        if data.get("url") and data.get("token"):
            base = data
            break
    if base is None:
        url = options.get(CONF_INFLUX_URL)
        token = options.get(CONF_INFLUX_TOKEN)
        if not url or not token:
            return None
        base = {
            "url": url,
            "token": token,
            "organization": options.get(CONF_INFLUX_ORG) or "",
            "api_version": "2",
            "verify_ssl": bool(
                options.get(CONF_INFLUX_VERIFY_SSL, True)
            ),
        }
    settings = InfluxSettings(
        url=base["url"],
        token=base["token"],
        org=(
            base.get("org")
            or base.get("organization")
            or base.get("org_name")
            or ""
        ),
        # Read bucket is independent from the export bucket configured
        # in HA's influxdb entry (that one only receives HA state writes).
        bucket=(
            options.get(CONF_INFLUX_BUCKET)
            or base.get("bucket")
            or base.get("bucket_name")
            or DEFAULT_INFLUX_BUCKET
        ),
        api_version=str(base.get("api_version") or ""),
        entry_keys=tuple(sorted(base.keys())),
        verify_ssl=bool(base.get("verify_ssl", True)),
        tag_key=options.get(CONF_INFLUX_TAG_KEY) or DEFAULT_INFLUX_TAG_KEY,
        import_measurement=options.get(CONF_INFLUX_IMPORT_MEASUREMENT)
        or DEFAULT_INFLUX_IMPORT_MEASUREMENT,
        import_field=options.get(CONF_INFLUX_IMPORT_FIELD)
        or DEFAULT_INFLUX_IMPORT_FIELD,
        import_tag=options.get(CONF_INFLUX_IMPORT_TAG)
        or DEFAULT_INFLUX_IMPORT_TAG,
        export_measurement=options.get(CONF_INFLUX_EXPORT_MEASUREMENT)
        or DEFAULT_INFLUX_EXPORT_MEASUREMENT,
        export_field=options.get(CONF_INFLUX_EXPORT_FIELD)
        or DEFAULT_INFLUX_EXPORT_FIELD,
        export_tag=options.get(CONF_INFLUX_EXPORT_TAG)
        or DEFAULT_INFLUX_EXPORT_TAG,
    )
    return settings


def _esc(value: str) -> str:
    """Escape a config string for safe Flux embedding."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _hourly_flux(
    bucket: str,
    measurement: str,
    field: str,
    start: datetime,
    stop: datetime,
    tag_key: str | None = None,
    tag_value: str | None = None,
) -> str:
    """Flux query: hourly mean of a measurement/field over a range."""
    tag_filter = ""
    if tag_key and tag_value:
        tag_filter = (
            f' and r["{_esc(tag_key)}"] == "{_esc(tag_value)}"'
        )
    return (
        f'from(bucket: "{_esc(bucket)}")'
        f' |> range(start: {start.isoformat()}, stop: {stop.isoformat()})'
        f' |> filter(fn: (r) => r._measurement == "{_esc(measurement)}"'
        f' and r._field == "{_esc(field)}"{tag_filter})'
        " |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)"
        ' |> keep(columns: ["_time", "_value"])'
    )


def _sync_query_prices(
    settings: InfluxSettings, start: datetime, stop: datetime
) -> tuple[dict[datetime, float], dict[datetime, float], dict]:
    """Blocking InfluxDB query; runs in the executor.

    Returns (import_points, export_points, meta) where points map an
    aware UTC hour to a float price.
    """
    from influxdb_client import InfluxDBClient  # provided by HA influxdb

    meta: dict[str, str] = {}
    client = InfluxDBClient(
        url=settings.url,
        token=settings.token,
        org=settings.org,
        verify_ssl=settings.verify_ssl,
    )
    try:
        query_api = client.query_api()

        import_m, import_f = settings.import_measurement, settings.import_field
        export_m, export_f = settings.export_measurement, settings.export_field
        import_tag, export_tag = settings.import_tag, settings.export_tag
        if not all((import_m, import_f, export_m, export_f)):
            import_m, import_f, export_m, export_f, discovered = (
                _discover(
                    query_api, settings.bucket, import_m, import_f,
                    export_m, export_f, meta,
                )
            )
            meta["influx_measurements"] = (
                ",".join(str(m) for m in discovered[:30]) or "none"
            )
        if "influx_measurements" not in meta:
            try:
                tables = query_api.query(
                    'import "influxdata/influxdb/schema"'
                    f' schema.measurements(bucket: "{_esc(settings.bucket)}")'
                )
                names = [
                    r.get_value() for t in tables for r in t.records
                ]
                meta["influx_measurements"] = (
                    ",".join(str(n) for n in names[:100]) or "none"
                )
            except Exception as err:  # noqa: BLE001
                meta["influx_discover_error"] = f"{err!r}"[:150]
        def series_label(m, f, tag):
            if not m:
                return "not_found"
            suffix = f"[{settings.tag_key}={tag}]" if tag else ""
            return f"{m}.{f}{suffix}"

        meta["import_series"] = series_label(import_m, import_f, import_tag)
        meta["export_series"] = series_label(export_m, export_f, export_tag)

        def points(measurement, field, tag):
            if not measurement or not field:
                return {}
            out: dict[datetime, float] = {}
            tables = query_api.query(
                _hourly_flux(
                    settings.bucket, measurement, field, start, stop,
                    settings.tag_key, tag,
                )
            )
            for table in tables:
                for record in table.records:
                    try:
                        hour = record.get_time().replace(
                            minute=0, second=0, microsecond=0
                        )
                        out[hour] = float(record.get_value())
                    except (TypeError, ValueError):
                        continue
            return out

        def peek(measurement, kind, tag=None):
            """Raw points of a measurement — diagnostic sample with tags."""
            tag_filter = ""
            if tag and settings.tag_key:
                tag_filter = (
                    f' and r["{_esc(settings.tag_key)}"]'
                    f' == "{_esc(tag)}"'
                )
            try:
                tables = query_api.query(
                    f'from(bucket: "{_esc(settings.bucket)}")'
                    " |> range(start: -365d)"
                    f' |> filter(fn: (r) => '
                    f'r._measurement == "{_esc(measurement)}"'
                    f"{tag_filter})"
                    " |> last()"
                )
                sample = [
                    f"{r.get_time()}|{r.values.get(settings.tag_key) or ''}"
                    f"|{r.get_field()}={r.get_value()}"
                    for t in tables
                    for r in t.records
                ][:8]
                meta[f"influx_{kind}_sample"] = (
                    ";".join(sample) or "empty"
                )
            except Exception as err:  # noqa: BLE001
                meta[f"influx_{kind}_sample"] = f"err:{err!r}"[:150]

        meta["influx_api_version"] = settings.api_version or "?"
        meta["influx_bucket"] = settings.bucket
        meta["influx_org"] = settings.org
        meta["influx_entry_keys"] = ",".join(settings.entry_keys)

        imp_pts = points(import_m, import_f, import_tag)
        exp_pts = points(export_m, export_f, export_tag)
        if not imp_pts and import_m:
            peek(import_m, "import", import_tag)
        if not exp_pts and export_m:
            peek(export_m, "export", export_tag)
        return imp_pts, exp_pts, meta
    finally:
        client.close()


def _discover(query_api, bucket, import_m, import_f, export_m, export_f,
              meta):
    """Auto-discover measurement/field pairs via influxdb/schema.

    Returns (import_m, import_f, export_m, export_f, measurements).
    Discovery errors are surfaced in ``meta`` for diagnosis."""
    try:
        tables = query_api.query(
            'import "influxdata/influxdb/schema"'
            f' schema.measurements(bucket: "{_esc(bucket)}")'
        )
        measurements = [r.get_value() for t in tables for r in t.records]
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("DSEM influx measurement discovery failed: %s", err)
        meta["influx_discover_error"] = str(err)[:200]
        measurements = []

    def pick(measurement, field, pattern):
        """Resolve (measurement, field) honoring explicit overrides."""
        candidates = [measurement] if measurement else [
            m for m in measurements if pattern.search(str(m))
        ]
        if not candidates and measurement:
            candidates = [measurement]
        if not candidates and not measurement and len(measurements) == 1:
            candidates = measurements
        if not candidates:
            return None, field
        m = candidates[0]
        if field:
            return m, field
        try:
            ft = query_api.query(
                'import "influxdata/influxdb/schema"'
                f' schema.fieldKeys(bucket: "{_esc(bucket)}",'
                f' predicate: (r) => r._measurement == "{_esc(m)}")'
            )
            fields = [r.get_value() for t in ft for r in t.records]
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("DSEM influx field discovery failed: %s", err)
            meta["influx_fieldkeys_error"] = str(err)[:200]
            fields = []
        f = next((f for f in fields if pattern.search(str(f))), None)
        if f is None and len(fields) == 1:
            f = fields[0]
        return m, f or "value"

    import_m, import_f = pick(import_m, import_f, _IMPORT_RE)
    export_m, export_f = pick(export_m, export_f, _EXPORT_RE)
    return import_m, import_f, export_m, export_f, measurements


async def async_query_hourly_prices(
    hass, settings: InfluxSettings, now: datetime, horizon_hours: int
) -> tuple[dict[datetime, float], dict[datetime, float], dict] | None:
    """Fetch hourly price points covering the plan horizon.

    ``now`` must be tz-aware. Returns (imp, exp, meta) or None on
    failure; meta carries the error so it is visible in plan_meta.
    """
    start = (now - timedelta(days=2)).replace(
        minute=0, second=0, microsecond=0
    )
    stop = now + timedelta(hours=horizon_hours + 2)
    try:
        return await hass.async_add_executor_job(
            _sync_query_prices, settings, start, stop
        )
    except Exception as err:  # noqa: BLE001 - optional source, degrade
        _LOGGER.debug("DSEM influx price query failed: %s", err)
        # ApiException carries the Flux error detail in .body
        detail = getattr(err, "body", None) or str(err)
        return {}, {}, {"influx_error": str(detail)[:300]}
