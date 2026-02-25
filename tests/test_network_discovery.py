from core.network_discovery import NetworkDiscovery
from core.network_discovery import parse_avahi_browse_output
from core.network_discovery import parse_ip_neigh_output


def test_parse_ip_neigh_output_filters_ipv4_and_extracts_fields():
    payload = """
192.168.1.1 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
192.168.1.50 dev wlan0 INCOMPLETE
fe80::1 dev wlan0 lladdr 11:22:33:44:55:66 STALE
""".strip()
    rows = parse_ip_neigh_output(payload)
    assert len(rows) == 2
    assert rows[0]["ip"] == "192.168.1.1"
    assert rows[0]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert rows[0]["alive"] is True
    assert rows[1]["ip"] == "192.168.1.50"
    assert rows[1]["alive"] is False


def test_parse_avahi_browse_output_extracts_service_rows():
    payload = """
=;wlan0;IPv4;Pixel 10;_adb._tcp;local;pixel-10.local;192.168.1.50;5555;
""".strip()
    rows = parse_avahi_browse_output(payload)
    assert len(rows) == 1
    row = rows[0]
    assert row["address"] == "192.168.1.50"
    assert row["service"] == "_adb._tcp"
    assert row["name"] == "Pixel 10"


def test_network_discovery_detects_pixel_candidate_and_change_state():
    def fake_runner(cmd: list[str], timeout_s: float):
        if cmd[:3] == ["ip", "neigh", "show"]:
            return (
                0,
                "192.168.1.50 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n",
                "",
            )
        if cmd[:2] == ["avahi-browse", "-art"]:
            return (
                0,
                "=;wlan0;IPv4;Pixel 10;_adb._tcp;local;pixel-10.local;192.168.1.50;5555;\n",
                "",
            )
        return 127, "", "unsupported"

    scanner = NetworkDiscovery(
        config={
            "enable_arp": True,
            "enable_mdns": True,
            "pixel_name_patterns": ["pixel", "pixel-10"],
            "pixel_ip_hints": ["192.168.1.50"],
        },
        command_runner=fake_runner,
        hailo_probe=lambda: False,
    )

    first = scanner.scan(force=True)
    second = scanner.scan(force=True)

    assert first["changed"] is True
    assert second["changed"] is False

    profile = first["profile"]
    assert profile["tpu"]["pixel_detected"] is True
    assert profile["tpu"]["pixel_count"] == 1
    assert len(profile["network_devices"]) == 1
    assert profile["network_devices"][0]["kind"] == "pixel_tpu_candidate"
