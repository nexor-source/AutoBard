"""Statically decrypt the embedded DMV2 configuration.

This script never executes bytes from the sample.  It only reimplements the
small byte generator observed at decoded-payload offsets 0xB6B/0xB9B.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "output" / "auto" / "payload_final.bin"
OUTPUT_DIR = ROOT / "output" / "auto"
CONFIG_OFFSET = 0x42EE
CONFIG_SIZE = 0x1D0
CONFIG_KEY = 0xC0DEFACE


def u32(value: int) -> int:
    return value & 0xFFFFFFFF


def config_keystream_byte(key: int, index: int) -> int:
    """Equivalent to the decoded routine at payload offset 0xB6B."""
    x = u32(key - u32(index * 0x61C88647))
    x ^= x >> 16
    x = u32(x * 0x7FEB352D)
    x ^= x >> 15
    x = u32(x * 0x846CA68B)
    return ((x >> 16) ^ x) & 0xFF


def decrypt_config(data: bytes) -> bytes:
    return bytes(
        value ^ config_keystream_byte(CONFIG_KEY, index)
        for index, value in enumerate(data)
    )


def printable_runs(data: bytes, minimum: int = 4) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []
    start: int | None = None
    for index, value in enumerate(data + b"\x00"):
        if 0x20 <= value <= 0x7E:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= minimum:
                runs.append(
                    {
                        "offset": f"0x{start:X}",
                        "encoding": "ascii",
                        "value": data[start:index].decode("ascii"),
                    }
                )
            start = None

    # Look separately for ordinary null-terminated UTF-16LE runs.
    for alignment in (0, 1):
        start = None
        chars: list[int] = []
        for index in range(alignment, len(data) - 1, 2):
            value = int.from_bytes(data[index : index + 2], "little")
            if 0x20 <= value <= 0x7E:
                if start is None:
                    start = index
                    chars = []
                chars.append(value)
            else:
                if start is not None and len(chars) >= minimum:
                    runs.append(
                        {
                            "offset": f"0x{start:X}",
                            "encoding": "utf-16le",
                            "value": "".join(chr(char) for char in chars),
                        }
                    )
                start = None
                chars = []
    return sorted(runs, key=lambda item: (int(str(item["offset"]), 16), str(item["encoding"])))


def hexdump(data: bytes, width: int = 16) -> str:
    lines = []
    for offset in range(0, len(data), width):
        chunk = data[offset : offset + width]
        hex_part = " ".join(f"{value:02X}" for value in chunk)
        text_part = "".join(chr(value) if 0x20 <= value <= 0x7E else "." for value in chunk)
        lines.append(f"{offset:04X}  {hex_part:<{width * 3 - 1}}  |{text_part}|")
    return "\n".join(lines) + "\n"


def main() -> None:
    payload = INPUT.read_bytes()
    encrypted = payload[CONFIG_OFFSET : CONFIG_OFFSET + CONFIG_SIZE]
    if len(encrypted) != CONFIG_SIZE:
        raise ValueError("decoded payload does not contain the expected config range")

    decrypted = decrypt_config(encrypted)
    magic = decrypted[:4]
    declared_size = int.from_bytes(decrypted[4:8], "little")
    version = int.from_bytes(decrypted[8:12], "little")
    valid = magic == b"DMV2" and declared_size == CONFIG_SIZE and version == 2

    report = {
        "input": str(INPUT),
        "payload_sha256": hashlib.sha256(payload).hexdigest().upper(),
        "config_offset": f"0x{CONFIG_OFFSET:X}",
        "config_size": f"0x{CONFIG_SIZE:X}",
        "config_key": f"0x{CONFIG_KEY:08X}",
        "encrypted_sha256": hashlib.sha256(encrypted).hexdigest().upper(),
        "decrypted_sha256": hashlib.sha256(decrypted).hexdigest().upper(),
        "magic_ascii": magic.decode("ascii", errors="replace"),
        "declared_size": declared_size,
        "version": version,
        "header_valid": valid,
        "decoded_fields": {
            "server": decrypted[0x0C:0x10B].split(b"\x00", 1)[0].decode(
                "ascii", errors="replace"
            ),
            "port": int.from_bytes(decrypted[0x154:0x156], "little"),
            "cache_directory_name_and_xor_key": decrypted[0x10B:0x147]
            .split(b"\x00", 1)[0]
            .decode("ascii", errors="replace"),
            "inner_marker": decrypted[0x147:0x14E].decode("ascii", errors="replace"),
            "field_0x15c_16_bytes_hex": decrypted[0x15C:0x16C].hex().upper(),
            "field_0x16c_32_bytes_hex": decrypted[0x16C:0x18C].hex().upper(),
            "inferred_cache_path": "%ProgramData%\\"
            + decrypted[0x10B:0x147].split(b"\x00", 1)[0].decode(
                "ascii", errors="replace"
            )
            + r"\1",
        },
        "nonzero_32_byte_field_at_0x16c": any(decrypted[0x16C : 0x16C + 32]),
        "printable_runs": printable_runs(decrypted),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "config_dmv2.bin").write_bytes(decrypted)
    (OUTPUT_DIR / "config_dmv2_hexdump.txt").write_text(hexdump(decrypted), encoding="utf-8")
    (OUTPUT_DIR / "config_dmv2.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not valid:
        raise SystemExit("DMV2 header validation failed")


if __name__ == "__main__":
    main()
