"""Pytest bootstrap: load DSEM pure modules without Home Assistant.

``deye_smart_energy_manager/__init__.py`` imports homeassistant, which is
not installed in the dev environment. We register a stub package whose
``__path__`` points at the component directory so intra-package imports
(``from .model import ...``) resolve, while pure modules (model, prices,
optimizer, forecast) load without HA.

``control.py`` additionally needs ``homeassistant.core`` and
``homeassistant.util.dt``; minimal stubs are registered so the guard
logic can be unit-tested with fake hass/coordinator objects.
"""
from __future__ import annotations

import sys
import types
from datetime import datetime, timezone
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

if "homeassistant" not in sys.modules:
    _ha = types.ModuleType("homeassistant")
    _ha.__path__ = []
    _ha_core = types.ModuleType("homeassistant.core")
    _ha_core.HomeAssistant = object  # annotation-only in control.py
    _ha_util = types.ModuleType("homeassistant.util")
    _ha_dt = types.ModuleType("homeassistant.util.dt")
    _ha_dt.now = lambda: datetime.now(timezone.utc)
    _ha_dt.utcnow = lambda: datetime.now(timezone.utc)
    _ha_util.dt = _ha_dt
    sys.modules["homeassistant"] = _ha
    sys.modules["homeassistant.core"] = _ha_core
    sys.modules["homeassistant.util"] = _ha_util
    sys.modules["homeassistant.util.dt"] = _ha_dt
