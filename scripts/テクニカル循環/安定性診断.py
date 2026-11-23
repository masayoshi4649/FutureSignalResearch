"""00011の固定済み運用に、利益集中と日単位の不確実性診断を追加する。"""

from collections import defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "study/00011_順行と反転のチャート構造と利益回収"
DETAIL = ROOT / "work/テクニカル循環/00011/全運用詳細.jsonl.gz"
SPEC = importlib.util.spec_from_file_location("安定性の共通表", ROOT / "scripts/レポート/設定結果レポート.py")
G = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = G
SPEC.loader.exec_module(G)


def sha(path: Path) -> str:
    """小型ファイルの内容指紋を返す。

    引数: path (Path) はファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(rows: list[dict], cid: str, period: str) -> dict:
    """無取引日も含む日クラスタと利益集中を計算する。

    引数: rows (list[dict]) は一候補・一期間の全場、cid/period (str) は識別。
    返り値: dict は観測模型の感度・参考区間。将来確率や多重性補正ではない。
    """
    dates = sorted({r["場"][:10] for r in rows})
    seed = 20261104 + int(hashlib.sha256((cid+period).encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(dates), size=(5000, len(dates)))
    daily = {day: {"純額": 0.0, "取引": 0} for day in dates}
    for row in rows:
        daily[row["場"][:10]]["純額"] += row["純額"]
        daily[row["場"][:10]]["取引"] += row["取引"]
    results = []
    for slip in (0, 5, 10):
        session_values = [r["純額"]-2*slip*10*r["取引"] for r in rows]
        day_values = np.array([daily[d]["純額"]-2*slip*10*daily[d]["取引"] for d in dates])
        draw_sums = day_values[indices].sum(axis=1)
        q = np.quantile(draw_sums, [.025, .975])
        positive = sorted((v for v in session_values if v > 0), reverse=True)
        results.append({"片道追加pt": slip, "観測純額円": sum(session_values),
                        "上位3黒字場除外参考円": sum(session_values)-sum(positive[:3]),
                        "除外黒字場数": min(3, len(positive)),
                        "赤字場数": sum(v < 0 for v in session_values),
                        "日クラスタ95参考下限円": float(q[0]), "日クラスタ95参考上限円": float(q[1])})
    return {"候補ID": cid, "期間": period, "場数": len(rows), "開始日数": len(dates),
            "活動場数": sum(r["取引"] > 0 for r in rows), "品質注意場数": sum(r["注意"] for r in rows),
            "日単位復元抽出回数": 5000, "seed": seed, "感度": results}


def main() -> None:
    """固定集計と詳細の一致を確かめ、追加診断を保存する。

    引数: なし。
    返り値: None。売買条件、既存結果、選定を変更しない。
    """
    report = json.loads((STUDY / "結果.json").read_text(encoding="utf-8"))
    artifact = json.loads((STUDY / "作業成果物.json").read_text(encoding="utf-8"))
    expected = next(r["展開内容SHA256"] for r in artifact["ファイル"] if r["パス"].endswith("全運用詳細.jsonl.gz"))
    groups, expanded = defaultdict(list), hashlib.sha256()
    with gzip.open(DETAIL, "rb") as stream:
        for line in stream:
            expanded.update(line)
            row = json.loads(line)
            period = row["品質"]["期間"]
            if period not in ("学習", "条件選択"):
                continue
            groups[row["候補ID"], period].append({"場": row["場"], "純額": sum(t["基準純損益円"] for t in row["取引"]),
                "取引": len(row["取引"]), "注意": bool(row["品質"]["観測経路注意"])})
    if expanded.hexdigest() != expected:
        raise ValueError("固定された作業詳細の展開SHAと異なります")
    results = []
    for row in report["結果"]:
        for period in ("学習", "条件選択"):
            detail = diagnose(groups[row["候補ID"], period], row["候補ID"], period)
            source = row[period]["運用"]
            if detail["品質注意場数"] != source["品質注意場数"] or detail["活動場数"] != source["活動場数"]:
                raise ValueError("固定集計と場の品質・活動が一致しません")
            for sensitivity in detail["感度"]:
                if sensitivity["観測純額円"] != source[f"追加{sensitivity['片道追加pt']}pt純損益円"]:
                    raise ValueError("固定損益との不一致")
            results.append(detail)
    payload = {"確認日": "2026-11-04", "固定結果SHA256": sha(STUDY / "結果.json"),
               "詳細展開SHA256": expanded.hexdigest(), "診断コードSHA256": sha(Path(__file__)),
               "環境": {"NumPy": np.__version__}, "結果": results,
               "限界": ["全65場は既使用。観測模型の診断であり将来の利益確率ではない。",
                        "日内依存をまとめるが日をまたぐ依存・候補選択・多重比較を補正しない。",
                        "上位3場除外は事後の感度であり、実際に回避できる取引規則ではない。",
                        "品質注意のある全体を確定額へ変換しない。無取引日も復元抽出へ含める。"]}
    (STUDY / "安定性診断.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    output = STUDY / "安定性診断.md"
    text = "# 00011：利益集中と日単位の安定性診断\n\n確認日2026-11-04。[元の結果](README.md)の固定売買を変更せず、全24候補・旧二期間を診断した。\n\n"
    text += "無取引日を含め、同開始日のデイ/ナイトをまとめて5,000回復元抽出する。区間は既使用資料の参考値で、候補選択・多重比較・日をまたぐ依存・観測空白を解消せず、将来の成功確率を表さない。上位3黒字場の事後除外は実行可能な回避策でも全体の代用でもない。\n\n"
    for slip in (0, 5, 10):
        rows = []
        for result in results:
            sensitivity = next(r for r in result["感度"] if r["片道追加pt"] == slip)
            rows.append([result["候補ID"], result["期間"], f"{result['活動場数']}/{result['場数']}",
                         sensitivity["観測純額円"], sensitivity["上位3黒字場除外参考円"],
                         f"{sensitivity['日クラスタ95参考下限円']:,.1f}〜{sensitivity['日クラスタ95参考上限円']:,.1f}",
                         result["品質注意場数"]])
        text += f"## 片道追加{slip}pt\n" + G.table(["候補", "期間", "活動/全場", "観測純額円", "上位3場除外参考円", "日クラスタ95参考区間円", "注意場"], rows)
    text += "5分_R2_X0の追加5pt後観測額は学習＋7,006円・選択＋5,130円だが、両期間とも上位3黒字場除外参考は赤字で、日単位参考区間も0をまたぐ。少数の大きな利益への依存と短い期間が残り、安定収益の達成証拠とはしない。\n\n"
    text += G.provenance([Path(__file__), STUDY / "結果.json", STUDY / "作業成果物.json", STUDY / "安定性診断.json"], output)
    output.write_text(text, encoding="utf-8")
    print("全24候補・旧二期間の安定性診断を保存しました。")


if __name__ == "__main__":
    main()
