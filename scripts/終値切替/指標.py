"""固定23の数値銀行と公開30分チャネルを変更せず参照する。"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("終値切替の固定23指標", ROOT/"scripts/高安再開/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, Indicators, features, ChannelBank = BASE.W, BASE.Indicators, BASE.features, BASE.ChannelBank
SOURCE_FIELDS = BASE.SOURCE_FIELDS
