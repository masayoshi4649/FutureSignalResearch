"""保存された実取引の勝ち負け・回収・初期否定を診断する。条件は選び直さない。"""

import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean, median


def main() -> None:
    """
    機能: 実完結玉の利益・損失分布と正益前後の集約を新規保存する。
    引数: --trades/--out/--md (Path) は圧縮玉診断と新規成果物。
    返り値: None。事後診断を条件選択済みの戦略成績へ置換しない。
    """
    parser = argparse.ArgumentParser()
    for name in ("trades", "out", "md"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.md.exists():
        raise FileExistsError("診断を上書きしません")
    before = hashlib.sha256(args.trades.read_bytes()).hexdigest()
    with gzip.open(args.trades, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    groups = defaultdict(list)
    for row in rows:
        assert row["lot"]["quantity"] == 0
        groups[row["key"]].append(row)
    values = {}
    for key in ("B0G1_D0", "B1G1_D0", "B0G1_D1", "B1G1_D1"):
        chosen = groups[key]
        lots = [r["lot"] for r in chosen]
        winners = [p["net_pnl"] for p in lots if p["net_pnl"] > 0]
        losers = [p["net_pnl"] for p in lots if p["net_pnl"] < 0]
        durations = [max(c["exit_time"] for c in r["closed"]) - r["lot"]["entry_time"] for r in chosen if not r["lot"]["flag"]]
        avg_win, avg_loss = mean(winners) if winners else None, mean(losers) if losers else None
        value = {"完結玉": len(lots), "勝ち玉": len(winners), "負け玉": len(losers), "同値玉": sum(p["net_pnl"] == 0 for p in lots),
            "費用後損益円": sum(p["net_pnl"] for p in lots), "平均勝ち円": avg_win, "平均負け円": avg_loss,
            "実現黒字率": len(winners) / len(lots) if lots else None,
            "損益均衡黒字率の算術参考": -avg_loss / (avg_win - avg_loss) if avg_win is not None and avg_loss is not None else None,
            "正益未観測玉": sum(not p["flag"] for p in lots), "正益未観測の損益円": sum(p["net_pnl"] for p in lots if not p["flag"]),
            "正益未観測保有秒中央値": median(durations) if durations else None,
            "正益未観測ATR幅中央値pt": median(p["d"] for p in lots if not p["flag"]) if durations else None,
            "全玉正益後赤字": sum(p["whole_flag"] and p["net_pnl"] < 0 for p in lots)}
        values[key] = value
    assert hashlib.sha256(args.trades.read_bytes()).hexdigest() == before
    output = {"試行": 82, "種類": "固定結果後の損益構造診断", "新売買再生": 0, "入力SHA256": before,
        "注意": "均衡率は観測平均の算術で、将来必要率や独立検証済み確率ではない。群を選び直した再生利益ではない。", "比較": values}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    text = ["# 82の回収額と損失額の構造", "", "固定結果を見た後の診断。新売買再生0、入口・費用・出口の選び直し0。新規100micro固定。均衡率は観測した平均勝ち・平均負けからの算術参考で、将来の勝率予測や独立確認ではない。", "",
        "| 政策 | 完結 | 勝ち／負け | 平均勝ち円 | 平均負け円 | 実現黒字率 | 観測平均での均衡率 | 正益未観測損益円 |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, value in values.items():
        cells = [value[k] for k in ("平均勝ち円", "平均負け円", "実現黒字率", "損益均衡黒字率の算術参考")]
        shown = [(f"{v * 100:.1f}%" if i > 1 else f"{v:,.0f}") if v is not None else "未計算" for i, v in enumerate(cells)]
        text.append(f"| {key} | {value['完結玉']} | {value['勝ち玉']}／{value['負け玉']} | {' | '.join(shown)} | {value['正益未観測の損益円']:,.0f} |")
    text += ["", "正益後の赤字防止だけでなく、正益前に仮説が否定された時の損失、利益を確定した後の残量、費用と取り逃した大きな利益を別に見る。観測分布を根拠に停止幅を後付けで選ばず、構造否定は次の新試行で固定する。", ""]
    args.md.write_text("\n".join(text), encoding="utf-8")
    print(json.dumps(values, ensure_ascii=False))


if __name__ == "__main__":
    main()
