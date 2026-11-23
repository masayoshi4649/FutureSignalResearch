"""試行227の1秒執行を原行と照合し、W08・W12の発動時に使えた情報を独立集計する。"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VERIFY = runpy.run_path(str(next((ROOT/"study").glob("00219_*/経路診断/出口の原行を照合する.py"))))
SOURCE = runpy.run_path(str(next((ROOT/"study").glob("00217_*/日経/入口を再生する.py"))))


def completed(records: np.ndarray, start: float, boundary: float) -> np.ndarray:
    """
    機能：判断原行の属する分より前だけで、開始から直前の完成1分までの正常気配中値終値を作る。
    引数：records（np.ndarray）は原行、start・boundary（float）は開始と最新完成足の終了秒。
    返り値：np.ndarray。欠分はNaNの1分終値時系列。
    """
    valid = records[(records["normal"]==1) & (records["time"]>=start) & (records["time"]<boundary)]
    closes = np.full(round((boundary-start)/60),np.nan)
    minute = ((valid["time"]-start)//60).astype(int)
    last = np.r_[minute[1:]!=minute[:-1],True]
    closes[minute[last]] = (valid["bid"][last]+valid["ask"][last])/2
    return closes


def verify_signal(code: str, records: np.ndarray, trade: dict, start: float, signed_signals: tuple) -> None:
    """
    機能：追加判断時点より前の正常気配・主入口だけで、W08・W12の価格・方向・時間条件を検算する。
    引数：code（str）はW08又はW12、records（np.ndarray）は原行、trade（dict）は建玉、
    start（float）は場開始、signed_signals（tuple）は有効な主入口の価格原行と売買符号。
    返り値：None。条件が成立しない元帳や先行成績を使った兆候を検出した場合に停止する。
    """
    stamp,entry = trade["extra_signal"],trade["entry_index"]
    current = records["time"][stamp]
    boundary = start+((current-start)//60)*60
    assert records["normal"][stamp]==1 and entry<stamp and records["time"][entry]<boundary<=current
    sign = 1 if trade["side"]==0 else -1
    prices = records[entry+1:stamp+1]
    path = prices[prices["normal"]==1]
    move = (path["bid" if sign==1 else "ask"]-trade["entry_price"])*sign
    width = trade["width"]
    closes = completed(records,start,boundary)
    missing = np.flatnonzero(~np.isfinite(closes))
    tail = closes[missing[-1]+1:] if len(missing) else closes
    assert len(tail)>=8
    fast = slow = float(tail[0])
    spread_change = 0.0
    for price in tail[1:]:
        old_spread = fast-slow
        fast += (price-fast)*.5
        slow += (price-slow)*2/9
        spread_change = (fast-slow)-old_spread
    length = np.abs(np.diff(tail[-4:])).sum()
    efficiency = sign*(tail[-1]-tail[-4])/length if length else 0.0
    # ----------------------------------------
    if code=="W08":
        assert move.max()>=.25*width and move[-1]>=20
        contracted = (len(tail)>=11 and tail[-11:-3].std()>0 and tail[-8:].std()<=.75*tail[-11:-3].std())
        assert (sign*spread_change<0 and efficiency<=0) or (contracted and sign*(tail[-1]-fast)<0)
        rows,sides = signed_signals
        latest = rows.searchsorted(stamp,side="right")-1
        assert latest>=0 and rows[latest]>entry and sides[latest]==-sign and current-records["time"][rows[latest]]<=90
    else:
        assert code=="W12" and (boundary-start)%300==0 and len(tail)>=15
        assert sign*(tail[-6]-tail[-11])>0 and sign*(tail[-1]-tail[-6])<0
        assert sign*(tail[-1]-slow)<0 and efficiency<=-.5
        prior = move[path["time"]<boundary]
        assert len(prior) and prior.max()>=.80*width and move[-1]>=.60*width
    # 追加床接触の最初の原行も、候補関数とは別の逐次処理で再評価する。
    if trade["extra_fill"]:
        path = records[stamp:trade["trigger_index"]+1]
        path = path[path["normal"]==1]
        move = (path["bid" if sign==1 else "ask"]-trade["entry_price"])*sign
        peak = float(move[0])
        for row,v in zip(path[1:],move[1:],strict=True):
            peak = max(peak,v)
            if v<=max(20,peak-.15*width):
                assert row["source_line"]==records["source_line"][trade["trigger_index"]]
                break
        else:
            raise ValueError("追加追尾の床に達した原行がありません。")


def main() -> None:
    """
    機能：全30方策×両待機について、取得・決済と清算側極値を検算し、W08・W12の実例も点検する。
    引数：なし。work/227各群の1秒執行元帳と固定199_02入口を用いる。
    返り値：None。群別の検算件数と方向別追加判断を作業領域に保存する。
    """
    groups = {"弱反転":8,"出来高":6,"停滞":6,"確定足転換":6,"量回復":4}
    trades = defaultdict(list)
    counts = {}
    samples = defaultdict(dict)
    for group,variants in groups.items():
        payload = json.loads((ROOT/f"work/227{group}/口座元帳.json").read_bytes())
        book = payload["口座再生"]
        assert len(book)==variants*2 and all(len(rows)==133 for rows in book.values())
        counter = Counter()
        for code,rows in book.items():
            for t in rows:
                counter.update(取得=1,未知=int(t["net"] is None),動的返済=int(t["status"]==5),追加返済=int(t["extra_fill"]))
                trades[t["scene"]].append(t)
                if code[:3] in ("W08","W12") and t["extra_signal"]>=0:
                    key = code[:3],t["entry_index"],t["side"],t["extra_signal"],t["extra_fill"]
                    samples[t["scene"]][key] = t
        counts[group] = dict(counter)
    # ----------------------------------------
    fingerprints = ("entry_index","entry_line","side","entry_price","entry_time","exit_index","exit_line","exit_price",
                    "exit_time","net","gross","status","trigger_time","trigger_index","max_unrealized_net",
                    "min_unrealized_net","max_unrealized_time","min_unrealized_time")
    archive = VERIFY["SOURCE"]["archives"]()
    assert len(trades)==45
    for scene,rows in trades.items():
        raw = VERIFY["SOURCE"]["load_records"](*archive[scene])
        for t in rows:
            for key in ("extra_signal","extra_trigger","activation_index"):
                stamp = t[key]
                clock = t["activation_time" if key=="activation_index" else key+"_time"]
                if stamp<0:
                    assert clock is None
                else:
                    assert t["entry_index"]<stamp<t["exit_index"] and raw["normal"][stamp]
                    assert raw["time"][stamp]==clock
            assert t["activated"]==(t["activation_index"]>=0)
            if t["extra_trigger"]>=0:
                assert 0<=t["extra_signal"]<=t["extra_trigger"]
            if t["extra_fill"]:
                assert t["extra_trigger"]==t["trigger_index"] and t["status"]==5
        unique = {tuple(t.get(k) for k in fingerprints):t for t in rows}
        for t in unique.values():
            VERIFY["verify"](raw,t)
    # ----------------------------------------
    verified = set()
    sides = Counter()
    for folder,archive_file,member,_ in SOURCE["parts"]():
        scenes,arrays,*_ = SOURCE["inputs"](folder,archive_file,member)
        for i,scene in enumerate(scenes):
            name = scene["session"]
            if name not in samples or name in verified:
                continue
            raw = VERIFY["SOURCE"]["load_records"](*archive[name])
            valid = ((arrays["scene"]==i) & (arrays["time"]<scene["end"]-960) & (arrays["core"]!=0) &
                     (np.where(arrays["branches"]==0,arrays["mw"],arrays["fw"])>0))
            signal = arrays["index"][valid],arrays["core"][valid]
            assert np.array_equal(raw["time"][signal[0]],arrays["time"][valid])
            assert np.array_equal(raw["source_line"][signal[0]],arrays["line"][valid])
            for key,t in samples[name].items():
                verify_signal(key[0],raw,t,scene["start"],signal)
                sides[(key[0],"買" if t["side"]==0 else "売",bool(t["extra_fill"]))] += 1
            verified.add(name)
    assert verified==set(samples)
    report = {"群別検算":counts,"固有の追加判断":{str(k):v for k,v in sides.items()}}
    directory = ROOT/"work/227原行照合"
    directory.mkdir(exist_ok=True)
    (directory/"検算件数.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()
