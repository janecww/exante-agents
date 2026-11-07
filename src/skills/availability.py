"""The single definition of "available" used by every agent.

Both the Estimation Recommendation prompt and the Parameter
Identification prompt insert `AVAILABILITY_DEFINITION` verbatim, so the
two agents can never be given different rules for the same judgement
(see docs/R2_alignment_plan.md, section 1). The same text is reproduced
for people in the `how_to_use` sheet of
`src/skills/scaleup_decision_framework.xlsx`.

Every input of a rule carries exactly one tag in the framework's
`inputs` column, e.g. ``lab_solvent_mass [LAB]; scale_factor [TARGET]``
or ``recovery_fraction [DEFAULT=0.75]``. `parse_inputs` turns that text
into structured records; the tags are always taken from the framework,
never from a model's answer.
"""

import re

LAB = "LAB"
CONSTANT = "CONSTANT"
DEFAULT = "DEFAULT"
LITERATURE = "LITERATURE"
TARGET = "TARGET"
TAGS = (LAB, CONSTANT, DEFAULT, LITERATURE, TARGET)

AVAILABLE = "available"
MISSING = "missing"
AMBIGUOUS = "ambiguous"
STATUSES = (AVAILABLE, MISSING, AMBIGUOUS)

# Provenance values that make a case value LAB evidence.
LAB_PROVENANCE = ("Reported", "Calculated")

_INPUT_PATTERN = re.compile(r"^\s*(?P<name>[A-Za-z0-9_]+)\s*\[(?P<tag>[A-Z]+)(?:=(?P<default>[^\]]+))?\]\s*$")


def parse_inputs(inputs: str | None) -> list[dict]:
    """Parse a rule's `inputs` cell into ``{name, tag, default}`` records.

    Raises `ValueError` on any item that does not follow the
    ``name [TAG]`` / ``name [DEFAULT=value]`` form, so a malformed
    framework row fails loudly at load time instead of reaching a prompt.
    """
    records = []
    for item in (inputs or "").split(";"):
        if not item.strip():
            continue
        match = _INPUT_PATTERN.match(item)
        if not match or match["tag"] not in TAGS:
            raise ValueError(f"Malformed framework input {item.strip()!r}: expected 'name [TAG]' with TAG in {TAGS}")
        if (match["tag"] == DEFAULT) != (match["default"] is not None):
            raise ValueError(f"Malformed framework input {item.strip()!r}: only DEFAULT carries a value, and it must")
        records.append({"name": match["name"], "tag": match["tag"], "default": match["default"]})
    return records


def decides_availability(tag: str) -> bool:
    """TARGET inputs never decide whether a rule is available."""
    return tag != TARGET


AVAILABILITY_DEFINITION = f"""\
DEFINITION OF "AVAILABLE" (the same definition is used by every agent in this workflow)

Every input of a rule carries one tag, shown in square brackets in the rule's `inputs`:

- [LAB]: measured or reported for this case. AVAILABLE only when the value is stated in the case evidence \
(LABORATORY PROCESS INVENTORY or LAB-DERIVED PARAMETERS) with Provenance {' or '.join(repr(p) for p in LAB_PROVENANCE)}, \
for the same process step, under this name or any clearly equivalent name, or when it follows from such values by an \
ALLOWED DERIVATION. A value with any other provenance (e.g. "Assumed", or none) is not LAB evidence. The TECHNOLOGY \
OVERVIEW gives context (product, functional unit, target scale), not LAB values.
- [CONSTANT]: a standard physical property of a named substance (heat capacity, density, enthalpy of vaporisation, ...). \
Always AVAILABLE: give the value and unit, and in `source` the substance and the standard reference.
- [DEFAULT=value]: a value fixed by the rule itself. Always AVAILABLE: use the stated value.
- [LITERATURE]: an external benchmark (industrial yield, specific energy, membrane flux, equipment design value, ...). \
AVAILABLE only if the value and its citation are present in the case evidence. Never look up, recall or cite \
literature yourself.
- [TARGET]: describes the industrial scale (scale factor, target output, industrial or target batch volume, target \
capacity). Never decides whether a rule is available. Report it as {MISSING!r} unless the case evidence states it.

ALLOWED DERIVATIONS (closed list; nothing else counts):
1. unit conversion within one quantity (e.g. min to h, L to m3, g to kg);
2. mass to volume and back, using a density stated in the evidence, or 1 kg/L for water and aqueous streams;
3. average power = energy / time, and the reverse;
4. the sum of values reported for the same process step;
5. a fraction or share of reported values (e.g. a mass fraction, a share of total electricity).
Whenever you derive a value, write the calculation in `derivation` as an equation: every operand with its unit and, \
in brackets, the sheet and row it comes from, then "=" and the result with its unit. Generic example (not from this \
case): "12.0 kWh (Process Inventory: P0X electricity) / 2.0 h (Lab-Derived Parameters: <stage> t) = 6.0 kW".

AMBIGUOUS EVIDENCE: an input is {AMBIGUOUS!r} only when two or more different values for it are reported in the \
evidence and the evidence does not say which one applies (e.g. the same parameter reported more than once for a step \
with different values): do not pick one; name the reported values in `note`. If only one value is reported but its \
context could be read in more than one way, the input is NOT ambiguous: use the reported value (status \
{AVAILABLE!r}) and describe the doubt in `note`. Never infer a further candidate value that is not reported.

INPUT STATUS: every input gets exactly one status: {AVAILABLE!r}, {MISSING!r} or {AMBIGUOUS!r}. For {AVAILABLE!r}, give \
value, unit and source (the sheet and row it came from, e.g. "Lab-Derived Parameters: Hydrolysis m_mix"); never invent, \
estimate or round a value beyond an allowed derivation.

A RULE IS AVAILABLE for a flow when (1) its `operations` include the flow's process step (or its scope is generic), \
(2) its `conditions` hold for this flow, and (3) every input tagged LAB, CONSTANT, DEFAULT or LITERATURE is \
{AVAILABLE!r}. TARGET inputs never count.
"""
