#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PORTS = [
    22, 23, 53, 80, 81, 443, 445, 515, 554, 631, 1883, 1900, 3389, 5900,
    6668, 8000, 8080, 8123, 8443, 8883, 9100, 32400, 5000, 55443
]

PORT_SERVICE = {
    22: "ssh",
    23: "telnet",
    53: "dns",
    80: "http",
    81: "http-alt",
    443: "https",
    445: "smb",
    515: "lpr",
    554: "rtsp",
    631: "ipp",
    1883: "mqtt",
    1900: "ssdp",
    6668: "tuya",
    3389: "rdp",
    5900: "vnc",
    8000: "http-alt",
    8080: "http-alt",
    8123: "home-assistant",
    8443: "https-alt",
    8883: "mqtts",
    9100: "printer-raw",
    32400: "plex",
    5000: "http-alt",
    55443: "yeelight",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cmd(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def detect_network() -> dict:
    if not shutil.which("ip"):
        raise RuntimeError("Commande 'ip' introuvable. Installez 'iproute2'.")

    routes = run_cmd(["ip", "-4", "route", "show"])
    cidr = None
    dev = None
    gateway = None
    src_ip = None

    for line in routes.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "default" and "via" in parts:
            try:
                gateway = parts[parts.index("via") + 1]
            except (ValueError, IndexError):
                gateway = None
            if "dev" in parts:
                try:
                    dev = parts[parts.index("dev") + 1]
                except (ValueError, IndexError):
                    dev = dev
        if "scope" in parts and "link" in parts and "/" in parts[0]:
            if not parts[0].startswith("169.254."):
                cidr = parts[0]
                if "dev" in parts:
                    try:
                        dev = parts[parts.index("dev") + 1]
                    except (ValueError, IndexError):
                        dev = dev
                if "src" in parts:
                    try:
                        src_ip = parts[parts.index("src") + 1]
                    except (ValueError, IndexError):
                        src_ip = None
                break

    if not cidr and dev:
        addr_out = run_cmd(["ip", "-4", "addr", "show", "dev", dev])
        for line in addr_out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                addr = line.split()[1]
                iface = ipaddress.ip_interface(addr)
                cidr = str(iface.network)
                src_ip = str(iface.ip)
                break

    if not cidr:
        raise RuntimeError("Impossible de detecter le reseau IPv4 local.")

    return {
        "cidr": cidr,
        "interface": dev,
        "gateway": gateway,
        "source_ip": src_ip,
    }


def parse_ports(raw: str | None) -> list[int]:
    if not raw:
        return DEFAULT_PORTS[:]
    ports = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_s, end_s = chunk.split("-", 1)
            start = int(start_s)
            end = int(end_s)
            for p in range(start, end + 1):
                ports.add(p)
        else:
            ports.add(int(chunk))
    return sorted(ports)


def ping_host(ip: str, timeout_s: int) -> tuple[str, bool, float | None]:
    if not shutil.which("ping"):
        return ip, False, None
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout_s), ip],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            match = re.search(r"time[=<]([\d.]+)\s*ms", result.stdout)
            rtt = float(match.group(1)) if match else None
            return ip, True, rtt
    except Exception:
        pass
    return ip, False, None


def ping_sweep(hosts: list[str], timeout_s: int, workers: int) -> dict[str, dict]:
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(ping_host, ip, timeout_s) for ip in hosts]
        for fut in as_completed(futures):
            ip, ok, rtt = fut.result()
            results[ip] = {"alive": ok, "ping_ms": rtt}
    return results


def read_neighbors() -> dict[str, dict]:
    neighbors = {}
    if not shutil.which("ip"):
        return neighbors
    out = run_cmd(["ip", "neigh", "show"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        ip = parts[0]
        dev = None
        mac = None
        state = parts[-1]
        if "dev" in parts:
            try:
                dev = parts[parts.index("dev") + 1]
            except (ValueError, IndexError):
                dev = None
        if "lladdr" in parts:
            try:
                mac = parts[parts.index("lladdr") + 1]
            except (ValueError, IndexError):
                mac = None
        neighbors[ip] = {"mac": mac, "state": state, "dev": dev}
    return neighbors


def check_port(ip: str, port: int, timeout_s: float) -> tuple[str, int, bool]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect((ip, port))
        sock.close()
        return ip, port, True
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return ip, port, False


def scan_ports(hosts: list[str], ports: list[int], timeout_s: float, workers: int) -> dict[str, list[int]]:
    results = {ip: [] for ip in hosts}
    tasks = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for ip in hosts:
            for port in ports:
                tasks.append(pool.submit(check_port, ip, port, timeout_s))
        for fut in as_completed(tasks):
            ip, port, open_ = fut.result()
            if open_:
                results[ip].append(port)
    for ip in results:
        results[ip] = sorted(results[ip])
    return results


def resolve_hostnames(hosts: list[str], timeout_s: float, workers: int) -> dict[str, str | None]:
    results = {}

    def _resolve(ip: str) -> tuple[str, str | None]:
        try:
            socket.setdefaulttimeout(timeout_s)
            name = socket.gethostbyaddr(ip)[0]
            return ip, name
        except Exception:
            return ip, None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_resolve, ip) for ip in hosts]
        for fut in as_completed(futures):
            ip, name = fut.result()
            results[ip] = name
    return results


