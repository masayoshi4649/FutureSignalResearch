"""版4を保持し、Force Indexを追加した版5の表を生成する。"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE/"手法カタログ_版4.json"
CATALOG = HERE/"手法カタログ_版5.json"
MASTER = ROOT/"docs/議論/手法と時間スケールの汎用表_版5.md"
TEXTBOOK = ROOT/"docs/technical-analysis/指標/ForceIndex.md"
ADDITION = {'id': 'V07', 'name': 'Force Index（価格変化×数量の平滑）', 'category': '数量由来の指標', 'source': 'docs/technical-analysis/指標/ForceIndex.md', 'additional_input': '確定終値差×整合する観測区間数量とEMA。期間/種/同場連続性/数量完全・0量と欠測/公開時点を固定し、実売買側フローと区別'}
SPEC = importlib.util.spec_from_file_location("カタログ版5の旧純描画", HERE/"設定結果レポート.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def load_catalog() -> dict:
    """版4をそのまま保持したV07だけの追加を検査する。

    引数: なし。
    返り値: dictは55手法・9尺度の版5。旧版を更新しない。
    """
    base = json.loads(BASE.read_text(encoding="utf-8"))
    expected = json.loads(json.dumps(base, ensure_ascii=False))
    expected["version"] = 5
    where = next(i+1 for i, row in enumerate(expected["methods"]) if row["id"] == "V06")
    expected["methods"].insert(where, ADDITION)
    value = json.loads(CATALOG.read_text(encoding="utf-8"))
    if value != expected or len(value["methods"]) != 55 or len(value["scales"]) != 9:
        raise ValueError("版5は版4を保持したV07だけの追加です")
    return value


def matrix(catalog: dict, output: Path, settings: list[dict] | None = None) -> str:
    """版5の全手法・全尺度を旧純描画へ明示引数で渡す。

    引数: catalog(dict)は版5、output(Path)は出力先、settings(list[dict]|None)は使用設定。
    返り値: strは55行・9尺度のMarkdown。旧globalを変更しない。
    """
    if catalog["version"] != 5 or len(catalog["methods"]) != 55:
        raise ValueError("版5の55手法が必要です")
    return G.matrix(catalog, output, settings)


def render(catalog: dict) -> str:
    """未設定表と再利用する記録欄を組み立てる。

    引数: catalog(dict)は検査済み版5。
    返り値: strは汎用表全文。試行の採用・成績を含めない。
    """
    text = "# 手法と時間スケールの汎用表・版5\n\n作成日：2026-11-06。55手法×9尺度＝495組。\n\n"
    text += "版4の54手法・9尺度・順序を保持し、V07 Force Indexだけを追加した。版1〜版4と過去の試行コピーは変更しない。\n\n"
    text += G.link(ROOT/"docs/議論/手法と時間スケールの汎用表_版4.md", MASTER, "版4の表")+" / "+G.link(TEXTBOOK, MASTER, "Force Indexの教材")+"\n\n"
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
    text += "## 再現\n\n```powershell\nC:/Python314/python.exe -X utf8 scripts/レポート/カタログ版5.py\nC:/Python314/python.exe -X utf8 scripts/レポート/カタログ版5.py --check\n```\n\n生成先は版5表だけ。--checkは保存済み表の一致だけを確認する。\n\n"
    return text+G.provenance([BASE, CATALOG, HERE/"設定結果レポート.py", Path(__file__), TEXTBOOK], MASTER)


def main() -> None:
    """版5だけを生成するか、保存済み表との一致を検査する。

    引数: なし。CLIは--check。
    返り値: None。不一致は例外。
    """
    parser = argparse.ArgumentParser(description="版5の55手法と9尺度の表")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    value = render(load_catalog())
    if args.check:
        if MASTER.read_text(encoding="utf-8") != value:
            raise ValueError("版5表に差")
    else:
        MASTER.write_text(value, encoding="utf-8")
    print("版5の55手法・9尺度を確認しました")


if __name__ == "__main__":
    main()
