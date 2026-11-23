"""出口X2で救った損失と早く確定した利益を、各建玉・週・当日の形に対応させる。"""
import csv
from collections import defaultdict
from datetime import date
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main() -> None:
    """
    機能：共通の取得ごとに2口座を結合し、週・日形・採用された出口別の増減を調べる。
    引数：なし。228の1秒口座元帳とRC20の形の日別CSVが必要。
    返り値：None。分類別金額と改善が集中した期間をMarkdownに保存する。
    """
    ref = json.loads((ROOT/"work/228入口/口座元帳.json").read_bytes())["口座再生"]["E0RC20"]
    book = json.loads((ROOT/"work/228併用1/口座元帳.json").read_bytes())["口座再生"]["X2C20"]
    with next((ROOT/"outputs").glob("00228_*/228_RC20_日別の形/日別の形と損益.csv")).open(encoding="utf-8-sig",newline="") as f:
        shapes = {r["セッション"]:r for r in csv.DictReader(f)}
    assert set(shapes)=={r["scene"] for r in ref}
    pairs = defaultdict(list)
    for a,b in zip(ref,book,strict=True):
        assert all(a[k]==b[k] for k in ("scene","side","entry_line","entry_price","width"))
        scene = a["scene"]
        for key in ("方向","値幅区分","片道区分","中心回帰区分"):
            pairs[key,shapes[scene][key]].append((a,b))
        week = date.fromisoformat(scene[:10]).isocalendar().week
        pairs["暦週",str(week)].append((a,b))
        pairs["先に決済した出口",b["winning_policy"]].append((a,b))
    lines = ["# 出口だけを変えたX2の利益はどこから来たか","",
             "RC20とX2C20の133建玉を同じ側・取得行・価格・片幅で対応させた。"
             "各区分の差はX2からRCを引いた費用後の円。損失差が負なら損失額が減った。"
             "日別の形には事後情報を使う。各切り口は同じ建玉を含む。","",
             "|切り口|区分|日数|建玉数|決済行が変化|赤字→黒字|総利益差|総損失差|収支差|",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    order = ("先に決済した出口","方向","値幅区分","片道区分","中心回帰区分","暦週")
    for key,value in sorted(pairs,key=lambda k:(order.index(k[0]),k[1])):
        rows = pairs[key,value]
        win = sum(max(b["net"],0)-max(a["net"],0) for a,b in rows)
        loss = sum(max(-b["net"],0)-max(-a["net"],0) for a,b in rows)
        shifts = sum(a["exit_line"]!=b["exit_line"] for a,b in rows)
        rescued = sum(a["net"]<0<b["net"] for a,b in rows)
        n = len({a["scene"] for a,_ in rows})
        lines.append(f"|{key}|{value}|{n}|{len(rows)}|{shifts}|{rescued}|{win:+,.0f}|{loss:+,.0f}|{win-loss:+,.0f}|")
    lines.extend(["","後半の11月18日はX2C20の最大赤字日。元の損切り2件・場末の赤字1件は同額で、"
                  "残る買いが元利確＋33,923円に届く前に追尾で＋11,923円に確定した。"
                  "そのため日次は−33,308円から−55,308円へ22,000円悪化した。"])
    (HERE/"日と建玉の寄与.md").write_text("\n".join(lines)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
