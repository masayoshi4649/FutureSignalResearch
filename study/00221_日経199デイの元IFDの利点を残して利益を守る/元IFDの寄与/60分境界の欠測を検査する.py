"""60分の過去を共通にした人工気配で、意思決定と将来の返済観測の独立を検査する。"""
from hashlib import sha256
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = runpy.run_path(str(HERE/"期限延長と追尾を組み合わせる.py"))
ENGINE = MODEL["ENGINE"]
OPEN, DUE = 60,3660
SCENE = {"start":0,"end":8100}
DATA_TYPE = [("time","f8"),("source_line","i8"),("normal","i1"),("bid","f8"),("ask","f8")]
CONTROL_HASHES = {"比較元帳":"a6813e6941354a0e35a4d354563ab9cc9d58adb2d33d74f5ee26c26c699db0ac",
                  "遅延比較元帳":"b926414fa2aa048c62df0fbfd2a077aebd5257d6855726dbe0a542cdd5944d7e"}


def run_case(name: str, side: int, delay: int) -> tuple:
    """
    機能：共通の取得と価格注文を持つ人工板の、60分境界の片側だけを変えて元の口座部品で再生する。
    引数：name（str）は欠測や静的先着の条件名、side（int）は注文方向、delay（int）は動的返済の秒数。
    返り値：tuple。元H60の実際の返済と4延長方式の結果。
    """
    past = list(range(0,DUE-30,30))+[DUE-1]
    first_future = {"通常":5,"遅着":45,"将来欠測":500,"期限後打切":None,
                    "逆行で見送る":45,"直前板なし":45,"直前静的先着":45,"期限瞬間の先着":0,
                    "先行価格欠測":5,"先行気配欠測":5,"直前の観測中断":45,"場末競合":5}[name]
    if name=="直前板なし":
        past = [t for t in past if t<=DUE-45]
    if name=="直前の観測中断":
        past = [t for t in past if t<DUE-300]
    if name=="先行価格欠測":
        past = [t for t in past if not 900<t<1260]
    later = [] if first_future is None else [DUE+first_future,*range(DUE+max(first_future+10,60),7200,30),7200]
    times = np.array(sorted(set(past+later)))
    rows = np.zeros(len(times),dtype=DATA_TYPE)
    rows["time"] = times
    rows["source_line"] = np.arange(1,len(times)+1)
    rows["normal"] = 1
    if name=="先行気配欠測":
        rows["normal"][(times>900)&(times<1260)] = 0
    move = np.full(len(times),-10.0)
    move[(times>=DUE-120)&(times<DUE)] = -40.0 if name=="逆行で見送る" else 30.0
    move[times>=DUE] = 60.0
    move[times>=DUE+120] = 10.0
    if name=="直前静的先着":
        move[times==DUE-1] = 100.0
    if name=="期限瞬間の先着":
        move[times==DUE] = 100.0
    if side==0:
        rows["bid"] = 1000.0+move
        rows["ask"] = rows["bid"]+10
    else:
        rows["ask"] = 1000.0-move
        rows["bid"] = rows["ask"]-10
    # ----------------------------------------
    scene = dict(SCENE,end=(DUE+960 if name=="場末競合" else SCENE["end"]))
    index = ENGINE["FINANCE"]["early179"].PriceIndex(rows)
    entry = int(times.searchsorted(OPEN))
    static = ENGINE["exits"](index,scene,MODEL["STATIC"])
    dynamic = MODEL["by_scene"](index,scene,static)
    old = static("D00",entry,side,100.0,"H60")
    results = {code:dynamic(f"{code}_{delay}",entry,side,100.0,"H60") for code in ("T03","T04","T05","T06")}
    return old,results


def main() -> None:
    """
    機能：旧期限に正常返済できない未来を含め、判断が同一の過去だけから決まることを検査する。
    引数：なし。45場の正本と修正前のSHA256も照合する。
    返り値：None。各人工シナリオの確認件数と、実績の一致検査を作業領域へ保存する。
    """
    cases = ("通常","遅着","将来欠測","期限後打切","逆行で見送る","直前板なし","直前静的先着","期限瞬間の先着",
             "先行価格欠測","先行気配欠測","直前の観測中断","場末競合")
    covered = {name:0 for name in cases}
    for side in (0,1):
        for delay in (1,3,5):
            common = {}
            for name in cases:
                base,results = run_case(name,side,delay)
                if name in ("通常","期限瞬間の先着"):
                    assert base["status"]==(1 if name=="期限瞬間の先着" else 3)
                elif name in ("遅着","将来欠測","期限後打切","逆行で見送る","直前板なし","先行価格欠測","先行気配欠測","直前の観測中断"):
                    assert base["net"] is None
                for code,row in results.items():
                    covered[name]+=1
                    eligible = name not in ("直前静的先着","先行価格欠測","先行気配欠測","直前の観測中断","場末競合")
                    assert row["eligible_for_extension"]==eligible
                    expect = eligible and (code=="T03" or name not in ("直前板なし","逆行で見送る"))
                    assert row["extended"]==expect
                    decision = tuple(row[k] for k in ("eligible_for_extension","extended","extension_quote_time",
                                                       "extension_mark_r","extension_efficiency"))
                    if name=="通常":
                        common[code] = decision
                    if name in ("遅着","将来欠測","期限後打切","期限瞬間の先着"):
                        assert decision==common[code]
                    if name in ("通常","遅着") and code!="T06":
                        assert row["status"]==5 and row["activation_time"]==DUE+(5 if name=="通常" else 45)
                    if name in ("将来欠測","期限後打切","先行価格欠測","先行気配欠測","直前の観測中断"):
                        assert row["exit_time"] is None and row["net"] is None and row["status"]>=10
                    if name in ("直前静的先着","期限瞬間の先着"):
                        assert row["status"]==1 and row["exit_time"]==(DUE-1 if name=="直前静的先着" else DUE)
                    if name in ("逆行で見送る","直前板なし") and not expect:
                        assert row["net"] is None
    # ----------------------------------------
    work = MODEL["ROOT"]/"work/221期限保護"
    actual = {name:sha256((work/(name+".json")).read_bytes()).hexdigest() for name in CONTROL_HASHES}
    assert actual==CONTROL_HASHES and all(count==24 for count in covered.values())
    report = {"実績元帳SHA256":actual,"人工例での候補・売買・遅延の組数":covered}
    (work/"60分境界の回帰結果.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
    print(sum(covered.values()))


if __name__=="__main__":
    main()
