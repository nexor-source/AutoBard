"""Recover hashed DLL/API names used by the decoded payload.

Only PE export metadata from the local Windows installation is parsed.  The
target executable and its decoded payload are never executed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pefile


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output" / "auto" / "recovered_hashes.json"
SYSTEM32 = Path(r"C:\Windows\System32")

MODULE_HASHES = {0x875D81E7, 0x9FFA651F, 0x386DC37D, 0x1582182F, 0xE4001C5A}
API_HASHES = {
    0xAB36B1F1, 0x70D84BDC, 0x8FACB393, 0x833D1475, 0xED1517A6,
    0xB40E1064, 0x9D846488, 0x39299190, 0xDC0C72C1, 0x04AE5004,
    0x399596DA, 0x7EBAF452, 0x5CE6F7FF, 0x40792BC4, 0x4EE9F32F,
    0x243AEEF1, 0xAA2CDDF3, 0x55A87EAE, 0x8DE975B1, 0x97E48871,
    0x7ACB8A78, 0xEBCEFE63, 0x97554F0E, 0x464D7E2B, 0xE4D4B38C,
    0x1D295D5D, 0x88AEFF03, 0x6909CF30, 0x831E04B8, 0x8378EE44,
    0x31C4C8C9, 0xDC8B7DCD, 0x42A1C55B, 0x9A6F9D11, 0xD4D757FC,
    0x74E10826, 0x90EC614B, 0x11170B6E, 0x8F3EC221, 0x9758F50E,
    0xF6131600, 0x5C2059DF, 0x91C424BC,
}


def name_hash(name: str) -> int:
    value = 0xB1F48651
    for char in name:
        codepoint = ord(char)
        if 0x61 <= codepoint <= 0x7A:
            codepoint -= 0x20
        value = ((value ^ codepoint) * 0x010001AB) & 0xFFFFFFFF
    return value


def find_modules() -> dict[int, list[str]]:
    found: dict[int, list[str]] = {target: [] for target in MODULE_HASHES}
    for path in SYSTEM32.glob("*.dll"):
        hashed = name_hash(path.name)
        if hashed in found:
            found[hashed].append(path.name)
    return found


def read_exports(path: Path) -> list[str]:
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]]
        )
        directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
        if directory is None:
            return []
        return [
            symbol.name.decode("ascii", errors="ignore")
            for symbol in directory.symbols
            if symbol.name
        ]
    except (OSError, pefile.PEFormatError, ValueError):
        return []


def recover_apis(module_names: set[str]) -> dict[int, list[dict[str, str]]]:
    found: dict[int, list[dict[str, str]]] = {target: [] for target in API_HASHES}
    for module_name in sorted(module_names):
        path = SYSTEM32 / module_name
        for export_name in read_exports(path):
            hashed = name_hash(export_name)
            if hashed in found:
                found[hashed].append({"module": module_name, "name": export_name})
    return found


def main() -> None:
    modules = find_modules()
    resolved_module_names = {
        module_name
        for names in modules.values()
        for module_name in names
    }

    # The first API group is resolved from kernel32, and some systems forward
    # many of those exports through KernelBase.  Include both for attribution.
    candidate_modules = resolved_module_names | {
        "kernel32.dll",
        "KernelBase.dll",
        "ntdll.dll",
    }
    apis = recover_apis(candidate_modules)

    report = {
        "algorithm": {
            "initial": "0xB1F48651",
            "case_folding": "ASCII lowercase converted to uppercase",
            "step": "hash = ((hash XOR character) * 0x010001AB) modulo 2^32",
        },
        "module_hashes": {
            f"0x{target:08X}": names for target, names in sorted(modules.items())
        },
        "api_hashes": {
            f"0x{target:08X}": matches for target, matches in sorted(apis.items())
        },
        "unresolved_module_hashes": [
            f"0x{target:08X}" for target, names in sorted(modules.items()) if not names
        ],
        "unresolved_api_hashes": [
            f"0x{target:08X}" for target, matches in sorted(apis.items()) if not matches
        ],
        "scanned_export_modules": sorted(candidate_modules),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
