"""元IFD・固定利確と追尾・上限なし追尾を同じ二つのデイで表示する。"""
import argparse
from hashlib import file_digest
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
NAMES = {"IFD":"元の単純IFD", "B400P3":"固定利確と期限前の可変追尾", "B400P4":"上限なし・期限前の可変追尾"}


def main() -> None:
    """
    機能：原板を参照する6つの表示と約定片を作り、指定時に配布版の数値APIと公開CSVを照合する。
    引数：CLIの --api（str）はローカルViewerのURL、--csv（フラグ）は公開済みCSVを併せて検算する。
    返り値：None。試行フォルダに閲覧資源、照合した場合は照合記録を保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--api")
    parser.add_argument("--csv",action="store_true")
    args = parser.parse_args()
    shared = runpy.run_path(str(next((ROOT/"study").glob("00217_*/Viewer/約定を出力する.py"))))
    converter,audit = shared["load"]("00215"),shared["load"]("00216")
    books = json.loads((ROOT/"work/220ポイント/比較元帳.json").read_bytes())["口座再生"]
    catalog = {"schema_version":1,"path_base":"catalog","base_dir":str(HERE),"resources":[]}
    catalog_path = HERE/"一覧.resources.json"
    pending, amounts = {},{}
    for scene in ("2026-10-05_Day","2026-11-20_Day"):
        data_dir = ROOT.parent/"JP_OSE_Data/future/NK225"/scene
        market = next(path for path in [data_dir/"book.jsonl.gz",data_dir/"book.jsonl"] if path.is_file())
        converter.SCENE = scene
        for code,title in NAMES.items():
            rows = [r for r in books[code] if r["scene"]==scene]
            assert rows and all(r["net"] is not None for r in rows)
            key = scene[:10]+"_"+code
            path = HERE/(key+".trades.jsonl")
            pieces = converter.fills(rows,code,100,538.5,0,1)
            path.write_text("".join(json.dumps(p,ensure_ascii=False)+"\n" for p in pieces),encoding="utf8")
            catalog["resources"].append({"id":key,"title":scene[5:10]+" "+code+" "+title,"symbol":"NK225",
                "session":scene,"method_id":code,"product":"NK225mini","point_value":100,"pnl_format":"trades",
                "pnl_basis":"net","market_path":str(market),"pnl_path":path.name})
            amounts[key] = {"建玉数":len(rows),"利益円":sum(max(t["net"],0) for t in rows),
                            "損失円":sum(max(-t["net"],0) for t in rows),"収支円":sum(t["net"] for t in rows)}
            if args.csv:
                names = json.loads((HERE.parent/"閲覧候補.json").read_bytes())
                shared["check_daily"](rows,"220_"+names[code],scene)
                amounts[key]["候補別日次CSV一致"] = True
            pending[key] = pieces,rows
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    # ----------------------------------------
    if args.api:
        for key,(pieces,rows) in pending.items():
            amounts[key]["配布版"] = audit.verify(args.api,catalog_path,key,pieces,rows)
        exe = ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
        with exe.open("rb") as stream:
            proof = {"配布版SHA256":file_digest(stream,"sha256").hexdigest(),"照合":amounts}
        (HERE/"Viewer照合.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
