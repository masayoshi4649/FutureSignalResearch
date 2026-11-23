"""元の同じ181建玉に対し、どの決済が追尾で変わったのかを金額と原行で検証する。"""
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STAT = runpy.run_path(str(next((ROOT/"study").glob("00219_*/出口を集計する.py"))))
GROUPS = ("221両注文","221期限の追試")
REASONS = {1:"利確",2:"損切",3:"通常期限",4:"場末"}


def contributions(base: list, fixed: list) -> dict:
    """
    機能：同じ取得の返済変化を、元IFDの決済理由ごとに数える。
    引数：base・fixed（list）は元181建玉と、新規固定で出口を変更した181建玉。
    返り値：dict。群の全件・変更件数・純損益差・赤字が黒字になった件数・事例。
    """
    counts = {name:{"全件":0,"変更":0,"改善":0,"悪化":0,"収支差":0,"赤字から黒字":0,"事例":[]} for name in REASONS.values()}
    for old,new in zip(base,fixed,strict=True):
        assert STAT["key"](old)==STAT["key"](new) and new["initial_stop_points"]==new["target_points"]==old["width"]
        v = counts[REASONS[old["status"]]]
        v["全件"] += 1
        if old["exit_index"]!=new["exit_index"]:
            assert 0<=new["exit_index"]<old["exit_index"] and new["status"]==5
            change = new["net"]-old["net"]
            v["収支差"] += round(change)
            v["変更"] += 1
            v["改善"] += change>0
            v["悪化"] += change<0
            v["赤字から黒字"] += old["net"]<0<new["net"]
            v["事例"].append([old["scene"],STAT["stamp"](old["entry_time"]),"売" if old["side"] else "買",
                             old["net"],new["net"],STAT["stamp"](new["exit_time"])])
    return counts


def main() -> None:
    """
    機能：初回・追試を事前の各群で照合し、口座と固定取得の寄与をMarkdownに書く。
    引数：なし。作業ディレクトリの各比較元帳、前試行のS1P2を参照する。
    返り値：None。群別表を試行内に、数値と事例を作業領域に出力する。
    """
    prior = json.loads((ROOT/"work/220主比較/比較元帳.json").read_bytes())
    dates, _, _ = STAT["sources"]("デイ")
    cases,groups,attribution = {},{},{}
    for folder in GROUPS:
        ledgers = json.loads((ROOT/"work"/folder/"比較元帳.json").read_bytes())
        old = ledgers["口座再生"]["IFD"]
        assert len(old)==181 and len(dates)==45
        assert all((t["entry_line"],t["exit_line"],t["net"])==(p["entry_line"],p["exit_line"],p["net"])
                   for t,p in zip(old,prior["口座再生"]["IFD"],strict=True))
        codes = list(ledgers["口座再生"])
        groups[folder] = [c for c in codes if c!="IFD"]
        for code in codes:
            if code=="IFD" and code in cases:
                continue
            book,fixed = [ledgers[key][code] for key in ("口座再生","入口固定")]
            if code=="A00":
                for key in ("口座再生","入口固定"):
                    for cur,ref in zip(ledgers[key][code],prior[key]["S1P2"],strict=True):
                        assert {k:v for k,v in cur.items() if k!="exit_strategy"}=={k:v for k,v in ref.items() if k!="exit_strategy"}
            cases[code],_ = STAT["evaluate"](dates,old,fixed,book)
            if code!="IFD":
                attribution[code] = contributions(old,fixed)
    # ----------------------------------------
    lines = ["# 元の両注文を維持した各追尾条件の比較","",
             "45デイの口座を全予約から再生した。損失は赤字取引の絶対額合計。金額単位は円。未知ありの行は既知の金額のみ。","",
             "|ID|取得／未知|総利益|総損失|収支|日末最大下落|赤字日|前24収支|後21収支|直近3収支|改善上位3日除外差|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for code,c in cases.items():
        a=c["期間"]["全45日"]
        vals=[a[k] for k in ("利益","損失","収支","場末DD既知","赤字場")]
        vals += [c["期間"][p]["収支"] for p in ("前24日","後21日","直近3日")]
        vals.append(c["改善上位3日を除く差"])
        lines.append("|"+code+f"|{a['取得']}／{a['未知']}|"+"|".join(f"{n:,.0f}" for n in vals)+"|")
    lines += ["","## 元181件の取得を固定し元の決済理由ごとに分解","","各理由の欄は「変更した建玉数／費用後収支差」。利確65、損切30、通常期限78、場末8の全181件を含む。",
              "","|ID|元利確|元損切|元通常期限|元場末|赤字→黒字|固定収支差|","|---|---:|---:|---:|---:|---:|---:|"]
    for code,parts in attribution.items():
        vals = [f"{p['変更']}／{p['収支差']:+,}" for p in parts.values()]
        total = sum(p["収支差"] for p in parts.values())
        assert total==cases[code]["入口固定"]["収支"]-cases["IFD"]["入口固定"]["収支"]
        lines.append("|"+code+"|"+"|".join(vals)+f"|{sum(p['赤字から黒字'] for p in parts.values())}|{total:+,}|")
    lines += ["","## 前24日による選抜",""]
    for folder,cs in groups.items():
        selected = STAT["front_choice"](cases,cs)
        lines.append(f"- {folder}　首位 {selected['選抜'] or 'なし'}、適格 {', '.join(selected['適格順位']) or 'なし'}。")
    (HERE/"全条件の結果.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    (ROOT/"work/221両注文/決済理由の寄与.json").write_text(json.dumps(attribution,ensure_ascii=False),encoding="utf8")


if __name__=="__main__":
    main()
