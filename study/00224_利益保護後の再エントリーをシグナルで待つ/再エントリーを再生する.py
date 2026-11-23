"""追尾返済後のシグナル再成立・価格到達で予約を再開し、実際に建てた取引を記録する。"""
from argparse import ArgumentParser
from functools import lru_cache
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = runpy.run_path(str(next(HERE.parent.glob("00222_*/建玉制限を再生する.py"))))
TRIAL = next(HERE.parent.glob("00223_*"))
POLICIES = {"P":runpy.run_path(str(TRIAL/"値幅による保護/失速の追試.py")),
            "S":runpy.run_path(str(TRIAL/"価格構造で保護/出口条件.py"))}
NAMES = {"P":"P20","S":"S00"}
ORIGINAL = {"P":"223値幅追試","S":"223構造"}
ENGINE = BASE["ENGINE"]
SOURCE = BASE["SOURCE"]
GATES = ("A","B","N","C","D")


def suppressed_rows(rule: str, t: dict, times: np.ndarray, signal: np.ndarray,
                    valid: np.ndarray, original: object) -> tuple:
    """
    機能：実返済の次秒から、解除条件をその原行までに観測できる最初の時点まで新規を抑止する。
    引数：rule（str）は再開条件、t（dict）は追尾で決済した建玉、times・signal・valid（np.ndarray）は
    当時の判断時計・有効な主入口の符号・正常気配の有無、original（callable）は元の価格先着を返す。
    返り値：tuple[int,int]。保有を終えてから、新規を抑止すべき判断原行の半開区間。
    """
    start = int(np.searchsorted(times,t["exit_time"],side="right"))
    end = len(times)
    side = 1 if t["side"]==0 else -1
    allowed_by_signal = end
    if rule in ("B","N","D"):
        change = signal[start:]!=side if rule=="N" else signal[start:]==-side
        hits = np.flatnonzero(change & valid[start:])
        if len(hits):
            allowed_by_signal = start+int(hits[0])
    if rule in ("B","N"):
        return start,allowed_by_signal
    assert rule in ("C","D")
    ref = original(t["entry_index"],t["side"],t["width"])
    if ref["exit_time"] is None:
        if allowed_by_signal<end and times[allowed_by_signal]>ref["confirmed_until"]:
            allowed_by_signal = end
        allowed_by_price = end
    else:
        assert ref["exit_time"]>=t["exit_time"]
        allowed_by_price = int(np.searchsorted(times,ref["exit_time"],side="right"))
    return start,min(allowed_by_signal,allowed_by_price)


def account(stream: tuple, scene: dict, index: object, code: str, close: object,
            original: object, rule: str) -> tuple:
    """
    機能：順に実現した追尾返済だけに新規禁止区間を設け、未決予約も含む元の1枠エンジンで再生する。
    引数：stream（tuple）は当該待機の全要求、scene（dict）とindex（PriceIndex）は当日、code・rule（str）は
    出口名・再開方針、close・original（callable）は実返済・元の価格到達の評価。
    返り値：tuple[list,list]。実建玉元帳と、追尾以後に抑止した実際の要求の監査。
    """
    keys,captures,arrays = stream
    signals = arrays["core"].copy()
    widths = np.where(arrays["branches"]==0,arrays["mw"],arrays["fw"])
    signals[widths==0] = 0
    times = np.asarray([k[0] for k in keys])
    valid = index.rows["normal"][arrays["index"]].astype(bool)
    filtered = dict(arrays)
    for key in ("core","technical","branches"):
        filtered[key] = arrays[key].copy()
    gates = []
    last_exit = -np.inf
    while True:
        book,audit = ENGINE["replay"]((keys,captures,filtered),scene,code,close)
        assert audit["peak_global_reserved"]<=1
        if rule=="A":
            return book,gates
        next_closed = next((r for r in book if r["status"]==5 and r["exit_time"]>last_exit),None)
        if next_closed is None:
            return book,gates
        last_exit = next_closed["exit_time"]
        start,end = suppressed_rows(rule,next_closed,times,signals,valid,original)
        assert start<=end<=len(keys)
        count = int(np.count_nonzero(signals[start:end]))
        gates.append({"新規原行":next_closed["entry_line"],"実返済原行":next_closed["exit_line"],
                      "実返済秒":last_exit,"最初の再開可能判断秒":float(times[end]) if end<len(times) else None,
                      "抑止判断行":end-start,"抑止した有効主入口":count})
        # 過去に処理済みの取得までの要求を保存し、影響した区間以降の予約だけが変わる。
        filtered["core"][start:end] = 0
        filtered["technical"][start:end] = 0
        filtered["branches"][start:end] = -1


