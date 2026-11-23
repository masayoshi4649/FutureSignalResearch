"""固定入口での出口差と、保有枠を再計算した口座差を照合する。"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "work/219出口"
sys.path.insert(0, str(next((ROOT/"study").glob("00216_*"))))
from 全場を集計する import JST, calculate, sources

COLS = {
    "場数":"場数", "参加場":"参加場数", "取得":"建玉回数", "未知":"未知件数", "利益":"既知利益円",
    "損失":"既知損失円", "収支":"既知収支円", "勝":"黒字件数", "敗":"赤字件数",
    "黒字場":"確定黒字日数", "赤字場":"確定赤字日数", "場末DD既知":"日末最大DD既知円",
    "建玉中央値下限":"建玉中央値下限円", "場中央値下限":"日次中央値下限円", "保有率":"既知保有時間率",
}
DAY = {"場":"セッション", "利益":"既知利益円", "損失":"既知損失円", "収支":"既知収支円", "確定収支":"確定収支円",
       "既知累計":"既知累計円", "確定累計":"確定累計円", "取得":"建玉回数", "勝":"黒字件数", "敗":"赤字件数",
       "未知":"未知件数", "保有率":"既知保有時間率"}


def key(t: dict) -> tuple:
    """
    機能：同じ判断・同じ売買側の取得を元帳をまたいで照合する。
    引数：t（dict）は一つの実取得。
    返り値：tuple。場、新規原行、売買側、判断原行。
    """
    return t["scene"], t["entry_line"], t["side"], t["request_line"]


def money(rows: list) -> dict:
    """
    機能：未知を分けて費用後の利益・損失・収支を計算する。
    引数：rows（list）は期間・方向・方法を限定した建玉群。
    返り値：dict。件数、未知数と既知の費用後円額。
    """
    vals = [r["net"] for r in rows if r["net"] is not None]
    profit = round(sum(v for v in vals if v > 0))
    loss = round(-sum(v for v in vals if v < 0))
    return {"件数":len(rows), "未知":len(rows)-len(vals), "利益":profit, "損失":loss, "収支":profit-loss}


def giveback(rows: list) -> dict:
    """
    機能：費用後の含み益経験と赤字決済の組合せを実現取引に限定して測る。
    引数：rows（list）は観測済み含み益と最終損益を持つ建玉。
    返り値：dict。含み益経験・利益後赤字の件数と該当確定損失額。
    """
    positive = [r for r in rows if r["max_unrealized_net"]>0]
    losses = [r for r in positive if r["net"] is not None and r["net"]<0]
    return {"含み益経験":len(positive), "利益後赤字":len(losses), "利益後の損失":money(losses)["損失"]}


def contrast(base: list, new: list) -> dict:
    """
    機能：口座の収支差を共通取得の出口変更と取引の入替えに分解する。
    引数：base・new（list）は元IFDと新方策の建玉。
    返り値：dict。各群の費用後損益と不明数。
    """
    oldmap, newmap = [{key(t):t for t in row} for row in (base, new)]
    assert len(oldmap)==len(base) and len(newmap)==len(new)
    common = oldmap.keys() & newmap.keys()
    parts = {name:money([mapping[k] for k in keys]) for name, mapping, keys in [
        ("共通旧",oldmap,common), ("共通新",newmap,common),
        ("旧専有",oldmap,oldmap.keys()-newmap.keys()), ("新専有",newmap,newmap.keys()-oldmap.keys())]}
    assert parts["共通新"]["収支"]-parts["共通旧"]["収支"]+parts["新専有"]["収支"]-parts["旧専有"]["収支"] == money(new)["収支"]-money(base)["収支"]
    return parts


def evaluate(dates: list, base: list, fixed: list, book: list) -> tuple:
    """
    機能：対象45日の安定性・時刻・費用感度と特定日を外した効果を確認する。
    引数：dates（list）は全日、base・fixed・book（list）は元IFD・固定取得・再生口座。
    返り値：tuple。期間集計・取引経路の分解と日別の成績。
    """
    assert [key(r) for r in fixed]==[key(r) for r in base]
    daily, all_stats = calculate(dates, book, "全体")
    old_daily, old_stats = calculate(dates, base, "全体")
    top = sorted((d for d in daily if d["確定収支"] is not None and d["収支"]>0), key=lambda d:-d["収支"])[:3]
    upper = {d["場"] for d in top}
    spans = {"全45日":dates, "前24日":dates[:24], "後21日":dates[24:], "直近3日":dates[42:],
             "10月20日除外":[d for d in dates if d!="2026-10-20_Day"],
             "自身の利益上位3日除外":[d for d in dates if d not in upper]}
    stats = {s:all_stats if s=="全45日" else calculate(ds,book,"全体")[1] for s,ds in spans.items()}
    # ----------------------------------------
    delta = [(a["場"], a["収支"]-b["収支"]) for a,b in zip(daily, old_daily, strict=True)
             if a["確定収支"] is not None and b["確定収支"] is not None]
    known_pairs = [(a,b) for a,b in zip(daily,old_daily,strict=True)
                   if a["確定収支"] is not None and b["確定収支"] is not None]
    worst_day = min((a for a,_ in known_pairs),key=lambda a:a["収支"])
    worst_trade = min((t for t in book if t["net"] is not None),key=lambda t:t["net"])
    gains = sorted(((day,v) for day,v in delta if v>0), key=lambda p:-p[1])
    weekly = {}
    for row, old in zip(daily, old_daily, strict=True):
        week = datetime.fromisoformat(row["場"][:10]).isocalendar().week
        w = weekly.setdefault(week, {"候補既知":0, "基準既知":0, "未知":0})
        w["候補既知"] += row["収支"]
        w["基準既知"] += old["収支"]
        w["未知"] += row["未知"] + old["未知"]
    directions = {}
    for s, values in (("元IFD",base), ("固定取得",fixed), ("口座再生",book)):
        directions[s] = {}
        for title, side in (("買い",0), ("売り",1)):
            group = [r for r in values if r["side"]==side]
            directions[s][title] = money(group)
            for morning, label in ((True,"11時30分前"), (False,"11時30分以降")):
                subset = [r for r in group if (datetime.fromtimestamp(r["entry_time"],JST).strftime("%H:%M")<"11:30")==morning]
                directions[s][title+label] = money(subset)
    case = {"期間":stats, "入口固定":money(fixed), "入替え":contrast(base,book), "方向":directions,
            "固定の利益保護":giveback(fixed), "口座の利益保護":giveback(book),
            "理由":dict(Counter(r["exit_reason"] for r in book)), "週":weekly,
            "改善日":sum(v>0 for _,v in delta), "悪化日":sum(v<0 for _,v in delta),
            "改善上位日":gains[:3], "改善上位3日を除く差":sum(v for _,v in delta)-sum(v for _,v in gains[:3]),
            "上位利益日":sorted(upper), "同日比較数":len(delta),
            "同時確定日の収支差":sum(v for _,v in delta),
            "同時確定日の損失差":sum(a["損失"]-b["損失"] for a,b in known_pairs),
            "最悪の確定日":[worst_day["場"],worst_day["収支"]],
            "最悪の確定建玉":[stamp(worst_trade["entry_time"]),worst_trade["net"]],
            "保護起動数":sum(t.get("activation_time") is not None for t in book),
            "片道滑り更に5pt増の既知収支差":(all_stats["収支"]-1000*(all_stats["取得"]-all_stats["未知"]))
                        -(old_stats["収支"]-1000*(old_stats["取得"]-old_stats["未知"]))}
    return case, daily


def stamp(value: float | None) -> str | None:
    """
    機能：Unix秒を日本時間の表示へ変換する。
    引数：value（float または None）は価格時計。
    返り値：str または None。未知は空欄。
    """
    return datetime.fromtimestamp(value,JST).strftime("%Y-%m-%d %H:%M:%S") if value is not None else None


def record(tables: dict, name: str, book: list, daily: list, case: dict) -> None:
    """
    機能：手法別CSVに期間・各セッション・詳細な取引日時を渡す。
    引数：tables・case（dict）は出力表と集計、name（str）は候補、book・daily（list）は明細。
    返り値：None。型付きの行を追加する。
    """
    for period, m in case["期間"].items():
        tables["候補比較"]["rows"].append([name,period]+[m[k] for k in COLS])
    for d in daily:
        tables["デイ"]["rows"].append([name]+[d[k] for k in DAY])
    for t in book:
        known = t["net"] is not None
        if known:
            change = (t["exit_price"]-t["entry_price"])*(1 if t["side"]==0 else -1)
            assert change*100-1077 == t["net"]
        tables["建玉明細"]["rows"].append([name,"買い" if t["side"]==0 else "売り",stamp(t["request_time"]),
            stamp(t["entry_time"]),t["entry_price"],t["width"],t["horizon"],stamp(t["exit_time"]),
            t["exit_price"],t["net"],t["exit_reason"],t["entry_line"],t["exit_line"] if known else None,
            t["max_unrealized_net"],stamp(t["max_unrealized_time"]),t["min_unrealized_net"],
            stamp(t["min_unrealized_time"]),stamp(t.get("activation_time")),stamp(t.get("trigger_time")),
            t.get("floor_points")])


def front_choice(cases: dict, names: list) -> dict:
    """
    機能：対象群の前24日の成績だけを用いて、初回と同じ適格条件・順位を適用する。
    引数：cases（dict）は期間集計、names（list）は同じ巡回で定義した方策ID。
    返り値：dict。適格なIDを順位順に格納し、不在なら選抜を空欄とする。
    """
    base = cases["IFD"]["期間"]["前24日"]
    passed = []
    for name, case in cases.items():
        if name not in names:
            continue
        a = case["期間"]["前24日"]
        if (a["未知"]<=base["未知"] and a["参加場"]==base["参加場"] and a["保有率"]>=.20
                and min(a["場中央値下限"],a["建玉中央値下限"])>0 and a["損失"]<base["損失"]
                and a["収支"]>base["収支"] and a["場末DD既知"]<=base["場末DD既知"]
                and a["赤字場"]<=base["赤字場"]):
            passed.append((a["損失"],a["場末DD既知"],-a["収支"],name))
    ranked = [x[3] for x in sorted(passed)]
    return {"選抜":ranked[0] if ranked else None,"適格順位":ranked}


def write_comparison(cases: dict) -> None:
    """
    機能：全候補の固定取得と口座結果を同じ基準でMarkdownに保存する。
    引数：cases（dict）は全候補の期間・経路別成績。
    返り値：None。試行内に全候補の比較表を生成する。
    """
    lines = ["# 全出口条件の比較", "",
             "費用後の既知円額。入口固定は元の181建玉をそのまま再決済する実験。口座再生は予約と保有を再計算した独立口座。日末DDは場末の既知累計の最大下落額。", "",
             "|候補|固定181収支|固定181損失|口座件数|不明|口座利益|口座損失|口座収支|赤字日|日末DD|保有率|利益後赤字|前24日収支|後21日収支|直近3日収支|自身の上位3日除外収支|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for name,c in cases.items():
        a = c["期間"]["全45日"]
        f = c["入口固定"]
        nums = [f["収支"],f["損失"],a["取得"],a["未知"],a["利益"],a["損失"],a["収支"],a["赤字場"],a["場末DD既知"]]
        periods = ["前24日","後21日","直近3日","自身の利益上位3日除外"]
        row = [name, *[f"{v:,.0f}" for v in nums], f"{a['保有率']:.1%}",str(c["口座の利益保護"]["利益後赤字"]),
               *[f"{c['期間'][k]['収支']:,.0f}" for k in periods]]
        lines.append("| "+" | ".join(row)+" |")
    (HERE/"全出口の比較.md").write_text("\n".join(lines)+"\n",encoding="utf8")


def main() -> None:
    """
    機能：両モードを検算して全条件の数値と指定した候補のCSV用入力を作る。
    引数：CLIの --元帳（Path、任意）・--閲覧（Path、任意）。
    返り値：None。作業フォルダに結果を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--元帳", type=Path, default=WORK/"比較元帳.json")
    parser.add_argument("--追加元帳", type=Path, nargs="*", default=[])
    parser.add_argument("--閲覧", type=Path)
    args = parser.parse_args()
    data = json.loads(args.元帳.read_bytes())
    for path in args.追加元帳:
        extra = json.loads(path.read_bytes())
        for mode in ("口座再生","入口固定"):
            assert data[mode]["IFD"]==extra[mode]["IFD"]
            for code, values in extra[mode].items():
                if code!="IFD":
                    assert code not in data[mode]
                    data[mode][code] = values
    dates, original, _ = sources("デイ")
    books, frozen = data["口座再生"], data["入口固定"]
    base = books["IFD"]
    assert len(dates)==45 and len(base)==181 and set(books)==set(frozen)
    fields = ("scene","side","entry_line","entry_time","exit_line","exit_time","entry_price","exit_price","net")
    assert all(all(a[k]==b[k] for k in fields) for a,b in zip(base,original["216:日経199_02"],strict=True))
    assert money(base)=={"件数":181,"未知":0,"利益":2362530,"損失":1342467,"収支":1020063}
    selected = json.loads(args.閲覧.read_bytes()) if args.閲覧 else {}
    assert set(selected)<=set(books)
    cases = {}
    tables = {"候補比較":{"headers":["候補","期間",*COLS.values()],"rows":[]},
              "デイ":{"headers":["候補",*DAY.values()],"rows":[]},
              "建玉明細":{"headers":["候補","方向","判断日時JST","新規日時JST","建値pt","元IFD片幅pt","元期限",
              "決済日時JST","決済値pt","費用後収支円","決済理由","新規原行","決済原行","最大含み益円（費用後評価の最大）",
              "評価最大時刻JST","最低含み損益円","評価最小時刻JST","保護起動時刻JST","追加返済発動時刻JST",
              "最終保護幅pt（建値比・順行側）"],"rows":[]}}
    for key_id in sorted(books,key=lambda code:(code!="IFD",code)):
        book = books[key_id]
        case, daily = evaluate(dates,base,frozen[key_id],book)
        cases[key_id] = case
        if key_id in selected:
            record(tables,"219:"+selected[key_id],book,daily,case)
    WORK.mkdir(parents=True,exist_ok=True)
    (WORK/"成績.json").write_text(json.dumps(cases,ensure_ascii=False,allow_nan=False),encoding="utf8")
    groups = [("E",1,14),("M",1,16),("M",17,26),("M",27,35),("W",1,15),("W",16,30),
              ("W",31,36),("K",0,6),("C",1,6),("L",0,7),("L",8,14)]
    selections = {}
    covered = set()
    for prefix, start, end in groups:
        names = [f"{prefix}{i:02d}" for i in range(start,end+1) if f"{prefix}{i:02d}" in cases]
        if names:
            covered.update(names)
            selections[names[0]+"〜"+names[-1]] = front_choice(cases,names)
    assert covered==set(cases)-{"IFD"}
    (WORK/"前半選抜.json").write_text(json.dumps(selections,ensure_ascii=False,allow_nan=False),encoding="utf8")
    if selected:
        write_comparison(cases)
        lines = ["# 前24日での群別選抜", "",
                 "各巡で定義した候補だけに前24日の同じ適格・順位規則を適用した。後発群の設計には既使用45日の診断が含まれる。", "",
                 "|対象群|選抜|適格な候補（順位順）|","|---|---|---|"]
        for group, choice in selections.items():
            lines.append(f"|{group}|{choice['選抜'] or '該当なし'}|{'、'.join(choice['適格順位']) or 'なし'}|")
        (HERE/"前半の選抜.md").write_text("\n".join(lines)+"\n",encoding="utf8")
        typed = {"tableNames":{"候補比較":"集計","デイ":"デイ","建玉明細":"建玉明細"},"tables":tables}
        (WORK/"閲覧入力.json").write_text(json.dumps(typed,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__ == "__main__":
    main()
