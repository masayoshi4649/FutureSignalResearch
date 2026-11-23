"""元の利確・損切を置いたまま、60分期限から場末期限へ変えた効果を診断する。"""
from hashlib import sha256
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ENGINE = runpy.run_path(str(next((ROOT/"study").glob("00219_*/口座再生.py"))))
POLICY = runpy.run_path(str(HERE/"出口定義.py"))
KEYS = ("scene","entry_line","request_line","side","exit_line","entry_time","exit_time","net")


def extend(settle: object):
    """
    機能：現在の建玉の出口期限だけを場末へ延長し、当時の入口が指定した期限も記録する。
    引数：settle（callable）は当日板の期限・約定を再生する219関数。
    返り値：callable。既存の予約エンジンに渡す決済関数。
    """
    def at(code: str, entry: int, side: int, width: float, horizon: str) -> dict:
        """
        機能：±1Rの利確・損切を維持し、場末までに成立した元注文と取得時の期限指定を保存する。
        引数：code・horizon（str）は診断と元の期限、entry・side（int）は原行と向き、width（float）は片幅。
        返り値：dict。場末を最長とした実返済または不明。
        """
        assert code=="D04"
        trade = settle("D00",entry,side,width,"SESSION")
        return dict(trade,horizon=horizon,exit_horizon="SESSION",exit_strategy=code)
    return at


def main() -> None:
    """
    機能：原板と元の入口要求を場ごとに読み、分期限を場末まで延長した口座と入口固定の診断を作る。
    引数：なし。試行219の原板索引とD00の再生元帳を使う。
    返り値：None。試行用の比較元帳と照合指紋を書き出す。
    """
    base_path = ROOT/"work/221元IFD/比較元帳.json"
    previous = json.loads(base_path.read_bytes())
    books = {mode:{"IFD":group["IFD"],"D04":[]} for mode,group in previous.items()}
    base = books["口座再生"]["IFD"]
    days = {row["scene"] for row in base}
    done = set()
    source = ENGINE["SOURCE"]
    # ----------------------------------------
    for folder,archive,member,manifest in source["parts"]():
        scenes,arrays,*_ = source["inputs"](folder,archive,member)
        lookup = {row["session"]:row for row in source["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            day = scene["session"]
            if day not in days or day in done:
                continue
            done.add(day)
            index = ENGINE["FINANCE"]["load_scene"](manifest.parent,lookup[day])
            stream = ENGINE["orders"](arrays,i,scene,index)
            static = ENGINE["exits"](index,scene,POLICY)
            rows,_ = ENGINE["replay"](stream,scene,"IFD",static)
            refs = [row for row in base if row["scene"]==day]
            assert all(all(a[k]==b[k] for k in KEYS) for a,b in zip(rows,refs,strict=True))
            late = extend(static)
            account,_ = ENGINE["replay"](stream,scene,"D04",late)
            books["口座再生"]["D04"].extend(account)
            for t in refs:
                changed = late("D04",t["entry_index"],t["side"],t["width"],t["horizon"])
                books["入口固定"]["D04"].append(dict(t,**changed))
    assert done==days and len(done)==45 and len(books["入口固定"]["D04"])==181
    out = ROOT/"work/221期限寄与"
    out.mkdir(parents=True,exist_ok=True)
    (out/"比較元帳.json").write_text(json.dumps(books,ensure_ascii=False,allow_nan=False),encoding="utf8")
    proof = {"元IFD元帳SHA256":sha256(base_path.read_bytes()).hexdigest(),"元口座照合件数":len(base),
             "期限診断SHA256":sha256(Path(__file__).read_bytes()).hexdigest(),"対象場":sorted(done)}
    (out/"再生照合.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf8")


if __name__=="__main__":
    main()
