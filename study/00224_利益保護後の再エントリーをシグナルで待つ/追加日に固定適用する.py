"""日経199_02の単純IFDと利益保護後の再開4条件を、追加デイに同じ候補のまま適用する。"""
from argparse import ArgumentParser
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
REFERENCE = next(HERE.parent.glob("00222_*"))
SIGNAL = next(HERE.parent.glob("00223_*/反対の入口シグナル/出口条件.py"))


def apply_day(module: dict, arrays: dict, position: int, scene: dict, index: object) -> dict:
    """
    機能：固定した両開始時刻で基準・反対信号保護・値幅保護を予約込み1枠で比較する。
    引数：module（dict）は試行224の再生関数、arrays（dict）は199の入口、position（int）は場番号、
    scene（dict）は日時と限界、index（PriceIndex）は原板の索引。
    返り値：dict[str,list]。候補別の当日実取引だけを収録した元帳。
    """
    baseline,_ = module["BASE"]["replay_day"](arrays,position,scene,index,(20,30))
    result = {code:baseline[code] for code in ("I20","I30")}
    signals = {"R":("R02",runpy.run_path(str(SIGNAL)),"223反対")}
    accounts,_ = module["day"](arrays,position,scene,index,signals,("A","C"))
    result.update(accounts)
    broad = {f:(module["NAMES"][f],module["POLICIES"][f],module["ORIGINAL"][f]) for f in ("P","S")}
    accounts,_ = module["day"](arrays,position,scene,index,broad,("C",))
    result.update(accounts)
    return result


def main() -> None:
    """
    機能：新規日の再選択を防ぎ、必要な入力・再生部品の指紋と条件別の日次CSVを保存する。
    引数：CLIの母集団・純入口・板索引・出力（Path）、場（list[str]）、圧縮内（str）、既使用照合（bool）。
    返り値：None。全候補・全日が揃った時点で新しい出力フォルダを公開する。
    """
    parser = ArgumentParser(description=__doc__)
    for key in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+key,type=Path,required=True)
    parser.add_argument("--場",nargs="+",required=True)
    parser.add_argument("--圧縮内",default="",help="旧形式の純入口ZIPを使う場合に、含まれるNPZの末尾名を指定する。")
    parser.add_argument("--既使用照合",action="store_true")
    args = parser.parse_args()
    frozen = json.loads((HERE/"追加日の固定条件.json").read_bytes())
    days = sorted(args.場)
    try:
        valid = len(days)==len(set(days)) and all(date.fromisoformat(s[:10]).isoformat()+"_Day"==s for s in days)
    except ValueError:
        valid = False
    if not valid or args.出力.exists():
        parser.error("場は重複しないYYYY-MM-DD_Day、出力は新しいフォルダを指定してください。")
    if args.既使用照合:
        if set(days)-frozen["既使用照合"].keys():
            parser.error("指定場の既使用照合指紋がありません。")
    elif days[0]<=frozen["既使用最終場"]:
        parser.error("追加日は2026年11月20日より後のデイを指定してください。")
    for name,value in frozen["ソースSHA256"].items():
        if sha256((HERE/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=value:
            parser.error(f"固定した研究部品の指紋と異なります。{name}")
    # ----------------------------------------
    methods = runpy.run_path(str(HERE/"再エントリーを再生する.py"))
    source = methods["SOURCE"]
    scenes,arrays,*_ = source["inputs"](args.母集団,args.純入口,args.圧縮内)
    lookup = {s["session"]:(i,s) for i,s in enumerate(scenes)}
    manifest = {s["session"]:s for s in source["read"](args.板索引)["scenes"]}
    if set(days)-(lookup.keys() & manifest.keys()):
        parser.error("対象日の入口と原板索引が必要です。")
    inputs = [args.純入口,args.板索引,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz"]
    if args.圧縮内:
        inputs.append(args.母集団/"取得対応.json.gz")
    archive = {"区分":"既使用照合" if args.既使用照合 else "追加日の固定適用","対象日":days,
               "純入口の圧縮内":args.圧縮内,
               "入力SHA256":{str(p):sha256(p.read_bytes()).hexdigest() for p in inputs},
               "口座再生":{code:[] for code in frozen["候補"]}}
    digest = runpy.run_path(str(REFERENCE/"追加デイへ適用する.py"))["digest"]
    for day in days:
        position,scene = lookup[day]
        index = methods["ENGINE"]["FINANCE"]["load_scene"](args.板索引.parent,manifest[day])
        books = apply_day(methods,arrays,position,scene,index)
        assert books.keys()==archive["口座再生"].keys()
        for code,book in books.items():
            if args.既使用照合 and digest(book)!=frozen["既使用照合"][day][code]:
                raise ValueError(f"{day}の{code}が既使用の全日口座と一致しません。")
            archive["口座再生"][code].extend(book)
    # ----------------------------------------
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    columns = ("場","利益","損失","収支","確定収支","既知累計","確定累計","取得","未知","対象秒","保有秒","保有率")
    with TemporaryDirectory(dir=args.出力.parent) as tmp:
        dest = Path(tmp)/"固定比較"
        dest.mkdir()
        for code,book in archive["口座再生"].items():
            daily,_ = methods["BASE"]["measures"](days,book,int(code[-2:]))
            with (dest/(code+"_デイ.csv")).open("w",encoding="utf-8-sig",newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("対象デイ","既知利益円","既知損失円","既知収支円","確定収支円","既知累計円",
                                 "確定累計円","建玉回数","未知件数","対象秒","実保有秒","保有時間率"))
                writer.writerows([d[k] for k in columns] for d in daily)
        (dest/"再生元帳.json").write_text(json.dumps(archive,ensure_ascii=False,allow_nan=False),encoding="utf8")
        dest.rename(args.出力)


if __name__=="__main__":
    main()
