"""元注文のどの決済が変わったかを、同じ取得と単一口座で照合する。"""
import argparse
import json
from pathlib import Path
import runpy
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT/"work/221集計"
PREVIOUS = runpy.run_path(str(next(HERE.parent.glob("00220_*/損切と利確を集計する.py"))))
OLD = PREVIOUS["OLD"]
GROUPS = {
    "元注文の寄与":"221元IFD", "分期限の寄与":"221期限寄与", "両注文と追尾":"221両注文",
    "終盤の追試":"221期限の追試", "入口別の保護":"221入口別", "指値の延長":"221延伸", "期限延長と保護":"221期限保護",
}
HEADERS = ["候補","方向","判断日時JST","新規日時JST","建値pt","元IFD片幅pt","元期限","決済日時JST",
           "決済値pt","費用後収支円","決済理由","新規原行","決済原行","最大評価損益円","最大評価日時JST",
           "最小評価損益円","最小評価日時JST","保護起動時刻JST","保護発動時刻JST","最終保護床の建値比pt",
           "初期損切価格pt","初期利確価格pt","発動時の保護床価格pt","変更後の利確価格pt"]


def partition(base: list, fixed: list) -> dict:
    """
    機能：元181件を元の決済理由別に分け、同じ出口を維持できた件数と既知同士の金額変化を求める。
    引数：base・fixed（list）は元の取得を同じ順に並べた基準と候補。
    返り値：dict。状態別に元件数・同じ返済原行かつ同額の件数・比較可能数・収支差を保持する。
    """
    groups = {}
    for prior, other in zip(base, fixed, strict=True):
        assert OLD["key"](prior)==OLD["key"](other) and prior["net"] is not None
        result = groups.setdefault(prior["status"], [0,0,0,0])
        result[0] += 1
        if other["net"] is not None:
            result[1] += (prior["exit_line"],prior["net"]) == (other["exit_line"],other["net"])
            result[2] += 1
            result[3] += other["net"]-prior["net"]
    assert [groups[k][0] for k in (1,2,3,4)]==[65,30,78,8]
    return groups


def append_prices(row: list, trade: dict, code: str) -> None:
    """
    機能：建値から各注文の理論価格を求め、指値を変更した場合は当初と変更後を分けて追記する。
    引数：row（list）は既存の出力行、trade（dict）は元帳の建玉、code（str）は候補。
    返り値：None。履歴に該当注文がない欄は空欄として扱う。
    """
    side = 1 if trade["side"]==0 else -1
    price = trade["entry_price"]
    loss = trade["width"] if code=="IFD" else trade["initial_stop_points"]
    target = trade["width"] if code=="IFD" else trade["target_points"]
    floor = trade.get("floor_points") if trade.get("trigger_time") is not None else None
    changed = trade.get("revised_target_points")
    row.extend([round(price+sign*d,5) if d is not None else None
                for d,sign in ((loss,-side),(target,side),(floor,side),(changed,side))])