def classify_services(open_ports: list[int]) -> list[str]:
    services = []
    for port in open_ports:
        services.append(PORT_SERVICE.get(port, f"tcp/{port}"))
    return services


def is_lamp_type(device_type: str) -> bool:
    value = (device_type or "").strip().lower()
    return value in {"lampe", "lamp", "light", "bulb"}


def yeelight_validate(ip: str, port: int, hold_s: float, timeout_s: float) -> tuple[bool, str]:
    cmd_id = 1000
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    try:
        sock.connect((ip, port))
    except Exception as exc:
        try:
            sock.close()
        except Exception:
            pass
        return False, f"connexion impossible: {exc}"

    def send_cmd(method: str, params: list) -> dict | None:
        nonlocal cmd_id
        cmd_id += 1
        payload = {"id": cmd_id, "method": method, "params": params}
        data = (json.dumps(payload) + "\r\n").encode()
        try:
            sock.sendall(data)
        except Exception:
            return None

        buf = b""
        start = time.time()
        while time.time() - start < timeout_s:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    lines = buf.splitlines()
                    for line in lines:
                        try:
                            resp = json.loads(line.decode(errors="ignore"))
                            if isinstance(resp, dict) and resp.get("id") == cmd_id:
                                return resp
                        except Exception:
                            continue
                    break
            except socket.timeout:
                break
            except Exception:
                break
        return None

    responses = []
    responses.append(send_cmd("set_power", ["on", "smooth", 300]))
    responses.append(send_cmd("set_scene", ["ct", 6500, 100]))
    time.sleep(max(0.0, hold_s))
    responses.append(send_cmd("set_power", ["off", "smooth", 300]))

    try:
        sock.close()
    except Exception:
        pass

    for resp in responses:
        if isinstance(resp, dict) and "error" in resp:
            message = resp.get("error", {}).get("message", "erreur")
            return False, message

    if any(resp is not None for resp in responses):
        return True, "ok"
    return False, "aucune reponse"


def load_tuya_devices(path: Path) -> dict:
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if isinstance(data, dict) and "devices" in data:
        items = data.get("devices") or []
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = list(data.values())
    else:
        items = []

    by_ip = {}
    by_name = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ip = item.get("ip") or item.get("address")
        name = item.get("name")
        if ip:
            by_ip[str(ip)] = item
        if name:
            by_name[str(name).strip().lower()] = item
    return {"by_ip": by_ip, "by_name": by_name}


def match_tuya_device(tuya_map: dict, ip: str, name: str | None) -> dict | None:
    if not tuya_map:
        return None
    by_ip = tuya_map.get("by_ip", {})
    by_name = tuya_map.get("by_name", {})
    if ip in by_ip:
        return by_ip.get(ip)
    if name:
        return by_name.get(name.strip().lower())
    return None


