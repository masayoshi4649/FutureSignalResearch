"""RC20の取引を一件ずつ検算し、原板のデイ・ナイト全日程に研究対象と損益を対応づける。"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: Path) -> list:
    """
    機能：列名付きの正式CSVをUTF-8として読み取る。
    引数：path（Path）はCSV。返り値：list[dict]。各行の列名と値。
    """
    with path.open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    """
    機能：日次の利益・損失・累計・取得を約定と照合し、夜間は対象外と明示する。
    引数：なし。試行224のRC20正式CSVと対象期間の銘柄別原板フォルダを参照する。
    返り値：None。CSV作成器に渡す型付き表を作業領域へ保存する。
    """
    folder = next((ROOT/"outputs").glob("00224*/224_RC20*"))
    days = {r["セッション"]:r for r in read(folder/"デイ.csv")}
    book = read(folder/"建玉明細.csv")
    dates = sorted(k[:10] for k in days)
    scenes = sorted(p.name for p in (ROOT.parent/"JP_OSE_Data/future/NK225").iterdir()
                    if p.is_dir() and p.name.endswith(("_Day","_Night")) and dates[0]<=p.name[:10]<=dates[-1])
    assert set(days)=={s for s in scenes if s.endswith("_Day")}
    label = book[0]["候補"]
    total,profit,loss = 0,0,0
    rows = []
    for scene in scenes:
        if scene.endswith("_Night"):
            rows.append([label,scene[:10],"ナイト","対象外",*[None]*7])
            continue
        trades = [r for r in book if r["セッション"]==scene]
        amounts = []
        for t in trades:
            value = (float(t["決済値pt"])-float(t["建値pt"]))*(100 if t["方向"]=="買い" else -100)-1077
            assert value==float(t["費用後収支円"])
            amounts.append(int(value))
        up = sum(v for v in amounts if v>0)
        down = -sum(v for v in amounts if v<0)
        net = up-down
        total += net
        profit += up
        loss += down
        buy = sum(t["方向"]=="買い" for t in trades)
        row = days[scene]
        assert (up,down,net,total,len(trades))==tuple(int(row[k]) for k in
            ("既知利益円","既知損失円","確定収支円","確定累計円","建玉回数"))
        rows.append([label,scene[:10],"デイ","対象",up,down,net,total,len(trades),buy,len(trades)-buy])
    # ----------------------------------------
    fields = ["候補","セッション開始日","時間帯","RC20の対象","利益円","損失円","収支円","累計収支円",
              "建玉回数","買い回数","売り回数"]
    summary = {"headers":["候補","対象デイ","対象外ナイト","建玉回数","利益円","損失円","収支円"],
               "rows":[[label,len(days),len(scenes)-len(days),len(book),profit,loss,total]]}
    data = {"tableNames":{"候補比較":"集計","全セッション":"全セッション"},
            "tables":{"候補比較":summary,"全セッション":{"headers":fields,"rows":rows}}}
    dest = ROOT/"work/227全場"
    dest.mkdir(parents=True,exist_ok=True)
    (dest/"閲覧入力.json").write_text(json.dumps(data,ensure_ascii=False),encoding="utf8")


if __name__=="__main__":
    main()
