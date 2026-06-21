import os
import sys
import socket
import subprocess
import logging
import time
from typing import Optional

import requests
import docker

CONFIG_PATH: str = os.getenv("TELEGRAF_CONFIG_PATH", "/etc/telegraf_dynamic/telegraf.conf")
CHECK_INTERVAL: int = int(os.getenv("CHECK_INTERVAL", "30"))
TELEGRAF_CONTAINER: str = os.getenv("TELEGRAF_CONTAINER_NAME", "adaptive_telegraf")
INFLUXDB_URL: str = os.getenv("INFLUXDB_URL", "http://127.0.0.1:8086")
INFLUXDB_TOKEN: str = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG: str = os.getenv("INFLUXDB_ORG", "homelab")
INFLUXDB_BUCKET: str = os.getenv("INFLUXDB_BUCKET", "realtime_metrics")
SNMP_COMMUNITY: str = os.getenv("SNMP_COMMUNITY", "public")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# SNMP v2c GetRequest for sysDescr.0 (OID 1.3.6.1.2.1.1.1.0)
_SNMP_PROBE = bytes([
    0x30, 0x29,
    0x02, 0x01, 0x01,
    0x04, 0x06, 0x70, 0x75, 0x62, 0x6c, 0x69, 0x63,
    0xa0, 0x1c,
    0x02, 0x04, 0x00, 0x00, 0x00, 0x01,
    0x02, 0x01, 0x00,
    0x02, 0x01, 0x00,
    0x30, 0x0e,
    0x30, 0x0c,
    0x06, 0x08, 0x2b, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00,
    0x05, 0x00,
])

# OUI prefix (first 8 chars of normalised MAC, e.g. "F8:E9:03") -> vendor
VENDOR_TABLE: dict[str, str] = {
    # TP-Link
    "F8:E9:03": "TP-Link",  "50:D4:F7": "TP-Link",  "AC:84:C6": "TP-Link",
    "04:BF:6D": "TP-Link",  "14:CC:20": "TP-Link",  "68:FF:7B": "TP-Link",
    "B0:4E:26": "TP-Link",  "A0:F3:C1": "TP-Link",  "00:27:19": "TP-Link",
    "54:A7:03": "TP-Link",  "98:DA:C4": "TP-Link",  "C4:E9:84": "TP-Link",
    # ASUS
    "00:23:69": "ASUS",     "00:26:5A": "ASUS",     "2C:FD:A1": "ASUS",
    "AC:9E:17": "ASUS",     "00:11:D8": "ASUS",     "04:92:26": "ASUS",
    "50:46:5D": "ASUS",     "74:D0:2B": "ASUS",
    # Netgear
    "00:1E:2A": "Netgear",  "00:14:6C": "Netgear",  "C0:3F:0E": "Netgear",
    "00:18:4D": "Netgear",  "A0:21:B7": "Netgear",  "20:E5:2A": "Netgear",
    "84:1B:5E": "Netgear",  "9C:3D:CF": "Netgear",
    # Cisco / Linksys
    "00:14:BF": "Linksys",  "00:1C:10": "Cisco",    "00:17:DF": "Cisco",
    "00:1B:54": "Cisco",    "00:40:96": "Cisco",    "58:BC:27": "Cisco",
    "FC:FB:FB": "Cisco",    "00:00:0C": "Cisco",
    # D-Link
    "00:1C:F0": "D-Link",   "B8:A3:86": "D-Link",   "00:19:5B": "D-Link",
    "28:10:7B": "D-Link",   "1C:7E:E5": "D-Link",   "84:C9:B2": "D-Link",
    # Huawei
    "00:46:4B": "Huawei",   "00:E0:FC": "Huawei",   "48:00:31": "Huawei",
    "04:BD:70": "Huawei",   "20:08:ED": "Huawei",   "6C:8D:C1": "Huawei",
    # MikroTik
    "4C:5E:0C": "MikroTik", "6C:3B:6B": "MikroTik", "00:0C:42": "MikroTik",
    "CC:2D:E0": "MikroTik", "E4:8D:8C": "MikroTik", "B8:69:F4": "MikroTik",
    # Ubiquiti
    "00:15:6D": "Ubiquiti", "04:18:D6": "Ubiquiti", "78:8A:20": "Ubiquiti",
    "DC:9F:DB": "Ubiquiti", "00:27:22": "Ubiquiti", "24:A4:3C": "Ubiquiti",
    # AVM FRITZ!Box
    "AC:16:2D": "AVM",      "C4:86:E9": "AVM",      "00:04:0E": "AVM",
    "3C:A6:2F": "AVM",      "90:8D:78": "AVM",
    # Raspberry Pi
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    # VMware / Hyper-V (virtual environments)
    "00:50:56": "VMware",   "00:0C:29": "VMware",   "00:15:5D": "Microsoft Hyper-V",
}


