"""全デイの損益と、研究窓・ザラバ全体で測った上昇・下落との対応を比較する。"""
import csv
from datetime import datetime
import json
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能：ザラバの最初・最後の分があるデイで約定足の始終方向を照合し、欠測と損益分布を調べる。
    引数：なし。「日別の形」の診断JSONと共用データの1分足を参照する。
    返り値：None。独立した窓の集計Markdownを「日別の形」へ出力する。
    """
    rows = json.loads((ROOT/"work/228日別の形/日別と分類.json").read_bytes())["日別"]
    changed = []
    for r in rows:
        path = ROOT.parent/"JP_OSE_Data/future/NK225"/r["セッション"]/"candle_1min.csv"
        with path.open(encoding="utf-8-sig",newline="") as stream:
            candles = {datetime.fromisoformat(a["time"]).strftime("%H:%M"):a for a in csv.DictReader(stream)
                       if a["closed"]=="true" and a["open"] and a["close"]}
        sign = "不足"
        if "08:45" in candles and "15:39" in candles:
            move = float(candles["15:39"]["close"])-float(candles["08:45"]["open"])
            sign = "上昇" if move>0 else "下落" if move<0 else "同値"
            if sign!=r["方向"]:
                changed.append(r["セッション"][:10])
        r["ザラバ方向"] = sign
    lines = ["# 測る時間を変えた場合とデータ密度の影響","",
             "主比較の正常気配に加え、確定した08:45開始の1分足の始値と15:39開始の1分足の終値でも"
             "ザラバの上昇・下落を測った。どちらかの分の価格が欠ける日は不足扱いとした。"
             "15:45の板寄せ、前日終値からの変化、夜間の変化は含まない。","",
             "|方向の定義|方向|日数|黒字日|総利益|総損失|収支|","|---|---|---:|---:|---:|---:|---:|"]
    for key,label in (("方向","09:05〜15:29正常中値"),("ザラバ方向","08:45〜15:40の1分足")):
        for sign in ("上昇","下落","同値","不足"):
            g = [r for r in rows if r[key]==sign]
            if g:
                amounts = [sum(r[k] for r in g) for k in ("利益円","損失円","収支円")]
                lines.append(f"|{label}|{sign}|{len(g)}|{sum(r['収支円']>0 for r in g)}|"+
                             "|".join(f"{v:,}" for v in amounts)+"|")
    # ----------------------------------------
    enough = [r for r in rows if r["正常気配のある分数"]>=365]
    lines.extend(["","方向が変わった日は"+"・".join(changed)+"。時計と価格系列の双方が変わる感度である。","",
                  f"主比較の384分のうち365分以上に正常気配がある{len(enough)}日のみの集計。"
                  "値幅区分は全45日の価格順位で決めた境界を保つ。","",
                  "|値幅区分|日数|黒字日|収支円|","|---|---:|---:|---:|"])
    for cat in ("小","中","大"):
        g = [r for r in enough if r["値幅区分"]==cat]
        lines.append(f"|{cat}|{len(g)}|{sum(r['収支円']>0 for r in g)}|{sum(r['収支円'] for r in g):,}|")
    lines.extend(["","|損益で分けた日|日数|値幅％中央値|片道比中央値|5分効率中央値|建玉数中央値|保有時間率中央値|",
                  "|---|---:|---:|---:|---:|---:|---:|"])
    for cat in ("黒字","赤字"):
        g = [r for r in rows if r["損益別"]==cat]
        cells = [f"{median(r[k] for r in g):.3f}" for k in ("値幅％","片道比","5分効率")]
        lines.append(f"|{cat}|{len(g)}|"+"|".join(cells)+
                     f"|{median(r['建玉回数'] for r in g):g}|{median(r['保有時間率'] for r in g):.2%}|")
    (HERE/"検算と別の窓.md").write_text("\n".join(lines)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
