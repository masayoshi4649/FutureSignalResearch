"""再開規則ごとの実口座を、単純IFDとの差・日別の広がり・含み益後の損失で比較する。"""
import argparse
import csv
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = runpy.run_path(str(next(HERE.parent.glob("00222_*/建玉制限を再生する.py"))))
CSV = runpy.run_path(str(next(HERE.parent.glob("00222_*/候補別CSVを用意する.py"))))
OLD = CSV["OLD"]
RULE = {"A":"即再開","B":"反対信号","N":"中立か反対","C":"元価格まで待つ","D":"価格か反対"}
FAMILY = {"P":"P20","S":"S00","R":"R02"}
FILES = {"候補比較":"集計","デイ":"デイ","建玉明細":"建玉明細"}
DETAIL = ["候補","セッション","方向","判断日時JST","新規日時JST","建値pt","IFD片幅pt","利確指値pt",
          "初期損切価格pt","決済日時JST","決済値pt","費用後収支円","決済理由","新規原行","決済原行",
          "最大評価損益円","最大評価日時JST","最小評価損益円","最小評価日時JST","追尾起動時刻JST","追尾発動時刻JST"]


def compare(dates: list, trade_list: list, baseline: list, wait: int) -> tuple:
    """
    機能：全日・前後期間の各実口座を集計し、改善額の日集中を同じ日の対照的な実口座の差で測る。
    引数：dates（list）は対象日、trade_list・baseline（list）は候補と基準の実建玉、wait（int）は静観分。
    返り値：tuple。期間別集計、全45日の各日、全体の基準差診断を順に返す。
    """
    periods = {"全45日":dates,"前24日":dates[:24],"後21日":dates[24:],"直近3日":dates[-3:]}
    results = {}
    for period,days in periods.items():
        selected = [t for t in trade_list if t["scene"] in days]
        base = [t for t in baseline if t["scene"] in days]
        real,summary = BASE["measures"](days,selected,wait)
        ref,old = BASE["measures"](days,base,wait)
        summary.update(収支差=summary["収支"]-old["収支"],損失差=summary["損失"]-old["損失"])
        results[period] = summary
        if period=="全45日":
            daily = real
            difference = [(r["場"][:10],r["収支"]-b["収支"]) for r,b in zip(real,ref,strict=True)]
    up = sorted([(d,v) for d,v in difference if v>0],key=lambda p:-p[1])
    down = [(d,v) for d,v in difference if v<0]
    diag = {"改善日":up,"悪化日":down,"改善上位3日除外収支差":results["全45日"]["収支差"]-sum(v for _,v in up[:3])}
    return results,daily,diag


def add_tables(tables: dict, code: str, book: list, results: dict, daily: list) -> None:
    """
    機能：一候補の実現取引・全45日・各期間の行をCSVの中間表に積む。
    引数：tables・results（dict）は出力表と期間計、code（str）は条件ID、book・daily（list）は建玉・日計。
    返り値：None。費用は全建玉で建値・返済値から独立に照合する。
    """
    name = f"224:{code}_{FAMILY[code[0]]}{RULE[code[1]]}"
    for t in book:
        tables["建玉明細"]["rows"].append(CSV["trade_row"](name,t))
    for day in daily:
        subset = [t for t in book if t["scene"]==day["場"]]
        g = OLD["giveback"](subset)
        tables["デイ"]["rows"].append([name,*[day[k] for k in OLD["DAY"]],day["対象秒"],day["保有秒"],
                                     g["利益後赤字"],g["利益後の損失"]])
    for period,r in results.items():
        tables["候補比較"]["rows"].append([name,period,*[r[k] for k in OLD["COLS"]],
                                       r["利益後赤字件数"],r["利益後赤字損失"],r["収支差"],r["損失差"]])


