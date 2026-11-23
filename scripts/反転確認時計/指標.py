"""固定25の全数値銀行と鏡像SARを変更せず読み取り再用する。"""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("反転確認時計の固定25指標", ROOT/"scripts/SAR持続/指標.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
W, Indicators, features, ChannelBank, SARBank = BASE.W, BASE.Indicators, BASE.features, BASE.ChannelBank, BASE.SARBank
SOURCE_FIELDS = BASE.SOURCE_FIELDS
