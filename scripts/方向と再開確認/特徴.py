"""固定60の全46特徴をそのまま参照し、62では入力を増減しない。"""

from copy import deepcopy
import importlib.util
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "波の区間分離/特徴.py"
SPEC = importlib.util.spec_from_file_location("方向再開が参照する固定60特徴", SOURCE)
F60 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F60)
FEATURES = deepcopy(F60.FEATURES)
RULES = deepcopy(F60.RULES)
SOURCE_FIELDS = F60.SOURCE_FIELDS


def extract(slot: dict, frames3: list[dict]) -> dict:
    """同じ公開済み入力を固定60へ渡し、全辞書を深い複写で返す。

    引数: slot(dict)は定時判断、frames3(list[dict])は既存の公開3分足。
    返り値: dictは旧60と完全同値。新情報・新しい準備除外・価格機械の変更はない。
    """
    return deepcopy(F60.extract(slot, frames3))
