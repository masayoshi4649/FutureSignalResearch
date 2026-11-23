"""固定21のnative不使用・A5保護をB0/C0にもそのまま適用する。"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("高安再開の固定21運用", ROOT/"scripts/異種発動/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
M, 切替状態, trail_parameters, replay = BASE.M, BASE.切替状態, BASE.trail_parameters, BASE.replay
