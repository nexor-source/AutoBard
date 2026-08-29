from __future__ import annotations

import argparse
import hashlib
import json
import struct
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import pefile
from capstone import CS_ARCH_X86, CS_MODE_64, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_REG_RIP


INTERESTING_IMPORTS = {
    "CreateThread",
    "WaitForSingleObject",
    "GetExitCodeThread",
    "VirtualAlloc",
    "VirtualProtect",
    "VirtualFree",
    "CreateFileW",
    "ReadFile",
    "WriteFile",
    "LoadLibraryExW",
    "GetProcAddress",
    "FlushInstructionCache",
    "IsDebuggerPresent",
    "TerminateProcess",
}


@dataclass
class Function:
    start_rva: int
    end_rva: int
    source: str
    instructions: list = field(default_factory=list)
    direct_calls: set[int] = field(default_factory=set)
    import_calls: set[str] = field(default_factory=set)
    strings: set[str] = field(default_factory=set)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def clean_name(raw: bytes) -> str:
    return raw.rstrip(b"\0").decode("ascii", errors="replace")


def is_executable_section(section: pefile.SectionStructure) -> bool:
    return bool(section.Characteristics & 0x20000000)


def section_for_rva(pe: pefile.PE, rva: int):
    for section in pe.sections:
        start = section.VirtualAddress
        end = start + max(section.Misc_VirtualSize, section.SizeOfRawData)
        if start <= rva < end:
            return section
    return None


def read_candidate_string(pe: pefile.PE, rva: int) -> str | None:
    section = section_for_rva(pe, rva)
    if section is None or is_executable_section(section):
        return None
    try:
        data = pe.get_data(rva, 512)
    except pefile.PEFormatError:
        return None

    ascii_end = data.find(b"\0")
    if ascii_end >= 4:
        raw = data[:ascii_end]
        if all(byte in (9, 10, 13) or 32 <= byte < 127 for byte in raw):
            return raw.decode("ascii", errors="replace")

    if len(data) >= 8:
        units: list[int] = []
        for offset in range(0, min(len(data), 512) - 1, 2):
            value = struct.unpack_from("<H", data, offset)[0]
            if value == 0:
                break
            if value < 32 and value not in (9, 10, 13):
                units = []
                break
            units.append(value)
        if len(units) >= 4:
            raw = b"".join(struct.pack("<H", value) for value in units)
            return raw.decode("utf-16le", errors="replace")
    return None


def imported_symbols(pe: pefile.PE) -> dict[int, str]:
    result: dict[int, str] = {}
    for descriptor in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        dll = descriptor.dll.decode("ascii", errors="replace")
        for symbol in descriptor.imports:
            name = (
                symbol.name.decode("ascii", errors="replace")
                if symbol.name
                else f"ordinal_{symbol.ordinal}"
            )
            result[int(symbol.address)] = f"{dll}!{name}"
    return result


def exception_functions(pe: pefile.PE) -> dict[int, tuple[int, str]]:
    result: dict[int, tuple[int, str]] = {}
    for entry in getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", []):
        begin = int(entry.struct.BeginAddress)
        end = int(entry.struct.EndAddress)
        if end > begin:
            result[begin] = (end, "pdata")
    return result


def decode_function(
    pe: pefile.PE,
    md: Cs,
    start_rva: int,
    end_rva: int,
    source: str,
    imports: dict[int, str],
) -> Function:
    function = Function(start_rva=start_rva, end_rva=end_rva, source=source)
    size = min(max(end_rva - start_rva, 1), 256 * 1024)
    code = pe.get_data(start_rva, size)
    start_va = pe.OPTIONAL_HEADER.ImageBase + start_rva
    for instruction in md.disasm(code, start_va):
        if instruction.address >= pe.OPTIONAL_HEADER.ImageBase + end_rva:
            break
        function.instructions.append(instruction)
        # Capstone emits id=0 pseudo instructions for undecodable bytes when
        # skipdata is enabled; detail/operands are intentionally unavailable.
        if instruction.id == 0:
            continue
        for operand in instruction.operands:
            if operand.type == X86_OP_MEM and operand.mem.base == X86_REG_RIP:
                target_va = instruction.address + instruction.size + operand.mem.disp
                imported = imports.get(target_va)
                if instruction.mnemonic == "call" and imported:
                    function.import_calls.add(imported)
                target_rva = target_va - pe.OPTIONAL_HEADER.ImageBase
                text = read_candidate_string(pe, target_rva)
                if text:
                    function.strings.add(text)
        if instruction.mnemonic == "call" and instruction.operands:
            operand = instruction.operands[0]
            if operand.type == X86_OP_IMM:
                target_rva = int(operand.imm - pe.OPTIONAL_HEADER.ImageBase)
                target_section = section_for_rva(pe, target_rva)
                if target_section is not None and is_executable_section(target_section):
                    function.direct_calls.add(target_rva)
    return function


def inferred_end(pe: pefile.PE, start: int, known_starts: list[int]) -> int:
    section = section_for_rva(pe, start)
    if section is None:
        return start + 1
    section_end = section.VirtualAddress + min(
        max(section.Misc_VirtualSize, section.SizeOfRawData), 0x100000
    )
    following = next((value for value in known_starts if value > start), section_end)
    return min(following, start + 0x2000, section_end)


