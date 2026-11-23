"""F01の追尾発動後の最短待ち時間のみ変え、原行と元IFDの利確維持数を照合する。"""
from collections import defaultdict
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
POLICY = runpy.run_path(str(HERE/"出口条件.py"))
SHARED = runpy.run_path(str(HERE.parent/"両注文を残す/A22の返済遅延.py"))
OLD = next((ROOT/"study").glob("00219_*"))


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：保護対象とIFDの金額を維持し、F01の保護発動後の遅延だけを変える。
    引数：code（str）は最短秒数、context・term（dict）は特徴と期限、index（PriceIndex）は原板、
    entry・side（int）は新規原行と方向、width（float）・horizon（str）は元幅と保有期限。
    返り値：dict。返済の原行・時刻・事由。
    """
    policy = "P2" if width==350 and horizon=="H60" else "P0"
    return POLICY["MAIN"]["settle"](policy,width,context,index,entry,side,width,horizon,term,int(code))


def verify(books: dict) -> tuple:
    """
    機能：出口の探索を再利用せず、元帳の全取得・実決済・含みの山谷・発動からの正常板順を照合する。
    引数：books（dict）は取得固定と1枠口座の元IFDおよび遅延別の元帳。
    返り値：tuple。全照合対象数、うち動的決済数。重複する対照も各元帳で照合する。
    """
    audit = runpy.run_path(str(OLD/"経路診断/出口の原行を照合する.py"))
    source = audit["SOURCE"]
    archive = source["archives"]()
    grouped = defaultdict(list)
    for ledger in books.values():
        for code,rows in ledger.items():
            for row in rows:
                grouped[row["scene"]].append((code,row))
    total = dynamic = 0
    for scene,rows in grouped.items():
        raw = source["load_records"](*archive[scene])
        for code,row in rows:
            total += 1
            assert row["net"] is not None
            if row["status"]!=5:
                audit["verify"](raw,row)
                continue
            dynamic += 1
            data = source["observe"](row,raw)
            for bound,typ in (("最大","max"),("最小","min")):
                assert data["観測"+bound+"損益円"]==row[typ+"_unrealized_net"]
                assert data[bound+"時"]==source["stamp"](row[typ+"_unrealized_time"])
            trigger = row["trigger_index"]
            assert row["entry_index"]<trigger<row["exit_index"] and raw["normal"][trigger]==1
            assert raw["time"][trigger]==row["trigger_time"]
            path = raw[trigger+1:row["exit_index"]+1]
            fills = np.flatnonzero((path["normal"]==1)&(path["time"]>=row["trigger_time"]+int(code)))
            assert len(fills)==1 and fills[0]==len(path)-1
    return total,dynamic


def main() -> None:
    """
    機能：1・3・5秒の各遅延を同じ予約で再生し、1秒で固定F01の全属性一致、全遅延で原行一致を確認する。
    引数：なし。元IFD・固定F01の元帳と219の価格索引を使う。
    返り値：None。照合結果と2例を含むMarkdownを試行に保存する。
    """
    stat = runpy.run_path(str(OLD/"出口を集計する.py"))
    engine = runpy.run_path(str(OLD/"口座再生.py"))
    delays = SHARED["DELAYS"]
    dates,_,_ = stat["sources"]("デイ")
    books,_ = engine["calculate"]({"prepare":POLICY["prepare"],"decide":decide},[str(v) for v in delays])
    recorded = json.loads((ROOT/"work/221入口別/比較元帳.json").read_bytes())
    for mode,ledger in books.items():
        assert ledger["IFD"]==recorded[mode]["IFD"]
        assert all(dict(row,exit_strategy="F01")==ref for row,ref in zip(ledger["1"],recorded[mode]["F01"],strict=True))
    total,dynamic = verify(books)
    # ----------------------------------------
    old = books["口座再生"]["IFD"]
    lines = ["# F01の返済遅延と同じ入口での二例","",
             "350pt幅・60分期限に限るF01の発動条件を固定し、追尾注文の発動から返済までの最短秒数を変えた。静的利確・損切、期限返済には元IFDの時計を使用。45デイ、日経225mini 1枚、往復1,077円控除後。","",
             "|条件|口座取得／未知|総利益円|総損失円|収支円|日末最大下落円|赤字日|元181件での収支差円|元65利確を同一原行で維持|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for code in ["IFD",*(str(v) for v in delays)]:
        fixed,book = [books[k][code] for k in ("入口固定","口座再生")]
        c,_ = stat["evaluate"](dates,old,fixed,book)
        a = c["期間"]["全45日"]
        kept = 0
        for b,t in zip(old,fixed,strict=True):
            assert stat["key"](b)==stat["key"](t)
            kept += b["status"]==1 and t["status"]==1 and b["exit_line"]==t["exit_line"]
        tag = "元IFD" if code=="IFD" else "F01・"+code+"秒"
        lines.append(f"|{tag}|{a['取得']}／{a['未知']}|{a['利益']:,.0f}|{a['損失']:,.0f}|{a['収支']:,.0f}|"
                     f"{a['場末DD既知']:,.0f}|{a['赤字場']}|{c['入口固定']['収支']-1020063:+,}|{kept}/65|")
    lines += ["",f"1秒の全件は既存のF01の原行・属性と一致。元IFDを含み固定取得・1枠口座の延べ{total:,}件を独立に原行照合し、動的返済{dynamic}件は各指定遅延後の最初の正常板と一致した。","",
              "## 両口座が同じ原行で建てた実例","","表の追尾は1秒条件。時刻は日本時間、出入口の価格はラージ板の実側気配。","",
              "|日付・取得|順行時の起動／床の発動|F01の返済|元IFDの60分期限返済|収支差円|",
              "|---|---|---|---|---:|"]
    for scene,line in (("2026-09-29_Day",115356),("2026-10-05_Day",1593)):
        b,t = [next(v for v in books["口座再生"][code] if (v["scene"],v["entry_line"])==(scene,line)) for code in ("IFD","1")]
        assert b["status"]==3 and t["status"]==5 and stat["key"](b)==stat["key"](t)
        clock = {k:stat["stamp"](v)[11:19] for k,v in t.items() if k in ("entry_time","activation_time","trigger_time","exit_time")}
        lines.append(f"|{scene[:10]} {clock['entry_time']} {t['entry_price']:,.0f}{'売り' if t['side'] else '買い'}|"
                     f"{clock['activation_time']}／{clock['trigger_time']}|{clock['exit_time']} {t['exit_price']:,.0f}（{t['net']:+,.0f}円）|"
                     f"{stat['stamp'](b['exit_time'])[11:19]} {b['exit_price']:,.0f}（{b['net']:+,.0f}円）|{t['net']-b['net']:+,.0f}|")
    lines += ["","9月29日の売りは守った利益が元期限では失われた。10月5日の買いは追尾返済後に上昇し、元期限まで保有した利益のほうが大きかった。どちらも元の350pt指値に到達する前の期限返済との比較。全期間は既に探索に使っている。","",
              "再現には[219の価格索引と元帳](../../00219_日経199デイの利益保護と出口条件を比較する/再現手順.md)と本試行の入口別元帳を準備し、試行内の `F01の返済感度を照合する.py` を実行する。"]
    (HERE/"F01の返済遅延と具体例.md").write_text("\n".join(lines)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
