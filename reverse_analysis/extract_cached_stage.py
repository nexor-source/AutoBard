"""Statically decrypt and decompress the cached second-stage payload.

The source cache file is opened read-only.  No extracted bytes are executed.
The depacker is a bounded Python transcription of payload functions
0x346B/0x34AB/0x34EB (an aPLib-style bitstream/LZ depacker).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pefile


CACHE = Path(r"C:\ProgramData\853EAFC200002A0D\1")
ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "stage2"
XOR_KEY = b"853EAFC200002A0D"
MAX_OUTPUT = 0x100000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def repeating_xor(data: bytes, key: bytes) -> bytes:
    return bytes(value ^ key[index % len(key)] for index, value in enumerate(data))


class DepackError(ValueError):
    pass


class BitReader:
    def __init__(self, data: bytes, position: int = 0) -> None:
        self.data = data
        self.position = position
        self.tag = 0
        self.bits_left = 0

    def byte(self) -> int:
        if self.position >= len(self.data):
            raise DepackError("compressed input ended unexpectedly")
        value = self.data[self.position]
        self.position += 1
        return value

    def bit(self) -> int:
        if self.bits_left == 0:
            self.tag = self.byte()
            self.bits_left = 8
        value = (self.tag >> 7) & 1
        self.tag = (self.tag << 1) & 0xFF
        self.bits_left -= 1
        return value

    def gamma2(self) -> int:
        value = 1
        while True:
            value = (value << 1) + self.bit()
            if self.bit() == 0:
                return value
            if value > MAX_OUTPUT * 2:
                raise DepackError("gamma value is outside the bounded output range")


def copy_match(output: bytearray, offset: int, length: int) -> None:
    if offset <= 0 or offset > len(output):
        raise DepackError(f"invalid back-reference offset {offset} at output {len(output)}")
    if length < 0 or len(output) + length > MAX_OUTPUT:
        raise DepackError("decompressed output exceeds the 1 MiB loader allocation")
    for _ in range(length):
        output.append(output[-offset])


def depack(data: bytes) -> tuple[bytes, int]:
    if not data:
        raise DepackError("empty compressed stream")
    reader = BitReader(data, 1)
    output = bytearray([data[0]])
    last_offset = -1
    lwm = 0

    while True:
        if reader.bit() == 0:
            output.append(reader.byte())
            lwm = 0
        elif reader.bit() == 0:
            offset_prefix = reader.gamma2()
            if lwm == 0 and offset_prefix == 2:
                offset = last_offset
                length = reader.gamma2()
            else:
                offset_prefix -= 3 if lwm == 0 else 2
                if offset_prefix < 0:
                    raise DepackError("negative match prefix")
                offset = (offset_prefix << 8) + reader.byte()
                length = reader.gamma2()
                if offset >= 0x7D00:
                    length += 1
                if offset >= 0x500:
                    length += 1
                if offset < 0x80:
                    length += 2
                last_offset = offset
            copy_match(output, offset, length)
            lwm = 1
        elif reader.bit() == 0:
            packed = reader.byte()
            offset = packed >> 1
            if offset == 0:
                break
            length = 2 + (packed & 1)
            copy_match(output, offset, length)
            last_offset = offset
            lwm = 1
        else:
            offset = 0
            for _ in range(4):
                offset = (offset << 1) + reader.bit()
            if offset == 0:
                output.append(0)
            else:
                copy_match(output, offset, 1)
            lwm = 0

        if len(output) > MAX_OUTPUT:
            raise DepackError("decompressed output exceeds the 1 MiB loader allocation")

    return bytes(output), reader.position


def pe_summary(data: bytes) -> dict[str, object]:
    pe = pefile.PE(data=data, fast_load=False)
    exports = []
    directory = getattr(pe, "DIRECTORY_ENTRY_EXPORT", None)
    if directory is not None:
        for symbol in directory.symbols:
            exports.append(
                {
                    "ordinal": symbol.ordinal,
                    "rva": f"0x{symbol.address:X}",
                    "name": symbol.name.decode("ascii", errors="replace") if symbol.name else None,
                }
            )
    imports: dict[str, list[str]] = {}
    for descriptor in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        module = descriptor.dll.decode("ascii", errors="replace")
        names = []
        for item in descriptor.imports:
            if item.name:
                names.append(item.name.decode("ascii", errors="replace"))
            else:
                names.append(f"ordinal:{item.ordinal}")
        imports[module] = names
    return {
        "machine": f"0x{pe.FILE_HEADER.Machine:04X}",
        "timestamp": pe.FILE_HEADER.TimeDateStamp,
        "image_base": f"0x{pe.OPTIONAL_HEADER.ImageBase:X}",
        "entry_rva": f"0x{pe.OPTIONAL_HEADER.AddressOfEntryPoint:X}",
        "size_of_image": pe.OPTIONAL_HEADER.SizeOfImage,
        "sections": [
            {
                "name": section.Name.rstrip(b"\x00").decode("ascii", errors="replace"),
                "rva": f"0x{section.VirtualAddress:X}",
                "virtual_size": section.Misc_VirtualSize,
                "raw_size": section.SizeOfRawData,
                "entropy": round(section.get_entropy(), 4),
            }
            for section in pe.sections
        ],
        "imports": imports,
        "exports": exports,
    }


def main() -> None:
    encrypted = CACHE.read_bytes()
    decrypted_compressed = repeating_xor(encrypted, XOR_KEY)
    stage2, consumed = depack(decrypted_compressed)
    if stage2[:2] != b"MZ":
        raise DepackError("decompressed result does not start with MZ")

    summary = pe_summary(stage2)
    report = {
        "source": str(CACHE),
        "source_size": len(encrypted),
        "source_sha256": sha256(encrypted),
        "xor_key_ascii": XOR_KEY.decode("ascii"),
        "decrypted_compressed_sha256": sha256(decrypted_compressed),
        "compressed_bytes_consumed": consumed,
        "compressed_trailing_bytes": len(decrypted_compressed) - consumed,
        "stage2_size": len(stage2),
        "stage2_sha256": sha256(stage2),
        "pe": summary,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "cache_encrypted.bin").write_bytes(encrypted)
    (OUTPUT_DIR / "cache_xor_decrypted_compressed.bin").write_bytes(decrypted_compressed)
    (OUTPUT_DIR / "stage2_unpacked.exe.bin").write_bytes(stage2)
    (OUTPUT_DIR / "stage2_summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
