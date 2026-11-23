"""71の同じ61特徴・条件教師を、約定支持を分割時に扱う比較へ接続する。"""

from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """固定コードを固有名で読み込む。

    引数: path(Path)は対象、name(str)は固有module名。
    返り値: ModuleTypeは読込結果。旧大域値を変更しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PREVIOUS_PATH = HERE.parent / "取得位置と支持/検証.py"
PREVIOUS_SHA = "5bb078e172c526f17d1d69471a430b7b942ae55b2f3cac1e041214eab389478f"
if hashlib.sha256(PREVIOUS_PATH.read_bytes()).hexdigest() != PREVIOUS_SHA:
    raise ValueError("固定71主コードの指紋が不一致")
PREVIOUS = load(PREVIOUS_PATH, "支持分割72の固定71")
I71 = PREVIOUS.I
I69, C, P, O, F = I71.I69, I71.C, I71.P, I71.O, I71.F
STUDY = ROOT / "study/00072_分割候補から約定支持を確保する"
PARENT = ROOT / "work/支持を満たす技法分割"
WORK = PARENT / "00072"
PREFLIGHT = PARENT / "入力接続確認.json"
OLD, OLDWORK = PREVIOUS.STUDY, PREVIOUS.WORK
SOURCE, SOURCEWORK = PREVIOUS.SOURCE, PREVIOUS.SOURCEWORK
LEDGER = PREVIOUS.PARENT / "71完了記録.json"
LEDGER_SHA = "c531d05db0e461f06a596882e6ae449c43fde8d712172e87072ef7650daf2c84"
FEATURES, POSITION_META, IDENTITY = deepcopy(I71.FEATURES), deepcopy(I71.POSITION_META), I71.IDENTITY
RULES = {"入力": "71と同じ61特徴・同69C条件教師・同共通可知pair。C/S間の追加列・追加除外なし",
    "固定参照": "71の成功台帳246対象を照合し、旧71G0/G1判断に含まれる全特徴と同値を確認",
    "旧60投影": "固定71入力の旧60特徴・当時BBO・g算術と入力公開時計の検査をそのまま再用",
    "追加取得": "市場入力・未予約11月5日Day・FutureAlgorithmResearchの追加取得なし",
    "対照": "旧71G0/G1の保存判断・入口先着・一枚運用を再集計。旧Gを新Cの学習再現条件にしない"}


def verify_previous() -> dict:
    """71の完了台帳と成功証拠を全対象で確認する。

    引数: なし。
    返り値: dictは不変の71結果。市場・学習を実行しない。
    """
    if C.sha(LEDGER) != LEDGER_SHA:
        raise ValueError("71完了台帳の指紋が不一致")
    for relative, expected in C.read_json(LEDGER)["成果物SHA256"].items():
        if C.sha(ROOT / relative) != expected:
            raise ValueError("71完了物が変化:" + relative)
    proof = C.read_json(OLD / "保存物確認.json")
    done = C.read_json(OLDWORK / "実行完了.json")
    if (not proof["全件一致"] or proof["不一致数"]
            or C.sha(OLD / "結果.json") != proof["結果SHA256"]
            or proof["結果SHA256"] != done["結果SHA256"]):
        raise ValueError("71の成功証拠が不一致")
    return C.read_json(OLD / "結果.json")


def verified_inputs() -> tuple:
    """同じ61特徴と保存参考Gを、固定された過去入力から結合する。

    引数: なし。
    返り値: tupleはentries/blocks/base60/extended61/immediate/conditions/measured/G保存blocks/checks。
        新しい足・ラベル・約定の計測と学習は行わない。
    """
    verify_previous()
    entries, blocks, base, extended, immediate, conditions, measured, _, old_checks = I71.verified_inputs()
    prior = C.read_json(I71.PREFLIGHT)
    if old_checks != prior["検査"]:
        raise ValueError("71入力接続確認の再現差")
    saved = [row for row in P.read_rows(OLDWORK / "定時判断と運用.jsonl.gz") if row["policy"] in ("G0", "G1")]
    if len(saved) != 92 or len({(row["session"], row["policy"]) for row in saved}) != 92:
        raise ValueError("71のG保存92運用が必要")
    comparisons = 0
    for block in saved:
        for slot in block["slots"]:
            if slot["feature"] != extended[slot["slot_id"]]:
                raise ValueError("旧71G保存特徴と再構成61列の差")
            comparisons += 1
    checks = {"71の入力検査": old_checks, "旧G保存運用": len(saved), "旧G保存特徴照合": comparisons,
        "全予定枠": len(extended), "準備済み枠": sum(item["ready"] for item in extended.values()),
        "特徴数": len(FEATURES), "同一61特徴を両政策へ使用": True,
        "61特徴SHA256": I69.fingerprint(extended), "条件SHA256": I69.fingerprint(conditions),
        "参照独立方向": len(measured)}
    if checks["全予定枠"] != 2442 or checks["準備済み枠"] != 2046 or checks["参照独立方向"] != 4092:
        raise ValueError("72の入力範囲が71と異なる")
    return entries, blocks, base, extended, immediate, conditions, measured, saved, checks


# ----------------------------------------
def preflight() -> dict:
    """新学習前に旧入力との全同値を記録する。

    引数: なし。
    返り値: dictは入力接続の確認とSHA。既存ファイルの上書きを拒否する。
    """
    if PREFLIGHT.exists():
        raise FileExistsError("72入力接続確認は保存済み")
    *_, checks = verified_inputs()
    result = {"試行": 72, "接続成功": True, "入力コードSHA256": C.sha(HERE / "入力.py"),
        "旧71台帳SHA256": LEDGER_SHA, "検査": checks, "新fit": 0, "新市場再生": 0}
    C.write_json(PREFLIGHT, result)
    return result


if __name__ == "__main__":
    import json
    print(json.dumps(preflight(), ensure_ascii=False), flush=True)
