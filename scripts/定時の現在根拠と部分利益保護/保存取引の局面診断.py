"""固定済81の実入口を窓別換算bp幅・終値・勢いへ分ける事後診断。新売買は生成しない。"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    """
    機能: 保存結果の前後不変を確かめる。
    引数: path (Path) は保存JSON。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    """
    機能: 実取引の時点入力と完結額を分類し、探索後の診断として新規保存する。
    引数: --input/--out/--md (Path) は再生根・新規JSON・新規Markdown。
    返り値: None。取引を除外して戦略損益を作り直さない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--md", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists() or args.md.exists():
        raise FileExistsError("保存診断は上書きしません")
    rows = defaultdict(lambda: {"玉数": 0, "損益円": 0, "正益未観測玉": 0, "正益未観測損益円": 0})
    hashes = {}
    for path in sorted(args.input.glob("*.json")):
        hashes[path.name] = digest(path)
        result = json.loads(path.read_text(encoding="utf-8"))
        grids = {(g["entry_policy"], g["at"]): g for g in result["grid_decisions"]}
        for key in ("B0G1_D0", "B0G1_D1", "B1G1_D0", "B1G1_D1"):
            book = result["books"][key]
            entries = {o["position_id"]: o for o in book["orders"] if o["kind"] == "entry" and o["filled_quantity"]}
            for lot in book["lots"]:
                order = entries[lot["id"]]
                decision = grids[key[:2], order["request_time"]]["decision"]
                t, s = decision["technical"], lot["side"]
                evidence = decision["evidence"]["buy" if s > 0 else "sell"]
                own5, own15 = s * evidence["own5"], s * evidence["own15"]
                assert own5 > 0 and own15 > 0 and lot["quantity"] == 0
                width = "5秒幅＜15秒幅の半分" if own5 < .5 * own15 else ("半分≦5秒幅＜15秒幅" if own5 < own15 else "5秒幅≧15秒幅")
                checks = [("窓別換算bp幅と役割", width + "・" + lot["role"])]
                if t["exit_known"] and t["spike_known"]:
                    bits = (s * (t["close3"] - t["ema8_3"]) > 0, s * (t["rsi3"] - t["previous_rsi3"]) > 0,
                        s * (t["histogram3"] - t["previous_histogram3"]) > 0)
                    label = "／".join("方向側" if value else "反対又は同値" for value in bits)
                else:
                    label = "必要値未知"
                checks.append(("終値位置／RSI増分／MACD増分", label))
                for kind, group in checks:
                    row = rows[key, kind, group]
                    row["玉数"] += 1
                    row["損益円"] += lot["net_pnl"]
                    row["正益未観測玉"] += not lot["flag"]
                    if not lot["flag"]:
                        row["正益未観測損益円"] += lot["net_pnl"]
    assert len(hashes) == 66
    assert all(digest(args.input / name) == sha for name, sha in hashes.items())
    groups = [{"政策": k[0], "分類": k[1], "群": k[2], **v} for k, v in sorted(rows.items())]
    value = {"試行": 81, "種類": "固定結果を見た後の保存実取引診断", "新売買再生": 0,
        "注意": "群を選んだ再生戦略の成績ではない。次の条件を作る場合は新試行で固定し、参加・保有の変化を再生する。",
        "源結果SHA256": hashes, "分類根拠": "own5/own15はRawReturn×窓秒数/Elapsedの窓別換算bp幅で、pt/秒の速度ではない。0.5/1は事後の比率分類で元FAR速度閾値の再現ではない。3分の終値/RSI/MACDは方向符号と0境界。本診断を81の事前選択性能としない。", "群": groups}
    with args.out.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    text = ["# 固定81の保存取引を局面へ分ける診断", "", "2026-11-07。結果を見た後の探索診断。新売買再生0。表は取引を選び直した戦略成績ではなく、次の仮説を作る材料である。", "",
        "own5／own15はRawReturn×窓秒数÷Elapsedで算出した窓別換算bp幅で、pt/秒の速度ではない。比0.5／1は事後の分類で、元FARの速度閾値を再現したものではない。終値位置・RSI増分・MACD増分は実方向符号で0を境界とし、既知性不足を別記する。各群を全て保存し、未来の利益を入口へ戻さない。", "",
        "初版は窓別幅を『速度』と誤記した。2026-11-07に単位と根拠を訂正した。保存群の数値・81の売買再生・正式損益は不変。", "",
        "| 政策 | 分類 | 保存群 | 玉数 | 損益円 | 正益未観測玉 | 同損益円 |", "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for row in groups:
        text.append(f"| {row['政策']} | {row['分類']} | {row['群']} | {row['玉数']} | {row['損益円']:,.0f} | {row['正益未観測玉']} | {row['正益未観測損益円']:,.0f} |")
    text += ["", "次に使う条件は別試行として固定する。同じ指標の加工を独立の賛成票に数えず、背景の方向、現在の進行、取得位置、量と価格の応答を役割ごとに判断する。少数の黒字群だけで将来安定性を認定しない。", ""]
    args.md.write_text("\n".join(text), encoding="utf-8")
    print(json.dumps({"保存群": len(groups), "新売買再生": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
