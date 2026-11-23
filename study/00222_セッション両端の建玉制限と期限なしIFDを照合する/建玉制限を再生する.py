"""セッション両端のノーポジションを予約から適用し、建玉ごとの時間制限を設けずに比較する。"""
from bisect import bisect_left
from hashlib import sha256
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT/"work/222境界照合"
PRIOR = next(HERE.parent.glob("00221_*"))
POLICY = runpy.run_path(str(PRIOR/"元IFDの寄与/期限延長と追尾を組み合わせる.py"))
ENGINE = POLICY["ENGINE"]
SOURCE = ENGINE["SOURCE"]
SUMMARY = SOURCE["SUMMARY"]
WAITS = (0,15,20,30)


def after_open(stream: tuple, allowed: float) -> tuple:
    """
    機能：判断時刻が待機終了以降の要求・取得対応だけを、一枚口座へ予約を渡す前に残す。
    引数：stream（tuple）は219の要求時刻・予約結果・入口配列、allowed（float）は許可時刻のUnix秒。
    返り値：tuple。境界同秒を含む元要求の接尾列。待機中に出た遅い予約の成立は引き継がない。
    """
    keys,fills,arrays = stream
    pos = bisect_left(keys,(allowed,))
    assert (not pos or keys[pos-1][0]<allowed) and (pos==len(keys) or keys[pos][0]>=allowed)
    return keys[pos:],fills[pos:],{k:v[pos:] for k,v in arrays.items()}


def replay_day(arrays: dict, i: int, scene: dict, index: object, wait_minutes: tuple) -> tuple:
    """
    機能：1デイの入口要求から開始待機別に固定両注文と追尾付きの期限なし口座を再生する。
    引数：arrays（dict）は純入口、i（int）は場番号、scene（dict）は場定義、index（PriceIndex）は価格索引、
    wait_minutes（tuple[int, ...]）は開始待機の分数。
    返り値：tuple。候補ID別の建玉と開始待機別の除外予約数。
    """
    stream = ENGINE["orders"](arrays,i,scene,index)
    assert all(a<=b for a,b in zip(stream[0],stream[0][1:]))
    opened,cut = SUMMARY["windows"](scene["session"],"全体")
    assert opened==scene["start"] and cut==scene["end"]-900
    static = ENGINE["exits"](index,scene,POLICY["STATIC"])
    decisions = {"I":POLICY["ORIGINAL"]["extend"](static),"T":POLICY["by_scene"](index,scene,static)}
    proof,books = {},{}
    for wait in wait_minutes:
        allowed = opened+60*wait
        valid = after_open(stream,allowed)
        gated = len(stream[0])-len(valid[0])
        crossing = sum(f["status"]=="filled" and f["fill_key"][0]>=allowed for f in stream[1][:gated])
        proof[str(wait)] = {"開始前要求除外":gated,"うち開始以後に取得予定だった要求":crossing}
        for kind,strategy in (("I","D04"),("T","T02_1")):
            tag = kind+f"{wait:02d}"
            account,audit = ENGINE["replay"](valid,scene,strategy,decisions[kind])
            assert audit["peak_global_reserved"]<=1
            if kind=="T":
                account = [dict(t,exit_strategy="T02") for t in account]
            assert all(t["exit_horizon"]=="SESSION" and t["status"]!=3 for t in account)
            books[tag] = account
    return books,proof


def measures(dates: list, book: list, wait: int) -> tuple:
    """
    機能：両端を除いた対象時間で保有率を求め直し、未知を除外せず収支・利益後赤字を集計する。
    引数：dates（list）は対象日の一覧、book（list）は期間の口座元帳、wait（int）は開始待機分。
    返り値：tuple。日別と期間計の辞書。損失欄は費用後赤字の絶対額。
    """
    daily,total = SUMMARY["calculate"](dates,book,"全体")
    denominator,holding = 0,0
    for day in daily:
        opened,cut = SUMMARY["windows"](day["場"],"全体")
        allowed = opened+wait*60
        trades = [t for t in book if t["scene"]==day["場"]]
        assert all(allowed<=t["request_time"]<=t["entry_time"]<cut-60 for t in trades)
        assert all(t["confirmed_until"]<=cut and (t["exit_time"] is None or t["exit_time"]<=cut) for t in trades)
        held = sum(t["confirmed_until"]-t["entry_time"] for t in trades)
        assert 0<=held<=cut-allowed
        assert abs(held/(cut-opened)-day["保有率"])<1e-9
        day["保有秒"],day["対象秒"],day["保有率"] = held,cut-allowed,held/(cut-allowed)
        denominator += cut-allowed
        holding += held
    total["保有率"] = holding/denominator
    members = set(dates)
    lost = [t for t in book if t["scene"] in members and t["max_unrealized_net"]>0 and t["net"] is not None and t["net"]<0]
    total["利益後赤字件数"] = len(lost)
    total["利益後赤字損失"] = -sum(t["net"] for t in lost)
    return daily,total


