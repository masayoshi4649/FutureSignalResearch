"""開始待機別に、同じ建玉の出口で得た効果と一枚口座に加わった効果を比較する。"""
import argparse
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PREVIOUS = runpy.run_path(str(next((ROOT/"study").glob("00222_*/建玉制限を再生する.py"))))
OLD = runpy.run_path(str(next((ROOT/"study").glob("00219_*/出口を集計する.py"))))


def details(baseline: list, fixed: list, account: list, dates: list, wait: int) -> dict:
    """
    機能：元の単純IFDとの損失・収支・日末DD・決済理由別の差を、入口固定と単一口座に分けて求める。
    引数：baseline・fixed・account（list）は基準、同じ取得での出口差、単一口座、dates（list）は全場、
    wait（int）は開始待機分。
    返り値：dict。期間、保有枠の入替、元決済への介入と改善の集中を収録する。
    """
    assert [OLD["key"](t) for t in baseline]==[OLD["key"](t) for t in fixed]
    periods = {}
    for label,subset in (("全45",dates),("前24",dates[:24]),("後21",dates[24:]),("直近3",dates[-3:])):
        prior,original = PREVIOUS["measures"](subset,baseline,wait)
        days,result = PREVIOUS["measures"](subset,account,wait)
        prior_days = {r["場"]:r for r in prior}
        delta = [r["収支"]-prior_days[r["場"]]["収支"] for r in days
                 if r["確定収支"] is not None and prior_days[r["場"]]["確定収支"] is not None]
        periods[label] = {"候補":result,"基準":original,
                           "金額差":{k:result[k]-original[k] for k in ("収支","損失","場末DD既知","赤字場","利益後赤字件数","利益後赤字損失")},
                           "確定同日":len(delta),"改善上位3日除外差":sum(delta)-sum(sorted((n for n in delta if n>0),reverse=True)[:3])}
    # ----------------------------------------
    source = {}
    for status in (1,2,4):
        pairs = [(a,b) for a,b in zip(baseline,fixed,strict=True) if a["status"]==status]
        known = [(a,b) for a,b in pairs if a["net"] is not None and b["net"] is not None]
        source[status] = {"母数":len(pairs),"返済原行維持":sum(a["exit_line"]==b["exit_line"] for a,b in known),
                          "確定数":len(known),"同一取得の収支差":sum(b["net"]-a["net"] for a,b in known),
                          "赤から黒":sum(a["net"]<0<b["net"] for a,b in known),
                          "黒から赤":sum(b["net"]<0<a["net"] for a,b in known)}
    assert sum(x["母数"] for x in source.values())==len(baseline)
    return {"期間":periods,"固定":OLD["money"](fixed),"元の理由別":source,"入替":OLD["contrast"](baseline,account),
            "固定の利益後赤字":OLD["giveback"](fixed),"口座の利益後赤字":OLD["giveback"](account),
            "追尾返済":sum(t["status"]==5 for t in account)}


def main() -> None:
    """
    機能：元帳の各設定について、待機別の候補比較をMarkdownとJSONに保存する。
    引数：CLI --入力（Path）は2モードの元帳、--出力名（str）は比較表の拡張子を除く名前。
    返り値：None。数値の正本を研究フォルダ、内訳を入力と同じ作業フォルダに保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--入力",type=Path,default=ROOT/"work/223値幅/比較元帳.json")
    parser.add_argument("--出力名",default="値幅ごとの結果")
    args = parser.parse_args()
    ledger = json.loads(args.入力.read_bytes())
    previous = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    dates = previous["対象場"]
    results = {}
    lines = ["# "+args.出力名,"","45デイの同じ開始待機の単純IFDを基準として比較する。"
             "「損失差」は総損失の増減で、負の値が損失減。固定は元の133建玉の取得日時・方向・価格を全てそろえた。"
             "確定しない建玉の損益は不明として扱い、いずれかに不明があるときは表の金額は既知分。",
             "","|条件|口座取得／不明|総利益|総損失|収支|損失差|収支差|日末DD|赤字日|含み益後赤字の損失|"
             "前24収支差|後21収支差|改善上位3日除外差|固定収支差|固定損失差|元利確維持|元損切の赤→黒|",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key,account in ledger["口座再生"].items():
        wait = int(key.rsplit("_",1)[1])
        baseline = previous["口座再生"][f"I{wait}"]
        if not key.startswith("P"):
            continue
        info = details(baseline,ledger["入口固定"][key],account,dates,wait)
        results[key] = info
        period = info["期間"]
        full = period["全45"]
        actual,base = full["候補"],full["基準"]
        fixed,source = info["固定"],info["元の理由別"]
        attrs = [actual["利益"],actual["損失"],actual["収支"],full["金額差"]["損失"],full["金額差"]["収支"],
                 actual["場末DD既知"],actual["赤字場"],actual["利益後赤字損失"],period["前24"]["金額差"]["収支"],
                 period["後21"]["金額差"]["収支"],full["改善上位3日除外差"],fixed["収支"]-base["収支"],fixed["損失"]-base["損失"]]
        lines.append("|"+"|".join([key,f"{actual['取得']}/{actual['未知']}",*[f"{x:,.0f}" for x in attrs],
                                     f"{source[1]['返済原行維持']}/{source[1]['母数']}",str(source[2]["赤から黒"])])+"|")
    (HERE/(args.出力名+".md")).write_text("\n".join(lines)+"\n",encoding="utf8")
    (args.入力.parent/(args.出力名+".json")).write_text(json.dumps(results,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