def day(arrays: dict, number: int, scene: dict, index: object, families: dict, gates: tuple) -> tuple:
    """
    機能：指定したデイを対象の出口と再開規則それぞれで、開始20・30分の待機で金融再生する。
    引数：arrays（dict）は日経199の純入口、number（int）は場位置、scene（dict）は場、index（PriceIndex）は板、
    families（dict）は入口と出口の対応、gates（tuple）は今回再生する再開方法。
    返り値：tuple[dict,dict]。候補別口座と、各休止区間の監査。
    """
    orders = ENGINE["orders"](arrays,number,scene,index)
    static = ENGINE["exits"](index,scene,BASE["POLICY"]["STATIC"])

    @lru_cache(maxsize=None)
    def original(entry: int, side: int, width: float) -> dict:
        """
        機能：元の±1Rの静的注文と場末に最初に達した時計を得る。
        引数：entry・side（int）は新規原行・実側、width（float）は元の片幅。
        返り値：dict。正常板の先着または観測打切。参照価格経路の仮想利益は口座へ計上しない。
        """
        return static("D00",entry,side,width,"SESSION")

    books,proof = {},{}
    for family,(name,policy,_) in families.items():
        if "prepare_signals" in policy:
            fields = ("index","line","time","core","branches","mw","fw")
            context = policy["prepare_signals"](index,scene,{k:orders[2][k] for k in fields})
            policy = dict(policy,prepare=lambda _index,_scene:context)
        dynamic = ENGINE["exits"](index,scene,policy)

        def close(code: str, entry: int, side: int, width: float, horizon: str) -> dict:
            """
            機能：元の価格注文と保護を、場末まで時間制限なく再生する。
            引数：code・horizon（str）は保護条件と入口の旧属性、entry・side（int）は新規・向き、width（float）は幅。
            返り値：dict。実決済の価格・時刻・保護情報。入口の旧期限は属性として記録する。
            """
            t = dynamic(code,entry,side,width,"SESSION")
            assert t["status"]!=3
            return dict(t,horizon=horizon,exit_horizon="SESSION")

        for wait in (20,30):
            selected = BASE["after_open"](orders,scene["start"]+wait*60)
            for rule in gates:
                key = family+rule+str(wait)
                books[key],proof[key] = account(selected,scene,index,name,close,original,rule)
    return books,proof


def main() -> None:
    """
    機能：45デイを再生し、即再開を試行223の口座、元価格まで休止を元取得固定の結果と照合する。
    引数：CLI --出力（Path）は口座と監査の作業先、--反対信号追試（bool）はR02のA/Cだけを再生。
    返り値：None。全45日参加・未知の有無にかかわらず元帳を保存する。
    """
    parser = ArgumentParser()
    parser.add_argument("--出力",type=Path)
    parser.add_argument("--反対信号追試",action="store_true")
    args = parser.parse_args()
    families = {f:(NAMES[f],policy,ORIGINAL[f]) for f,policy in POLICIES.items()}
    gates = GATES
    if args.反対信号追試:
        policy = runpy.run_path(str(TRIAL/"反対の入口シグナル/出口条件.py"))
        families = {"R":("R02",policy,"223反対")}
        gates = ("A","C")
    output = args.出力 or ROOT/("work/224反対追試" if args.反対信号追試 else "work/224再開")
    previous = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    dates = previous["対象場"]
    books = {family+rule+str(wait):[] for family in families for rule in gates for wait in (20,30)}
    audits = {}
    for folder,archive,member,manifest in SOURCE["parts"]():
        scenes,arrays,*_ = SOURCE["inputs"](folder,archive,member)
        ref = {s["session"]:s for s in SOURCE["read"](manifest)["scenes"]}
        for n,scene in enumerate(scenes):
            name = scene["session"]
            if name not in dates or name in audits:
                continue
            index = ENGINE["FINANCE"]["load_scene"](manifest.parent,ref[name])
            rows,audits[name] = day(arrays,n,scene,index,families,gates)
            for code,b in rows.items():
                books[code].extend(b)
    assert set(audits)==set(dates)
    # ----------------------------------------
    key = ("scene","request_line","request_time","entry_line","entry_time","entry_price","side","width",
           "exit_line","exit_time","exit_price","net","status","activation_time","trigger_time")
    for family,(name,_,folder) in families.items():
        old = json.loads((ROOT/"work"/folder/"比較元帳.json").read_bytes())
        for wait in (20,30):
            source = f"{name}_{wait}"
            assert books[f"{family}A{wait}"]==old["口座再生"][source]
            assert all(all(a[k]==b[k] for k in key)
                       for a,b in zip(books[f"{family}C{wait}"],old["入口固定"][source],strict=True))
    output.mkdir(parents=True,exist_ok=True)
    payload = {"対象場":dates,"開始待機分":{k:int(k[-2:]) for k in books},"口座再生":books}
    for name,obj in (("口座元帳",payload),("予約休止照合",audits)):
        (output/(name+".json")).write_text(json.dumps(obj,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
