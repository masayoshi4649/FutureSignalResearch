"""新しい日経199_02デイに、元IFD・B400P3・B400P4・S3P3を同じ入力で固定適用する。"""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
OLD = next(HERE.parent.glob("00219_*"))
MODES = ("口座再生","入口固定")


def digest(data: list) -> str:
    """
    機能：同じ場・候補の取引の順序と全項目を、JSONキーの表示順に依存せず照合する。
    引数：data（list）は全取引の元帳。
    返り値：str。正規化したUTF-8のSHA256。
    """
    payload = json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    return sha256(payload.encode("utf8")).hexdigest()


def main() -> None:
    """
    機能：指定した新しい場の固定予約を1枠で再生し、元IFDの取得だけに適用した診断も保存する。
    引数：CLIの母集団・純入口・板索引・出力（Path）、場（str列）、既使用照合（bool）。
    返り値：None。新規JSONに指紋、使用場、取得と決済の両元帳を出力する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+arg,type=Path,required=True)
    parser.add_argument("--場",nargs="+",required=True)
    parser.add_argument("--既使用照合",action="store_true",help="固定した既使用3日の原行と両元帳を照合")
    args = parser.parse_args()
    frozen = json.loads((HERE/"追加デイの固定条件.json").read_bytes())
    days = sorted(args.場)
    for day in days:
        try:
            valid = day==date.fromisoformat(day[:10]).isoformat()+"_Day"
        except ValueError:
            valid = False
        if not valid or days.count(day)>1:
            parser.error("重複のない YYYY-MM-DD_Day 形式のデイを指定してください。")
        if args.既使用照合 and day not in frozen["既使用照合"]:
            parser.error("照合元があるのは11月18日・19日・20日です。")
        if not args.既使用照合 and day<=frozen["既使用最終場"]:
            parser.error("追加適用は11月20日より新しい場を指定してください。既使用日には --既使用照合 を使用します。")
    for filename,expected in frozen["ソースSHA256"].items():
        if sha256((HERE/filename).read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=expected:
            parser.error(f"固定条件のソースに変更があります。{filename}")
    # ----------------------------------------
    engine = runpy.run_path(str(OLD/"口座再生.py"))
    main_policy = runpy.run_path(str(HERE/"主比較/出口条件.py"))
    points_policy = runpy.run_path(str(HERE/"絶対幅/出口条件.py"))
    source = engine["SOURCE"]
    scenes,arrays,*_ = source["inputs"](args.母集団,args.純入口,"")
    lookup = {s["session"]:(i,s) for i,s in enumerate(scenes)}
    manifests = {s["session"]:s for s in source["read"](args.板索引)["scenes"]}
    if set(days)-(lookup.keys() & manifests.keys()):
        parser.error("指定したデイに対応する当時特徴・純入口・価格索引が必要です。")
    paths = (args.純入口,args.板索引,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz")
    result = {"区分":"既使用データの再現照合" if args.既使用照合 else "固定後の追加デイ",
              "対象場":days,"入力SHA256":{str(p):sha256(p.read_bytes()).hexdigest() for p in paths},
              "口座再生":{},"入口固定":{}}
    for day in days:
        scene_id,scene = lookup[day]
        index = engine["FINANCE"]["load_scene"](args.板索引.parent,manifests[day])
        stream = engine["orders"](arrays,scene_id,scene,index)
        primary = engine["exits"](index,scene,main_policy)
        points = engine["exits"](index,scene,points_policy)
        base,_ = engine["replay"](stream,scene,"IFD",primary)
        for code in frozen["候補"]:
            if code=="IFD":
                account,fixed = base,base
            else:
                settle = primary if code=="S3P3" else points
                account,_ = engine["replay"](stream,scene,code,settle)
                fixed = [dict(t,**settle(code,t["entry_index"],t["side"],t["width"],t["horizon"])) for t in base]
            for mode,rows in zip(MODES,(account,fixed),strict=True):
                if args.既使用照合 and digest(rows)!=frozen["既使用照合"][day][mode][code]:
                    raise ValueError(f"45日の基準元帳と一致しません。{day}・{mode}・{code}")
                result[mode].setdefault(code,[]).extend(rows)
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    with args.出力.open("x",encoding="utf8") as dst:
        json.dump(result,dst,ensure_ascii=False,allow_nan=False)


if __name__=="__main__":
    main()
