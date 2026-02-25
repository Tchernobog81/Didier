#!/usr/bin/env python3
"""Compatibility wrapper for RAM check script."""

from hailo_ram_check import main


if __name__ == "__main__":
    raise SystemExit(main())
