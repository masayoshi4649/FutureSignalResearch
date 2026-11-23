"""89の既存2正本から同実入口の出口差と参加差を記述する。"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    """
    機能: 診断入力の内容指紋を得る。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sign(value: float) -> str:
    """
    機能: 最終損益の符号を表示用に分ける。
    引数: value (float) は費用後円。
    返り値: str は黒字/赤字/同値。
    """
    return "黒字" if value > 0 else "赤字" if value < 0 else "同値"


def exact(left: dict, right: dict) -> bool:
    """
    機能: 同参照の要求と実取得が全て同じか確認する。
    引数: left/right (dict) は正式玉診断。
    返り値: bool は要求/方向/時刻/価格/量の一致。
    """
    return left["entry_order"]["request_time"] == right["entry_order"]["request_time"] and all(left["lot"][name] == right["lot"][name] for name in ("side", "entry_time", "entry_price", "initial_quantity"))


def lot_metrics(rows: list[dict]) -> dict:
    """
    機能: 実約定した完結玉の損益・配分・要求後変化を集計する。
    引数: rows (list[dict]) は一会計の正式玉診断。
    返り値: dict は記述統計。未計測を0円へ補完しない。
    """
    lots = [r["lot"] for r in rows]
    wins = [r["net_pnl"] for r in lots if r["net_pnl"] > 0]
    losses = [r["net_pnl"] for r in lots if r["net_pnl"] < 0]
    pieces = [c for r in rows for c in r["closed"]]
    known = [c for c in pieces if c["request_to_fill_adverse_yen"] is not None]
    missing = [c for c in pieces if c["request_to_fill_adverse_yen"] is None]
    return {"完結玉": len(lots), "新規枚数": sum(r["initial_quantity"] for r in lots), "費用後円": sum(r["net_pnl"] for r in lots),
        "勝ち玉": len(wins), "負け玉": len(losses), "勝ち合計円": sum(wins), "負け合計円": sum(losses),
        "平均勝ち円": sum(wins)/len(wins) if wins else None, "平均負け円": sum(losses)/len(losses) if losses else None,
        "PF": sum(wins)/abs(sum(losses)) if losses else None,
        "残玉正益前損益円": sum(r["net_pnl"] for r in lots if not r["flag"]),
        "残玉正益後損益円": sum(r["net_pnl"] for r in lots if r["flag"]),
        "全玉正益": sum(r["whole_flag"] for r in lots), "全玉正益後赤字": sum(r["whole_flag"] and r["net_pnl"] < 0 for r in lots),
        "収穫枚数": sum(c["quantity"] for c in pieces if c["harvest"]),
        "収穫純額円": sum(c["pnl5"] for c in pieces if c["harvest"]),
        "非収穫純額円": sum(c["pnl5"] for c in pieces if not c["harvest"]),
        "要求後悪化の既知分円": sum(c["request_to_fill_adverse_yen"] for c in known),
        "要求後悪化の未計測片": len(missing), "要求後悪化の未計測枚": sum(c["quantity"] for c in missing),
        "返済理由別枚数": dict(Counter({reason: sum(c["quantity"] for c in pieces if c["reason"] == reason) for reason in sorted({c["reason"] for c in pieces})}))}


