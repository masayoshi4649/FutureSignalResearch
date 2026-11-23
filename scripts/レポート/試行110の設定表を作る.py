"""110の設定定義から版6の全セルと候補別の条件・結果欄を作る。"""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / "study/00110_三時間軸の有効状態と値幅を残す必須保護"
OUTPUT = TRIAL / "設定と結果.md"
SPEC = importlib.util.spec_from_file_location("試行110の版6描画", ROOT / "scripts/レポート/カタログ版6.py")
CAT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CAT
SPEC.loader.exec_module(CAT)


def render() -> str:
    """設定定義と候補を検査し、未実行の結果欄を作る。

    引数: なし。正式な設定定義.json・研究条件案.jsonを読む。
    返り値: strは56手法×9尺度と固定前36候補のMarkdown。
    """
    catalog = CAT.load_catalog()
    definition = json.loads((TRIAL / "設定定義.json").read_text(encoding="utf-8"))
    plan = json.loads((TRIAL / "研究条件案.json").read_text(encoding="utf-8"))
    rows = definition["settings"]
    assert definition["trial"] == plan["trial"] == 110
    assert definition["catalog_version"] == 6 and len(plan["configs"]) == 36
    assert len({row["設定ID"] for row in rows}) == len(rows)
    methods = {row["id"] for row in catalog["methods"]}
    scales = {row["id"] for row in catalog["scales"]}
    for row in rows:
        assert set(row["手法ID"]) <= methods and set(row["尺度ID"]) <= scales
        assert all(row[key] for key in ["短記", "定義", "結果短記"])
    text = "# 00110：設定と結果\n\n設計・市場実行前の表。未実行を0円や成立としない。使用版6、全56手法×9尺度を保持する。\n\n"
    text += "[計画](README.md) / [汎用表・版6](../../docs/議論/手法と時間スケールの汎用表_版6.md) / [前試行109](../00109_三時間軸の取得確認と一定利益の必須保護/README.md)\n\n"
    text += "## 手法×時間スケール\n\n複合成績を指標単独の効果とはしない。未使用・診断のみ・データ不足・対象外を区別する。\n\n"
    matrix = CAT.matrix(catalog, OUTPUT, rows)
    lines = matrix.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("| X04 |") or line.startswith("| E01 |"):
            parts = line.split(" | ")
            parts[2] = "データ不足（mini実板なし）" if line.startswith("| X04 |") else "対象外（旧先着合否は保留）"
            lines[i] = " | ".join(parts)
    text += "\n".join(lines)+"\n\n## 設定明細\n\n"
    text += CAT.G.table(["設定ID", "手法ID・尺度", "短い定義", "閾値・初期化・役割", "評価・状態"],
                        [[row["設定ID"], "/".join(row["手法ID"])+"・"+"/".join(row["尺度ID"]), row["短記"], row["定義"], row["結果短記"]] for row in rows])
    text += "## 共通条件\n\n"+definition["common"]+"\n\n"
    text += "## 36複合評価\n\n各行は独立した運用候補。費用感度を独立標本や合算損益とはしない。\n\n"
    evaluations = []
    keys = set()
    for i, config in enumerate(plan["configs"], 1):
        key = f"{config['candidate']}_C{config['slip_pts']}_D{config['delay_seconds']}"
        assert key not in keys
        keys.add(key)
        evaluations.append([f"R{i:02d}", config["candidate"], f"C{config['slip_pts']}/D{config['delay_seconds']}",
                            config["settings"], "既使用70場予定・主7,980枠", "未検証", "未検証", "未検証"])
    text += CAT.G.table(["評価ID", "入口/保護", "費用", "構成", "分母", "費用後純額", "利益後赤字/DD", "実参加"], evaluations)
    text += "## 再現と出典\n\n技法・依存・実行物の指紋を市場前に固定する。本生成器は金融固定後に未実行表を上書きしない。\n\n"
    text += CAT.G.provenance([ROOT / "scripts/レポート/手法カタログ_版6.json", TRIAL / "設定定義.json", TRIAL / "研究条件案.json", Path(__file__)], OUTPUT)
    text += "\n```powershell\npython -X utf8 scripts/レポート/試行110の設定表を作る.py\npython -X utf8 scripts/レポート/試行110の設定表を作る.py --check\n```\n"
    return text


def main() -> None:
    """110の事前設定表を生成又は照合する。

    引数: CLIの--check(bool)で保存値との一致のみ確認する。
    返り値: None。不正なID・候補数・金融固定後の上書きは拒否する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if (TRIAL / "金融条件.json").exists() and not args.check:
        raise ValueError("金融固定後は事前表を上書きしません")
    value = render()
    if args.check:
        assert OUTPUT.read_text(encoding="utf-8") == value
    else:
        OUTPUT.write_text(value, encoding="utf-8")
    print("110の56手法・9尺度・36条件を確認しました")


if __name__ == "__main__":
    main()
