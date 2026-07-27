"""Pydantic models mirroring src/schemas/technology.yaml."""

from pydantic import BaseModel, Field


class TechnologyInfo(BaseModel):
    """High-level description of the technology under assessment."""

    name: str | None = None
    type: str | None = None
    functional_unit: str | None = None
    description: str | None = None


class CurrentState(BaseModel):
    """Laboratory-scale state of the technology."""

    trl: int | None = None
    scale: str | None = None
    throughput: float | None = None


class TargetState(BaseModel):
    """Industrial-scale target state of the technology."""

    trl: int | None = None
    scale: str | None = None
    throughput: float | None = None


class InventoryFlow(BaseModel):
    """A single input or output flow of a process."""

    name: str | None = None
    value: float | None = None
    unit: str | None = None


class Process(BaseModel):
    """A single laboratory-scale process step in the technology workflow."""

    id: str | None = None
    name: str | None = None
    process_type: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    note: str | None = None
    inputs: list[InventoryFlow] = Field(default_factory=list)
    outputs: list[InventoryFlow] = Field(default_factory=list)


class Technology(BaseModel):
    """Top-level model corresponding to technology.yaml."""

    technology: TechnologyInfo
    current_state: CurrentState
    target_state: TargetState
    processes: list[Process] = Field(default_factory=list)
