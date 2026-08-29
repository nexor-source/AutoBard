from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from capstone import CS_ARCH_X86, CS_MODE_64, Cs
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG, X86_REG_RIP


class DecodeStopped(RuntimeError):
    pass


@dataclass(frozen=True)
class Layer:
    number: int
    kind: str
    old_entry: int
    new_entry: int
    description: str
    sha256: str


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def rol(value: int, count: int, bits: int) -> int:
    count %= bits
    mask = (1 << bits) - 1
    if count == 0:
        return value & mask
    return ((value << count) | (value >> (bits - count))) & mask


def ror(value: int, count: int, bits: int) -> int:
    count %= bits
    mask = (1 << bits) - 1
    if count == 0:
        return value & mask
    return ((value >> count) | (value << (bits - count))) & mask


def instruction_at(md: Cs, data: bytearray, offset: int):
    if not 0 <= offset < len(data):
        raise DecodeStopped(f"instruction pointer out of range: 0x{offset:X}")
    instruction = next(md.disasm(bytes(data[offset : offset + 16]), offset, count=1), None)
    if instruction is None:
        raise DecodeStopped(f"cannot decode instruction at 0x{offset:X}")
    return instruction


def is_same_register_noop(instruction) -> bool:
    if not instruction.mnemonic.startswith("cmov") and instruction.mnemonic != "mov":
        return False
    if len(instruction.operands) != 2:
        return False
    left, right = instruction.operands
    return (
        left.type == X86_OP_REG
        and right.type == X86_OP_REG
        and left.reg == right.reg
    )


def is_zero_shift_noop(instruction) -> bool:
    if instruction.mnemonic not in {"shl", "shr", "rcl", "rcr", "rol", "ror"}:
        return False
    return (
        len(instruction.operands) == 2
        and instruction.operands[0].type == X86_OP_REG
        and instruction.operands[1].type == X86_OP_IMM
        and instruction.operands[1].imm % 64 == 0
    )


