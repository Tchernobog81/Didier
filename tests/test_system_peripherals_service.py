import unittest

from core.system_peripherals_service import PeripheralServiceError
from core.system_peripherals_service import SystemPeripheralsDeps
from core.system_peripherals_service import collect_peripherals
from core.system_peripherals_service import toggle_peripheral


class SystemPeripheralsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_peripherals_includes_wifi_link_state(self) -> None:
        async def _service_state(service: str) -> tuple[bool, str]:
            return (service == "wifi.service"), "active"

        async def _run_systemctl(_cmd: str, _service: str) -> tuple[int, str]:
            raise AssertionError("unused")

        deps = SystemPeripheralsDeps(
            now=lambda: 42.0,
            service_state=_service_state,
            run_systemctl=_run_systemctl,
            wifi_link_state=lambda: "up",
        )

        result = await collect_peripherals(
            {
                "wifi": {
                    "label": "WiFi",
                    "kind": "connectivite",
                    "channel": "wifi",
                    "service": "wifi.service",
                }
            },
            deps=deps,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["ts"], 42.0)
        self.assertEqual(result["items"][0]["link_state"], "up")

    async def test_toggle_peripheral_defaults_to_inverse_current_state(self) -> None:
        calls: list[tuple[str, str]] = []
        state = {"active": True, "value": "active"}

        async def _service_state(_service: str) -> tuple[bool, str]:
            return state["active"], state["value"]

        async def _run_systemctl(cmd: str, service: str) -> tuple[int, str]:
            calls.append((cmd, service))
            state["active"] = False
            state["value"] = "inactive"
            return 0, "ok"

        deps = SystemPeripheralsDeps(
            now=lambda: 100.0,
            service_state=_service_state,
            run_systemctl=_run_systemctl,
            wifi_link_state=lambda: "up",
        )

        result = await toggle_peripheral(
            {"id": "sound"},
            {
                "sound": {
                    "label": "Son",
                    "kind": "actionneur",
                    "channel": "audio",
                    "service": "sound.service",
                }
            },
            deps=deps,
        )

        self.assertEqual(calls, [("stop", "sound.service")])
        self.assertEqual(result["requested"], "stop")
        self.assertFalse(result["after"]["active"])
        self.assertEqual(result["item"]["service"], "sound.service")

    async def test_toggle_peripheral_rejects_unknown_id(self) -> None:
        async def _service_state(_service: str) -> tuple[bool, str]:
            raise AssertionError("unused")

        async def _run_systemctl(_cmd: str, _service: str) -> tuple[int, str]:
            raise AssertionError("unused")

        deps = SystemPeripheralsDeps(
            now=lambda: 0.0,
            service_state=_service_state,
            run_systemctl=_run_systemctl,
        )

        with self.assertRaises(PeripheralServiceError) as ctx:
            await toggle_peripheral({}, {}, deps=deps)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "unknown peripheral id")

    async def test_toggle_peripheral_raises_when_systemctl_fails(self) -> None:
        async def _service_state(_service: str) -> tuple[bool, str]:
            return False, "inactive"

        async def _run_systemctl(cmd: str, service: str) -> tuple[int, str]:
            return 1, f"{cmd} failed for {service}"

        deps = SystemPeripheralsDeps(
            now=lambda: 0.0,
            service_state=_service_state,
            run_systemctl=_run_systemctl,
        )

        with self.assertRaises(PeripheralServiceError) as ctx:
            await toggle_peripheral(
                {"id": "video", "enabled": True},
                {
                    "video": {
                        "label": "Video",
                        "kind": "sense",
                        "channel": "video",
                        "service": "video.service",
                    }
                },
                deps=deps,
            )

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("systemctl start failed for video.service", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
