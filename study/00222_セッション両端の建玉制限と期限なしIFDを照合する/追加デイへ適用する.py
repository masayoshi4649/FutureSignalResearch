"""開始20分・30分を見送る日経199_02の固定4口座を、追加日の入力に適用する。"""
import argparse
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
WAITS = (20,30)


def digest(rows: list) -> str:
    """
    機能：場内の建玉順・全項目を、JSONキーの表示順と改行に依存せず照合する。
    引数：rows（list）は同一デイ・同一候補の建玉明細。
    返り値：str。正規化したUTF-8のSHA256。
    """
    data = json.dumps(rows,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(",",":"))
    return sha256(data.encode("utf8")).hexdigest()


def main() -> None:
    """
    機能：指定日の199_02純入口を予約から処理し、4候補それぞれの日次CSVと建玉元帳を保存する。
    引数：母集団・純入口・板索引・出力（Path）、場（str列）、既使用照合（bool、任意）。
    返り値：None。既使用照合では基準45日から得た同日の建玉・順序・全項目の指紋も検査する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+arg,type=Path,required=True)
    parser.add_argument("--場",required=True,nargs="+")
    parser.add_argument("--既使用照合",action="store_true")
    args = parser.parse_args()
    frozen = json.loads((HERE/"追加デイの固定条件.json").read_bytes())
    days = sorted(args.場)
    try:
        valid = len(days)==len(set(days)) and all(date.fromisoformat(s[:10]).isoformat()+"_Day"==s for s in days)
    except ValueError:
        valid = False
    if not valid:
        parser.error("場は重複しない YYYY-MM-DD_Day 形式で指定してください。")
    if args.既使用照合:
        if set(days)-frozen["既使用照合"].keys():
            parser.error("既使用照合の対象は2026年11月18・19・20日です。")
    elif days[0]<=frozen["既使用最終場"]:
        parser.error("追加日には既使用期間より後のデイを指定してください。")
    if args.出力.exists():
        parser.error("出力には新規フォルダ名を指定してください。")
    for name,value in frozen["ソースSHA256"].items():
        if sha256((HERE/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=value:
            parser.error(f"固定した再生コードが変更されています。{name}")
    # ----------------------------------------
    research = runpy.run_path(str(HERE/"建玉制限を再生する.py"))
    source = research["SOURCE"]
    scenes,arrays,*_ = source["inputs"](args.母集団,args.純入口,"")
    lookup = {s["session"]:(i,s) for i,s in enumerate(scenes)}
    manifests = {s["session"]:s for s in source["read"](args.板索引)["scenes"]}
    if set(days)-(lookup.keys() & manifests.keys()):
        parser.error("対象日に対応する母集団・純入口・板索引が必要です。")
    inputs = [args.純入口,args.板索引,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz"]
    output = {"区分":"既使用照合" if args.既使用照合 else "追加日の固定適用","対象場":days,
              "入力SHA256":{str(p):sha256(p.read_bytes()).hexdigest() for p in inputs},
              "口座再生":{code:[] for code in frozen["候補"]},"場別の予約":{}}
    for day in days:
        i,scene = lookup[day]
        index = research["ENGINE"]["FINANCE"]["load_scene"](args.板索引.parent,manifests[day])
        accounts,output["場別の予約"][day] = research["replay_day"](arrays,i,scene,index,WAITS)
        assert accounts.keys()==output["口座再生"].keys()
        for code,rows in accounts.items():
            if args.既使用照合 and digest(rows)!=frozen["既使用照合"][day][code]:
                raise ValueError(f"{day}・{code}の建玉が45デイの結果と一致しません。")
            output["口座再生"][code].extend(rows)
    # ----------------------------------------
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    fields = ["対象デイ","費用後既知利益円","費用後既知損失円","費用後既知収支円","費用後確定収支円",
              "費用後既知累計円","費用後確定累計円","建玉回数","決済未知件数","対象秒","既知保有秒","保有時間率"]
    keys = ["場","利益","損失","収支","確定収支","既知累計","確定累計","取得","未知","対象秒","保有秒","保有率"]
    with TemporaryDirectory(dir=args.出力.parent) as tmp:
        dest = Path(tmp)/"保存先"
        dest.mkdir()
        for code,book in output["口座再生"].items():
            daily,_ = research["measures"](days,book,frozen["候補"][code])
            with (dest/(code+"_デイ.csv")).open("w",encoding="utf-8-sig",newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(fields)
                writer.writerows([row[key] for key in keys] for row in daily)
        (dest/"再生元帳.json").write_text(json.dumps(output,ensure_ascii=False,allow_nan=False),encoding="utf8")
        dest.rename(args.出力)


if __name__=="__main__":
    main()
