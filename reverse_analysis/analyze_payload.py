from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
from collections import Counter
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_64, Cs


TRAILER = struct.Struct("<16sIIQQ")


def entropy(data: bytes) -> float:
    counts = Counter(data)
    return -sum(
        (count / len(data)) * math.log2(count / len(data)) for count in counts.values()
    )


def printable_strings(data: bytes) -> list[dict[str, object]]:
    strings: list[dict[str, object]] = []
    for match in re.finditer(rb"[\x20-\x7e]{5,}", data):
        strings.append(
            {
                "offset": f"0x{match.start():X}",
                "encoding": "ascii",
                "value": match.group().decode("ascii", errors="replace"),
            }
        )
    for match in re.finditer(rb"(?:[\x20-\x7e]\x00){5,}", data):
        strings.append(
            {
                "offset": f"0x{match.start():X}",
                "encoding": "utf-16le",
                "value": match.group().decode("utf-16le", errors="replace"),
            }
        )
    return sorted(strings, key=lambda value: int(str(value["offset"]), 16))


def disassemble(data: bytes, start: int, size: int) -> list[str]:
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.skipdata = True
    return [
        f"{instruction.address:08X}  {instruction.mnemonic:<9} {instruction.op_str}"
        for instruction in md.disasm(data[start : start + size], start)
    ]


def rotate_left_32(value: int, count: int) -> int:
    count &= 31
    return ((value << count) | (value >> (32 - count))) & 0xFFFFFFFF


def rotate_right_32(value: int, count: int) -> int:
    count &= 31
    return ((value >> count) | (value << (32 - count))) & 0xFFFFFFFF


def decode_obfuscated_stage_one(payload: bytes) -> tuple[bytes, int] | None:
    """Apply the mutations made by the small tail decoder in this sample.

    The initial CALL places payload+5 on the stack.  The decoder pops that
    address, transforms five dwords relative to it, and jumps there.
    """
    if len(payload) < 25 or payload[0] != 0xE8:
        return None
    base = 5
    decoded = bytearray(payload)

    def get32(offset: int) -> int:
        return struct.unpack_from("<I", decoded, base + offset)[0]

    def put32(offset: int, value: int) -> None:
        struct.pack_into("<I", decoded, base + offset, value & 0xFFFFFFFF)

    put32(0, rotate_left_32(get32(0), 0x8F))
    put32(4, get32(4) + 0x9EFC6A2E)
    put32(8, rotate_right_32(get32(8), 5))
    put32(12, rotate_right_32(get32(12), 0xE0))
    put32(16, get32(16) + 0x486DC6AF)
    return bytes(decoded), base


def decode_obfuscated_stage_two(stage_one: bytes) -> tuple[bytes, int] | None:
    """Reproduce the backward byte loop at the decoded stage-one entry."""
    data_base = 0x28
    count = 0x470E
    if len(stage_one) <= data_base + count:
        return None
    decoded = bytearray(stage_one)
    key = 0x7E
    for counter in range(count, 0, -1):
        offset = data_base + counter
        decoded[offset] ^= key
        key = (key + decoded[offset]) & 0xFF
    return bytes(decoded), data_base + 1


def decode_obfuscated_stage_three(stage_two: bytes) -> tuple[bytes, int] | None:
    """Apply the second tail decoder reached by CALL from offset 0x32."""
    base = 0x37
    if len(stage_two) < base + 20:
        return None
    decoded = bytearray(stage_two)

    def get32(offset: int) -> int:
        return struct.unpack_from("<I", decoded, base + offset)[0]

    def put32(offset: int, value: int) -> None:
        struct.pack_into("<I", decoded, base + offset, value & 0xFFFFFFFF)

    put32(4, rotate_left_32(get32(4), 0xC0))
    put32(8, rotate_right_32(get32(8), 0xA5))
    put32(12, get32(12) + 0xDF9B61F7)
    put32(16, get32(16) - 0xB777DBE5)
    return bytes(decoded), base


def decode_obfuscated_stage_four(stage_three: bytes) -> tuple[bytes, int] | None:
    """Reproduce the second backward rolling-XOR loop."""
    data_base = 0x55
    count = 0x46A0
    if len(stage_three) <= data_base + count:
        return None
    decoded = bytearray(stage_three)
    key = 0x82
    for counter in range(count, 0, -1):
        offset = data_base + counter
        decoded[offset] ^= key
        key = (key + decoded[offset]) & 0xFF
    return bytes(decoded), data_base + 1


