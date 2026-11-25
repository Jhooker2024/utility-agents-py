"""The settings in `config.yml`, read once. A test changes a value for its own duration."""

from pathlib import Path

import yaml

PACKAGE = Path(__file__).parent

settings: dict = yaml.safe_load((PACKAGE / "config.yml").read_text())