def verify(tables: dict, folder: Path) -> None:
    """
    機能：公開CSVの全セルを元帳から再計算した候補・日付・取引・金額と照合する。
    引数：tables（dict）は出力した全行、folder（Path）は候補ごとのCSVの親ディレクトリ。
    返り値：None。行・列・文字列・数値のいずれかが異なると検査を停止する。
    """
    for key,table in tables.items():
        for name in {row[0] for row in table["rows"]}:
            path = folder/name.replace(":","_")/(FILES[key]+".csv")
            with path.open(encoding="utf-8-sig",newline="") as stream:
                reader = csv.reader(stream)
                assert next(reader)==table["headers"]
                subset = [row for row in table["rows"] if row[0]==name]
                for row,wanted in zip(reader,subset,strict=True):
                    for cell,value in zip(row,wanted,strict=True):
                        same = float(cell)==value if isinstance(value,(int,float)) else cell==("" if value is None else value)
                        assert same,(path,cell,value)


def main() -> None:
    """
    機能：初回と追試を区別し、結果表とCSV用入力を作って公開済みなら全セルを読む。
    引数：CLI --照合（Path、任意）は公開先。元帳は試行222と224の標準作業先を参照する。
    返り値：None。条件別の45日集計と日付別の効果を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--照合",type=Path)
    args = parser.parse_args()
    baseline = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())
    dates = baseline["対象場"]
    diagnostic = {}
    benefit = ["含み益後赤字件数","含み益後赤字の損失円"]
    columns = {"候補比較":["候補","期間",*OLD["COLS"].values(),*benefit,"単純IFDとの収支差円","単純IFDとの損失差円"],
               "デイ":["候補",*OLD["DAY"].values(),"対象秒数","既知保有秒数",*benefit],"建玉明細":DETAIL}
    tables = {k:{"headers":v,"rows":[]} for k,v in columns.items()}
    lines = ["# 利益保護の後に再開する条件別の口座比較","",
             "mini 1枚、費用後の円。総損失は赤字の絶対額。差は同じ開始待機の単純IFDを引いた値。"
             "保有率は実際の建玉時間を開始待機後から15:30までの合計時間で割った。"
             "上位3除外は対照との日次収支差が良かった3日を除いた収支差。全口座とも45/45日参加、未知0件。"]
    for title,source in (("P20とS00の初回比較","224再開"),("R02への追加追試","224反対追試")):
        ledger = json.loads((ROOT/"work"/source/"口座元帳.json").read_bytes())
        assert dates==ledger["対象場"]
        lines.extend(["","## "+title,"",
                      "|条件|建玉|総利益|総損失|収支|損失差|収支差|赤字日|日末DD|保有率|含み益後赤字損失|前24日収支差|後21日収支差|後21日損失差|改善日／悪化日|上位3除外|",
                      "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        for code,book in sorted(ledger["口座再生"].items(),key=lambda x:(x[0][-2:],x[0][:2])):
            wait = ledger["開始待機分"][code]
            result,daily,diag = compare(dates,book,baseline["口座再生"]["I"+str(wait)],wait)
            full = result["全45日"]
            assert full["参加場"]==45 and full["未知"]==0
            diagnostic[code] = {"期間":result,**diag}
            n = [full[k] for k in ("取得","利益","損失","収支","損失差","収支差","赤字場","場末DD既知")]
            extra = [full["利益後赤字損失"],result["前24日"]["収支差"],result["後21日"]["収支差"],result["後21日"]["損失差"]]
            line = [code,*[f"{v:,.0f}" for v in n],f"{full['保有率']:.2%}",*[f"{v:,.0f}" for v in extra],
                    f"{len(diag['改善日'])}/{len(diag['悪化日'])}",f"{diag['改善上位3日除外収支差']:,.0f}"]
            lines.append("|"+"|".join(line)+"|")
            # 試行223に公開済みのAは再掲せず、休止方法ごとに日別結果を保存する。
            if code[1]!="A":
                add_tables(tables,code,book,result,daily)
    output = ROOT/"work/224再開"
    (HERE/"全条件の比較.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    (output/"集計.json").write_text(json.dumps(diagnostic,ensure_ascii=False,allow_nan=False),encoding="utf8")
    payload = {"tableNames":FILES,"tables":tables}
    (output/"閲覧入力.json").write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")
    if args.照合:
        verify(tables,args.照合)


if __name__=="__main__":
    main()
