"""69の全定時枠・60特徴・旧即時教師と新条件線を固定保存物へ接続する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = ROOT / "study/00069_条件入口に合わせて技法群の教師を作る"
WORK = ROOT / "work/条件入口の教師/00069"
PREFLIGHT = ROOT / "work/条件入口の教師/入力接続確認.json"
LEDGER = ROOT / "work/条件発動前の否定/68完了記録.json"
LEDGER_SHA = "693bc60f329efa2ec2810fee9f77a4f77140247373459b361ceed17108ef294e"


def load(path: Path, name: str):
    """旧globalを書き換えずに固定された純関数を読む。

    引数: path(Path)は入力コード、name(str)は固有のmodule名。
    返り値: ModuleTypeは読込結果。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


P65 = load(HERE.parent / "現在状態と量価格/検証.py", "条件教師69の固定65入力")
P68 = load(HERE.parent / "条件発動前の否定/検証.py", "条件教師69の固定68入力")
C, P, O, F = P65.C, P65.P, P65.O, P65.F
fingerprint = P68.fingerprint


def pure_for(slot: dict, feature: dict, side: int, policy: str = "独立69") -> dict:
    """全定時の一方向を独立測定の純条件候補へ写す。

    引数: slot/feature(dict)は当時入力、side(int)は±1、policy(str)は識別。
    返り値: dictは条件線と先着へ接続する候補。DI同値は測定用の順行仮置。
    """
    if type(side) is not int or side not in (-1, 1) or not feature["ready"]:
        raise ValueError("独立候補は準備済みの±1のみ")
    background = feature["background_direction"]
    return {**{key: slot[key] for key in ("session", "slot_id", "scheduled", "time", "line")},
        "policy": policy, "side": side, "role": "順行" if background in (0, side) else "反転",
        "ready": True, "reason": "採否と独立した全定時条件測定", "atr": feature["atr"], "D": feature["D"],
        "feature": feature}


def verified_inputs() -> tuple:
    """68完了物と65の全特徴を照合し、全ready枠へ条件線を結合する。

    引数: なし。
    返り値: tupleはentries/blocks/prepared/immediate/conditions/旧N運用/照合数。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("68完了台帳の指紋差")
    ledger = C.read_json(LEDGER)
    for relative, expected in ledger["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("68完了物の変更:" + relative)
    entries, blocks, prepared, baseline, measured, _, inherited = P65.verified_saved_inputs()
    if len(entries) != 66 or any(entry["symbol"] != "NK225" for entry in entries):
        raise ValueError("既使用NK225の66場だけを対象にする")
    old = P.read_rows(ROOT / "work/条件発動前の否定/00068/定時判断と運用.jsonl.gz")
    if len(old) != 92 or {block["policy"] for block in old} != {"N0", "N1"}:
        raise ValueError("68の保存92運用が必要")
    checks = {"旧68完了不変": len(ledger["成果物SHA256"]), "旧68特徴保存一致": 0,
        "旧68採用条件一致": 0, "全ready条件線": 0, "即時教師接続": 0}
    for block in old:
        for slot in block["slots"]:
            if prepared[slot["slot_id"]] != slot["feature"]:
                raise ValueError("旧68と全60特徴が違う")
            checks["旧68特徴保存一致"] += 1
    _, sources = C.inputs()
    frames = {source["session"]: source["frames3"] for source in sources}
    conditions = {}
    for entry in entries:
        block = blocks[entry["session"]]
        expected = 25 if entry["session"].endswith("Day") else 49
        if len(block["slots"]) != expected:
            raise ValueError("全予定枠数が違う")
        for slot in block["slots"]:
            feature = prepared[slot["slot_id"]]
            if not feature["ready"]:
                continue
            sides = [pure_for(slot, feature, side) for side in (1, -1)]
            pair = [P68.condition_for(item, frames[entry["session"]]) for item in sides]
            if pair[0] != pair[1]:
                raise ValueError("売買の条件出典が異なる")
            conditions[slot["slot_id"]] = pair[0]
            checks["全ready条件線"] += 1
            for side in (1, -1):
                prior = measured[slot["slot_id"], side]
                if prior["barrier"] != baseline[slot["slot_id"], side]:
                    raise ValueError("旧即時障壁の保存接続差")
                if prior["features"] != feature["vectors"][str(side)]:
                    raise ValueError("旧回収の60特徴接続差")
                checks["即時教師接続"] += 1
    for block in old:
        for identity, condition in block["conditions"].items():
            if condition != conditions[identity]:
                raise ValueError("旧68採用分の条件線差")
            checks["旧68採用条件一致"] += 1
    return entries, blocks, prepared, measured, conditions, old, checks


def preflight() -> None:
    """結果を計測する前に入力の数と指紋を保存する。

    引数: なし。
    返り値: None。市場再生・新教師測定・学習・新予測は行わない。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("69入力接続確認は既存")
    entries, blocks, prepared, immediate, conditions, _, checks = verified_inputs()
    ready = sum(feature["ready"] for feature in prepared.values())
    payload = {"試行": 69, "接続成功": True, "検査": checks,
        "全66場既使用": True, "場数": len(entries), "全予定枠": len(prepared),
        "準備済み枠": ready, "新独立測定予定方向": ready * 2,
        "全特徴SHA256": fingerprint(prepared), "全条件SHA256": fingerprint(conditions),
        "全予定判断SHA256": fingerprint({name: block["slots"] for name, block in blocks.items()}),
        "旧即時測定数": len(immediate), "旧68完了台帳SHA256": C.sha(LEDGER),
        "前巡分類": "進捗。68の92運用と独立照合、外部2資料、失った成功の診断を完了",
        "原板追加読取": False, "市場再生": False, "新fit": False,
        "条件出典": "68と同じ当時最新完全公開3分SOURCE。ready全枠で売買同値"}
    C.write_json(PREFLIGHT, payload)
    print(json.dumps({key: payload[key] for key in ("接続成功", "全予定枠", "準備済み枠", "新独立測定予定方向", "検査")}, ensure_ascii=False))


if __name__ == "__main__":
    preflight()
