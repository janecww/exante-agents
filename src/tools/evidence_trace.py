"""Check C6: every "available" value must be traceable to the case evidence.

The checks C2 and C5 confirm that the two agents agree and that a value
and source were filled in; neither opens the case workbook. This module
does: for an input tagged LAB, LITERATURE or LAB|LITERATURE that a model marked
"available", the value (or, for a derived value, every number it was
derived from) must appear in the case evidence:

- LAB: a value on the Process Inventory or Lab-Derived Parameters sheet
  whose Provenance is "Reported" or "Calculated";
- LITERATURE: a value anywhere in that evidence (the definition requires
  the value and its citation to be in the case evidence);
- LAB|LITERATURE: either of the above, so a value anywhere in that evidence.

CONSTANT and DEFAULT inputs are not traced (a stated physical constant;
a value fixed by the framework).

Deliberately not over-strict, so that a legitimate value is never lost:
- unit conversions count as traced (allowed derivation 1), as does
  mass <-> volume at 1 kg/L (allowed derivation 2), even when the model
  wrote no derivation. When both units are known, only conversions within
  the same kind of quantity are tried (so 1 kg never matches 0.0167 h);
  when the model gave no unit, common conversion factors are tried; when
  the evidence unit is unknown or compound (kg/L), only an exact match
  counts (so 4503.25 never matches 1.25 x 3600 by coincidence);
- values match within 0.5 % (rounding: 0.333 h for 20 min is 0.1 %);
- numbers that are pure conversion constants (1, 60, 1000, ...) inside a
  derivation need no trace;
- a non-numeric value (e.g. a reaction equation) is not traced;
- a derivation whose arithmetic the code cannot parse keeps its status
  with an informational note; only a parsed derivation that gives a
  different result is downgraded.

Whether the matched evidence belongs to the same process step is not
checked here; that stays part of the shared definition the models apply.
"""

import ast
import operator
import re

from src.models.technology import Technology
from src.skills.availability import LAB, LAB_OR_LITERATURE, LAB_PROVENANCE, LITERATURE

# 0.5 %: covers rounding (0.333 for 20/60 is 0.1 %; 10.8 for 3.61/0.333 is
# 0.4 %) without letting a stated 1 match a reported 1.01.
TOLERANCE = 0.005

# unit -> (kind of quantity, factor to the kind's base unit)
UNITS = {
    "s": ("time", 1.0), "sec": ("time", 1.0), "min": ("time", 60.0), "h": ("time", 3600.0), "hr": ("time", 3600.0),
    "hour": ("time", 3600.0), "hours": ("time", 3600.0), "d": ("time", 86400.0), "day": ("time", 86400.0),
    "mg": ("mass", 1e-6), "g": ("mass", 1e-3), "kg": ("mass", 1.0), "t": ("mass", 1000.0), "tonne": ("mass", 1000.0),
    "ml": ("volume", 1e-6), "l": ("volume", 1e-3), "m3": ("volume", 1.0), "m³": ("volume", 1.0),
    "j": ("energy", 1.0), "kj": ("energy", 1e3), "mj": ("energy", 1e6), "wh": ("energy", 3600.0),
    "kwh": ("energy", 3.6e6), "mwh": ("energy", 3.6e9),
    "w": ("power", 1.0), "kw": ("power", 1e3), "mw": ("power", 1e6),
}
_WATER_DENSITY = 1000.0  # kg per m3 (allowed derivation 2)

# Used only when a unit is unknown on either side.
_BASE_FACTORS = (1.0, 1000.0, 60.0, 3600.0, 1_000_000.0, 3.6, 24.0, 100.0)
UNIT_FACTORS = tuple(sorted({f for b in _BASE_FACTORS for f in (b, 1.0 / b)}))
# Numbers that may appear in a derivation as conversion constants or the
# 1 kg/L water density, without needing a trace.
CONVERSION_CONSTANTS = {1.0, 60.0, 1000.0, 3600.0, 1_000_000.0, 3.6, 24.0, 100.0, 0.001}

_NUMBER = re.compile(r"(?<![A-Za-z_\d.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_NUMBER_WITH_UNIT = re.compile(
    r"(?<![A-Za-z_\d.])([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*([A-Za-zµ³]+[0-9³]?)?"
)


def _unit(text) -> tuple[str, float] | None:
    return UNITS.get(str(text).strip().lower()) if text else None


def build_evidence_index(technology: Technology, lab_derived_parameters: list[dict]) -> list[dict]:
    """Every numeric evidence value: {value, unit, provenance, label}."""
    index = []
    for process in technology.processes:
        for kind, flows in (("input", process.inputs), ("output", process.outputs)):
            for flow in flows:
                if isinstance(flow.value, (int, float)) and not isinstance(flow.value, bool):
                    index.append({"value": float(flow.value), "unit": flow.unit, "provenance": flow.provenance,
                                  "label": f"Process Inventory: {process.id} {kind} {flow.name}"})
    for row in lab_derived_parameters:
        value = row.get("Value (numeric)")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            index.append({"value": float(value), "unit": row.get("Unit"), "provenance": row.get("Provenance"),
                          "label": f"Lab-Derived Parameters: {row.get('Process stage')} {row.get('Parameter')}"})
    return index


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    return abs(a - b) <= TOLERANCE * max(abs(a), abs(b))