def lookup_vendor(mac: str) -> str:
    oui = mac[:8]
    if oui in VENDOR_TABLE:
        return VENDOR_TABLE[oui]
    try:
        resp = requests.get(
            f"https://api.macvendors.com/{mac}",
            timeout=3,
            headers={"Accept": "text/plain"},
        )
        if resp.status_code == 200:
            return resp.text.strip()
    except requests.RequestException:
        pass
    return "Unknown"


def get_gateway_details() -> tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        route_out = subprocess.check_output(
            ["ip", "route", "show", "default"], text=True
        )
        parts = route_out.split()
        gateway_ip = parts[parts.index("via") + 1]
        interface = parts[parts.index("dev") + 1]
    except (subprocess.CalledProcessError, ValueError, IndexError):
        return None, None, None

    subprocess.run(
        ["ping", "-c", "1", "-W", "1", gateway_ip],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        arp_out = subprocess.check_output(["arp", "-n", gateway_ip], text=True)
    except subprocess.CalledProcessError:
        return None, None, None

    gateway_mac = ""
    for line in arp_out.splitlines():
        if gateway_ip in line:
            cols = line.split()
            if len(cols) >= 3 and cols[2] not in ("(incomplete)", "<incomplete>"):
                gateway_mac = cols[2]
            break

    if not gateway_mac:
        return None, None, None

    return gateway_ip, interface, gateway_mac.upper()


def check_snmp(ip: str) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    try:
        sock.sendto(_SNMP_PROBE, (ip, 161))
        data, _ = sock.recvfrom(1024)
        return len(data) > 0
    except (socket.timeout, OSError):
        return False
    finally:
        sock.close()


def build_telegraf_config(
    ip: str,
    iface: str,
    vendor: str,
    snmp_enabled: bool,
) -> str:
    config = f"""\
[agent]
  interval = "5s"
  flush_interval = "5s"
  hostname = "adaptive-node"

[global_tags]
  router_vendor = "{vendor}"
  gateway_ip    = "{ip}"

[[outputs.influxdb_v2]]
  urls         = ["{INFLUXDB_URL}"]
  token        = "{INFLUXDB_TOKEN}"
  organization = "{INFLUXDB_ORG}"
  bucket       = "{INFLUXDB_BUCKET}"

[[inputs.net]]
  interfaces = ["{iface}"]

[[inputs.ping]]
  urls             = ["{ip}"]
  count            = 1
  ping_interval    = 1.0
  deadline         = 5
"""

    if snmp_enabled:
        config += f"""
[[inputs.snmp]]
  agents    = ["{ip}:161"]
  version   = 2
  community = "{SNMP_COMMUNITY}"
  name      = "router_snmp"

  [[inputs.snmp.field]]
    name = "uptime"
    oid  = "DISMAN-EXPRESSION-MIB::sysUpTimeInstance"

  [[inputs.snmp.field]]
    name = "sysName"
    oid  = "SNMPv2-MIB::sysName.0"

  [[inputs.snmp.field]]
    name = "sysDescr"
    oid  = "SNMPv2-MIB::sysDescr.0"

  [[inputs.snmp.table]]
    name = "router_interface"
    oid  = "IF-MIB::ifTable"
"""

    return config


def write_config(config: str) -> None:
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(config)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)
    log.info("telegraf.conf written to %s", CONFIG_PATH)


def reload_telegraf() -> None:
    try:
        client = docker.from_env()
        container = client.containers.get(TELEGRAF_CONTAINER)
        container.kill(signal="HUP")
        log.info("Telegraf reloaded via SIGHUP.")
    except docker.errors.NotFound:
        log.warning("Container '%s' not found; skipping reload.", TELEGRAF_CONTAINER)
    except docker.errors.APIError as exc:
        log.error("Docker API error during reload: %s", exc)


def main() -> None:
    log.info(
        "Discovery daemon started | interval=%ds container=%s",
        CHECK_INTERVAL,
        TELEGRAF_CONTAINER,
    )
    last_key = ""

    while True:
        ip, iface, mac = get_gateway_details()

        if ip and mac:
            key = f"{ip}-{mac}"
            if key != last_key:
                vendor = lookup_vendor(mac)
                snmp_up = check_snmp(ip)
                log.info(
                    "Router change | IP=%s MAC=%s Vendor=%s SNMP=%s iface=%s",
                    ip, mac, vendor, snmp_up, iface,
                )
                config = build_telegraf_config(ip, iface, vendor, snmp_up)
                write_config(config)
                reload_telegraf()
                last_key = key
        else:
            log.warning("No gateway detected; retrying in %ds.", CHECK_INTERVAL)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