def tuya_validate(ip: str, hold_s: float, timeout_s: float, device: dict) -> tuple[bool, str]:
    try:
        import tinytuya
    except Exception as exc:
        return False, f"tinytuya indisponible: {exc}"

    dev_id = device.get("id") or device.get("device_id")
    local_key = device.get("key") or device.get("local_key")
    if not dev_id or not local_key:
        return False, "device id/local key manquant"

    version = device.get("version") or 3.3
    dev_type = (device.get("type") or device.get("device_type") or "bulb").lower()

    try:
        if dev_type in {"outlet", "switch", "plug"}:
            d = tinytuya.OutletDevice(dev_id, ip, local_key, version=version)
        else:
            d = tinytuya.BulbDevice(dev_id, ip, local_key)
            if hasattr(d, "set_version"):
                d.set_version(float(version))
        if hasattr(d, "set_socketPersistent"):
            d.set_socketPersistent(True)
        if hasattr(d, "set_sendWait"):
            d.set_sendWait(timeout_s)

        try:
            d.turn_on()
        except Exception:
            d.set_status(True)

        if hasattr(d, "set_white"):
            try:
                d.set_white(1000, 10)
            except Exception:
                try:
                    d.set_white_percentage(100, 0)
                except Exception:
                    pass

        time.sleep(max(0.0, hold_s))

        try:
            d.turn_off()
        except Exception:
            d.set_status(False)

        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def prompt(text: str, default: str | None = None) -> str:
    if default:
        text = f"{text} [{default}] "
    else:
        text = f"{text} "
    resp = input(text).strip()
    return resp if resp else (default or "")


def prompt_bool(text: str, default: bool | None = None) -> bool:
    if default is True:
        suffix = " [o]"
    elif default is False:
        suffix = " [n]"
    else:
        suffix = " [o/n]"
    while True:
        resp = input(f"{text}{suffix} ").strip().lower()
        if not resp and default is not None:
            return default
        if resp in {"o", "oui", "y", "yes"}:
            return True
        if resp in {"n", "non", "no"}:
            return False


def merge_existing(existing: dict | None) -> dict:
    if not existing:
        return {}
    mapping = {}
    for item in existing.get("devices", []):
        key = item.get("mac") or item.get("ip")
        if key:
            mapping[key] = item
    return mapping


def build_inventory(
    scan: dict,
    only_alive: bool,
    existing: dict | None,
    lamp_hold_s: float,
    yeelight_port: int,
    yeelight_timeout_s: float,
    yeelight_enabled: bool,
    tuya_devices: dict,
    tuya_enabled: bool,
    tuya_timeout_s: float,
    inventory_path: Path | None,
    skip_known: bool,
) -> dict:
    existing_map = merge_existing(existing)
    generated_at = now_iso()
    devices = []
    hosts = scan.get("hosts", [])
    for host in hosts:
        if only_alive and not host.get("alive"):
            continue
        key = host.get("mac") or host.get("ip")
        prev = existing_map.get(key, {})

        if skip_known and prev.get("name") and prev.get("device_type") and "validated" in prev:
            merged = dict(host)
            for field in (
                "name",
                "device_type",
                "validated",
                "notes",
                "validation",
                "control_allowed",
                "control_methods",
                "control_endpoint",
                "control_notes",
            ):
                if field in prev:
                    merged[field] = prev[field]
            devices.append(merged)
            if inventory_path:
                save_json(
                    inventory_path,
                    {"meta": {"generated_at": generated_at, "source_scan": scan.get("meta", {}).get("scan_id")}, "devices": devices},
                )
            continue

        print("\n---")
        print(f"IP: {host.get('ip')}")
        if host.get("hostname"):
            print(f"Hostname: {host.get('hostname')}")
        if host.get("mac"):
            print(f"MAC: {host.get('mac')} ({host.get('neighbor_state')})")
        if host.get("open_ports"):
            print(f"Ports ouverts: {host.get('open_ports')}")
        if host.get("services"):
            print(f"Services: {', '.join(host.get('services'))}")

        name = prompt("Nom du peripherique", prev.get("name") or "")
        device_type = prompt("Type (routeur, laptop, phone, tv, camera, iot, serveur, lampe, autre)", prev.get("device_type") or "")

        validation = prev.get("validation")
        if isinstance(validation, dict):
            validation = [validation]
        if not isinstance(validation, list):
            validation = []
        if is_lamp_type(device_type) and yeelight_enabled:
            ok, msg = yeelight_validate(host.get("ip"), yeelight_port, lamp_hold_s, yeelight_timeout_s)
            validation.append(
                {
                    "method": "yeelight-lan",
                    "ok": ok,
                    "message": msg,
                    "at": now_iso(),
                }
            )
            print(f"Validation Yeelight: {'OK' if ok else 'ECHEC'} ({msg})")
        if is_lamp_type(device_type) and tuya_enabled:
            tuya_device = match_tuya_device(tuya_devices, host.get("ip"), name)
            if tuya_device:
                ok, msg = tuya_validate(host.get("ip"), lamp_hold_s, tuya_timeout_s, tuya_device)
                validation.append(
                    {
                        "method": "tuya-lan",
                        "ok": ok,
                        "message": msg,
                        "at": now_iso(),
                    }
                )
                print(f"Validation Tuya: {'OK' if ok else 'ECHEC'} ({msg})")
            else:
                if "lepro" in (host.get("hostname") or "").lower():
                    print("Validation Tuya: impossible (pas d'info device id/local key)")
        validated = prompt_bool("Valider ce peripherique ?", prev.get("validated") if "validated" in prev else True)
        notes = prompt("Notes (optionnel)", prev.get("notes") or "")

        merged = dict(host)
        merged.update(
            {
                "name": name,
                "device_type": device_type,
                "validated": validated,
                "notes": notes,
                "validation": validation,
            }
        )
        devices.append(merged)
        if inventory_path:
            save_json(
                inventory_path,
                {"meta": {"generated_at": generated_at, "source_scan": scan.get("meta", {}).get("scan_id")}, "devices": devices},
            )

    return {
        "meta": {
            "generated_at": generated_at,
            "source_scan": scan.get("meta", {}).get("scan_id"),
        },
        "devices": devices,
    }