def deadline_detail(base: list, fixed: list) -> list:
    """
    機能：元の60分で決着しなかった建玉に、期限延長後の決済理由と追加時間を対応させる。
    引数：base・fixed（list）は対応する元181取得とD04による返済。
    返り値：list。結果を知る前に分かる性質と、決済後に分かる到達理由それぞれの内訳表。
    """
    matched = [(a,b) for a,b in zip(base,fixed,strict=True) if a["status"]==3]
    groups = {"全て":matched,"元の買い":[p for p in matched if p[0]["side"]==0],
              "元の売り":[p for p in matched if p[0]["side"]==1],
              "60分時に費用後黒字":[p for p in matched if p[0]["net"]>0],
              "60分時に費用後赤字":[p for p in matched if p[0]["net"]<0]}
    groups.update({title:[p for p in matched if p[1]["status"]==status]
                   for status,title in ((1,"延長後に利確"),(2,"延長後に損切"),(4,"延長後に場末決済"))})
    lines = ["# 60分期限の後に価格はどこへ到達したか","",
             "元の60分期限で決済した78件を、取得日時・方向・幅を固定してD04で再生。"
             "全件で元の利確指値と損切を維持し、デイ終了15分前まで保有した。追加時間は両方の実決済時刻の差。"
             "同じ建玉を複数の切り口で示す。最終3行は決済後に判明した内訳。","",
             "|分類|件数|延長後利確|延長後損切|延長後場末|黒字→赤字|赤字→黒字|追加時間中央値（分）|費用後収支差（円）|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    assert len(matched)==78
    for title,group in groups.items():
        assert all(b["net"] is not None and b["exit_time"]>=a["exit_time"] for a,b in group)
        outcomes = [sum(b["status"]==s for _,b in group) for s in (1,2,4)]
        assert sum(outcomes)==len(group)
        flips = [sum(a["net"]>0 and b["net"]<0 for a,b in group),sum(a["net"]<0 and b["net"]>0 for a,b in group)]
        minutes = median((b["exit_time"]-a["exit_time"])/60 for a,b in group)
        change = sum(b["net"]-a["net"] for a,b in group)
        lines.append("|"+"|".join([title,str(len(group)),*map(str,outcomes+flips),f"{minutes:.1f}",f"{change:+,.0f}"])+"|")
    return lines


def main() -> None:
    """
    機能：試行ごとの元帳を検算し、全候補の比較表と公開対象ごとの型付きCSV入力を作る。
    引数：CLIの --途中（bool）は元帳がまだ揃わない段階のローカル検算用。
    返り値：None。試行と作業領域にMarkdown・JSONを保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--途中",action="store_true")
    args = parser.parse_args()
    selected = {} if args.途中 else json.loads((HERE/"閲覧候補.json").read_bytes())
    dates, originals, _ = OLD["sources"]("デイ")
    expected = originals["216:日経199_02"]
    tables = {"候補比較":{"headers":["候補","期間",*OLD["COLS"].values()],"rows":[]},
              "デイ":{"headers":["候補",*OLD["DAY"].values()],"rows":[]},
              "建玉明細":{"headers":HEADERS,"rows":[]}}
    summary = ["# 出口を変えたときの全成績","",
               "単位は円、mini 1枚費用後。日末DDは各日の累計収支からの最大下落。未知を含む行の金額は既知分。"
               "「上位3日除外差」は元IFDに対する改善額の大きい3日を外した口座差。",
               "","|群|ID|建玉|未知|利益|損失|収支|赤字日|日末DD|前24日|後21日|直近3日|上位3日除外差|",
               "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    parts = ["","## 元181取得の出口と後続取引","",
             "各理由は「同じ返済原行かつ同額の件数／元件数、既知同士の収支差」。固定181差と口座共通・入替差は別々の比較。"
             "入替差は新しい候補だけが建てた取引の収支から、元IFDだけが建てた取引の収支を引く。",
             "","|ID|元利確|元損切|元60分|元場末|固定不明|固定181差（既知対）|口座共通差¹|口座入替差¹|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    cases,rankings = {},{}
    capped = ["","## 利確の約定を指値ちょうどに制限した感度","",
              "6代表は元の1R指値を維持する。取得と返済の原行をそろえたまま、静的利確に有利な価格改善があれば1Rで打ち切った。"
              "損切・追尾・期限は実際の返済側気配、費用は同じ。指値での約定順位は未検証。","",
              "|候補|指値より有利な決済|差し引いた金額（円）|価格改善なしの費用後収支（円）|","|---|---:|---:|---:|"]
    base = None
    for group, folder in GROUPS.items():
        path = ROOT/"work"/folder/"比較元帳.json"
        if args.途中 and not path.is_file():
            continue
        ledger = json.loads(path.read_bytes())
        accounts,fixed = ledger["口座再生"],ledger["入口固定"]
        if base is None:
            base = accounts["IFD"]
            assert len(dates)==45 and len(base)==181
            keys = ("scene","entry_line","entry_time","entry_price","side","width","horizon","exit_line","net")
            assert all(all(a[k]==b[k] for k in keys) for a,b in zip(base,expected,strict=True))
        assert accounts["IFD"]==base and accounts.keys()==fixed.keys()
        for code,account in accounts.items():
            if code=="IFD" and code in cases:
                continue
            assert code not in cases
            c,days = PREVIOUS["series"](account,fixed[code],base,dates)
            p = c["期間"]
            a = p["全45日"]
            reason = partition(base,fixed[code])
            c["元理由別"] = reason
            cases[code] = c
            if code=="D04" and not args.途中:
                (HERE/"期限後の到達.md").write_text("\n".join(deadline_detail(base,fixed[code]))+"\n",encoding="utf8")
            nums = [a[k] for k in ("取得","未知","利益","損失","収支","赤字場","場末DD既知")]
            nums += [p[k]["収支"] for k in ("前24日","後21日","直近3日")] + [c["改善上位3日を除く差"]]
            summary.append("|"+"|".join([group,code,*[f"{v:,.0f}" for v in nums]])+"|")
            stages = [f"{n[1]}/{n[0]}、{n[3]:+,.0f}" for n in (reason[k] for k in (1,2,3,4))]
            common = c["入替え"]
            direct = common["共通新"]["収支"]-common["共通旧"]["収支"]
            changed = common["新専有"]["収支"]-common["旧専有"]["収支"]
            assert direct+changed==a["収支"]-cases["IFD"]["期間"]["全45日"]["収支"]
            parts.append("|"+"|".join([code,*stages,str(c["入口固定"]["未知"]),f"{sum(n[3] for n in reason.values()):+,.0f}",
                                        f"{direct:+,d}",f"{changed:+,d}"])+"|")
            if code in selected:
                excess = [max(0,t["net"]-(t["width"]*100-1077)) for t in account if t["status"]==1]
                adjustment = sum(excess)
                capped.append(f"|{code}|{sum(x>0 for x in excess)}|{adjustment:,.0f}|{a['収支']-adjustment:,.0f}|")
                start = len(tables["建玉明細"]["rows"])
                OLD["record"](tables,"221:"+selected[code],account,days,c)
                for row,trade in zip(tables["建玉明細"]["rows"][start:],account,strict=True):
                    append_prices(row,trade,code)
        if group not in ("元注文の寄与","分期限の寄与"):
            rankings[group] = OLD["front_choice"](cases,[code for code in accounts if code!="IFD"])
    # ----------------------------------------
    assert selected.keys()<=cases.keys()
    WORK.mkdir(parents=True,exist_ok=True)
    (WORK/"全成績.json").write_text(json.dumps(cases,ensure_ascii=False,allow_nan=False),encoding="utf8")
    if args.途中:
        return
    summary += ["","## 前24日での選抜","","各群内で既定の損失・収支・赤字場・参加などの条件を適用。"
                "D群は注文の寄与を調べる対照。後から加えた群の後21日も既使用期間。",""]
    summary += [f"- {group}　{r['選抜'] or '適格なし'}（適格{len(r['適格順位'])}案）" for group,r in rankings.items()]
    parts += ["","¹ 不明を含む候補の口座差は各口座の既知分の差。"]
    (HERE/"全条件の比較.md").write_text("\n".join(summary+parts+capped)+"\n",encoding="utf8")
    payload = {"tableNames":{"候補比較":"集計","デイ":"デイ","建玉明細":"建玉明細"},"tables":tables}
    (WORK/"閲覧入力.json").write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
