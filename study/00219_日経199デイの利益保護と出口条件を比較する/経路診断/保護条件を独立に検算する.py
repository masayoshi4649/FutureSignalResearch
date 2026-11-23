"""W31とW36の事前決定・発動・約定順序を、出口実装を使わず順番にたどる。"""
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import runpy

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = runpy.run_path(str(HERE/"元の保有経路を測る.py"))


def check(rows: np.ndarray, normals: np.ndarray, start: float, trade: dict, code: str) -> None:
    """
    機能：取得前の終値系列で損切り幅を定め、正常気配を順に読んで決済と追尾を独立に計算する。
    引数：rows（np.ndarray）は時刻順原行、normals（np.ndarray）は正常BBOの行番号、start（float）はデイ開始、
          trade（dict）は既知決済の建玉、code（str）はW31またはW36。
    返り値：None。初期倍率・初回発動・利益床・初回返済要求・決済原行と区分の一致を確認する。
    """
    entry, opened, width = trade["entry_index"], trade["entry_time"], trade["width"]
    minute = int((opened-start)//60)
    scale = 1.0
    if code=="W31" and minute>=165:
        closes = []
        for offset in range(minute-13, minute):
            block = normals[(rows["time"][normals]>=start+60*offset) & (rows["time"][normals]<start+60*(offset+1))]
            if len(block):
                bar = rows[block[-1]]
                closes.append((bar["bid"]+bar["ask"])*.5)
        if len(closes)==13:
            distance = sum(abs(v-u) for u,v in zip(closes,closes[1:]))
            if not distance or abs(closes[-1]-closes[0])/distance<=.35:
                scale = 1.10
    assert scale==trade["initial_stop_multiple"]
    # ----------------------------------------
    horizon = trade["horizon"]
    cut = start+(6*60+45)*60
    nominal = float("inf") if horizon=="SESSION" else opened+int(horizon[1:])*60
    prices = rows["bid" if trade["side"]==0 else "ask"]
    sign = 1 if trade["side"]==0 else -1
    peak, activation, signal, floor = float("-inf"), -1, -1, None
    start_r = .95 if horizon=="SESSION" else .90
    end = trade["exit_index"]
    assert end>=0
    ids = normals[(normals>entry)&(normals<=end)]
    assert len(ids) and ids[-1]==end
    assert max(np.diff(rows["time"][np.r_[entry,ids]]))<=300
    for idx in ids:
        t = rows["time"][idx]
        move = sign*(prices[idx]-trade["entry_price"])
        # 指値・非常停止が同じ原行で完成するなら追尾からの執行より優先する。
        loss_hit = 10*move<=-(11 if scale>1 else 10)*width
        if t<=min(cut,nominal) and (move>=width or loss_hit):
            status = 1 if move>=width else 2
            break
        if t>=cut-59:
            assert t<=cut
            status = 4
            break
        if t>=nominal:
            assert t<=nominal+30
            status = 3
            break
        if signal>=0:
            if t>=rows["time"][signal]+1:
                status = 5
                break
            continue
        previous = activation
        peak = max(peak,move)
        if peak>=width*start_r:
            if activation<0:
                activation = idx
            floor = max(20.,peak-.70*width)
        if previous>=0 and move<=floor:
            signal = idx
    else:
        raise AssertionError((code,trade["scene"],entry,"決済理由なし"))
    assert (idx,status)==(end,trade["status"]), (code,trade["scene"],entry,idx,status,end,trade["status"])
    assert (activation,signal,floor)==(trade["activation_index"],trade["trigger_index"],trade["floor_points"])
    assert trade["activation_time"] == (None if activation<0 else rows["time"][activation])
    assert trade["trigger_time"] == (None if signal<0 else rows["time"][signal])


def main() -> None:
    """
    機能：45デイの口座再生と入口固定について、2出口すべての保護条件を別経路で照合する。
    引数：なし。先にW系列を口座再生し、価格索引を準備する。
    返り値：None。確認した条件適用・追尾の起動・返済の件数を保存する。
    """
    books = json.loads((ROOT/"work/219逆行/比較元帳.json").read_bytes())
    versions, by_scene = {}, defaultdict(list)
    archives = SOURCE["archives"]()
    for mode,accounts in books.items():
        for code in ("W31","W36"):
            rows = accounts[code]
            versions[mode+"_"+code] = {"件数":len(rows),"損幅を1.10倍":sum(t["initial_stop_multiple"]>1 for t in rows),
                "追尾起動":sum(t["activated"] for t in rows),"追尾の返済":sum(t["status"]==5 for t in rows)}
            for trade in rows:
                by_scene[trade["scene"]].append((code,trade))
    for scene,trades in by_scene.items():
        data = SOURCE["load_records"](*archives[scene])
        normals = np.flatnonzero((data["normal"]==1) & (data["bid"]>0) & (data["ask"]>data["bid"]))
        start = datetime.fromisoformat(scene[:10]+"T08:45:00+09:00").timestamp()
        for code,trade in trades:
            check(data,normals,start,trade,code)
    (HERE/"利益保護の独立照合.json").write_text(json.dumps(versions,ensure_ascii=False,indent=2)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
