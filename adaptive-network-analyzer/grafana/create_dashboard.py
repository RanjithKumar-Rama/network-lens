#!/usr/bin/env python3
"""
Grafana dashboard generator for network-lens.

Usage:
    python3 create_dashboard.py              # write JSON to disk
    python3 create_dashboard.py --push       # write + push to live Grafana
"""
import argparse
import json
import os
import sys

import requests

GRAFANA_URL      = os.getenv("GRAFANA_URL", "http://localhost:3000")
GRAFANA_USER     = os.getenv("GRAFANA_USER", "")
GRAFANA_PASSWORD = os.getenv("GRAFANA_PASSWORD", "")
INFLUXDB_BUCKET  = os.getenv("INFLUXDB_BUCKET", "realtime_metrics")
DS_UID           = "influxdb-adaptive"
OUTPUT_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboards", "network-lens.json")

_DS_REF = {"type": "influxdb", "uid": DS_UID}


def _target(ref_id: str, query: str) -> dict:
    return {"refId": ref_id, "datasource": _DS_REF, "query": query.strip()}


def _row(title: str, pid: int, y: int) -> dict:
    return {
        "id": pid, "type": "row", "title": title, "collapsed": False,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
    }


def _stat(title: str, pid: int, targets: list, unit: str = "short",
          x: int = 0, y: int = 0, w: int = 6, h: int = 4) -> dict:
    return {
        "id": pid, "type": "stat", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": _DS_REF,
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "textMode": "auto",
            "colorMode": "background",
            "graphMode": "none",
        },
        "targets": targets,
    }


def _timeseries(title: str, pid: int, targets: list, unit: str = "short",
                x: int = 0, y: int = 0, w: int = 12, h: int = 8) -> dict:
    return {
        "id": pid, "type": "timeseries", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": _DS_REF,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"lineWidth": 2, "fillOpacity": 8, "spanNulls": True},
            },
            "overrides": [],
        },
        "options": {
            "tooltip": {"mode": "multi", "sort": "none"},
            "legend": {"displayMode": "list", "placement": "bottom"},
        },
        "targets": targets,
    }


def _table(title: str, pid: int, targets: list,
           x: int = 0, y: int = 0, w: int = 24, h: int = 8) -> dict:
    return {
        "id": pid, "type": "table", "title": title,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": _DS_REF,
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {"sortBy": [], "footer": {"show": False}},
        "targets": targets,
    }