def analyze(sample: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pe = pefile.PE(str(sample), fast_load=False)
    if pe.FILE_HEADER.Machine != 0x8664:
        raise RuntimeError("This analyzer currently expects an x64 PE image")

    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    md.skipdata = True
    imports = imported_symbols(pe)
    boundaries = exception_functions(pe)
    entry = int(pe.OPTIONAL_HEADER.AddressOfEntryPoint)
    if entry not in boundaries:
        boundaries[entry] = (inferred_end(pe, entry, sorted(boundaries)), "entry")

    functions: dict[int, Function] = {}
    queue = deque(sorted(boundaries))
    seen: set[int] = set()
    while queue:
        start = queue.popleft()
        if start in seen:
            continue
        seen.add(start)
        if start in boundaries:
            end, source = boundaries[start]
        else:
            starts = sorted(set(boundaries) | seen | set(queue))
            end, source = inferred_end(pe, start, starts), "call-target"
        function = decode_function(pe, md, start, end, source, imports)
        functions[start] = function
        for target in function.direct_calls:
            if target not in seen:
                queue.append(target)

    callers: dict[int, set[int]] = defaultdict(set)
    for function in functions.values():
        for target in function.direct_calls:
            callers[target].add(function.start_rva)

    import_callers: dict[str, list[int]] = defaultdict(list)
    for function in functions.values():
        for imported in function.import_calls:
            import_callers[imported].append(function.start_rva)

    interesting: set[int] = {entry}
    for function in functions.values():
        names = {name.rsplit("!", 1)[-1] for name in function.import_calls}
        if names & INTERESTING_IMPORTS:
            interesting.add(function.start_rva)
    frontier = list(interesting)
    for _ in range(3):
        next_frontier: list[int] = []
        for child in frontier:
            for parent in callers.get(child, set()):
                if parent not in interesting:
                    interesting.add(parent)
                    next_frontier.append(parent)
        frontier = next_frontier

    def function_summary(function: Function) -> dict:
        return {
            "rva": f"0x{function.start_rva:X}",
            "va": f"0x{pe.OPTIONAL_HEADER.ImageBase + function.start_rva:X}",
            "end_rva": f"0x{function.end_rva:X}",
            "source": function.source,
            "instruction_count": len(function.instructions),
            "direct_calls": [f"0x{value:X}" for value in sorted(function.direct_calls)],
            "called_by": [f"0x{value:X}" for value in sorted(callers.get(function.start_rva, set()))],
            "import_calls": sorted(function.import_calls),
            "strings": sorted(function.strings),
        }

    summary = {
        "sample": str(sample.resolve()),
        "sha256": sha256(sample),
        "machine": f"0x{pe.FILE_HEADER.Machine:X}",
        "image_base": f"0x{pe.OPTIONAL_HEADER.ImageBase:X}",
        "entry_rva": f"0x{entry:X}",
        "function_count": len(functions),
        "imports": {
            f"0x{address:X}": name for address, name in sorted(imports.items())
        },
        "import_callers": {
            name: [f"0x{value:X}" for value in sorted(values)]
            for name, values in sorted(import_callers.items())
        },
        "interesting_functions": [
            function_summary(functions[start])
            for start in sorted(interesting)
            if start in functions
        ],
        "all_functions": [
            function_summary(function) for _, function in sorted(functions.items())
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (output_dir / "interesting_disassembly.txt").open("w", encoding="utf-8") as out:
        out.write(f"sample: {sample.resolve()}\nsha256: {summary['sha256']}\n\n")
        for start in sorted(interesting):
            function = functions.get(start)
            if function is None:
                continue
            out.write(
                f"=== FUN_{start:08X} .. {function.end_rva:08X} "
                f"({function.source}) ===\n"
            )
            if function.import_calls:
                out.write("imports: " + ", ".join(sorted(function.import_calls)) + "\n")
            if function.strings:
                out.write("strings: " + repr(sorted(function.strings)) + "\n")
            for instruction in function.instructions:
                suffix = ""
                if (
                    instruction.id != 0
                    and instruction.mnemonic == "call"
                    and instruction.operands
                ):
                    operand = instruction.operands[0]
                    if operand.type == X86_OP_IMM:
                        target = int(operand.imm - pe.OPTIONAL_HEADER.ImageBase)
                        suffix = f" ; FUN_{target:08X}"
                    elif operand.type == X86_OP_MEM and operand.mem.base == X86_REG_RIP:
                        target_va = instruction.address + instruction.size + operand.mem.disp
                        if target_va in imports:
                            suffix = f" ; {imports[target_va]}"
                out.write(
                    f"{instruction.address:016X}  {instruction.mnemonic:<9} "
                    f"{instruction.op_str}{suffix}\n"
                )
            out.write("\n")

    with (output_dir / "all_strings.txt").open("w", encoding="utf-8") as out:
        for function in sorted(functions.values(), key=lambda value: value.start_rva):
            for text in sorted(function.strings):
                out.write(f"FUN_{function.start_rva:08X}\t{text!r}\n")

    print(json.dumps({
        "summary": str((output_dir / "summary.json").resolve()),
        "disassembly": str((output_dir / "interesting_disassembly.txt").resolve()),
        "functions": len(functions),
        "interesting": len(interesting),
        "sha256": summary["sha256"],
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Static x64 PE analysis with pefile + Capstone")
    parser.add_argument("sample", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    analyze(args.sample, args.output_dir)


if __name__ == "__main__":
    main()
