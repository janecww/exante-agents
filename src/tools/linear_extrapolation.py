"""Linear extrapolation calculation, per the tier-3 "linear extrapolation"
methods in `src/skills/scaleup_decision_framework.xlsx`
(REACT-T3/SOLV-T3/CAT-T3/HEAT-T3/ENER-T3).

This module is a standalone, deterministic calculation utility, called
from `src.prompts.estimation_recommendation_prompt` to pre-compute
tier-3 applicability before the LLM ever sees an inventory (see
`_attach_linear_extrapolation`); it performs no LLM reasoning itself.

Concept
-------

The laboratory and industrial cases can share the same functional unit
even though their physical production scales differ enormously (e.g. a
lab batch vs. continuous industrial production). Linear extrapolation
assumes specific consumption -- input per unit of product -- is
constant across that scale difference; it is a screening assumption,
not a claim that industrial equipment behaves identically to
laboratory equipment (see each method's `limitations` in the knowledge
base for where that assumption is known to break down, e.g. energy,
heat, mixing).

Given that assumption, there are three calculation bases, chosen
deterministically from which raw inputs are available -- never
invented, never hardcoded as a fallback of 1, and Tier 3 is never
treated as inapplicable merely because a production output is unknown:

- `derived_from_outputs`: both `laboratory_output` and
  `industrial_output` (physical production quantities, e.g. kg
  product/batch) are known. `production_scale_factor =
  industrial_output / laboratory_output` is a genuine physical
  production ratio, used to scale the batch-based laboratory quantity.
- `unchanged_specific_consumption`: a derived `production_scale_factor`
  cannot be calculated (either output is unknown), but Tier 3 remains
  applicable: the assumption is that laboratory-specific consumption
  per functional unit stays unchanged at industrial scale. This basis
  needs only the laboratory input quantity itself and a defined
  functional unit (`functional_unit_defined`) -- it does NOT require
  `laboratory_output` or `industrial_output`:
    - if `laboratory_output` is known, the laboratory input is
      normalized by it (`laboratory_input_value / laboratory_output`)
      for a more precise per-functional-unit figure;
    - if `laboratory_output` is unknown, the raw laboratory input
      value itself is assumed to already approximate the input
      required per functional unit -- a weaker, explicitly logged
      assumption layered on top of "unchanged specific consumption",
      never silently treated as equivalent to a derived factor.
- `already_normalized_to_FU`: the laboratory inventory is already
  reported per functional unit (e.g. "3.16 kg starch/kg SNC"); no
  batch/output conversion is needed at all.

Only when the laboratory input cannot be normalized by any of the
above -- `laboratory_output` is unknown AND the case defines no
functional unit at all to anchor the unchanged-specific-consumption
assumption -- is the result `unavailable`, with the missing information
reported, never invented. Every result's `explanation` distinguishes
"a derived production scale factor could not be calculated" from
"Tier 3 remains applicable" so a caller (or an LLM reading it) can
never conflate the two into a contradictory statement such as
recommending a tier-3 method while also describing it as inapplicable.

All raw scale-up inputs (`laboratory_output`, `industrial_output`,
`functional_unit_defined`, whether an inventory is already
per-functional-unit) are expected to come from the case's own data
(e.g. `Technology.current_state.throughput` /
`Technology.target_state.throughput` / `Technology.technology.functional_unit`
in `laboratory_case_workbook.xlsx`) -- this module never hardcodes a
case-specific value itself.
"""

from dataclasses import dataclass

DERIVED_FROM_OUTPUTS = "derived_from_outputs"
UNCHANGED_SPECIFIC_CONSUMPTION = "unchanged_specific_consumption"
ALREADY_NORMALIZED_TO_FU = "already_normalized_to_FU"
UNAVAILABLE = "unavailable"

_MISSING_LABORATORY_OUTPUT_OR_FUNCTIONAL_UNIT = (
    "laboratory production output (or, failing that, a defined functional unit)"
)


@dataclass
class LinearExtrapolationResult:
    """The result of applying linear extrapolation to one inventory flow.

    `industrial_input_per_functional_unit` is `None` only when `basis`
    is `UNAVAILABLE`. `production_scale_factor` is populated only when
    `basis` is `DERIVED_FROM_OUTPUTS` (or, incidentally, when
    `ALREADY_NORMALIZED_TO_FU` happens to have both outputs available
    as context) -- it is genuinely inapplicable, not just unknown, for
    `UNCHANGED_SPECIFIC_CONSUMPTION` (never defaulted to 1 or any other
    placeholder). `industrial_input_batch` is populated only when a
    `production_scale_factor` was actually used to scale the value.
    """

    basis: str
    industrial_input_per_functional_unit: float | None
    explanation: str
    production_scale_factor: float | None = None
    laboratory_input_per_functional_unit: float | None = None
    industrial_input_batch: float | None = None
    missing_information: str | None = None


def compute_production_scale_factor(
    laboratory_output: float | None, industrial_output: float | None
) -> float | None:
    """The physical production ratio industrial_output / laboratory_output.

    Returns `None` -- never a placeholder like 1 -- whenever either
    value is unavailable or `laboratory_output` is zero (which would
    make the ratio undefined). This is the *only* function that
    computes this ratio; it must never be reimplemented or
    approximated elsewhere.
    """
    if laboratory_output is None or industrial_output is None:
        return None
    if laboratory_output == 0:
        return None
    return industrial_output / laboratory_output


