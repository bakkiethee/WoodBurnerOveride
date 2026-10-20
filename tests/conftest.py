"""Load the pure-Python modules without importing Home Assistant.

The package ``__init__`` needs Home Assistant, so the tests register a bare package
object that only points at the directory.
"""

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "custom_components" / "wood_stove_mode"

# With Home Assistant installed the real package imports normally and the
# integration tests run too; without it only the pure-Python tests can run.
HAS_HA = importlib.util.find_spec("homeassistant") is not None

if HAS_HA:
    pytest_plugins = "pytest_homeassistant_custom_component"
else:
    for name, path in (
        ("custom_components", ROOT / "custom_components"),
        ("custom_components.wood_stove_mode", PKG_DIR),
    ):
        if name not in sys.modules:
            module = types.ModuleType(name)
            module.__path__ = [str(path)]
            sys.modules[name] = module
