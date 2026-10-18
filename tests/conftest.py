"""Pytest bootstrap: load DSEM pure modules without Home Assistant.

``deye_smart_energy_manager/__init__.py`` imports homeassistant, which is
not installed in the dev environment. We register a stub package whose
``__path__`` points at the component directory so intra-package imports
(``from .model import ...``) resolve, while pure modules (model, prices,
optimizer, forecast) load without HA.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_PKG_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "deye_smart_energy_manager"
)

if "dsem" not in sys.modules:
    _pkg = types.ModuleType("dsem")
    _pkg.__path__ = [str(_PKG_DIR)]
    sys.modules["dsem"] = _pkg
