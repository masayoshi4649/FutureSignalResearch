"""入口だけ・出口だけの独立比較に対し、入口と出口を同時に変えた実口座を再生する。"""
from functools import partial
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENTRY = runpy.run_path(str(HERE/"入口/順行入口を再生する.py"))
POLICY = runpy.run_path(str(HERE/"出口/併用条件.py"))


def main() -> None:
    """
    機能：E0/E2/E3の入口をX2の出口で運用し、元の要求と予約から一枚口座を再構成する。
    引数：なし。参照元帳は228の入口群・出口併用群、板・シグナル・特徴は基準試行と共通。
    返り値：None。両方変更した実口座と、対照一致を検査したE0口座を保存する。
    """
    source,engine = ENTRY["SOURCE"],ENTRY["ENGINE"]
    known = json.loads((ROOT/"work/228入口/口座元帳.json").read_bytes())
    contrast = json.loads((ROOT/"work/228併用1/口座元帳.json").read_bytes())["口座再生"]
    dates,books,seen = known["対象場"],{},set()
    for folder,archive,member,manifest in source["parts"]():
        scenes,arrays,values,columns,_ = source["inputs"](folder,archive,member)
        meta = {s["session"]:s for s in source["read"](manifest)["scenes"]}
        for n,scene in enumerate(scenes):
            day = scene["session"]
            if day not in dates or day in seen:
                continue
            seen.add(day)
            index = engine["FINANCE"]["load_scene"](manifest.parent,meta[day])
            stream = engine["orders"](arrays,n,scene,index)
            rows = (arrays["scene"]==n) & (arrays["time"]<scene["end"]-960)
            assert np.array_equal(stream[2]["line"],arrays["line"][rows])
            contexts = [ENTRY["vetoes"](values[s][rows],columns) for s in ("buy","sell")]
            fields = ("index","line","time","core","branches","mw","fw")
            ctx = POLICY["prepare_signals"](index,scene,{k:stream[2][k] for k in fields})
            dynamic = engine["exits"](index,scene,dict(POLICY,prepare=lambda _index,_scene:ctx))
            static = engine["exits"](index,scene,ENTRY["BASE"]["POLICY"]["STATIC"])

            def barrier(entry: int, side: int, width: float) -> dict:
                """
                機能：保護決済後に元のIFDが到達した時刻を新規再開の条件にする。
                引数：entry・side（int）は取得行と側、width（float）は元注文の片幅。
                返り値：dict。損益を計上しない観測上の価格到達記録。
                """
                return static("D00",entry,side,width,"SESSION")

            for pos in (0,2,3):
                changed,_ = ENTRY["modified"](stream,contexts[0][pos],contexts[1][pos],False)
                for wait in (20,30):
                    selected = ENTRY["BASE"]["after_open"](changed,scene["start"]+60*wait)
                    records,_ = ENTRY["CONTROL"]["account"](selected,scene,index,"X2",
                                                  partial(ENTRY["close_rc"],dynamic),barrier,"C")
                    books.setdefault(f"E{pos}X2C{wait}",[]).extend(records)
    # ----------------------------------------
    assert seen==set(dates)
    fields = ("scene","request_line","entry_line","side","entry_time","entry_price","width")
    for wait in (20,30):
        assert books[f"E0X2C{wait}"]==contrast[f"X2C{wait}"]
        for pos in (2,3):
            for a,b in zip(books[f"E{pos}X2C{wait}"],known["口座再生"][f"E{pos}RC{wait}"],strict=True):
                assert all(a[k]==b[k] for k in fields)
    dest = ROOT/"work/228両方"
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"口座元帳.json").write_text(json.dumps({"対象場":dates,"口座再生":books},ensure_ascii=False,
                                           allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