def decode_obfuscated_stage_five(stage_four: bytes) -> tuple[bytes, int] | None:
    """Apply the third tail decoder reached by CALL from offset 0x5A."""
    base = 0x5F
    if len(stage_four) < base + 25:
        return None
    decoded = bytearray(stage_four)

    def get32(offset: int) -> int:
        return struct.unpack_from("<I", decoded, base + offset)[0]

    def put32(offset: int, value: int) -> None:
        struct.pack_into("<I", decoded, base + offset, value & 0xFFFFFFFF)

    put32(9, rotate_right_32(get32(9), 0x90))
    put32(13, ~get32(13))
    put32(17, ~get32(17))
    put32(21, ~get32(21))
    return bytes(decoded), base


def decode_obfuscated_stage_six(stage_five: bytes) -> tuple[bytes, int] | None:
    """Reproduce the third backward rolling-XOR loop."""
    data_base = 0x82
    count = 0x463A
    if len(stage_five) <= data_base + count:
        return None
    decoded = bytearray(stage_five)
    key = 0x04
    for counter in range(count, 0, -1):
        offset = data_base + counter
        decoded[offset] ^= key
        key = (key + decoded[offset]) & 0xFF
    return bytes(decoded), data_base + 1


def decode_obfuscated_stage_seven(stage_six: bytes) -> tuple[bytes, int] | None:
    """Apply the fourth tail decoder reached by CALL from offset 0x87."""
    base = 0x8C
    if len(stage_six) < base + 33:
        return None
    decoded = bytearray(stage_six)

    def get32(offset: int) -> int:
        return struct.unpack_from("<I", decoded, base + offset)[0]

    def put32(offset: int, value: int) -> None:
        struct.pack_into("<I", decoded, base + offset, value & 0xFFFFFFFF)

    put32(0x0D, get32(0x0D) + 0xE2347A46)
    put32(0x11, rotate_right_32(get32(0x11), 0xE8))
    put32(0x15, get32(0x15) + 0x32F35EA7)
    put32(0x19, get32(0x19) - 0x810E7D8D)
    put32(0x1D, get32(0x1D) ^ 0x611E755B)
    return bytes(decoded), base


def decode_obfuscated_stage_eight(stage_seven: bytes) -> tuple[bytes, int] | None:
    """Reproduce the fourth backward rolling-XOR loop."""
    data_base = 0xBD
    count = 0x45A5
    if len(stage_seven) <= data_base + count:
        return None
    decoded = bytearray(stage_seven)
    key = 0xEC
    for counter in range(count, 0, -1):
        offset = data_base + counter
        decoded[offset] ^= key
        key = (key + decoded[offset]) & 0xFF
    return bytes(decoded), data_base + 1


def decode_obfuscated_stage_nine(stage_eight: bytes) -> tuple[bytes, int] | None:
    """Apply the fifth tail decoder reached by CALL from offset 0xC7."""
    base = 0xCC
    if len(stage_eight) < base + 25:
        return None
    decoded = bytearray(stage_eight)

    def get32(offset: int) -> int:
        return struct.unpack_from("<I", decoded, base + offset)[0]

    def put32(offset: int, value: int) -> None:
        struct.pack_into("<I", decoded, base + offset, value & 0xFFFFFFFF)

    put32(9, rotate_right_32(get32(9), 0x5E))
    put32(13, ~get32(13))
    put32(17, get32(17) ^ 0x7469DC22)
    put32(21, get32(21) ^ 0x9F18C4D5)
    return bytes(decoded), base


def decode_obfuscated_stage_ten(stage_nine: bytes) -> tuple[bytes, int] | None:
    """Reproduce the fifth backward rolling-XOR loop."""
    data_base = 0xF3
    count = 0x452B

    if len(stage_nine) <= data_base + count:
        return None
    decoded = bytearray(stage_nine)
    key = 0x51
    for counter in range(count, 0, -1):
        offset = data_base + counter
        decoded[offset] ^= key
        key = (key + decoded[offset]) & 0xFF
    return bytes(decoded), data_base + 1


