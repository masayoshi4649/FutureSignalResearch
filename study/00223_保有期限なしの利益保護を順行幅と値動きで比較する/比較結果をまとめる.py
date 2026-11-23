"""出口変更の効果を全口座、同じ元取得、前後期間、元の決済理由別に計算する。"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT/"work/223集計"
BASE = runpy.run_path(str(next(HERE.parent.glob("00222_*/建玉制限を再生する.py"))))
OLD = runpy.run_path(str(next(HERE.parent.glob("00219_*/出口を集計する.py"))))


def compare(dates: list, wait: int, base: list, fixed: list, account: list) -> dict:
    """
    機能：元の価格注文を残せた件数、同じ元取得での金額変化、実口座の赤字と入替えを集計する。
    引数：dates（list）は45場、wait（int）は開始待機分、base・fixed・account（list）は各建玉元帳。
    返り値：dict。実口座と固定入口、期間別・集中度・理由別・前半の適格判定を含む。
    """
    assert [OLD["key"](t) for t in base]==[OLD["key"](t) for t in fixed]
    periods = {"全45日":dates,"前24日":dates[:24],"後21日":dates[24:],"直近3日":dates[-3:]}
    totals,old,details = {},{},{}
    for name,span in periods.items():
        days,totals[name] = BASE["measures"](span,account,wait)
        prior,old[name] = BASE["measures"](span,base,wait)
        if name=="全45日":
            delta = [(x["場"],x["収支"]-y["収支"]) for x,y in zip(days,prior,strict=True)
                     if x["未知"]+y["未知"]==0]
            totals[name]["改善上位日"] = max(delta,key=lambda p:p[1])
            totals[name]["改善上位1日除外差"] = sum(n for _,n in delta)-max(n for _,n in delta)
            totals[name]["改善上位3日除外差"] = sum(n for _,n in delta)-sum(sorted([n for _,n in delta],reverse=True)[:3])
            totals[name]["改善日"] = sum(n>0 for _,n in delta)
            totals[name]["悪化日"] = sum(n<0 for _,n in delta)
    for prior,t in zip(base,fixed,strict=True):
        group = details.setdefault(prior["status"],[0,0,0,0])
        group[0] += 1
        if t["net"] is not None:
            group[1] += (prior["exit_line"],prior["net"])==(t["exit_line"],t["net"])
            group[2] += t["net"]-prior["net"]
        else:
            group[3] += 1
    a,b = totals["前24日"],old["前24日"]
    valid = (a["未知"]==0 and a["参加場"]==len(dates[:24]) and a["保有率"]>=.20 and
             min(a["建玉中央値下限"],a["場中央値下限"])>0 and a["損失"]<b["損失"] and a["収支"]>b["収支"] and
             a["赤字場"]<=b["赤字場"] and a["場末DD既知"]<=b["場末DD既知"])
    for name,c in totals.items():
        for field in ("損失","収支","利益後赤字損失"):
            c[field+"差"] = c[field]-old[name][field]
    fixed_delta = OLD["money"](fixed)
    fixed_delta["収支差"] = fixed_delta["収支"]-OLD["money"](base)["収支"]
    pairs = OLD["contrast"](base,account)
    side_result = {}
    for side,title in ((0,"買い"),(1,"売り")):
        side_result[title] = OLD["money"]([t for t in account if t["side"]==side])
    return {"口座":totals,"固定":fixed_delta,"固定利益後赤字":OLD["giveback"](fixed),"固定の元理由":details,
            "入替え":pairs,"方向":side_result,"前24日適格":valid}


def main() -> None:
    """
    機能：各実験の個別元帳を収集し、前半選抜、全条件の金額と元利確保持数をMarkdownに保存する。
    引数：CLIの元帳（Path列）と任意の --閲覧（Path）は候補IDからCSV表示名への辞書。
    返り値：None。診断JSON、比較表、指定時は候補別CSV入力も作成する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("元帳",nargs="+",type=Path)
    parser.add_argument("--閲覧",type=Path)
    args = parser.parse_args()
    before = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    dates,baselines = before["対象場"],before["口座再生"]
    cases,books = {},{}
    groups = defaultdict(dict)
    text = ["# 日経199_02の利益保護・全条件","",
            "mini1枚、費用後の円。損失は正額。固定差は同じ133取得での収支差。元利確は同原行・同額を保った件数。"
            "口座は予約・保有1枚で全要求を再生。各差は同じ開始待機の単純IFD比。未知がある場合の金額は既知分。","",
            "|出口|待機|建玉|未知|総利益|総損失|費用後収支|日末DD|赤字日|利益後赤字の損失|固定差|元利確維持|前24日収支差|後21日収支差|最大改善日除外差|",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for path in sorted(args.元帳,key=lambda p:p.parent.name):
        data = json.loads(path.read_bytes())
        for key,account in data["口座再生"].items():
            id_,tail = key.split("_")
            wait = int(tail)
            assert key not in cases
            b = baselines[f"I{wait}"]
            fixed = data["入口固定"][key]
            c = compare(dates,wait,b,fixed,account)
            cases[key],books[key] = c,account
            if not any(mark in id_ for mark in ("L","D")):
                groups[id_][wait] = c
            a = c["口座"]["全45日"]
            fields = [a[k] for k in ("取得","未知","利益","損失","収支","場末DD既知","赤字場","利益後赤字損失")]
            fields.append(c["固定"]["収支差"])
            kept = c["固定の元理由"][1]
            ends = [c["口座"][p]["収支差"] for p in ("前24日","後21日")]+[a["改善上位1日除外差"]]
            text.append("|"+"|".join([id_,tail,*[f"{x:,.0f}" for x in fields],f"{kept[1]}/{kept[0]}",*[f"{x:+,.0f}" for x in ends]])+"|")
            if id_ in ("V00","V01"):
                ref = baselines[("I" if id_=="V00" else "T")+tail]
                assert all(all(x[k]==y[k] for k in ("scene","side","entry_line","exit_line","net","exit_time"))
                           for x,y in zip(account,ref,strict=True))
    eligible = []
    for id_,items in groups.items():
        assert items.keys()=={20,30}
        if all(c["前24日適格"] for c in items.values()):
            eligible.append((max(c["口座"]["前24日"]["利益後赤字損失差"] for c in items.values()),
                             max(c["口座"]["前24日"]["損失差"] for c in items.values()),id_))
    eligible.sort()
    text += ["","## 前24日での共通選抜","",
             "両待機適格の順位　"+("、".join(v[-1] for v in eligible) if eligible else "該当なし")+"。遅延感度は順位に含めない。"
             "再試行には既使用期間全体の診断が入る。前後の期間分解を新規データ検証と解釈しない。"]
    WORK.mkdir(parents=True,exist_ok=True)
    (WORK/"全成績.json").write_text(json.dumps(cases,ensure_ascii=False,allow_nan=False),encoding="utf8")
    (HERE/"全条件の比較.md").write_text("\n".join(text)+"\n",encoding="utf8")
    if args.閲覧:
        csv_input(json.loads(args.閲覧.read_bytes()),books,dates)


def csv_input(labels: dict, books: dict, dates: list) -> None:
    """
    機能：選んだ出口を開始20分と30分の別候補に分け、日次・期間別・建玉表を出力する。
    引数：labels（dict）は出口IDと日本語短名、books（dict）は口座元帳、dates（list）は45場。
    返り値：None。共通CSV出力器に渡す型付きJSONを作業領域へ保存する。
    """
    csv = runpy.run_path(str(next(HERE.parent.glob("00222_*/候補別CSVを用意する.py"))))
    payload = None
    for id_,label in labels.items():
        names = {f"I{n}":f"223:{id_}_{label}_{n}分" for n in (20,30)}
        csv["NAMES"].clear()
        csv["NAMES"].update(names)
        small = csv["build"]({"対象場":dates,"開始待機分":{"I20":20,"I30":30},
                              "口座再生":{k:books[f"{id_}_{k[1:]}"] for k in names}})
        if payload is None:
            payload = small
        else:
            for table in small["tables"]:
                payload["tables"][table]["rows"].extend(small["tables"][table]["rows"])
    (WORK/"閲覧入力.json").write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