def main() -> None:
    """
    機能：全45デイの時間順に元の入口を処理し、開始待機4水準×出口2種類の口座と日別結果を作る。
    引数：なし。元入口の板索引・純入口、221の開始待機なし参照元帳を読む。
    返り値：None。作業領域に全取引・日別・照合数、試行に全条件のMarkdown表を保存する。
    """
    dates,_,_ = SUMMARY["sources"]("デイ")
    waits = {kind+f"{wait:02d}":wait for kind in ("I","T") for wait in WAITS}
    books = {tag:[] for tag in waits}
    proof,seen = {},set()
    for folder,archive,member,manifest in SOURCE["parts"]():
        scenes,arrays,*_ = SOURCE["inputs"](folder,archive,member)
        lookup = {s["session"]:s for s in SOURCE["read"](manifest)["scenes"]}
        for i,scene in enumerate(scenes):
            day = scene["session"]
            if day not in dates or day in seen:
                continue
            seen.add(day)
            index = ENGINE["FINANCE"]["load_scene"](manifest.parent,lookup[day])
            accounts,proof[day] = replay_day(arrays,i,scene,index,WAITS)
            for tag,account in accounts.items():
                books[tag].extend(account)
    assert seen==set(dates) and len(dates)==45
    # ----------------------------------------
    refs = {"I00":("221期限寄与","D04"),"T00":("221期限保護","T02")}
    hashes = {}
    for tag,(folder,code) in refs.items():
        path = ROOT/"work"/folder/"比較元帳.json"
        previous = json.loads(path.read_bytes())["口座再生"][code]
        assert books[tag]==previous
        hashes[tag] = {"参照元帳SHA256":sha256(path.read_bytes()).hexdigest(),"全項目一致件数":len(previous)}
    result = {}
    text = ["# 建玉ごとの時間上限を設けず、開始待機だけを比較する","",
            "日経199_02・既使用45デイ・日経225mini 1枚換算。利益・損失・収支は往復1,077円控除後。"
            "15:29に場末返済を要求し、15:30までに全決済する。取得から60分の判定は全候補にない。"
            "開始待機中の判断を注文予約ごと除外し、それまでの価格履歴は指標に利用する。"
            "開始20・30分を主比較とし、15分は短い参考条件、0分は旧口座の照合に使用。","",
            "|ID|開始待機|出口|参加日|建玉|不明|総利益（円）|総損失（円）|収支（円）|赤字日|日末最大下落（円）|保有率|前24日収支|後21日収支|直近3日収支|",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for tag,book in books.items():
        wait = waits[tag]
        detail = {}
        for label,days in (("全45日",dates),("前24日",dates[:24]),("後21日",dates[24:]),("直近3日",dates[-3:])):
            daily,detail[label] = measures(days,book,wait)
            if label=="全45日":
                detail["日別"] = daily
        result[tag] = detail
        a = detail["全45日"]
        kind = "固定±1R" if tag.startswith("I") else "固定±1R＋追尾"
        mandatory = [a[k] for k in ("参加場","取得","未知","利益","損失","収支","赤字場","場末DD既知")]
        money = [detail[label]["収支"] for label in ("前24日","後21日","直近3日")]
        text.append("|"+"|".join([tag,str(wait)+"分",kind,*[f"{x:,.0f}" for x in mandatory],
                                 f"{a['保有率']:.2%}",*[f"{x:,.0f}" for x in money]])+"|")
    text.extend(["","保有率は確認できた保有秒数÷（08:45＋開始待機分から15:30までの秒数）。"
                 "買い・売りは共用の予約・建玉1枚。待機中の要求が終了後に約定する経路も除いた。"
                 "開始待機0分は過去のD04とT02を全取引・全項目で照合した。","",
                 "## 20分と30分で収支の変わった日","",
                 "同一デイ・同一出口で30分待機の収支から20分待機の収支を引いた費用後の差。"
                 "残りの日は両者の収支が一致した。","",
                 "|対象場|固定±1Rの差（円）|固定±1R＋追尾の差（円）|","|---|---:|---:|"])
    for i,day in enumerate(dates):
        gaps = [result[k+"30"]["日別"][i]["収支"]-result[k+"20"]["日別"][i]["収支"] for k in ("I","T")]
        if any(gaps):
            text.append(f"|{day}|{gaps[0]:+,.0f}|{gaps[1]:+,.0f}|")
    text.append("")
    WORK.mkdir(parents=True,exist_ok=True)
    (HERE/"全条件の比較.md").write_text("\n".join(text),encoding="utf8")
    artifacts = {"口座元帳":{"対象場":dates,"開始待機分":waits,"口座再生":books},
                 "集計":result,"照合":{"開始待機なし":hashes,"場別の予約":proof}}
    for name,data in artifacts.items():
        (WORK/(name+".json")).write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