def analyze(sample: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = sample.read_bytes()
    if len(image) < TRAILER.size:
        raise RuntimeError("File is too small to contain a BLT trailer")
    magic, version, architecture, offset, size = TRAILER.unpack(image[-TRAILER.size :])
    if not magic.startswith(b"BLT_PAYLOAD_001"):
        raise RuntimeError(f"Unexpected trailer magic: {magic!r}")
    if offset + size + TRAILER.size != len(image):
        raise RuntimeError("Payload bounds do not match the file size")

    payload = image[offset : offset + size]
    payload_path = output_dir / "payload.bin"
    payload_path.write_bytes(payload)

    initial_call_target: int | None = None
    if len(payload) >= 5 and payload[0] == 0xE8:
        displacement = struct.unpack_from("<i", payload, 1)[0]
        initial_call_target = 5 + displacement

    strings = printable_strings(payload)
    stage_one = decode_obfuscated_stage_one(payload)
    stage_one_path: Path | None = None
    stage_two: tuple[bytes, int] | None = None
    stage_two_path: Path | None = None
    stage_three: tuple[bytes, int] | None = None
    stage_three_path: Path | None = None
    stage_four: tuple[bytes, int] | None = None
    stage_four_path: Path | None = None
    stage_five: tuple[bytes, int] | None = None
    stage_five_path: Path | None = None
    stage_six: tuple[bytes, int] | None = None
    stage_six_path: Path | None = None
    stage_seven: tuple[bytes, int] | None = None
    stage_seven_path: Path | None = None
    stage_eight: tuple[bytes, int] | None = None
    stage_eight_path: Path | None = None
    stage_nine: tuple[bytes, int] | None = None
    stage_nine_path: Path | None = None
    stage_ten: tuple[bytes, int] | None = None
    stage_ten_path: Path | None = None
    if stage_one is not None:
        stage_one_bytes, stage_one_entry = stage_one
        stage_one_path = output_dir / "payload_stage1.bin"
        stage_one_path.write_bytes(stage_one_bytes)
        stage_two = decode_obfuscated_stage_two(stage_one_bytes)
        if stage_two is not None:
            stage_two_bytes, _ = stage_two
            stage_two_path = output_dir / "payload_stage2.bin"
            stage_two_path.write_bytes(stage_two_bytes)
            stage_three = decode_obfuscated_stage_three(stage_two_bytes)
            if stage_three is not None:
                stage_three_bytes, _ = stage_three
                stage_three_path = output_dir / "payload_stage3.bin"
                stage_three_path.write_bytes(stage_three_bytes)
                stage_four = decode_obfuscated_stage_four(stage_three_bytes)
                if stage_four is not None:
                    stage_four_bytes, _ = stage_four
                    stage_four_path = output_dir / "payload_stage4.bin"
                    stage_four_path.write_bytes(stage_four_bytes)
                    stage_five = decode_obfuscated_stage_five(stage_four_bytes)
                    if stage_five is not None:
                        stage_five_bytes, _ = stage_five
                        stage_five_path = output_dir / "payload_stage5.bin"
                        stage_five_path.write_bytes(stage_five_bytes)
                        stage_six = decode_obfuscated_stage_six(stage_five_bytes)
                        if stage_six is not None:
                            stage_six_bytes, _ = stage_six
                            stage_six_path = output_dir / "payload_stage6.bin"
                            stage_six_path.write_bytes(stage_six_bytes)
                            stage_seven = decode_obfuscated_stage_seven(stage_six_bytes)
                            if stage_seven is not None:
                                stage_seven_bytes, _ = stage_seven
                                stage_seven_path = output_dir / "payload_stage7.bin"
                                stage_seven_path.write_bytes(stage_seven_bytes)
                                stage_eight = decode_obfuscated_stage_eight(
                                    stage_seven_bytes
                                )
                                if stage_eight is not None:
                                    stage_eight_bytes, _ = stage_eight
                                    stage_eight_path = output_dir / "payload_stage8.bin"
                                    stage_eight_path.write_bytes(stage_eight_bytes)
                                    stage_nine = decode_obfuscated_stage_nine(
                                        stage_eight_bytes
                                    )
                                    if stage_nine is not None:
                                        stage_nine_bytes, _ = stage_nine
                                        stage_nine_path = output_dir / "payload_stage9.bin"
                                        stage_nine_path.write_bytes(stage_nine_bytes)
                                        stage_ten = decode_obfuscated_stage_ten(
                                            stage_nine_bytes
                                        )
                                        if stage_ten is not None:
                                            stage_ten_bytes, _ = stage_ten
                                            stage_ten_path = output_dir / "payload_stage10.bin"
                                            stage_ten_path.write_bytes(stage_ten_bytes)
    report = {
        "container": str(sample.resolve()),
        "container_sha256": hashlib.sha256(image).hexdigest().upper(),
        "magic": magic.rstrip(b"\0").decode("ascii", errors="replace"),
        "version": version,
        "architecture": f"0x{architecture:X}",
        "payload_offset": offset,
        "payload_size": size,
        "payload_sha256": hashlib.sha256(payload).hexdigest().upper(),
        "payload_entropy": round(entropy(payload), 4),
        "initial_call_target": (
            f"0x{initial_call_target:X}" if initial_call_target is not None else None
        ),
        "strings": strings,
        "stage_one_entry": (
            f"0x{stage_one[1]:X}" if stage_one is not None else None
        ),
        "stage_two_entry": (
            f"0x{stage_two[1]:X}" if stage_two is not None else None
        ),
        "stage_two_entropy": (
            round(entropy(stage_two[0]), 4) if stage_two is not None else None
        ),
        "stage_two_strings": (
            printable_strings(stage_two[0]) if stage_two is not None else []
        ),
        "stage_three_entry": (
            f"0x{stage_three[1]:X}" if stage_three is not None else None
        ),
        "stage_three_entropy": (
            round(entropy(stage_three[0]), 4) if stage_three is not None else None
        ),
        "stage_three_strings": (
            printable_strings(stage_three[0]) if stage_three is not None else []
        ),
        "stage_four_entry": (
            f"0x{stage_four[1]:X}" if stage_four is not None else None
        ),
        "stage_four_entropy": (
            round(entropy(stage_four[0]), 4) if stage_four is not None else None
        ),
        "stage_four_strings": (
            printable_strings(stage_four[0]) if stage_four is not None else []
        ),
        "stage_five_entry": (
            f"0x{stage_five[1]:X}" if stage_five is not None else None
        ),
        "stage_five_entropy": (
            round(entropy(stage_five[0]), 4) if stage_five is not None else None
        ),
        "stage_five_strings": (
            printable_strings(stage_five[0]) if stage_five is not None else []
        ),
        "stage_six_entry": (
            f"0x{stage_six[1]:X}" if stage_six is not None else None
        ),
        "stage_six_entropy": (
            round(entropy(stage_six[0]), 4) if stage_six is not None else None
        ),
        "stage_six_strings": (
            printable_strings(stage_six[0]) if stage_six is not None else []
        ),
        "stage_seven_entry": (
            f"0x{stage_seven[1]:X}" if stage_seven is not None else None
        ),
        "stage_seven_entropy": (
            round(entropy(stage_seven[0]), 4) if stage_seven is not None else None
        ),
        "stage_seven_strings": (
            printable_strings(stage_seven[0]) if stage_seven is not None else []
        ),
        "stage_eight_entry": (
            f"0x{stage_eight[1]:X}" if stage_eight is not None else None
        ),
        "stage_eight_entropy": (
            round(entropy(stage_eight[0]), 4) if stage_eight is not None else None
        ),
        "stage_eight_strings": (
            printable_strings(stage_eight[0]) if stage_eight is not None else []
        ),
        "stage_nine_entry": (
            f"0x{stage_nine[1]:X}" if stage_nine is not None else None
        ),
        "stage_nine_entropy": (
            round(entropy(stage_nine[0]), 4) if stage_nine is not None else None
        ),
        "stage_nine_strings": (
            printable_strings(stage_nine[0]) if stage_nine is not None else []
        ),
        "stage_ten_entry": (
            f"0x{stage_ten[1]:X}" if stage_ten is not None else None
        ),
        "stage_ten_entropy": (
            round(entropy(stage_ten[0]), 4) if stage_ten is not None else None
        ),
        "stage_ten_strings": (
            printable_strings(stage_ten[0]) if stage_ten is not None else []
        ),
    }
    (output_dir / "payload_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (output_dir / "payload_disassembly.txt").open("w", encoding="utf-8") as out:
        out.write("=== payload entry ===\n")
        out.write("\n".join(disassemble(payload, 0, min(len(payload), 256))))
        out.write("\n\n")
        if initial_call_target is not None and 0 <= initial_call_target < len(payload):
            out.write(f"=== initial call target 0x{initial_call_target:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        payload,
                        initial_call_target,
                        min(len(payload) - initial_call_target, 1024),
                    )
                )
            )
            out.write("\n")

    if stage_two is not None:
        stage_two_bytes, stage_two_entry = stage_two
        with (output_dir / "payload_stage2_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-two entry 0x{stage_two_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_two_bytes,
                        stage_two_entry,
                        min(len(stage_two_bytes) - stage_two_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_three is not None:
        stage_three_bytes, stage_three_entry = stage_three
        with (output_dir / "payload_stage3_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-three entry 0x{stage_three_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_three_bytes,
                        stage_three_entry,
                        min(len(stage_three_bytes) - stage_three_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_four is not None:
        stage_four_bytes, stage_four_entry = stage_four
        with (output_dir / "payload_stage4_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-four entry 0x{stage_four_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_four_bytes,
                        stage_four_entry,
                        min(len(stage_four_bytes) - stage_four_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_five is not None:
        stage_five_bytes, stage_five_entry = stage_five
        with (output_dir / "payload_stage5_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-five entry 0x{stage_five_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_five_bytes,
                        stage_five_entry,
                        min(len(stage_five_bytes) - stage_five_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_six is not None:
        stage_six_bytes, stage_six_entry = stage_six
        with (output_dir / "payload_stage6_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-six entry 0x{stage_six_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_six_bytes,
                        stage_six_entry,
                        min(len(stage_six_bytes) - stage_six_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_seven is not None:
        stage_seven_bytes, stage_seven_entry = stage_seven
        with (output_dir / "payload_stage7_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-seven entry 0x{stage_seven_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_seven_bytes,
                        stage_seven_entry,
                        min(len(stage_seven_bytes) - stage_seven_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_eight is not None:
        stage_eight_bytes, stage_eight_entry = stage_eight
        with (output_dir / "payload_stage8_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-eight entry 0x{stage_eight_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_eight_bytes,
                        stage_eight_entry,
                        min(len(stage_eight_bytes) - stage_eight_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_nine is not None:
        stage_nine_bytes, stage_nine_entry = stage_nine
        with (output_dir / "payload_stage9_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-nine entry 0x{stage_nine_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_nine_bytes,
                        stage_nine_entry,
                        min(len(stage_nine_bytes) - stage_nine_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_ten is not None:
        stage_ten_bytes, stage_ten_entry = stage_ten
        with (output_dir / "payload_stage10_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-ten entry 0x{stage_ten_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_ten_bytes,
                        stage_ten_entry,
                        min(len(stage_ten_bytes) - stage_ten_entry, 16384),
                    )
                )
            )
            out.write("\n")

    if stage_one is not None:
        stage_one_bytes, stage_one_entry = stage_one
        with (output_dir / "payload_stage1_disassembly.txt").open(
            "w", encoding="utf-8"
        ) as out:
            out.write(f"=== decoded stage-one entry 0x{stage_one_entry:X} ===\n")
            out.write(
                "\n".join(
                    disassemble(
                        stage_one_bytes,
                        stage_one_entry,
                        min(len(stage_one_bytes) - stage_one_entry, 4096),
                    )
                )
            )
            out.write("\n")

    print(
        json.dumps(
            {
                "payload": str(payload_path.resolve()),
                "payload_sha256": report["payload_sha256"],
                "payload_size": size,
                "entropy": report["payload_entropy"],
                "initial_call_target": report["initial_call_target"],
                "strings": len(strings),
                "stage_one": str(stage_one_path.resolve()) if stage_one_path else None,
                "stage_two": str(stage_two_path.resolve()) if stage_two_path else None,
                "stage_three": (
                    str(stage_three_path.resolve()) if stage_three_path else None
                ),
                "stage_four": (
                    str(stage_four_path.resolve()) if stage_four_path else None
                ),
                "stage_five": (
                    str(stage_five_path.resolve()) if stage_five_path else None
                ),
                "stage_six": (
                    str(stage_six_path.resolve()) if stage_six_path else None
                ),
                "stage_seven": (
                    str(stage_seven_path.resolve()) if stage_seven_path else None
                ),
                "stage_eight": (
                    str(stage_eight_path.resolve()) if stage_eight_path else None
                ),
                "stage_nine": (
                    str(stage_nine_path.resolve()) if stage_nine_path else None
                ),
                "stage_ten": (
                    str(stage_ten_path.resolve()) if stage_ten_path else None
                ),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract and inspect a BLT appended payload")
    parser.add_argument("sample", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    analyze(args.sample, args.output_dir)


if __name__ == "__main__":
    main()
