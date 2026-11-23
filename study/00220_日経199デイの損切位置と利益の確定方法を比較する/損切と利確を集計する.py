"""日経199_02の出口を一枚口座で比較し、代表条件の建玉ごとの注文水準を記録する。"""
import argparse
from datetime import date
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = runpy.run_path(str(next(HERE.parent.glob("00219_*/出口を集計する.py"))))
WORK = ROOT/"work"/"220出口集計"


def levels(row: dict, code: str) -> list:
    """
    機能：新規で置いた初期ストップと静的利確、追尾が発動した際の床を絶対価格で返す。
    引数：row（dict）は再生元帳の1建玉、code（str）は出口識別子。
    返り値：list。価格水準は理論閾値、該当する注文がない場合はNone。
    """
    price, sign = row["entry_price"], 1 if row["side"]==0 else -1
    loss = row["width"] if code=="IFD" else row.get("initial_stop_points",row.get("stop_points"))
    assert loss is not None and loss>0
    target = row["width"] if code=="IFD" else row["target_points"]
    floor = row.get("floor_points") if row.get("trigger_time") is not None else None
    return [round(loss,5),round(price-sign*loss,5),target,round(price+sign*target,5) if target is not None else None,
            round(price+sign*floor,5) if floor is not None else None]


def series(book: list, fixed: list, base: list, dates: list) -> tuple:
    """
    機能：全期・前後・一週除外や大きな損失を同一デイ集合で診断する。
    引数：book・fixed・base（list）は対象と固定181件と元口座、dates（list）は45日。
    返り値：tuple。比較統計と全場の日計。
    """
    c, days = OLD["evaluate"](dates,base,fixed,book)
    old, _ = OLD["calculate"](dates,base,"全体")
    # ----------------------------------------
    weeks = {}
    for day,b in zip(days,old,strict=True):
        week = date.fromisoformat(day["場"][:10]).isocalendar().week
        totals = weeks.setdefault(week,[0,0,0])
        totals[0] += day["収支"]-b["収支"]
        totals[1] += b["損失"]-day["損失"]
        totals[2] += day["未知"]+b["未知"]
    weekly = [[sum(v[i] for w,v in weeks.items() if w!=week) for i in range(3)] for week in weeks]
    c["週除外の両改善数"] = sum(n>0 and l>0 and u==0 for n,l,u in weekly)
    c["起動後赤字"] = sum(t.get("activation_time") is not None and t["net"] is not None and t["net"]<0 for t in book)
    return c,days


def main() -> None:
    """
    機能：元帳を統合し、候補群別の前半選択、全設定の比較、代表別CSVの型付き入力を生成する。
    引数：CLIの元帳（Path列）は各群の比較元帳、--閲覧（Path）は候補名の辞書。
    返り値：None。作業領域に数値、試行フォルダにMarkdown表を出力する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("元帳",type=Path,nargs="+")
    parser.add_argument("--閲覧",type=Path)
    args = parser.parse_args()
    selected = json.loads(args.閲覧.read_bytes()) if args.閲覧 else {}
    cases,groups = {},{}
    dates,orig,_ = OLD["sources"]("デイ")
    expected = orig["216:日経199_02"]
    headers = ["候補","方向","判断日時JST","新規日時JST","建値pt","元IFD片幅pt","元期限",
               "決済日時JST","決済値pt","費用後収支円","決済理由","新規原行","決済原行","最大評価損益円",
               "最大評価日時JST","最小評価損益円","最小評価日時JST","保護起動時刻JST","保護発動時刻JST","最終保護床の建値比pt",
               "初期損切幅pt","初期損切価格","固定利確幅pt","固定利確価格","保護発動時の床価格"]
    tables = {"候補比較":{"headers":["候補","期間",*OLD["COLS"].values()],"rows":[]},
              "デイ":{"headers":["候補",*OLD["DAY"].values()],"rows":[]},
              "建玉明細":{"headers":headers,"rows":[]}}
    lines = ["# 損切と利確の全組合せ","",
             "円はmini 1枚、往復1,077円控除後。損失・最大下落は正額。未知があれば利益・損失・収支は既知分。週除外は9通りのうち、元IFDより損失減・収支増かつ両者に未知のない残存40日の数。","",
             "|群|ID|件数|未知|総利益|総損失|費用後収支|最大1件損失|日末最大下落|赤字日|固定181損失|固定181収支|前24収支|後21収支|改善上位3日除外差|週除外|",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    base = None
    for path in args.元帳:
        data = json.loads(path.read_bytes())
        acc,fx = data["口座再生"],data["入口固定"]
        if base is None:
            base = acc["IFD"]
            assert len(base)==181 and len(dates)==45
            assert all((a["entry_line"],a["exit_line"],a["net"])==(b["entry_line"],b["exit_line"],b["net"])
                       for a,b in zip(base,expected,strict=True))
        assert acc["IFD"]==base and set(acc)==set(fx)
        group = path.parent.name
        groups[group] = [code for code in acc if code!="IFD"]
        for code,book in acc.items():
            if code=="IFD" and code in cases:
                continue
            assert code not in cases
            c,days = series(book,fx[code],base,dates)
            cases[code] = c
            a,f,p = c["期間"]["全45日"],c["入口固定"],c["期間"]
            nums = [a["取得"],a["未知"],a["利益"],a["損失"],a["収支"],-c["最悪の確定建玉"][1],
                    a["場末DD既知"],a["赤字場"],f["損失"],f["収支"],p["前24日"]["収支"],p["後21日"]["収支"],
                    c["改善上位3日を除く差"],c["週除外の両改善数"]]
            lines.append("|"+"|".join([group,code,*[f"{n:,.0f}" for n in nums]])+"|")
            if code in selected:
                start = len(tables["建玉明細"]["rows"])
                OLD["record"](tables,"220:"+selected[code],book,days,c)
                for row, trade in zip(tables["建玉明細"]["rows"][start:],book,strict=True):
                    row.extend(levels(trade,code))
    # ----------------------------------------
    assert set(selected)<=cases.keys()
    lines.extend(["","## 各群で前24日の基準を適用した結果","",
                  "順位条件は[比較方針](比較方針.md)を参照。結果を見て追加した群も既使用期間内の診断である。",""])
    for group,codes in groups.items():
        choice = OLD["front_choice"](cases,codes)
        lines.append(f"- {group}　{choice['選抜'] or '該当なし'}（適格 {len(choice['適格順位'])}案）")
    WORK.mkdir(parents=True,exist_ok=True)
    (WORK/"全成績.json").write_text(json.dumps(cases,ensure_ascii=False,allow_nan=False),encoding="utf8")
    if selected:
        (HERE/"全条件の比較.md").write_text("\n".join(lines)+"\n",encoding="utf8")
        payload = {"tableNames":{"候補比較":"集計","デイ":"デイ","建玉明細":"建玉明細"},"tables":tables}
        (WORK/"閲覧入力.json").write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
