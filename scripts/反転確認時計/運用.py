"""固定25の単一建玉・A5・最低同値保護と固定役割を再用する。"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("反転確認時計の固定25運用", ROOT/"scripts/SAR持続/運用.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
M, 切替状態, trail_parameters, replay = BASE.M, BASE.切替状態, BASE.trail_parameters, BASE.replay
