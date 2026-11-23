"""版1を保持し、CCIを追加した版2の汎用表だけを独立生成する。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = HERE / "手法カタログ.json"
CATALOG = HERE / "手法カタログ_版2.json"
RENDERER = HERE / "設定結果レポート.py"
MASTER = ROOT / "docs/議論/手法と時間スケールの汎用表_版2.md"
OLD_MASTER = ROOT / "docs/議論/手法と時間スケールの汎用表.md"
CCI = ROOT / "docs/technical-analysis/指標/CCI.md"
DATE = "2026-11-05"
ADDITION = {
    "id": "I13",
    "name": "CCI",
    "category": "指標",
    "source": "docs/technical-analysis/指標/CCI.md",
    "additional_input": "入力Source（HLC3/Close等）・期間・同じ現在窓平均による平均絶対偏差。MD=0は無効",
}


def load_renderer() -> object:
    """版1の純粋な表・リンク描画関数を読み込む。

    引数: なし。RENDERER (Path) は読取専用の旧描画コード。
    返り値: object は読み込んだモジュール。旧mainや旧生成関数は呼ばない。
    """
    spec = importlib.util.spec_from_file_location("カタログ版2用の旧描画", RENDERER)
    if spec is None or spec.loader is None:
        raise RuntimeError("旧描画コードを読み込めない")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


G = load_renderer()


def load_catalog() -> dict:
    """版2を読み、版1の定義・順序・尺度の保存とI13だけの追加を確認する。

    引数: なし。BASE/CATALOG (Path) は版1/版2のJSON。
    返り値: dict は検査を通過した版2カタログ。不整合時はValueError。
    """
    base = json.loads(BASE.read_text(encoding="utf-8-sig"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
    if base.get("version") != 1 or len(base["methods"]) != 51 or len(base["scales"]) != 9:
        raise ValueError("版1は51手法・9尺度の固定正本でなければならない")

    # ----------------------------------------
    # 元の辞書と相対順序を保ち、I12の直後へI13だけを追加する。
    expected = json.loads(json.dumps(base, ensure_ascii=False))
    expected["version"] = 2
    location = next(index + 1 for index, method in enumerate(expected["methods"])
                    if method["id"] == "I12")
    expected["methods"].insert(location, ADDITION.copy())
    if catalog != expected:
        raise ValueError("版2は版1をそのまま保持してI13だけを追加する")
    ids = [method["id"] for method in catalog["methods"]]
    if len(ids) != 52 or len(set(ids)) != 52:
        raise ValueError("版2の52手法IDは一意でなければならない")
    for method in catalog["methods"]:
        if not (ROOT / method["source"]).is_file():
            raise ValueError(f"出典が存在しない：{method['source']}")
    return catalog


def matrix(catalog: dict, output: Path, settings: list[dict] | None = None) -> str:
    """版2のカタログを引数で渡して全手法・全尺度を描画する。

    引数: catalog (dict) は版2定義、output (Path) は出力先、settings (list[dict] | None) は設定。
    返り値: str はMarkdown表。旧モジュールのglobalは変更しない。
    """
    if catalog.get("version") != 2 or len(catalog["methods"]) != 52 or len(catalog["scales"]) != 9:
        raise ValueError("52手法・9尺度の版2カタログが必要")
    return G.matrix(catalog, output, settings)


def render(catalog: dict) -> str:
    """版2の未記入表と記録欄を組み立てる。

    引数: catalog (dict) は検査済み版2定義。
    返り値: str は版2汎用表の全文。既存試行の内容は生成しない。
    """
    text = f"# 手法と時間スケールの汎用表・版2\n\n作成日：{DATE}。カタログ版2。52手法×9尺度＝468組。\n\n"
    text += "版1の51手法ID・定義・既存順と9尺度を保持し、I13 CCIだけを追加した。"
    text += "版1のカタログ・汎用表・既存生成処理・過去の試行コピーは変更しない。\n\n"
    text += G.link(OLD_MASTER, MASTER, "版1の汎用表") + " / "
    text += G.link(CCI, MASTER, "追加したCCIの教科書") + " / "
    text += G.link(ROOT / "docs/議論/手法と時間スケールの記録方針.md", MASTER, "記録方針") + "\n\n"
    text += "版2を使う新しい試行では、カタログ版を明記して本表を `設定と結果.md` へコピーする。"
    text += "使用セルへ設定ID・短い閾値・複合評価IDを記し、未使用セルも残す。"
    text += "教科書の追加は採用・検証済みを意味せず、CCIの条件カードも未実行である。\n\n"
    text += "収録範囲は本リポジトリの教科書、価格・数量・板・関連系列と研究用のモデル・評価・保護。"
    text += "世界中の技法を網羅するものではない。時間尺度は計算に使う足であり、CCI20の20本という期間と区別する。"
    text += "セッション足はデイまたはナイトを1本とする足で、VWAPの起算点とは別。間引き間隔も時間足へ読み替えない。\n\n"
    text += "## 手法×時間スケール\n\n全セルは未設定・未検証。試行では未使用・未検証・データ不足・対象外を区別する。"
    text += "準備にだけ使うセルと値で採否を変えるセル、診断専用のセルも区別する。"
    text += "複合評価の成績を指標単独の効果としない。\n\n"
    text += matrix(catalog, MASTER)

    # ----------------------------------------
    # コピー後の記録欄は未設定であり、過去の結果を転記しない。
    text += "## 設定明細（コピー後に記入）\n"
    text += G.table(["設定ID", "手法ID・尺度", "役割", "計算期間・入力・初期化", "買い/売りの閾値・等号", "適用候補・複合評価", "実行状態・出典"],
                    [["S01", "未設定", "環境/位置/発動/準備/決済/保護/診断/評価", "未設定", "未設定", "R01", "未検証"]])
    text += "## 複合条件と結果（コピー後に記入）\n"
    text += G.table(["評価ID", "構成設定と入口・出口", "入力・対象期間", "分母・件数・日数・場数", "結果・費用・執行仮定", "不明・未約定・限界"],
                    [["R01", "未設定", "未設定", "未設定", "未検証", "未検証"]])
    text += "運用損益と先着率、原発動・純入口・実参加、学習・条件選択・固定後確認を分ける。"
    text += "結果を見て主要条件を変える場合は、新しい試行として固定し直す。\n\n"
    extras = [[method["id"], method["additional_input"]] for method in catalog["methods"]
              if method.get("additional_input")]
    text += "## 追加入力・定義の確認欄\n\n次は定義上の確認事項。入力の有無は試行で確認し、未使用をデータ不存在としない。\n"
    text += G.table(["手法ID", "必要な入力・確認"], extras)
    text += "## 独立生成と再現\n\n"
    text += "```powershell\nC:/Python314/python.exe -X utf8 scripts/レポート/カタログ版2.py\n"
    text += "C:/Python314/python.exe -X utf8 scripts/レポート/カタログ版2.py --check\n```\n\n"
    text += "生成先はこの版2汎用表だけ。JSONは版2の正本として読み、旧描画の `matrix(catalog, output, settings)` 等を引数付きで再用する。"
    text += "旧モジュールのglobalや生成先を書き換えず、旧main・既存試行の生成処理を実行しない。"
    text += "`--check` は表示の一致を確認し、ファイルを書き換えない。\n\n"
    text += G.provenance([BASE, CATALOG, RENDERER, Path(__file__).resolve(), CCI], MASTER)
    return text


def main() -> int:
    """版2表だけを生成するか、保存済み表との一致を確認する。

    引数: なし。CLIの--check (bool) は書込なしの照合を指定する。
    返り値: int は成功0、保存済み表が不一致なら1。
    """
    parser = argparse.ArgumentParser(description="版1を変更せずCCIを追加した版2表を独立生成する")
    parser.add_argument("--check", action="store_true", help="書き込まず、保存済み版2表との一致を確認する")
    arguments = parser.parse_args()
    old_paths = [BASE, RENDERER, OLD_MASTER]
    before = {path: G.sha(path) for path in old_paths}
    catalog = load_catalog()
    text = render(catalog)
    if arguments.check:
        if not MASTER.is_file() or MASTER.read_bytes() != text.encode("utf-8"):
            print("版2汎用表が未生成または現在の正本と不一致")
            return 1
    else:
        MASTER.write_text(text, encoding="utf-8", newline="\n")
    if before != {path: G.sha(path) for path in old_paths}:
        raise RuntimeError("版1の固定ファイルが実行中に変化した")
    print("版2：52手法×9尺度＝468組。版1の3固定ファイル不変、旧global変更なし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
