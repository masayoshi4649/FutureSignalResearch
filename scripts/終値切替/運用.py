"""固定23の単一建玉とA5・ATR距離・最低同値保護を参照する。"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("終値切替の固定23運用", ROOT/"scripts/高安再開/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
M, 切替状態, trail_parameters, replay = BASE.M, BASE.切替状態, BASE.trail_parameters, BASE.replay
