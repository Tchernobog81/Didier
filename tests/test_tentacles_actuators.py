import json
import tempfile
import unittest
from pathlib import Path

from tentacles.actuators import ActuatorsTentacle


class ActuatorsTentacleTests(unittest.TestCase):
    def test_yeelight_identity_for_ip_uses_arp_mac(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        with tempfile.TemporaryDirectory() as tmpdir:
            arp_path = Path(tmpdir) / "arp.txt"
            arp_path.write_text(
                "IP address       HW type     Flags       HW address            Mask     Device\n"
                "192.168.1.23     0x1         0x2         64:90:c1:b3:b5:dc     *        eth0\n",
                encoding="utf-8",
            )
            tentacle._arp_path = arp_path

            identity = tentacle._yeelight_identity_for_ip("192.168.1.23")

        self.assertEqual(identity, "mac:64:90:c1:b3:b5:dc")

    def test_normalize_devices_treats_none_like_yeelight_id_as_missing(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)

        devices = tentacle._normalize_devices(
            {
                "lamp": {
                    "type": "yeelight",
                    "ip": "192.168.1.10",
                    "yeelight_id": "None",
                }
            }
        )

        self.assertIsNone(devices["lamp"]["yeelight_id"])

    def test_persist_devices_preserves_reference_metrics(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        tentacle._devices = {
            "lamp": {
                "id": "lamp",
                "type": "yeelight",
                "ip": "192.168.1.10",
                "name": "Cuisine",
                "yeelight_id": "0x10",
                "validated": True,
                "capabilities": ["on", "off"],
                "tags": ["light"],
                "last_command": None,
                "last_validation": None,
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "actuators.json"
            registry.write_text(
                json.dumps(
                    {
                        "devices": {},
                        "reference_metrics": {
                            "baseline": {"hex": "#00FF03"}
                        },
                    }
                ),
                encoding="utf-8",
            )
            tentacle._registry_path = registry

            tentacle._persist_devices()

            payload = json.loads(registry.read_text(encoding="utf-8"))

        self.assertEqual(payload["reference_metrics"]["baseline"]["hex"], "#00FF03")
        self.assertEqual(payload["devices"]["lamp"]["yeelight_id"], "0x10")

    def test_get_status_returns_live_yeelight_probe(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        tentacle._devices = {
            "lamp": {
                "id": "lamp",
                "type": "yeelight",
                "ip": "192.168.1.10",
                "name": "Cuisine",
                "validated": True,
                "last_command": {"action": "on", "ts": 1.0, "params": {}},
                "last_validation": {"ts": 1.0, "result": "ok"},
            }
        }
        tentacle._yeelight_get_status = lambda ip: {
            "reachable": True,
            "state": {
                "power": "off",
                "bright": "55",
                "rgb": "255",
                "power_on": False,
            },
            "error": None,
        }

        status = tentacle.get_status("lamp")

        self.assertTrue(status["reachable"])
        self.assertFalse(status["state"]["power_on"])
        self.assertEqual(status["state"]["bright"], "55")
        self.assertEqual(status["last_command"]["action"], "on")

    def test_command_returns_follow_up_status_snapshot(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        tentacle._devices = {
            "lamp": {
                "id": "lamp",
                "type": "yeelight",
                "ip": "192.168.1.10",
                "name": "Cuisine",
                "validated": True,
                "last_command": None,
                "last_validation": None,
            }
        }
        tentacle._persist_devices = lambda: None
        tentacle._yeelight_command = lambda device, action, params: (True, None)
        tentacle._yeelight_get_status = lambda ip: {
            "reachable": True,
            "state": {
                "power": "on",
                "bright": "100",
                "rgb": "16777215",
                "power_on": True,
            },
            "error": None,
        }

        result = tentacle.command("lamp", "on", {})

        self.assertTrue(result["ok"])
        self.assertTrue(result["reachable"])
        self.assertTrue(result["state"]["power_on"])
        self.assertEqual(result["action"], "on")
        self.assertEqual(
            tentacle._devices["lamp"]["last_command"]["action"],
            "on",
        )

    def test_reconcile_updates_stale_ips_from_discovery(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        tentacle._devices = {
            "lamp_a": {
                "id": "lamp_a",
                "type": "yeelight",
                "ip": "192.168.1.12",
                "yeelight_id": None,
            },
            "lamp_b": {
                "id": "lamp_b",
                "type": "yeelight",
                "ip": "192.168.1.18",
                "yeelight_id": None,
            },
        }
        persisted = []
        tentacle._persist_devices = lambda: persisted.append(True)

        matched = tentacle._reconcile_yeelight_devices(
            [
                {"id": "0x18", "ip": "192.168.1.18", "state": {"power_on": True}},
                {"id": "0x13", "ip": "192.168.1.13", "state": {"power_on": True}},
            ]
        )

        self.assertEqual(tentacle._devices["lamp_a"]["ip"], "192.168.1.13")
        self.assertEqual(tentacle._devices["lamp_a"]["yeelight_id"], "0x13")
        self.assertEqual(tentacle._devices["lamp_b"]["ip"], "192.168.1.18")
        self.assertEqual(tentacle._devices["lamp_b"]["yeelight_id"], "0x18")
        self.assertEqual(matched["lamp_a"]["ip"], "192.168.1.13")
        self.assertEqual(len(persisted), 1)

    def test_get_device_status_falls_back_to_discovery_snapshot(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        device = {
            "id": "lamp",
            "type": "yeelight",
            "ip": "192.168.1.12",
            "yeelight_id": None,
        }

        tentacle._yeelight_get_status = lambda ip: {
            "reachable": False,
            "state": {},
            "error": "[Errno 111] Connection refused",
        }

        def reconcile():
            device["ip"] = "192.168.1.13"
            return {
                "lamp": {
                    "id": "0x13",
                    "ip": "192.168.1.13",
                    "state": {
                        "power": "on",
                        "bright": "100",
                        "power_on": True,
                    },
                }
            }

        tentacle._reconcile_yeelight_devices = reconcile

        status = tentacle._yeelight_get_device_status(device)

        self.assertTrue(status["reachable"])
        self.assertEqual(status["error"], "live state via discovery")
        self.assertTrue(status["state"]["power_on"])
        self.assertEqual(device["ip"], "192.168.1.13")

    def test_reconcile_avoids_binding_multiple_devices_to_same_ip(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        tentacle._devices = {
            "yl_192_168_1_19": {
                "id": "yl_192_168_1_19",
                "type": "yeelight",
                "ip": "192.168.1.23",
                "yeelight_id": None,
            },
            "yl_192_168_1_23": {
                "id": "yl_192_168_1_23",
                "type": "yeelight",
                "ip": "192.168.1.23",
                "yeelight_id": None,
            },
        }
        tentacle._persist_devices = lambda: None

        matched = tentacle._reconcile_yeelight_devices(
            [
                {"id": "0x23", "ip": "192.168.1.23", "state": {"power_on": True}},
                {"id": "0x20", "ip": "192.168.1.20", "state": {"power_on": True}},
            ]
        )

        self.assertEqual(tentacle._devices["yl_192_168_1_23"]["ip"], "192.168.1.23")
        self.assertEqual(tentacle._devices["yl_192_168_1_19"]["ip"], "192.168.1.20")
        self.assertEqual(len(matched), 2)

    def test_reconcile_skips_partial_inventory_rebind(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        tentacle._devices = {
            "yl_192_168_1_12": {
                "id": "yl_192_168_1_12",
                "type": "yeelight",
                "ip": "192.168.1.12",
                "yeelight_id": None,
            },
            "yl_192_168_1_18": {
                "id": "yl_192_168_1_18",
                "type": "yeelight",
                "ip": "192.168.1.18",
                "yeelight_id": None,
            },
        }
        tentacle._persist_devices = lambda: None

        matched = tentacle._reconcile_yeelight_devices(
            [
                {"id": "0x13", "ip": "192.168.1.13", "state": {"power_on": True}},
            ]
        )

        self.assertEqual(tentacle._devices["yl_192_168_1_12"]["ip"], "192.168.1.12")
        self.assertEqual(tentacle._devices["yl_192_168_1_18"]["ip"], "192.168.1.18")
        self.assertEqual(matched, {})

    def test_command_retries_after_reconcile_on_transport_error(self) -> None:
        tentacle = object.__new__(ActuatorsTentacle)
        device = {
            "id": "lamp",
            "type": "yeelight",
            "ip": "192.168.1.12",
            "name": "Cuisine",
            "validated": True,
            "yeelight_id": None,
            "last_command": None,
            "last_validation": None,
        }
        tentacle._devices = {"lamp": device}
        tentacle._persist_devices = lambda: None
        attempts = []

        def command_with_retry(current_device, action, params):
            attempts.append(current_device["ip"])
            if len(attempts) == 1:
                return False, "[Errno 111] Connection refused"
            return True, None

        def reconcile():
            device["ip"] = "192.168.1.13"
            return {"lamp": {"id": "0x13", "ip": "192.168.1.13"}}

        tentacle._yeelight_command = command_with_retry
        tentacle._reconcile_yeelight_devices = reconcile
        tentacle._yeelight_get_device_status = lambda current_device: {
            "reachable": True,
            "state": {"power": "on", "power_on": True},
            "error": None,
        }

        result = tentacle.command("lamp", "on", {})

        self.assertTrue(result["ok"])
        self.assertEqual(attempts, ["192.168.1.12", "192.168.1.13"])
        self.assertEqual(device["ip"], "192.168.1.13")
        self.assertTrue(result["state"]["power_on"])


if __name__ == "__main__":
    unittest.main()
