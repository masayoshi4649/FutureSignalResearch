"""60分直前の判定値と、1・3・5秒待った後の最初の正常気配での返済を原行から照合する。"""
from collections import Counter
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = runpy.run_path(str(next((ROOT/"study").glob("00219_*/経路診断/元の保有経路を測る.py"))))


def main() -> None:
    """
    機能：延長分岐に用いた実側気配と既発表12分効率、追尾要求後の最初の正常原行を全候補で照合する。
    引数：なし。全遅延の口座・固定建玉を読み、利益保護や期限コードを再実行せず原板価格から確認する。
    返り値：None。照合した建玉数、分岐数と追尾数を作業フォルダへ保存する。
    """
    work = ROOT/"work/221期限保護"
    ledger = json.loads((work/"遅延比較元帳.json").read_bytes())
    grouped = {}
    for mode,group in ledger.items():
        for code,trades in group.items():
            if code=="IFD":
                continue
            for trade in trades:
                grouped.setdefault(trade["scene"],[]).append((mode,code,trade))
    archives = SOURCE["archives"]()
    counts = Counter()
    for day,trades in grouped.items():
        raw = SOURCE["load_records"](*archives[day])
        valid = np.flatnonzero(raw["normal"])
        times = raw["time"][valid]
        for mode,code,t in trades:
            counts["建玉"]+=1
            if t["status"]==5:
                sign = 1 if t["side"]==0 else -1
                price = raw["bid" if sign==1 else "ask"][t["trigger_index"]]
                assert (price-t["entry_price"])*sign<=t["floor_points"]
                earliest = times.searchsorted(t["trigger_time"]+int(code.split("_")[1]))
                assert valid[earliest]==t["exit_index"]
                counts["追尾返済"]+=1
            if not t["eligible_for_extension"]:
                continue
            counts["60分の分岐"]+=1
            due = t["entry_time"]+3600
            pos = int(times.searchsorted(due))-1
            mark,er = None,None
            if pos>=0 and due-times[pos]<=30:
                assert t["extension_quote_time"]==times[pos]
                sign = 1 if t["side"]==0 else -1
                price = raw["bid" if sign==1 else "ask"][valid[pos]]
                mark = float(sign*(price-t["entry_price"])/t["width"])
                assert t["extension_mark_r"]==mark
                end = due//60*60
                bounds = end-np.arange(12,-1,-1)*60
                locations = times.searchsorted(bounds)-1
                if np.all(locations>=0) and np.all(times[locations]>=bounds-60):
                    last = valid[locations]
                    mid = (raw["bid"][last]+raw["ask"][last])/2
                    path = np.abs(np.diff(mid)).sum()
                    er = float(sign*(mid[-1]-mid[0])/path) if path else 0.0
                assert er==t["extension_efficiency"]
            else:
                assert t["extension_quote_time"] is None and t["extension_mark_r"] is None
            wide = mark is not None and mark>=-.25
            stronger = wide and (mark>=.25 or (er is not None and er>=.15))
            label = code.split("_")[0]
            extended = {"T03":True,"T04":wide,"T05":stronger,"T06":wide}[label]
            assert extended==t["extended"]
    assert set(grouped)=={t["scene"] for t in ledger["口座再生"]["IFD"]} and len(grouped)==45
    (work/"延長と追尾執行の照合.json").write_text(json.dumps(counts,ensure_ascii=False,indent=2),encoding="utf8")
    print(dict(counts))


if __name__=="__main__":
    main()
