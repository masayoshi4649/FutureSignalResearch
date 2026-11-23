"""20分・30分待機の同じ日経入口に、保有期限なしの出口を適用する。"""
import argparse
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LAST = runpy.run_path(str(next(HERE.parent.glob("00222_*/建玉制限を再生する.py"))))
ENGINE = LAST["ENGINE"]
SOURCE = LAST["SOURCE"]


def day(orders: tuple, scene: dict, index: object, policy: dict, codes: list, baselines: dict) -> dict:
    """
    機能：一日の全新規要求を予約から再生し、単純IFDの取得だけを各出口で返す比較も行う。
    引数：orders（tuple）は全要求、scene・policy・baselines（dict）は場・出口定義・待機別の元取得、
    index（PriceIndex）は板、codes（list[str]）は出口ID。
    返り値：dict。口座再生・同一入口固定それぞれの候補別元帳。
    """
    if "prepare_signals" in policy:
        fields = ("index","line","time","core","branches","mw","fw")
        known = {key:orders[2][key] for key in fields}
        context = policy["prepare_signals"](index,scene,known)
        policy = dict(policy,prepare=lambda _index,_scene:context)
    settle = ENGINE["exits"](index,scene,policy)

    def close(code: str, entry: int, side: int, width: float, horizon: str) -> dict:
        """
        機能：入口の元属性を残し、全建玉でセッションの許可時間内に価格注文・保護を処理する。
        引数：code・horizon（str）は候補・旧入口属性、entry・side（int）は原行・売買、width（float）は片幅。
        返り値：dict。保有時間上限なしの出口での決済情報。
        """
        result = settle(code,entry,side,width,"SESSION")
        assert result["status"]!=3
        return dict(result,horizon=horizon,exit_horizon="SESSION")

    result = {"口座再生":{},"入口固定":{}}
    for wait in (20,30):
        eligible = LAST["after_open"](orders,scene["start"]+wait*60)
        for code in codes:
            key = f"{code}_{wait}"
            book,_ = ENGINE["replay"](eligible,scene,code,close)
            result["口座再生"][key] = book
            result["入口固定"][key] = [dict(t,**close(code,t["entry_index"],t["side"],t["width"],t["horizon"]))
                                         for t in baselines[wait]]
    return result


def main() -> None:
    """
    機能：候補群の出口を45日の原板と両待機の入口に適用し、原行付きの比較元帳を保存する。
    引数：CLIの --定義・--出力（Path）、--候補（任意の文字列列）。
    返り値：None。指定作業先へ比較元帳JSONを出力する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--定義",type=Path,required=True)
    parser.add_argument("--出力",type=Path,required=True)
    parser.add_argument("--候補",nargs="+")
    args = parser.parse_args()
    policy = runpy.run_path(str(args.定義))
    codes = args.候補 or list(policy["POLICIES"])
    assert len(codes)==len(set(codes)) and set(codes)<=set(policy["POLICIES"])
    baseline = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    dates = baseline["対象場"]
    books = {"口座再生":{},"入口固定":{}}
    observed = set()
    for folder,archive,member,manifest in SOURCE["parts"]():
        scenes,arrays,*_ = SOURCE["inputs"](folder,archive,member)
        lookup = {s["session"]:s for s in SOURCE["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            session = scene["session"]
            if session not in dates or session in observed:
                continue
            observed.add(session)
            index = ENGINE["FINANCE"]["load_scene"](manifest.parent,lookup[session])
            orders = ENGINE["orders"](arrays,i,scene,index)
            refs = {n:[t for t in baseline["口座再生"][f"I{n}"] if t["scene"]==session] for n in (20,30)}
            groups = day(orders,scene,index,policy,codes,refs)
            for mode,accounts in groups.items():
                for name,rows in accounts.items():
                    books[mode].setdefault(name,[]).extend(rows)
    # ----------------------------------------
    assert observed==set(dates)
    assert all(len(rows)==133 for rows in books["入口固定"].values())
    args.出力.mkdir(parents=True,exist_ok=True)
    (args.出力/"比較元帳.json").write_text(json.dumps(books,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
