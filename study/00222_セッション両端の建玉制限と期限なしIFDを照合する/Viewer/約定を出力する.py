"""開始20分と30分で口座の取引が入れ替わった2日を、日経ラージの板と一緒に表示する。"""
from argparse import ArgumentParser
from hashlib import file_digest
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCENES = ("2026-11-16_Day","2026-11-17_Day")
WAITS = {"I20":20,"I30":30}


def main() -> None:
    """
    機能：4口座日の全建玉をViewer用約定へ変換し、候補別の公開日計と配布版の数値表示を照合する。
    引数：CLIの --api（str、省略可）はローカルViewerのURL。
    返り値：None。一覧・約定片を、APIを指定した場合は配布版と日次CSVの照合記録も保存する。
    """
    parser = ArgumentParser()
    parser.add_argument("--api")
    args = parser.parse_args()
    shared = runpy.run_path(str(next((ROOT/"study").glob("00217_*/Viewer/約定を出力する.py"))))
    converter,audit = shared["load"]("00215"),shared["load"]("00216")
    accounts = json.loads((ROOT/"work/222境界照合/口座元帳.json").read_bytes())["口座再生"]
    catalog = {"schema_version":1,"path_base":"catalog","base_dir":str(HERE),"resources":[]}
    catalog_path = HERE/"一覧.resources.json"
    ready,results = {},{}
    for scene in SCENES:
        converter.SCENE = scene
        folder = ROOT.parent/"JP_OSE_Data/future/NK225"/scene
        market = next(p for p in (folder/"book.jsonl.gz",folder/"book.jsonl") if p.is_file())
        for code,wait in WAITS.items():
            trades = [t for t in accounts[code] if t["scene"]==scene]
            directory = next((ROOT/"outputs").glob("00222_*/222_"+code+"_*/デイ.csv")).parent.name
            profit,loss,net = shared["check_daily"](trades,directory,scene)
            pieces = converter.fills(trades,code,100,538.5,0,1)
            key = scene[:10]+"_"+code
            path = HERE/(key+".trades.jsonl")
            path.write_text("".join(json.dumps(p,ensure_ascii=False)+"\n" for p in pieces),encoding="utf8")
            catalog["resources"].append({"id":key,"title":scene[5:10]+" デイ・開始"+str(wait)+"分待機",
                        "method_id":code,"symbol":"NK225","product":"NK225mini","session":scene,
                        "point_value":100,"pnl_format":"trades","pnl_basis":"net","market_path":str(market),"pnl_path":path.name})
            ready[key] = pieces,trades
            results[key] = {"建玉件数":len(trades),"公開日計と照合した利益円":profit,"公開日計と照合した損失円":loss,
                            "公開日計と照合した収支円":net}
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    # ----------------------------------------
    if args.api:
        for key,(pieces,trades) in ready.items():
            results[key]["配布版"] = audit.verify(args.api,catalog_path,key,pieces,trades)
        exe = ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
        with exe.open("rb") as src:
            proof = {"配布版SHA256":file_digest(src,"sha256").hexdigest(),"照合":results}
        (HERE/"Viewer照合.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