def direct_target(instruction) -> int:
    if len(instruction.operands) != 1 or instruction.operands[0].type != X86_OP_IMM:
        raise DecodeStopped(
            f"expected direct target at 0x{instruction.address:X}: "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
    return int(instruction.operands[0].imm)


def mutate_memory(data: bytearray, offset: int, size: int, mnemonic: str, value: int) -> None:
    if size not in {1, 2, 4, 8}:
        raise DecodeStopped(f"unsupported mutation width: {size}")
    if offset < 0 or offset + size > len(data):
        raise DecodeStopped(f"mutation out of bounds: 0x{offset:X}+{size}")
    bits = size * 8
    current = int.from_bytes(data[offset : offset + size], "little")
    mask = (1 << bits) - 1
    if mnemonic == "add":
        result = current + value
    elif mnemonic == "sub":
        result = current - value
    elif mnemonic == "xor":
        result = current ^ value
    elif mnemonic == "not":
        result = ~current
    elif mnemonic == "rol":
        result = rol(current, value, bits)
    elif mnemonic == "ror":
        result = ror(current, value, bits)
    else:
        raise DecodeStopped(f"unsupported mutation: {mnemonic}")
    data[offset : offset + size] = int(result & mask).to_bytes(size, "little")


def run_tail_decoder(md: Cs, data: bytearray, call_instruction) -> tuple[int, list[str]]:
    return_address = call_instruction.address + call_instruction.size
    pc = direct_target(call_instruction)
    stack = [return_address]
    registers: dict[str, int] = {}
    trace: list[str] = []

    for _ in range(100):
        instruction = instruction_at(md, data, pc)
        trace.append(
            f"0x{instruction.address:X}: {instruction.mnemonic} {instruction.op_str}".rstrip()
        )
        next_pc = instruction.address + instruction.size

        if instruction.mnemonic == "jmp":
            operand = instruction.operands[0]
            if operand.type == X86_OP_IMM:
                pc = int(operand.imm)
                continue
            if operand.type == X86_OP_REG:
                register = instruction.reg_name(operand.reg)
                if register not in registers:
                    raise DecodeStopped(f"unknown jump register {register} at 0x{pc:X}")
                return registers[register], trace
            raise DecodeStopped(f"unsupported jump at 0x{pc:X}")

        if instruction.mnemonic == "pop" and instruction.operands[0].type == X86_OP_REG:
            if not stack:
                raise DecodeStopped(f"decoder stack underflow at 0x{pc:X}")
            registers[instruction.reg_name(instruction.operands[0].reg)] = stack.pop()
            pc = next_pc
            continue

        if is_same_register_noop(instruction) or is_zero_shift_noop(instruction):
            pc = next_pc
            continue
        if instruction.mnemonic in {"nop", "cmc", "clc", "cld", "std"}:
            pc = next_pc
            continue

        if instruction.mnemonic in {"add", "sub", "xor", "not", "rol", "ror"}:
            destination = instruction.operands[0]
            if destination.type != X86_OP_MEM or destination.mem.index != 0:
                raise DecodeStopped(f"unsupported decoder operation at 0x{pc:X}")
            base_register = instruction.reg_name(destination.mem.base)
            if base_register not in registers:
                raise DecodeStopped(
                    f"unknown memory base {base_register} at 0x{pc:X}"
                )
            offset = registers[base_register] + int(destination.mem.disp)
            if instruction.mnemonic == "not":
                immediate = 0
            else:
                source = instruction.operands[1]
                if source.type != X86_OP_IMM:
                    raise DecodeStopped(f"non-immediate mutation at 0x{pc:X}")
                immediate = int(source.imm)
            mutate_memory(
                data,
                offset,
                int(destination.size),
                instruction.mnemonic,
                immediate,
            )
            pc = next_pc
            continue

        raise DecodeStopped(
            f"unsupported tail instruction at 0x{pc:X}: "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
    raise DecodeStopped("tail decoder exceeded instruction limit")


def peel_one(md: Cs, data: bytearray, entry: int) -> tuple[str, int, str]:
    pc = entry
    register_values: dict[str, int] = {}
    trace: list[str] = []

    for _ in range(80):
        instruction = instruction_at(md, data, pc)
        trace.append(
            f"0x{instruction.address:X}: {instruction.mnemonic} {instruction.op_str}".rstrip()
        )
        next_pc = instruction.address + instruction.size

        if instruction.mnemonic == "jmp":
            pc = direct_target(instruction)
            continue

        if instruction.mnemonic == "call":
            target, tail_trace = run_tail_decoder(md, data, instruction)
            description = " | ".join(trace + tail_trace)
            return "tail-mutation", target, description

        if is_same_register_noop(instruction) or is_zero_shift_noop(instruction):
            pc = next_pc
            continue
        if instruction.mnemonic in {"nop", "cmc", "clc", "cld", "std"}:
            pc = next_pc
            continue

        if instruction.mnemonic == "mov" and len(instruction.operands) == 2:
            destination, source = instruction.operands
            if destination.type == X86_OP_REG and source.type == X86_OP_IMM:
                register_values[instruction.reg_name(destination.reg)] = int(source.imm)
                pc = next_pc
                continue

        if instruction.mnemonic == "lea" and len(instruction.operands) == 2:
            destination, source = instruction.operands
            if (
                destination.type == X86_OP_REG
                and source.type == X86_OP_MEM
                and source.mem.base == X86_REG_RIP
                and source.mem.index == 0
            ):
                register_values[instruction.reg_name(destination.reg)] = (
                    instruction.address + instruction.size + int(source.mem.disp)
                )
                pc = next_pc
                continue

        if instruction.mnemonic in {"add", "sub"} and len(instruction.operands) == 2:
            destination, source = instruction.operands
            if destination.type == X86_OP_REG and source.type == X86_OP_IMM:
                cursor = next_pc
                middle: list = []
                while len(middle) < 4:
                    candidate = instruction_at(md, data, cursor)
                    if is_same_register_noop(candidate) or is_zero_shift_noop(candidate):
                        middle.append(candidate)
                        cursor = candidate.address + candidate.size
                        continue
                    break
                inverse = instruction_at(md, data, cursor)
                expected = "sub" if instruction.mnemonic == "add" else "add"
                if (
                    inverse.mnemonic == expected
                    and len(inverse.operands) == 2
                    and inverse.operands[0].type == X86_OP_REG
                    and inverse.operands[0].reg == destination.reg
                    and inverse.operands[1].type == X86_OP_IMM
                    and int(inverse.operands[1].imm) == int(source.imm)
                ):
                    trace.extend(
                        f"0x{value.address:X}: {value.mnemonic} {value.op_str}".rstrip()
                        for value in middle
                    )
                    trace.append(
                        f"0x{inverse.address:X}: {inverse.mnemonic} "
                        f"{inverse.op_str}".rstrip()
                    )
                    pc = inverse.address + inverse.size
                    continue

        if instruction.mnemonic == "xor" and len(instruction.operands) == 2:
            destination, source = instruction.operands
            if (
                destination.type == X86_OP_MEM
                and destination.mem.base != 0
                and destination.mem.index != 0
                and source.type == X86_OP_REG
            ):
                base_name = instruction.reg_name(destination.mem.base)
                index_name = instruction.reg_name(destination.mem.index)
                key_name = instruction.reg_name(source.reg)
                if not all(
                    name in register_values for name in (base_name, index_name, key_name)
                ):
                    raise DecodeStopped(f"unknown rolling-loop register at 0x{pc:X}")
                add_instruction = instruction_at(md, data, next_pc)
                loop_instruction = instruction_at(
                    md, data, add_instruction.address + add_instruction.size
                )
                if add_instruction.mnemonic != "add" or loop_instruction.mnemonic != "loop":
                    raise DecodeStopped(f"unexpected rolling-loop body at 0x{pc:X}")
                count = register_values[index_name]
                key = register_values[key_name] & 0xFF
                base = register_values[base_name] + int(destination.mem.disp)
                if count <= 0 or base + count >= len(data):
                    raise DecodeStopped(
                        f"rolling-loop bounds invalid: base=0x{base:X} count=0x{count:X}"
                    )
                for counter in range(count, 0, -1):
                    offset = base + counter
                    data[offset] ^= key
                    key = (key + data[offset]) & 0xFF
                new_entry = loop_instruction.address + loop_instruction.size
                description = (
                    f"rolling XOR: base=0x{base:X}, count=0x{count:X}, "
                    f"initial_key=0x{register_values[key_name] & 0xFF:02X}"
                )
                return "rolling-xor", new_entry, description

        raise DecodeStopped(
            f"unsupported setup instruction at 0x{pc:X}: "
            f"{instruction.mnemonic} {instruction.op_str}"
        )
    raise DecodeStopped("layer setup exceeded instruction limit")


def strings(data: bytes) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for match in re.finditer(rb"[\x20-\x7e]{5,}", data):
        result.append(
            {
                "offset": f"0x{match.start():X}",
                "encoding": "ascii",
                "value": match.group().decode("ascii", errors="replace"),
            }
        )
    for match in re.finditer(rb"(?:[\x20-\x7e]\x00){5,}", data):
        result.append(
            {
                "offset": f"0x{match.start():X}",
                "encoding": "utf-16le",
                "value": match.group().decode("utf-16le", errors="replace"),
            }
        )
    return sorted(result, key=lambda item: int(item["offset"], 16))


def main() -> None:
    parser = argparse.ArgumentParser(description="Peel constrained BLT decoder layers")
    parser.add_argument("payload", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--entry", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--max-layers", type=int, default=100)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = bytearray(args.payload.read_bytes())
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    entry = args.entry
    layers: list[Layer] = []
    stop_reason = "maximum layer count reached"

    for number in range(1, args.max_layers + 1):
        before = bytes(data)
        try:
            kind, new_entry, description = peel_one(md, data, entry)
        except DecodeStopped as exc:
            stop_reason = str(exc)
            break
        if bytes(data) == before:
            raise RuntimeError(f"layer {number} did not change the payload")
        layer = Layer(
            number=number,
            kind=kind,
            old_entry=entry,
            new_entry=new_entry,
            description=description,
            sha256=digest(data),
        )
        layers.append(layer)
        entry = new_entry
        (args.output_dir / f"auto_stage_{number:02d}.bin").write_bytes(data)

    final_path = args.output_dir / "payload_final.bin"
    final_path.write_bytes(data)
    final_disassembly = args.output_dir / "payload_final_disassembly.txt"
    with final_disassembly.open("w", encoding="utf-8") as out:
        for instruction in md.disasm(bytes(data[entry:]), entry):
            out.write(
                f"{instruction.address:08X}  {instruction.mnemonic:<9} "
                f"{instruction.op_str}\n"
            )

    report = {
        "input": str(args.payload.resolve()),
        "input_sha256": digest(args.payload.read_bytes()),
        "layers_peeled": len(layers),
        "final_entry": f"0x{entry:X}",
        "final_sha256": digest(data),
        "stop_reason": stop_reason,
        "layers": [
            {
                "number": layer.number,
                "kind": layer.kind,
                "old_entry": f"0x{layer.old_entry:X}",
                "new_entry": f"0x{layer.new_entry:X}",
                "description": layer.description,
                "sha256": layer.sha256,
            }
            for layer in layers
        ],
        "strings": strings(data),
    }
    report_path = args.output_dir / "peel_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "layers_peeled": len(layers),
        "final_entry": f"0x{entry:X}",
        "stop_reason": stop_reason,
        "report": str(report_path.resolve()),
        "final_payload": str(final_path.resolve()),
    }, indent=2))


if __name__ == "__main__":
    main()