def diagnose(result_path: Path, trades_path: Path, output: Path, markdown: Path) -> dict:
    """
    機能: 配分比較を同実出口差・取得変更・片側参加へ結ぶ。
    引数: result_path/trades_path (Path) は2正本、output/markdown (Path) は新規先。
    返り値: dict は限定診断。原板・市場再売買・APIを使わない。
    """
    before = {"結果": sha(result_path), "玉診断": sha(trades_path)}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["試行"] == 89 and result["場数"] == 66 and len(result["場別"]) == 528
    with gzip.open(trades_path, "rt", encoding="utf-8") as stream:
        trades = [json.loads(line) for line in stream if line.strip()]
    grouped = {key: {} for key in result["比較"]}
    for row in trades:
        identity = row["session"], row["lot"]["reference_id"]
        assert identity not in grouped[row["key"]]
        assert row["lot"]["quantity"] == 0
        assert sum(c["pnl5"] for c in row["closed"]) == row["lot"]["net_pnl"]
        grouped[row["key"]][identity] = row
    metrics = {key: lot_metrics(list(rows.values())) for key, rows in grouped.items()}
    for key, actual in metrics.items():
        expected = result["比較"][key]
        assert actual["完結玉"] == expected["完結玉"] and actual["費用後円"] == expected["費用後損益円"]
        assert actual["新規枚数"] == expected["新規枚数"] and actual["全玉正益"] == expected["全玉旗"]
        assert actual["全玉正益後赤字"] == expected["全玉旗後赤字"]
    pairs = {}
    for delay in (0, 1):
        for entry in ("E0", "E1"):
            k0, k1 = f"{entry}G1_D{delay}", f"{entry}G2_D{delay}"
            left, right = grouped[k0], grouped[k1]
            common = set(left) & set(right)
            same = {identity for identity in common if exact(left[identity], right[identity])}
            changed, only0, only1 = common-same, set(left)-set(right), set(right)-set(left)
            categories, examples = {}, []
            for identity in sorted(same):
                a, b = left[identity], right[identity]
                pa, pb = a["lot"]["net_pnl"], b["lot"]["net_pnl"]
                label = sign(pa)+"→"+sign(pb)
                group = categories.setdefault(label, {"玉数": 0, "G1円": 0, "G2円": 0, "差円": 0, "同額玉": 0})
                for name, value in (("玉数", 1), ("G1円", pa), ("G2円", pb), ("差円", pb-pa), ("同額玉", pa == pb)):
                    group[name] += value
                if pa != pb:
                    examples.append({"場": identity[0], "参照ID": identity[1], "量": a["lot"]["initial_quantity"], "G1円": pa, "G2円": pb, "差円": pb-pa,
                        "G1全玉正益": a["lot"]["whole_flag"], "G2全玉正益": b["lot"]["whole_flag"],
                        "G1返済理由": dict(Counter(c["reason"] for c in a["closed"])), "G2返済理由": dict(Counter(c["reason"] for c in b["closed"]))})
            parts = {"同実出口差円": sum(right[i]["lot"]["net_pnl"]-left[i]["lot"]["net_pnl"] for i in same),
                "取得変更差円": sum(right[i]["lot"]["net_pnl"]-left[i]["lot"]["net_pnl"] for i in changed),
                "G1のみ損益円": sum(left[i]["lot"]["net_pnl"] for i in only0), "G2のみ損益円": sum(right[i]["lot"]["net_pnl"] for i in only1)}
            difference = metrics[k1]["費用後円"]-metrics[k0]["費用後円"]
            assert difference == parts["同実出口差円"]+parts["取得変更差円"]-parts["G1のみ損益円"]+parts["G2のみ損益円"]
            formal = result["出口間の同実新規分解"][f"{entry}G2対{entry}G1_D{delay}"]
            assert (len(common), len(same), len(changed), len(only0), len(only1), parts["同実出口差円"]) == tuple(formal[n] for n in ("同参照ID", "同実新規", "共通だが取得変更", "Aのみ", "Bのみ", "同実新規出口差円"))
            pairs[f"{entry}_D{delay}"] = {"比較": [k0, k1], "全差円": difference, "同参照": len(common), "同実新規": len(same), "取得変更": len(changed), "G1のみ": len(only0), "G2のみ": len(only1),
                **parts, "同実入口の最終損益符号別": categories, "同実で差のある玉": examples}
    assert before == {"結果": sha(result_path), "玉診断": sha(trades_path)}
    value = {"試行": 89, "成功": True, "入力SHA256": before, "市場再生": 0, "原板読取": 0, "API": 0, "新期間": 0,
        "集計対象": "実約定して完結した玉。未約定/取消要求の活動は正式結果の判断とSource監査を参照。",
        "会計別": metrics, "利益配分の対応比較": pairs,
        "限界": "既使用66場の記述統計。最終損益符号の遷移と、含み益の初回観測後の赤字化は別の分類。PFは負け0の場合null。未計測悪化は0補完しない。"}
    text = ["# 89：利益配分と参加差の診断", "", "固定E0/E1入口に対するG1部分収穫とG2保護付き残全量追尾の比較。売買の再生成・原板・APIの利用は0。", "",
        "| 会計 | 完結玉 | 費用後円 | 平均勝ち円 | 平均負け円 | 全玉正益後赤字/全玉正益 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, row in metrics.items():
        amounts = ["未実績" if row[name] is None else f"{row[name]:,.1f}" for name in ("平均勝ち円", "平均負け円")]
        text.append(f"| {key} | {row['完結玉']} | {row['費用後円']:,} | {amounts[0]} | {amounts[1]} | {row['全玉正益後赤字']}/{row['全玉正益']} |")
    text += ["", "| 比較 | 同実新規 | 同実出口差円 | 取得変更差円 | G1のみ円 | G2のみ円 | 全差円 |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for key, row in pairs.items():
        text.append("| "+key+" | "+" | ".join(f"{row[name]:,}" for name in ("同実新規", "同実出口差円", "取得変更差円", "G1のみ損益円", "G2のみ損益円", "全差円"))+" |")
    text += ["", "G1のみの損益は全差の式で差し引く。単なる参加集合の違いを同入口の利幅改善へ足さない。", "",
        "[小型JSON](利益配分と参加差の診断.json)は同実入口の最終黒字/赤字/同値の全区分を保持し、差0も数える。同実で金額が変わった玉だけ、量・金額・返済理由を出典付きで列挙する。", "",
        "最低建値床の起動は費用後黒字約定の保証ではない。平均勝敗額、正益前後、収穫/非収穫額、要求後悪化の既知/未計測を別々に解釈する。", ""]
    for path, content in ((output, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n"), (markdown, "\n".join(text))):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    return value


def main() -> None:
    """
    機能: 明示した2正本から診断を新規保存する。
    引数: --result/--trades/--out/--md (Path) は入出力。
    返り値: None。不一致は保存前に停止する。
    """
    parser = argparse.ArgumentParser()
    for name in ("result", "trades", "out", "md"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    value = diagnose(args.result, args.trades, args.out, args.md)
    print(json.dumps({"成功": value["成功"], "配分比較": len(value["利益配分の対応比較"]), "市場再生": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
