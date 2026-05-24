"""
gen_poly_random.py
Generates poly_random.h from python-chess's POLYGLOT_RANDOM_ARRAY.
These are the standard Polyglot opening book random numbers.
"""
import chess.polyglot

values = chess.polyglot.POLYGLOT_RANDOM_ARRAY
assert len(values) == 781, f"Expected 781, got {len(values)}"

lines = ["#pragma once", "#include <stdint.h>", "",
         "static const uint64_t POLY_RAND[781] = {"]
for i, v in enumerate(values):
    comma = "," if i < 780 else ""
    if i % 4 == 0:
        lines.append("    " + f"0x{v:016X}ULL{comma}", )
    else:
        lines[-1] += f" 0x{v:016X}ULL{comma}"
lines.append("};")
lines.append("")

with open("poly_random.h", "w") as f:
    f.write("\n".join(lines))

print(f"Written poly_random.h ({len(values)} entries)")
