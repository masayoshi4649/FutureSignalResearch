"""新しい日経デイの純入口と原板に、固定したRC・W12を開始20分／30分待機で適用する。"""
from argparse import ArgumentParser
import csv
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import runpy
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent
LAST = next(TRIAL.parent.glob("00224_*"))
CODES = ("RC20","RC30","W12C20","W12C30")
ENTRY = ("scene","request_time","request_line","side","entry_index","entry_time","entry_line","entry_price","width")


def checked_day(engine: dict, families: dict, arrays: dict, position: int, scene: dict, index: object) -> dict:
    """
    機能：両候補を同じ日の全要求から再生し、各開始条件の予約・新規・実側の一致を確認する。
    引数：engine・families・arrays・scene（dict）は224の再生関数・追加候補・純入口配列・場情報、
    position（int）は母集団内の場番号、index（PriceIndex）は場内の原板。
    返り値：dict。建玉のない候補も含む4口座の当日元帳。未確定の損益は元の未知値を保つ。
    """
    books,_ = engine["day"](arrays,position,scene,index,families,("C",))
    for wait in ("20","30"):
        for base,test in zip(books["RC"+wait],books["W12C"+wait],strict=True):
            assert all(base[k]==test[k] for k in ENTRY)
            if base["exit_index"]>=0:
                assert 0<=test["exit_index"]<=base["exit_index"]
            if not test["extra_fill"]:
                assert all(base[k]==test[k] for k in ("exit_index","status","net","confirmed_until"))
    return books


def main() -> None:
    """
    機能：指定日を固定候補だけで比較し、指紋を検査した元帳から4候補の日次CSVを別々に出す。
    引数：CLIの母集団・純入口・板索引・出力（Path）、場（list[str]）、圧縮内（str）、既使用照合（bool）。
    返り値：None。出力が揃ったら指定した新しいフォルダに一括で保存する。
    """
    parser = ArgumentParser(description=__doc__)
    for name in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--場",required=True,nargs="+")
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
        parser.error("重複しないYYYY-MM-DD_Dayと、新しい出力フォルダを指定してください。")
    if args.既使用照合 and set(days)-frozen["既使用照合"].keys():
        parser.error("指定日の既使用照合指紋がありません。")
    if not args.既使用照合 and days[0]<=frozen["既使用最終場"]:
        parser.error("追加検証は既使用最終日より後の日を指定してください。")
    for folder,config in ((HERE,frozen),(LAST,json.loads((LAST/"追加日の固定条件.json").read_bytes()))):
        for name,value in config["ソースSHA256"].items():
            if sha256((folder/name).read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=value:
                parser.error("固定時から研究コードが変わっています。"+name)
    # ----------------------------------------
    engine = runpy.run_path(str(LAST/"再エントリーを再生する.py"))
    rules = runpy.run_path(str(TRIAL/"弱い反転/確定足の転換.py"))
    families = {"R":("R02",rules["FIRST"]["COMMON"]["RC"],""),"W12":("W12",rules,"")}
    source = engine["SOURCE"]
    scenes,arrays,*_ = source["inputs"](args.母集団,args.純入口,args.圧縮内)
    positions = {s["session"]:(i,s) for i,s in enumerate(scenes)}
    prices = {s["session"]:s for s in source["read"](args.板索引)["scenes"]}
    if set(days)-(positions.keys() & prices.keys()):
        parser.error("指定した日の母集団・純入口・板索引が必要です。")
    digest = runpy.run_path(str(next(TRIAL.parent.glob("00222_*/追加デイへ適用する.py"))))["digest"]
    books = {code:[] for code in CODES}
    for day in days:
        position,scene = positions[day]
        index = engine["ENGINE"]["FINANCE"]["load_scene"](args.板索引.parent,prices[day])
        accounts = checked_day(engine,families,arrays,position,scene,index)
        if args.既使用照合 and digest([accounts[code] for code in CODES])!=frozen["既使用照合"][day]:
            raise ValueError(f"{day}の4候補の全項目が45日版に一致しません。")
        for code,rows in accounts.items():
            books[code].extend(rows)
    # ----------------------------------------
    sources = [args.純入口,args.板索引,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz"]
    if args.圧縮内:
        sources.append(args.母集団/"取得対応.json.gz")
    archive = {"区分":"既使用照合" if args.既使用照合 else "追加日","対象場":days,"純入口の圧縮内":args.圧縮内,
               "入力SHA256":{str(p):sha256(p.read_bytes()).hexdigest() for p in sources},"口座再生":books}
    keys = ("場","利益","損失","収支","確定収支","既知累計","確定累計","取得","未知","対象秒","保有秒","保有率")
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(dir=args.出力.parent) as temp:
        dest = Path(temp)/"日次"
        dest.mkdir()
        for code,rows in books.items():
            daily,_ = engine["BASE"]["measures"](days,rows,int(code[-2:]))
            with (dest/(code+"_デイ.csv")).open("w",encoding="utf-8-sig",newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("対象デイ","既知利益円","既知損失円","既知収支円","確定収支円","既知累計円",
                                 "確定累計円","建玉回数","決済未知件数","対象秒","実保有秒","保有時間率"))
                writer.writerows([d[k] for k in keys] for d in daily)
        (dest/"再生元帳.json").write_text(json.dumps(archive,ensure_ascii=False,allow_nan=False),encoding="utf8")
        dest.rename(args.出力)


if __name__=="__main__":
    main()
