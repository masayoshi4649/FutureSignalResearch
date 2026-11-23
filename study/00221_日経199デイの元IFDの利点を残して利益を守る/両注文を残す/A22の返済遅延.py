"""利益を保護するA22の返済に1秒、3秒、5秒かかる場合の感度を調べる。"""
from functools import partial
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODEL = runpy.run_path(str(HERE/"期限の追試.py"))
DELAYS = [1,3,5]


def decide(code: str, context: dict, index: object, entry: int, side: int,
           width: float, horizon: str, term: dict) -> dict:
    """
    機能：A22の起動・床・期限を保ち、追加保護注文だけの仮定遅延を変える。
    引数：code（str）は秒数、context・term（dict）は特徴と期限、index（PriceIndex）は板、
    entry・side（int）は建玉原行と方向、width（float）・horizon（str）は元幅と期限。
    返り値：dict。選択した板と決済理由。
    """
    rule = partial(MODEL["locks"],session=horizon=="SESSION")
    return MODEL["FIRST"]["apply_rule"]("A22",context,index,entry,side,width,horizon,term,rule,int(code))


def main() -> None:
    """
    機能：遅延を変え元帳を再生し、1秒条件の全件同体を確認して簡易比較表を保存する。
    引数：なし。試行219の口座計算器と、221追試元帳を使う。
    返り値：None。Markdownの口座別・固定取得別集計を試行フォルダへ書き出す。
    """
    engine = runpy.run_path(str(next((ROOT/"study").glob("00219_*/口座再生.py"))))
    stat = runpy.run_path(str(next((ROOT/"study").glob("00219_*/出口を集計する.py"))))
    reference = json.loads((ROOT/"work/221期限の追試/比較元帳.json").read_bytes())
    dates,_,_ = stat["sources"]("デイ")
    books,_ = engine["calculate"]({"prepare":MODEL["prepare"],"decide":decide},[str(t) for t in DELAYS])
    old = books["口座再生"]["IFD"]
    for mode,records in books.items():
        for row,ref in zip(records["1"],reference[mode]["A22"],strict=True):
            assert dict(row,exit_strategy="A22")==ref
    # ----------------------------------------
    lines = ["# A22の追加保護返済だけを遅らせた感度","",
             "静的IFDと期限の注文は全条件で同じ。追加した追尾の発動から、指定秒数以上経過後の最初の正常板で執行する。日経225mini 1枚、費用後円、全45日。元IFDの収支は1,020,063円。","",
             "|秒数|口座取得／未知|総利益|総損失|収支|日末最大下落|赤字日|同じ元181件の収支差|元利確65のうち保全|",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for delay in DELAYS:
        fixed,book = [books[k][str(delay)] for k in ("入口固定","口座再生")]
        assert all(t["exit_time"]-t["trigger_time"]>=delay for t in [*fixed,*book] if t["status"]==5)
        c,_ = stat["evaluate"](dates,old,fixed,book)
        a = c["期間"]["全45日"]
        retained = sum(t["status"]==1 and b["exit_line"]==t["exit_line"] for b,t in zip(old,fixed,strict=True) if b["status"]==1)
        lines.append(f"|{delay}|{a['取得']}／{a['未知']}|{a['利益']:,}|{a['損失']:,}|{a['収支']:,}|"
                     f"{a['場末DD既知']:,}|{a['赤字場']}|{c['入口固定']['収支']-1020063:+,}|{retained}|")
    (HERE/"A22の返済遅延.md").write_text("\n".join(lines)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
