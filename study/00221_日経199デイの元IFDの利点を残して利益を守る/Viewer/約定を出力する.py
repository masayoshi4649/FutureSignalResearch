"""同一の取得から期限延長で利確または損切になった隣り合う二日を表示する。"""
import argparse
from hashlib import file_digest
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CASES = (("2026-11-12_Day",53634,"延長で利確"),("2026-11-13_Day",50769,"延長で損切"))
METHODS = {"IFD":"元IFD・60分期限","D04":"元の利確・損切を場末まで維持"}


def main() -> None:
    """
    機能：二つの取得の元IFDと延長の実際の返済を、四つの独立した表示に変換する。
    引数：CLIの --api（str、省略可）は稼働中のローカルViewerのURL。
    返り値：None。閲覧用一覧・建玉別約定片と、指定時には配布版との照合記録を出力する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--api")
    args = parser.parse_args()
    shared = runpy.run_path(str(next((ROOT/"study").glob("00217_*/Viewer/約定を出力する.py"))))
    converter,audit = shared["load"]("00215"),shared["load"]("00216")
    books = json.loads((ROOT/"work/221期限寄与/比較元帳.json").read_bytes())
    catalog = {"schema_version":1,"path_base":"catalog","base_dir":str(HERE),"resources":[]}
    catalog_path = HERE/"一覧.resources.json"
    prepared = {}
    for scene,line,outcome in CASES:
        folder = ROOT.parent/"JP_OSE_Data/future/NK225"/scene
        market = next(p for p in (folder/"book.jsonl.gz",folder/"book.jsonl") if p.is_file())
        converter.SCENE = scene
        for code,label in METHODS.items():
            records = []
            for ledger in books.values():
                row, = (t for t in ledger[code] if (t["scene"],t["entry_line"])==(scene,line))
                records.append(row)
            assert records[0]==records[1]
            row = records[0]
            key = scene[:10]+"_"+code
            path = HERE/(key+".trades.jsonl")
            parts = converter.fills([row],code,100,538.5,0,1)
            path.write_text("".join(json.dumps(p,ensure_ascii=False)+"\n" for p in parts),encoding="utf8")
            catalog["resources"].append({"id":key,"title":scene[5:10]+" "+outcome+"　"+label,"symbol":"NK225",
                "session":scene,"method_id":code,"product":"NK225mini","point_value":100,"pnl_format":"trades",
                "pnl_basis":"net","market_path":str(market),"pnl_path":path.name})
            prepared[key] = parts,[row]
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    # ----------------------------------------
    if args.api:
        checked = {key:audit.verify(args.api,catalog_path,key,*args_) for key,args_ in prepared.items()}
        exe = ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
        with exe.open("rb") as stream:
            proof = {"配布版SHA256":file_digest(stream,"sha256").hexdigest(),"照合":checked}
        (HERE/"Viewer照合.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf8")


if __name__=="__main__":
    main()
