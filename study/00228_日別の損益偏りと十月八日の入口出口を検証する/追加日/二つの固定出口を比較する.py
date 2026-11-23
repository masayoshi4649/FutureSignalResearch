"""日経199_02の追加デイに試行228のX2と元のRCを固定適用し、各口座の日次成績を別々に出力する。"""
from argparse import ArgumentParser
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
STUDIES = HERE.parents[1]
PREV = next(STUDIES.glob("00227_*/追加日"))
CONTROL = next(STUDIES.glob("00224_*"))
CODES = ("RC20","X2C20","RC30","X2C30")


def fixed_day(engine: dict, previous: dict, policies: tuple, arrays: dict, i: int, scene: dict, index: object) -> dict:
    """
    機能：227の固定追加日経路でRCを再現し、同じ全要求に228のX2を適用して両者の取得と費用を照合する。
    引数：engine・previous（dict）は元口座と227追加日関数、policies（tuple）は既存・新規出口群、
    arrays・scene（dict）は199の入口と場情報、i（int）は場番号、index（PriceIndex）は板。
    返り値：dict。開始20/30分それぞれのRCとX2の日中元帳。
    """
    old,fresh = policies
    verified = previous["checked_day"](engine,old,arrays,i,scene,index)
    result,_ = engine["day"](arrays,i,scene,index,fresh,("C",))
    for wait in ("20","30"):
        standard = verified["RC"+wait]
        result["RC"+wait] = standard
        for a,b in zip(standard,result["X2C"+wait],strict=True):
            assert all(a[k]==b[k] for k in previous["ENTRY"])
            if a["exit_index"]>=0:
                assert 0<=b["exit_index"]<=a["exit_index"]
            if not b["extra_fill"]:
                assert all(a[k]==b[k] for k in ("exit_index","status","net","confirmed_until"))
            if b["net"] is not None:
                assert b["gross"]-1077==b["net"]
    return result


def main() -> None:
    """
    機能：最終既使用日との区別、条件ソース、正常板索引、既使用日全建玉を確認し、結果を一括保存する。
    引数：CLIの母集団・純入口・板索引・出力（Path）、場（list[str]）、圧縮内（str）、既使用照合（bool）。
    返り値：None。新規出力先に元帳と候補別の日次CSVを作る。
    """
    parser = ArgumentParser(description=__doc__)
    for name in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--場",nargs="+",required=True)
    parser.add_argument("--圧縮内",default="")
    parser.add_argument("--既使用照合",action="store_true")
    args = parser.parse_args()
    frozen = json.loads((HERE/"固定条件.json").read_bytes())
    days = sorted(args.場)
    try:
        valid = len(set(days))==len(days) and all(date.fromisoformat(s[:10]).isoformat()+"_Day"==s for s in days)
    except ValueError:
        valid = False
    if not valid or args.出力.exists():
        parser.error("対象は重複のない日経デイ、保存先は未使用のフォルダとして下さい。")
    if args.既使用照合 and set(days)-frozen["既使用照合"].keys():
        parser.error("この場には既使用照合の参照元帳がありません。")
    if not args.既使用照合 and days[0]<=frozen["既使用最終場"]:
        parser.error("既使用日には --既使用照合 が必要です。")
    for folder,config in ((HERE,frozen),(PREV,json.loads((PREV/"固定条件.json").read_bytes())),
                          (CONTROL,json.loads((CONTROL/"追加日の固定条件.json").read_bytes()))):
        for name,expected in config["ソースSHA256"].items():
            if sha256((folder/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=expected:
                parser.error("固定した研究ソースと一致しません。"+name)
    # ----------------------------------------
    engine = runpy.run_path(str(CONTROL/"再エントリーを再生する.py"))
    previous = runpy.run_path(str(PREV/"固定した出口を比較する.py"))
    w12 = runpy.run_path(str(PREV.parent/"弱い反転/確定足の転換.py"))
    x2 = runpy.run_path(str(HERE.parent/"出口/併用条件.py"))
    policies = ({"R":("R02",w12["FIRST"]["COMMON"]["RC"],""),"W12":("W12",w12,"")},{"X2":("X2",x2,"")})
    source = engine["SOURCE"]
    scenes,arrays,*_ = source["inputs"](args.母集団,args.純入口,args.圧縮内)
    positions = {s["session"]:(i,s) for i,s in enumerate(scenes)}
    manifest = source["read"](args.板索引)
    prices = {s["session"]:s for s in manifest["scenes"]}
    if not manifest["success"] or set(days)-(prices.keys() & positions.keys()):
        parser.error("対象日の母集団・199_02純入口・成功した板索引が必要です。")
    digest = runpy.run_path(str(next(STUDIES.glob("00222_*/追加デイへ適用する.py"))))["digest"]
    books = {k:[] for k in CODES}
    for name in days:
        i,scene = positions[name]
        item = prices[name]
        assert item["success"] and item["contract"]==scene["contract"]
        assert item["raw"]["sha256"]==scene["raw"]["sha256"]==item["actual_raw_sha256"]
        index = engine["ENGINE"]["FINANCE"]["load_scene"](args.板索引.parent,item)
        day = fixed_day(engine,previous,policies,arrays,i,scene,index)
        if args.既使用照合 and digest([day[k] for k in CODES])!=frozen["既使用照合"][name]:
            raise ValueError(f"{name}の全建玉指紋が固定した45日版に一致しません。")
        for k,r in day.items():
            books[k].extend(r)
    sources = [args.純入口,args.板索引,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz"]
    if args.圧縮内:
        sources.append(args.母集団/"取得対応.json.gz")
    # ----------------------------------------
    data = {"区分":"既使用照合" if args.既使用照合 else "追加日","対象場":days,"純入口の圧縮内":args.圧縮内,
            "固定条件SHA256":sha256((HERE/"固定条件.json").read_bytes()).hexdigest(),
            "入力SHA256":{str(p.resolve()):sha256(p.read_bytes()).hexdigest() for p in sources},
            "場別入力":{n:{k:prices[n][k] for k in ("contract","rows","raw","index")} for n in days},"口座再生":books}
    fields = ("場","利益","損失","収支","確定収支","既知累計","確定累計","取得","未知","対象秒","保有秒","保有率")
    headers = ("対象デイ","既知利益円","既知損失円","既知収支円","確定収支円","既知累計円",
               "確定累計円","建玉回数","決済未知件数","対象秒","実保有秒","保有時間率")
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=args.出力.parent) as staging:
        out = Path(staging)/"日次"
        out.mkdir()
        for k,ledger in books.items():
            daily,_ = engine["BASE"]["measures"](days,ledger,int(k[-2:]))
            with (out/(k+"_デイ.csv")).open("w",encoding="utf-8-sig",newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(headers)
                writer.writerows([r[col] for col in fields] for r in daily)
        (out/"再生元帳.json").write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding="utf8")
        out.rename(args.出力)


if __name__=="__main__":
    main()