def _matches(number: float, unit, entry: dict) -> bool:
    stated, held = _unit(unit), _unit(entry["unit"])
    if stated and held:
        if stated[0] == held[0]:
            return _close(number * stated[1], entry["value"] * held[1])
        kinds = {stated[0], held[0]}
        if kinds == {"mass", "volume"}:  # water at 1 kg/L
            to_kg = lambda value, unit: value * unit[1] * (_WATER_DENSITY if unit[0] == "volume" else 1.0)
            return _close(to_kg(number, stated), to_kg(entry["value"], held))
        return False
    if held and not stated:
        # The model gave no unit: try common conversion factors.
        return any(_close(number, entry["value"] * factor) for factor in UNIT_FACTORS)
    # The evidence unit is unknown or compound (e.g. kg/L): an exact match
    # only, so that a coincidental factor (1.25 x 3600 = 4500) never counts.
    return _close(number, entry["value"])


def find_trace(number: float, index: list[dict], lab_only: bool, unit=None) -> dict | None:
    """The evidence entry `number` (in `unit`, if known) matches."""
    for entry in index:
        if lab_only and entry["provenance"] not in LAB_PROVENANCE:
            continue
        if _matches(number, unit, entry):
            return entry
    return None


def _first_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value or ""))
    return float(match.group()) if match else None


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _evaluate(expression: str) -> float | None:
    """Safely evaluate + - * / arithmetic; None if it is anything else."""
    if not expression:
        return None
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        raise ValueError("unsupported")

    try:
        return walk(tree)
    except (ValueError, ZeroDivisionError):
        return None


def _strip_labels(text: str) -> str:
    """Remove parenthetical labels such as '(Lab-Derived Parameters: V1)' or
    '(P04 electricity)', but keep arithmetic groups such as '(1 h / 60 min)'
    or '(3.16 kg + 15.61 kg)': a group holding a free-standing number is
    arithmetic, not a label (digits inside identifiers like P04 or V1 do not
    count)."""

    def replace(match: re.Match) -> str:
        inner = match.group(0)[1:-1]
        return match.group(0) if _NUMBER.search(inner) else " "

    previous = None
    while previous != text:  # innermost labels first
        previous = text
        text = re.sub(r"\([^()]*\)", replace, text)
    return text


def _arithmetic(left: str) -> str:
    """Reduce '3.61 kWh (P04 electricity) / 0.333 h (...)' to '3.61 / 0.333'."""
    text = _strip_labels(left)
    text = re.sub(r"(?<=[\s\d])[x×](?=[\s\d])", " * ", text).replace("÷", "/")
    # Unit tokens, including compound units such as kg/L or kWh/kg.
    text = re.sub(r"[A-Za-zµ°%][A-Za-z0-9µ°%³²_]*(?:/[A-Za-zµ°%][A-Za-z0-9µ°%³²_]*)*", " ", text)
    text = re.sub(r"[^0-9.eE+\-*/() ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def check_available_value(
    name: str, tag: str, value, derivation: str | None, index: list[dict], unit=None
) -> tuple[bool, str | None]:
    """C6 for one input. Returns (keep_available, message or None)."""
    if tag not in (LAB, LITERATURE, LAB_OR_LITERATURE):
        return True, None
    lab_only = tag == LAB
    where = "a Reported or Calculated value of the case evidence" if lab_only else "the case evidence"
    number = _first_number(value)

    if derivation and derivation.strip():
        # The expression is what precedes the FIRST "=": later segments are
        # the model's intermediate results (e.g. "a / (b + c) = a / 1342.76 =
        # 0.000171"), not inputs to trace.
        left = derivation.split("=", 1)[0] if "=" in derivation else derivation
        operands = [
            (float(match.group(1)), match.group(2))
            for match in _NUMBER_WITH_UNIT.finditer(_strip_labels(left))
        ]
        if "=" not in derivation and number is not None:
            operands = [item for item in operands if not _close(item[0], number)]  # the result itself
        untraced = [
            x for x, x_unit in operands
            if abs(x) not in CONVERSION_CONSTANTS and find_trace(x, index, lab_only, x_unit) is None
        ]
        if untraced:
            return False, f"C6: {name}: derivation uses {', '.join(f'{x:g}' for x in untraced)}, not found in {where}; treated as missing"
        result = _evaluate(_arithmetic(left)) if "=" in derivation else None
        if result is None or number is None:
            return True, f"C6 (note): {name}: derivation not recomputed by code; its numbers were traced to the evidence"
        if not _close(result, number):
            return False, f"C6: {name}: derivation gives {result:g}, not the stated {number:g}; treated as missing"
        return True, None

    if number is None:
        return True, None  # non-numeric value (e.g. a reaction equation): not traced
    if find_trace(number, index, lab_only, unit) is None:
        hint = ""
        if lab_only and find_trace(number, index, False, unit) is not None:
            hint = " (it appears only with a provenance other than Reported/Calculated)"
        return False, f"C6: {name}: value {number:g} {unit or ''} not found in {where}{hint}; treated as missing".replace("  ", " ")
    return True, None
