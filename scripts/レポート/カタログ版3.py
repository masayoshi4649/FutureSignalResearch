"""版2を保持し、線形回帰と決定係数を追加した版3の表を生成する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE/"手法カタログ_版2.json"
CATALOG = HERE/"手法カタログ_版3.json"
MASTER = ROOT/"docs/議論/手法と時間スケールの汎用表_版3.md"
TEXTBOOK = ROOT/"docs/technical-analysis/指標/線形回帰と決定係数.md"
ADDITION = {"id": "I14", "name": "線形回帰と決定係数（OLS・R²）", "category": "指標",
    "source": "docs/technical-analysis/指標/線形回帰と決定係数.md",
    "additional_input": "確定価格・当足の包含・期間・切片・欠枠/セッション・公開時点。傾き方向と標本内R²を分け、全同値のR²は未定義"}
SPEC = importlib.util.spec_from_file_location("カタログ版3の旧純描画", HERE/"設定結果レポート.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def load_catalog() -> dict:
    """版2をそのまま保持したI14だけの追加を検査する。

    引数: なし。
    返り値: dictは53手法・9尺度の版3。旧版を更新しない。
    """
    base = json.loads(BASE.read_text(encoding="utf-8"))
    expected = json.loads(json.dumps(base, ensure_ascii=False))
    expected["version"] = 3
    where = next(i+1 for i, row in enumerate(expected["methods"]) if row["id"] == "I13")
    expected["methods"].insert(where, ADDITION)
    value = json.loads(CATALOG.read_text(encoding="utf-8"))
    if value != expected or len(value["methods"]) != 53 or len(value["scales"]) != 9:
        raise ValueError("版3は版2を保持したI14だけの追加です")
    return value


def matrix(catalog: dict, output: Path, settings: list[dict] | None = None) -> str:
    """版3の全手法・全尺度を旧純描画へ明示引数で渡す。

    引数: catalog(dict)は版3、output(Path)は出力先、settings(list[dict]|None)は使用設定。
    返り値: strは53行・9尺度のMarkdown。旧globalを変更しない。
    """
    if catalog["version"] != 3 or len(catalog["methods"]) != 53:
        raise ValueError("版3の53手法が必要です")
    return G.matrix(catalog, output, settings)


def render(catalog: dict) -> str:
    """未設定表と再利用する記録欄を組み立てる。

    引数: catalog(dict)は検査済み版3。
    返り値: strは汎用表全文。試行の採用・成績を含めない。
    """
    text = "# 手法と時間スケールの汎用表・版3\n\n作成日：2026-11-05。53手法×9尺度＝477組。\n\n"
    text += "版2の52手法・9尺度・順序を保持し、I14 線形回帰と決定係数だけを追加した。版1・版2と過去の試行コピーは変更しない。\n\n"
    text += G.link(ROOT/"docs/議論/手法と時間スケールの汎用表_版2.md", MASTER, "版2の表")+" / "+G.link(TEXTBOOK, MASTER, "線形回帰と決定係数の教材")+"\n\n"
    text += "新試行ではカタログ版を明記し、本表を設定と結果.mdへコピーする。使用セルに設定ID・短い閾値・複合評価IDを記す。"
    text += "未使用・未検証・データ不足・対象外、準備のみ・値で選別・診断を区別する。教材追加は収益や採用の証明ではない。\n\n"
    text += "## 手法×時間スケール\n\n全セルは未設定・未検証。足の時間尺度と計算期間・間引き間隔・VWAPの起算点を区別する。複合成績を指標単独の効果にしない。\n\n"
    text += matrix(catalog, MASTER)
    text += "## 設定明細（コピー後に記入）\n\n"
    text += G.table(["設定ID", "手法ID・尺度", "役割", "計算期間・入力・初期化", "買い/売りの閾値・等号", "適用候補・複合評価", "実行状態・出典"], [["S01", "未設定", "未設定", "未設定", "未設定", "R01", "未検証"]])
    text += "## 複合条件と結果（コピー後に記入）\n\n"
    text += G.table(["評価ID", "構成設定と入口・出口", "入力・対象期間", "分母・件数・日数・場数", "結果・費用・執行仮定", "不明・未約定・限界"], [["R01", "未設定", "未設定", "未設定", "未検証", "未検証"]])
    text += "## 追加入力・定義の確認欄\n\n"
    text += G.table(["手法ID", "必要な入力・確認"], [[r["id"], r["additional_input"]] for r in catalog["methods"] if r.get("additional_input")])
    text += "## 再現\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/レポート/カタログ版3.py\nC:/Python314/python.exe -X utf8 scripts/レポート/カタログ版3.py --check\n```\n\n生成先は版3表だけ。--checkは保存済み表の一致だけを確認する。\n\n"
    return text+G.provenance([BASE, CATALOG, HERE/"設定結果レポート.py", Path(__file__), TEXTBOOK], MASTER)


def main() -> None:
    """版3だけを生成するか、保存済み表との一致を検査する。

    引数: なし。CLIは--check。
    返り値: None。不一致は例外。
    """
    parser = argparse.ArgumentParser(description="版3の53手法と9尺度の表")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = render(load_catalog())
    if args.check:
        if MASTER.read_text(encoding="utf-8") != value:
            raise ValueError("版3表に差")
    else:
        MASTER.write_text(value, encoding="utf-8")
    print("版3の53手法・9尺度を確認しました")


if __name__ == "__main__":
    main()
