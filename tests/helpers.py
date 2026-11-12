"""Test helpers for loading the integration without importing Home Assistant."""

import importlib
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PATH = ROOT / "custom_components" / "renpho_rmsb01"
PACKAGE_NAME = "_renpho_rmsb01_test"

if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PACKAGE_PATH)]
    package.__package__ = PACKAGE_NAME
    sys.modules[PACKAGE_NAME] = package


def load_module(name: str):
    """Load one component module while bypassing the HA-facing __init__."""
    return importlib.import_module(f"{PACKAGE_NAME}.{name}")
