"""固定21の指標銀行を複製せず読み取り再利用する。"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("局面変化の固定21指標", ROOT/"scripts/異種発動/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, Indicators, features = BASE.W, BASE.Indicators, BASE.features
