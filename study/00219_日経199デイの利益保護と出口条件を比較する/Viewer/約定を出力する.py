"""出口で損益の差が生じた二営業日を、元IFD・W31・W36で比較する。"""
import argparse
from hashlib import file_digest
from csv import DictReader
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCENES = ("2026-10-07_Day", "2026-11-17_Day")
NAMES = {"IFD": "元IFD", "W31": "W31 午後の低効率時だけ損幅を拡大", "W36": "W36 元の損幅で追尾"}


def main() -> None:
    """
    機能：2日×3口座の約定を閲覧形式へ変換し、指定時は配布版の全約定・費用・残高を検算する。
    引数：CLIの --api（str、省略可）は稼働中のローカルSessionTradeViewerのURL。
    返り値：None。原板参照の一覧・6約定ファイル・API検算時には照合記録を生成する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--api")
    args = parser.parse_args()
    previous = next((ROOT/"study").glob("00217_*/Viewer/約定を出力する.py"))
    loader = runpy.run_path(str(previous))["load"]
    converter, audit = loader("00215"), loader("00216")
    books = json.loads((ROOT/"work/219逆行/比較元帳.json").read_bytes())["口座再生"]
    catalog_path = HERE/"一覧.resources.json"
    catalog = {"schema_version":1, "path_base":"catalog", "base_dir":str(HERE), "resources":[]}
    prepared, amounts = {}, {}
    for scene in SCENES:
        folder = ROOT.parent/"JP_OSE_Data/future/NK225"/scene
        raw = next(p for p in (folder/"book.jsonl.gz", folder/"book.jsonl") if p.is_file())
        converter.SCENE = scene
        for code, name in NAMES.items():
            trades = [t for t in books[code] if t["scene"] == scene]
            assert trades and all(t["net"] is not None for t in trades)
            pieces = converter.fills(trades, code, 100, 538.5, 0, 1)
            key = scene[:10]+"_"+code
            path = HERE/(key+".trades.jsonl")
            path.write_text("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in pieces), encoding="utf8")
            catalog["resources"].append({"id":key, "title":scene[5:10]+" デイ "+name, "symbol":"NK225",
                "session":scene, "method_id":code, "product":"NK225mini", "point_value":100, "pnl_format":"trades",
                "pnl_basis":"net", "market_path":str(raw), "pnl_path":path.name})
            prepared[key] = pieces, trades
            nets = [t["net"] for t in trades]
            amounts[key] = {"建玉回数":len(nets), "利益円":sum(v for v in nets if v>0),
                            "損失円":-sum(v for v in nets if v<0), "純益円":sum(nets)}
            prefix = "219_元の単純IFD" if code=="IFD" else "219_"+code+"*"
            daily = next((ROOT/"outputs").glob("00219_*/"+prefix+"/デイ.csv"))
            with daily.open(encoding="utf-8-sig", newline="") as stream:
                row, = (row for row in DictReader(stream) if row["セッション"]==scene)
            assert int(row["未知件数"])==0
            for key1,key2 in (("建玉回数","建玉回数"), ("利益円","既知利益円"), ("損失円","既知損失円"), ("純益円","確定収支円")):
                assert amounts[key][key1] == float(row[key2])
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    # ----------------------------------------
    if args.api:
        for key, (pieces, trades) in prepared.items():
            amounts[key]["配布版"] = audit.verify(args.api, catalog_path, key, pieces, trades)
        exe = ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
        with exe.open("rb") as stream:
            digest = file_digest(stream, "sha256").hexdigest()
        result = {"配布版SHA256":digest, "表示":amounts}
        (HERE/"Viewer照合.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf8")


if __name__=="__main__":
    main()
