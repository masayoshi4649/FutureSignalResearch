"""開始の静観を除いた参加率と、建玉・各日・期間の損益を候補別CSVへ渡す。"""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT/"work/222境界照合"
OLD = runpy.run_path(str(next(HERE.parent.glob("00219_*/出口を集計する.py"))))
NAMES = {f"{prefix}{wait:02d}":f"222:{prefix}{wait:02d}_{title}{wait}分待機"
         for wait in (0,15,20,30) for prefix,title in (("I","両注文"),("T","両注文と追尾"))}
TABLE_NAMES = {"候補比較":"集計","デイ":"デイ","建玉明細":"建玉明細"}


def trade_row(name: str, trade: dict) -> list:
    """
    機能：新規、返済、追尾の時計と価格を取り出し、費用後の建玉損益を独立に計算して照合する。
    引数：name（str）は候補の表示名、trade（dict）は予約1枠で取得した建玉。
    返り値：list。CSVの1行分の値。未確定の決済欄は空欄として扱う。
    """
    stamp = OLD["stamp"]
    sign = 1 if trade["side"]==0 else -1
    entry = trade["entry_price"]
    width = trade["width"]
    net = trade["net"]
    if net is not None:
        assert net==(trade["exit_price"]-entry)*sign*100-1077
        assert trade["status"] in (1,2,4,5)
    return [name,trade["scene"],"買い" if sign>0 else "売り",stamp(trade["request_time"]),
            stamp(trade["entry_time"]),entry,width,entry+sign*width,entry-sign*width,stamp(trade["exit_time"]),
            trade["exit_price"],net,trade["exit_reason"],trade["entry_line"],trade["exit_line"] if net is not None else None,
            trade["max_unrealized_net"],stamp(trade["max_unrealized_time"]),trade["min_unrealized_net"],
            stamp(trade["min_unrealized_time"]),stamp(trade.get("activation_time")),stamp(trade.get("trigger_time"))]


def build(data: dict) -> dict:
    """
    機能：全45日を残し、開始静観と場末無保有を除いた時間を分母にして候補別の各表を作る。
    引数：data（dict）は対象場、候補ごとの開始待機分と口座再生元帳。
    返り値：dict。既存の候補別CSV出力器に渡す型付き表。
    """
    dates = data["対象場"]
    accounts = data["口座再生"]
    waits = data["開始待機分"]
    assert sorted(set(dates))==dates and len(dates)==45 and all(d.endswith("_Day") for d in dates)
    assert set(accounts)==set(waits)==set(NAMES)
    extra = ["対象秒数","既知保有秒数","含み益後赤字件数","含み益後赤字の損失円"]
    headers = {
        "候補比較":["候補","期間",*OLD["COLS"].values(),*extra],
        "デイ":["候補",*OLD["DAY"].values(),*extra],
        "建玉明細":["候補","セッション","方向","判断日時JST","新規日時JST","建値pt","IFD片幅pt","利確指値pt",
                  "初期損切価格pt","決済日時JST","決済値pt","費用後収支円","決済理由","新規原行","決済原行",
                  "最大評価損益円","最大評価日時JST","最小評価損益円","最小評価日時JST","追尾起動時刻JST","追尾発動時刻JST"]}
    tables = {key:{"headers":columns,"rows":[]} for key,columns in headers.items()}
    # ----------------------------------------
    for code,name in NAMES.items():
        wait = waits[code]
        assert wait==int(code[1:])
        seconds = (405-wait)*60
        groups = defaultdict(list)
        held = {d:0 for d in dates}
        for trade in accounts[code]:
            day = trade["scene"]
            midnight = datetime.fromisoformat(day[:10]).replace(tzinfo=OLD["JST"])
            start = (midnight+timedelta(hours=8,minutes=45+wait)).timestamp()
            end = (midnight+timedelta(hours=15,minutes=30)).timestamp()
            entry = trade["entry_time"]
            observed = trade["confirmed_until"]
            assert day in held and start<=trade["request_time"]<=entry<end-60 and entry<=observed<=end
            assert trade["exit_time"] is None or trade["exit_time"]==observed
            groups[day].append(trade)
            held[day] += observed-entry
            tables["建玉明細"]["rows"].append(trade_row(name,trade))
        spans = {"全45日":dates,"前24日":dates[:24],"後21日":dates[24:],"直近3日":dates[-3:]}
        for period,days in spans.items():
            selected = [row for day in days for row in groups[day]]
            daily,summary = OLD["calculate"](days,selected,"全体")
            for item in daily:
                day = item["場"]
                assert 0<=held[day]<=seconds
                item["保有率"] = held[day]/seconds
                if period=="全45日":
                    g = OLD["giveback"](groups[day])
                    tables["デイ"]["rows"].append([name,*[item[k] for k in OLD["DAY"]],seconds,
                                                  held[day],g["利益後赤字"],g["利益後の損失"]])
            duration = sum(held[d] for d in days)
            available = seconds*len(days)
            summary["保有率"] = duration/available
            g = OLD["giveback"](selected)
            tables["候補比較"]["rows"].append([name,period,*[summary[k] for k in OLD["COLS"]],
                                              available,duration,g["利益後赤字"],g["利益後の損失"]])
    return {"tableNames":TABLE_NAMES,"tables":tables}


def verify(payload: dict, folder: Path) -> None:
    """
    機能：公開済みCSVを読み戻し、候補・列・各行の全数値と日時を元帳から作った表と照合する。
    引数：payload（dict）は型付きの3表、folder（Path）は候補別CSVフォルダの親。
    返り値：None。差異があればアサーションを送出する。
    """
    for name in NAMES.values():
        for key,title in TABLE_NAMES.items():
            table = payload["tables"][key]
            path = folder/name.replace(":","_")/(title+".csv")
            wanted = [row for row in table["rows"] if row[0]==name]
            with path.open(encoding="utf-8-sig",newline="") as stream:
                rows = csv.reader(stream)
                assert next(rows)==table["headers"]
                for i,(row,expected) in enumerate(zip(rows,wanted,strict=True),2):
                    for cell,value in zip(row,expected,strict=True):
                        same = float(cell)==value if isinstance(value,(float,int)) else cell==("" if value is None else value)
                        assert same,(str(path),i,cell,value)


def main() -> None:
    """
    機能：研究元帳から閲覧入力を出力し、指定した場合は観測済みの全CSVを再照合する。
    引数：CLIの --元帳・--出力（Path）は入出力、--照合（Path、任意）は候補別CSVの親。
    返り値：None。閲覧入力JSONを書き出す。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--元帳",type=Path,default=WORK/"口座元帳.json")
    parser.add_argument("--出力",type=Path,default=WORK/"閲覧入力.json")
    parser.add_argument("--照合",type=Path)
    args = parser.parse_args()
    payload = build(json.loads(args.元帳.read_bytes()))
    if args.照合:
        verify(payload,args.照合)
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    args.出力.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding="utf8")


if __name__=="__main__":
    main()
