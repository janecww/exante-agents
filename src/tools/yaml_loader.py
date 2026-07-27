"""Generic YAML load/save helpers used across the project."""

from pathlib import Path

import yaml


def load_yaml(path: str | Path) -> dict:
    """Load a YAML file and return its contents as a dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not valid YAML.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"YAML file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse YAML file {path}: {e}") from e


def save_yaml(data: dict, path: str | Path) -> None:
    """Save a dict to a YAML file, creating parent directories as needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False, allow_unicode=True)