def build_dashboard(bucket: str) -> dict:
    panels = []
    pid = 1

    # ── Row: Overview ────────────────────────────────────────────────────────
    panels.append(_row("Overview", pid, y=0)); pid += 1

    panels.append(_stat("Gateway IP", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "ping")
  |> filter(fn: (r) => r["_field"] == "average_response_ms")
  |> last()
  |> map(fn: (r) => ({{r with _value: r["url"]}}))
""")], x=0, y=1, w=6, h=4)); pid += 1

    panels.append(_stat("Router Vendor", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "ping")
  |> filter(fn: (r) => r["_field"] == "average_response_ms")
  |> last()
  |> map(fn: (r) => ({{r with _value: r["router_vendor"]}}))
""")], x=6, y=1, w=6, h=4)); pid += 1

    panels.append(_stat("Avg Ping Latency", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "ping")
  |> filter(fn: (r) => r["_field"] == "average_response_ms")
  |> mean()
""")], unit="ms", x=12, y=1, w=6, h=4)); pid += 1

    panels.append(_stat("Packet Loss", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "ping")
  |> filter(fn: (r) => r["_field"] == "percent_packet_loss")
  |> mean()
""")], unit="percent", x=18, y=1, w=6, h=4)); pid += 1

    # ── Row: Connectivity ────────────────────────────────────────────────────
    panels.append(_row("Connectivity", pid, y=5)); pid += 1

    panels.append(_timeseries("Gateway Ping Latency", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "ping")
  |> filter(fn: (r) => r["_field"] == "average_response_ms")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
""")], unit="ms", x=0, y=6, w=12, h=8)); pid += 1

    panels.append(_timeseries("Packet Loss %", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "ping")
  |> filter(fn: (r) => r["_field"] == "percent_packet_loss")
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
""")], unit="percent", x=12, y=6, w=12, h=8)); pid += 1

    # ── Row: Interface Traffic ───────────────────────────────────────────────
    panels.append(_row("Interface Traffic", pid, y=14)); pid += 1

    panels.append(_timeseries("Throughput — Received vs Sent", pid, [
        _target("A", f"""
from(bucket: "{bucket}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "net")
  |> filter(fn: (r) => r["_field"] == "bytes_recv")
  |> derivative(unit: 1s, nonNegative: true)
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({{r with _field: "bytes_recv/s"}}))
"""),
        _target("B", f"""
from(bucket: "{bucket}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "net")
  |> filter(fn: (r) => r["_field"] == "bytes_sent")
  |> derivative(unit: 1s, nonNegative: true)
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
  |> map(fn: (r) => ({{r with _field: "bytes_sent/s"}}))
"""),
    ], unit="Bps", x=0, y=15, w=24, h=8)); pid += 1

    panels.append(_timeseries("Packets/s — Dropped & Errors", pid, [
        _target("A", f"""
from(bucket: "{bucket}")
  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)
  |> filter(fn: (r) => r["_measurement"] == "net")
  |> filter(fn: (r) => r["_field"] == "drop_in" or r["_field"] == "drop_out" or r["_field"] == "err_in" or r["_field"] == "err_out")
  |> derivative(unit: 1s, nonNegative: true)
  |> aggregateWindow(every: v.windowPeriod, fn: mean, createEmpty: false)
"""),
    ], unit="pps", x=0, y=23, w=24, h=7)); pid += 1

    # ── Row: Router Hardware (SNMP) ──────────────────────────────────────────
    panels.append(_row("Router Hardware — SNMP (when available)", pid, y=30)); pid += 1

    panels.append(_stat("Router Uptime", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "router_snmp")
  |> filter(fn: (r) => r["_field"] == "uptime")
  |> last()
  |> map(fn: (r) => ({{r with _value: float(v: r._value) / 100.0}}))
""")], unit="s", x=0, y=31, w=6, h=4)); pid += 1

    panels.append(_stat("System Name", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "router_snmp")
  |> filter(fn: (r) => r["_field"] == "sysName")
  |> last()
""")], x=6, y=31, w=6, h=4)); pid += 1

    panels.append(_stat("System Description", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -5m)
  |> filter(fn: (r) => r["_measurement"] == "router_snmp")
  |> filter(fn: (r) => r["_field"] == "sysDescr")
  |> last()
""")], x=12, y=31, w=12, h=4)); pid += 1

    panels.append(_table("SNMP Interface Table", pid, [_target("A", f"""
from(bucket: "{bucket}")
  |> range(start: -2m)
  |> filter(fn: (r) => r["_measurement"] == "router_interface")
  |> last()
  |> pivot(rowKey: ["_time", "ifIndex"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["ifIndex", "ifDescr", "ifType", "ifMtu", "ifSpeed", "ifOperStatus", "ifInOctets", "ifOutOctets"])
""")], x=0, y=35, w=24, h=8)); pid += 1

    return {
        "uid": "network-lens-main",
        "title": "Network Lens — Adaptive Monitor",
        "tags": ["network-lens", "adaptive", "router"],
        "timezone": "browser",
        "refresh": "10s",
        "schemaVersion": 38,
        "time": {"from": "now-30m", "to": "now"},
        "timepicker": {},
        "graphTooltip": 1,
        "editable": True,
        "fiscalYearStartMonth": 0,
        "liveNow": False,
        "panels": panels,
        "templating": {"list": []},
        "annotations": {"list": []},
        "links": [],
    }


def write_json(dashboard: dict) -> None:
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dashboard, f, indent=2)
    print(f"[dashboard] JSON written to {OUTPUT_PATH}")


def push_to_grafana(dashboard: dict) -> None:
    session = requests.Session()
    session.auth = (GRAFANA_USER, GRAFANA_PASSWORD)
    session.headers.update({"Content-Type": "application/json"})

    resp = session.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        json={"dashboard": dashboard, "overwrite": True, "folderId": 0},
        timeout=10,
    )
    if resp.status_code in (200, 201):
        uid = resp.json().get("uid", "")
        print(f"[dashboard] Pushed OK -> {GRAFANA_URL}/d/{uid}")
    else:
        print(f"[dashboard] Push failed [{resp.status_code}]: {resp.text}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true",
                        help="Push dashboard to the live Grafana instance after generating")
    args = parser.parse_args()

    if args.push:
        missing = [v for v in ("GRAFANA_USER", "GRAFANA_PASSWORD") if not os.getenv(v)]
        if missing:
            print(f"[dashboard] ERROR: required env vars not set: {', '.join(missing)}", file=sys.stderr)
            sys.exit(1)

    dashboard = build_dashboard(INFLUXDB_BUCKET)
    write_json(dashboard)
    if args.push:
        push_to_grafana(dashboard)


if __name__ == "__main__":
    main()