def apply_linear_extrapolation(
    laboratory_input_value: float,
    *,
    laboratory_output: float | None = None,
    industrial_output: float | None = None,
    already_per_functional_unit: bool = False,
    functional_unit_defined: bool = False,
) -> LinearExtrapolationResult:
    """Apply linear extrapolation to one laboratory inventory value.

    Args:
        laboratory_input_value: The laboratory quantity to transfer --
            either a per-batch value (e.g. 3.16 kg starch/batch) or,
            if `already_per_functional_unit` is True, already a
            per-functional-unit value (e.g. 3.16 kg starch/kg SNC).
        laboratory_output: The laboratory process's physical production
            output (e.g. kg product/batch), if known. Ignored when
            `already_per_functional_unit` is True. Not required for
            `UNCHANGED_SPECIFIC_CONSUMPTION`.
        industrial_output: The industrial process's physical production
            output, in the same quantity as `laboratory_output`, if
            known. Ignored when `already_per_functional_unit` is True.
            Not required for `UNCHANGED_SPECIFIC_CONSUMPTION`.
        already_per_functional_unit: Whether `laboratory_input_value`
            is already reported per functional unit (see
            `ALREADY_NORMALIZED_TO_FU`), rather than per batch.
        functional_unit_defined: Whether the case defines a functional
            unit (e.g. `Technology.technology.functional_unit` is
            populated). Only consulted when `laboratory_output` is
            unknown, to anchor the unchanged-specific-consumption
            assumption; ignored otherwise.

    Returns:
        A `LinearExtrapolationResult` recording which basis applied,
        the resulting per-functional-unit industrial value (or `None`
        only if genuinely `UNAVAILABLE`), and -- when derived from
        known outputs -- the production scale factor and industrial
        batch quantity as supporting, auditable detail.
    """
    if already_per_functional_unit:
        return LinearExtrapolationResult(
            basis=ALREADY_NORMALIZED_TO_FU,
            industrial_input_per_functional_unit=laboratory_input_value,
            laboratory_input_per_functional_unit=laboratory_input_value,
            production_scale_factor=compute_production_scale_factor(
                laboratory_output, industrial_output
            ),
            explanation=(
                "Laboratory inventory is already reported per functional "
                "unit; transferred to industrial scale unchanged."
            ),
        )

    scale_factor = compute_production_scale_factor(laboratory_output, industrial_output)
    if scale_factor is not None:
        laboratory_input_per_fu = laboratory_input_value / laboratory_output
        return LinearExtrapolationResult(
            basis=DERIVED_FROM_OUTPUTS,
            industrial_input_per_functional_unit=laboratory_input_per_fu,
            laboratory_input_per_functional_unit=laboratory_input_per_fu,
            production_scale_factor=scale_factor,
            industrial_input_batch=laboratory_input_value * scale_factor,
            explanation=(
                "Production scale factor derived from known laboratory and "
                "industrial production outputs, and used to scale the "
                "batch-based laboratory quantity."
            ),
        )

    # A derived production scale factor cannot be calculated (industrial
    # output is unknown, laboratory output is unknown, or both) -- but
    # Tier 3 is NOT thereby inapplicable. The unchanged-specific-
    # consumption assumption only needs the laboratory input quantity
    # itself and a defined functional unit, not the raw production
    # outputs; it is deliberately distinguished below from "a scale
    # factor could not be derived" so the two are never conflated into
    # a contradictory statement.
    if laboratory_output is not None:
        laboratory_input_per_fu = laboratory_input_value / laboratory_output
        return LinearExtrapolationResult(
            basis=UNCHANGED_SPECIFIC_CONSUMPTION,
            industrial_input_per_functional_unit=laboratory_input_per_fu,
            laboratory_input_per_functional_unit=laboratory_input_per_fu,
            explanation=(
                "A derived production scale factor cannot be calculated "
                "because the industrial production output is unavailable. "
                "Tier 3 remains applicable under the unchanged-specific-"
                "consumption assumption: laboratory-specific consumption "
                "per functional unit is assumed unchanged at industrial "
                "scale."
            ),
        )

    if functional_unit_defined:
        return LinearExtrapolationResult(
            basis=UNCHANGED_SPECIFIC_CONSUMPTION,
            industrial_input_per_functional_unit=laboratory_input_value,
            laboratory_input_per_functional_unit=laboratory_input_value,
            explanation=(
                "A derived production scale factor cannot be calculated "
                "because the laboratory production output is unavailable, "
                "so the laboratory input cannot be normalized against a "
                "known batch yield. Tier 3 remains applicable under the "
                "unchanged-specific-consumption assumption: the recorded "
                "laboratory input quantity is assumed to already "
                "approximate the input required per functional unit, and "
                "that consumption is assumed unchanged at industrial "
                "scale."
            ),
        )

    return LinearExtrapolationResult(
        basis=UNAVAILABLE,
        industrial_input_per_functional_unit=None,
        explanation=(
            "Linear extrapolation cannot normalize this batch-based "
            "inventory to the functional unit: the laboratory production "
            "output is unavailable, and the case defines no functional "
            "unit to anchor the unchanged-specific-consumption assumption "
            "instead."
        ),
        missing_information=_MISSING_LABORATORY_OUTPUT_OR_FUNCTIONAL_UNIT,
    )