def build_control_targets(inventory: dict) -> dict:
    targets = []
    for device in inventory.get("devices", []):
        if not device.get("validated"):
            continue

        print("\n===")
        print(f"IP: {device.get('ip')}")
        if device.get("name"):
            print(f"Nom: {device.get('name')}")
        if device.get("open_ports"):
            print(f"Ports ouverts: {device.get('open_ports')}")
        if device.get("services"):
            print(f"Services: {', '.join(device.get('services'))}")

        suggested = []
        for port in device.get("open_ports") or []:
            if port in PORT_SERVICE:
                suggested.append(PORT_SERVICE[port])
        suggested = sorted(set(suggested))
        suggested_text = ", ".join(suggested) if suggested else ""

        allowed = prompt_bool("Didier peut-il prendre la main sur ce peripherique ?", device.get("control_allowed"))
        methods = []
        endpoint = ""
        notes = ""
        if allowed:
            methods_default = ", ".join(device.get("control_methods", [])) if device.get("control_methods") else suggested_text
            methods_raw = prompt("Methodes (ex: ssh,http,mqtt)", methods_default)
            methods = [m.strip() for m in methods_raw.split(",") if m.strip()]
            endpoint = prompt("Endpoint ou URL (optionnel)", device.get("control_endpoint") or "")
            notes = prompt("Notes de controle (optionnel)", device.get("control_notes") or "")

        target = {
            "ip": device.get("ip"),
            "mac": device.get("mac"),
            "name": device.get("name"),
            "device_type": device.get("device_type"),
            "control_allowed": allowed,
            "control_methods": methods,
            "control_endpoint": endpoint,
            "control_notes": notes,
        }
        if allowed:
            targets.append(target)

        device["control_allowed"] = allowed
        device["control_methods"] = methods
        device["control_endpoint"] = endpoint
        device["control_notes"] = notes

    return {
        "meta": {
            "generated_at": now_iso(),
            "source_inventory": inventory.get("meta", {}).get("generated_at"),
        },
        "targets": targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan reseau local + questionnaire.")
    parser.add_argument("--cidr", help="CIDR a scanner (ex: 192.168.1.0/24)")
    parser.add_argument("--ports", help="Liste ports TCP (ex: 22,80,443,8000-8100)")
    parser.add_argument("--max-hosts", type=int, default=1024, help="Limite de securite sur le nb d'hotes")
    parser.add_argument("--ping-timeout", type=int, default=1, help="Timeout ping (secondes)")
    parser.add_argument("--port-timeout", type=float, default=0.5, help="Timeout TCP (secondes)")
    parser.add_argument("--workers", type=int, default=64, help="Workers pour ping/ports")
    parser.add_argument("--only-alive", action="store_true", help="Questionnaire seulement pour les IP vivantes")
    parser.add_argument("--all-hosts", action="store_true", help="Questionnaire pour toutes les IP")
    parser.add_argument("--lamp-hold", type=float, default=1.2, help="Duree lampe ON en blanc (secondes)")
    parser.add_argument("--yeelight-port", type=int, default=55443, help="Port Yeelight LAN")
    parser.add_argument("--yeelight-timeout", type=float, default=1.5, help="Timeout Yeelight LAN (secondes)")
    parser.add_argument("--no-yeelight-test", action="store_true", help="Ne pas tester les lampes Yeelight")
    parser.add_argument("--tuya-devices", default="data/tuya_devices.json", help="Fichier JSON Tuya (id/key/ip)")
    parser.add_argument("--tuya-timeout", type=float, default=1.5, help="Timeout Tuya LAN (secondes)")
    parser.add_argument("--no-tuya-test", action="store_true", help="Ne pas tester les lampes Tuya")
    parser.add_argument("--skip-known", action="store_true", help="Sauter les peripheriques deja identifies")
    parser.add_argument("--mode", choices=["scan", "label", "control", "all"], default="all")
    parser.add_argument("--scan-out", default="data/network_scan.json")
    parser.add_argument("--inventory-out", default="data/network_inventory.json")
    parser.add_argument("--control-out", default="data/didier_control_targets.json")
    args = parser.parse_args()

    scan_path = Path(args.scan_out)
    inventory_path = Path(args.inventory_out)
    control_path = Path(args.control_out)

    scan_data = None
    if args.mode in {"scan", "all"}:
        net = detect_network()
        cidr = args.cidr or net["cidr"]
        network = ipaddress.ip_network(cidr, strict=False)

        hosts = [str(ip) for ip in network.hosts()]
        if len(hosts) > args.max_hosts:
            raise RuntimeError(
                f"Reseau trop grand ({len(hosts)} hotes). "
                f"Augmentez --max-hosts ou reduisez --cidr."
            )

        start = time.time()
        ping_results = ping_sweep(hosts, args.ping_timeout, args.workers)
        neighbors = read_neighbors()
        ports = parse_ports(args.ports)
        port_results = scan_ports(hosts, ports, args.port_timeout, args.workers)

        alive_hosts = []
        for ip in hosts:
            neighbor = neighbors.get(ip, {})
            ping = ping_results.get(ip, {})
            open_ports = port_results.get(ip, [])
            alive = bool(ping.get("alive")) or bool(open_ports) or (neighbor.get("state") not in {None, "FAILED"})
            if alive:
                alive_hosts.append(ip)

        hostnames = resolve_hostnames(alive_hosts, 1.0, min(args.workers, 32))

        host_entries = []
        for ip in hosts:
            neighbor = neighbors.get(ip, {})
            ping = ping_results.get(ip, {})
            open_ports = port_results.get(ip, [])
            services = classify_services(open_ports)
            alive = bool(ping.get("alive")) or bool(open_ports) or (neighbor.get("state") not in {None, "FAILED"})
            host_entries.append(
                {
                    "ip": ip,
                    "alive": alive,
                    "ping_ms": ping.get("ping_ms"),
                    "mac": neighbor.get("mac"),
                    "neighbor_state": neighbor.get("state"),
                    "interface": neighbor.get("dev"),
                    "hostname": hostnames.get(ip),
                    "open_ports": open_ports,
                    "services": services,
                }
            )

        scan_data = {
            "meta": {
                "scan_id": f"scan-{int(time.time())}",
                "generated_at": now_iso(),
                "cidr": str(network),
                "interface": net.get("interface"),
                "gateway": net.get("gateway"),
                "source_ip": net.get("source_ip"),
                "ports_scanned": ports,
                "host_count": len(hosts),
                "duration_seconds": round(time.time() - start, 2),
            },
            "hosts": host_entries,
        }
        save_json(scan_path, scan_data)

    if args.mode in {"label", "control", "all"}:
        if not scan_data:
            scan_data = load_json(scan_path)
        if not scan_data:
            raise RuntimeError("Aucun scan disponible. Lancez d'abord --mode scan.")

    if args.mode in {"label", "all"}:
        existing = load_json(inventory_path)
        only_alive = args.only_alive or not args.all_hosts
        tuya_devices = load_tuya_devices(Path(args.tuya_devices))
        inventory = build_inventory(
            scan_data,
            only_alive,
            existing,
            args.lamp_hold,
            args.yeelight_port,
            args.yeelight_timeout,
            not args.no_yeelight_test,
            tuya_devices,
            not args.no_tuya_test,
            args.tuya_timeout,
            inventory_path,
            args.skip_known,
        )
        save_json(inventory_path, inventory)
    else:
        inventory = load_json(inventory_path) if inventory_path.exists() else None

    if args.mode in {"control", "all"}:
        if not inventory:
            raise RuntimeError("Aucun inventaire disponible. Lancez d'abord --mode label.")
        targets = build_control_targets(inventory)
        save_json(inventory_path, inventory)
        save_json(control_path, targets)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
