"""元の利確を保てなかった日と損切を利益へ変えた日を、当日の全建玉で表示する。"""
from argparse import ArgumentParser
from csv import DictReader
from hashlib import file_digest
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCENES = ("2026-09-28_Day", "2026-10-14_Day")
CASES = {"I20": ("222境界照合", "00222_*/222_I20_*", "単純IFD"),
         "RC20": ("224反対追試", "00224_*/224_RC20_*", "反対主信号2回で保護")}


def main() -> None:
    """
    機能：日次と全建玉の公式CSVを照合し、全約定片と一覧を作成する。
    引数：CLIの --api（str・任意）は配布版Viewerの接続先。
    返り値：なし。API指定時は配布版の費用後収支・残数量・約定時刻も確認して保存する。
    """
    parser = ArgumentParser()
    parser.add_argument("--api")
    args = parser.parse_args()
    shared = runpy.run_path(str(next((ROOT/"study").glob("00217_*/Viewer/約定を出力する.py"))))
    to_fills, audit = shared["load"]("00215"), shared["load"]("00216")
    csv_module = runpy.run_path(str(next((ROOT/"study").glob("00222_*/候補別CSVを用意する.py"))))
    catalog = {"schema_version": 1, "path_base": "catalog", "base_dir": str(HERE), "resources": []}
    catalog_path = HERE/"一覧.resources.json"
    prepared, results = {}, {}
    for code, (source, pattern, name) in CASES.items():
        public = next((ROOT/"outputs").glob(pattern))
        book = json.loads((ROOT/"work"/source/"口座元帳.json").read_bytes())["口座再生"][code]
        with (public/"建玉明細.csv").open(encoding="utf-8-sig", newline="") as file:
            all_rows = list(DictReader(file))
        for scene in SCENES:
            trades = [t for t in book if t["scene"] == scene]
            published = [r for r in all_rows if r["セッション"] == scene]
            for trade, row in zip(trades, published, strict=True):
                desired = csv_module["trade_row"](row["候補"], trade)
                assert all(float(cell) == val if isinstance(val, (float, int)) else cell == (val or "")
                           for cell, val in zip(row.values(), desired, strict=True))
            gain, loss, net = shared["check_daily"](trades, public.name, scene)
            to_fills.SCENE = scene
            pieces = to_fills.fills(trades, code, 100, 538.5, 0, 1)
            key = scene[:10]+"_"+code
            path = HERE/(key+".trades.jsonl")
            path.write_text("".join(json.dumps(p, ensure_ascii=False)+"\n" for p in pieces), encoding="utf8")
            market = ROOT.parent/"JP_OSE_Data/future/NK225"/scene
            raw = next(p for p in (market/"book.jsonl.gz", market/"book.jsonl") if p.is_file())
            catalog["resources"].append({"id": key, "title": scene[5:10]+" デイ "+name,
                "method_id": code, "symbol": "NK225", "product": "NK225mini", "session": scene,
                "point_value": 100, "pnl_format": "trades", "pnl_basis": "net",
                "market_path": str(raw), "pnl_path": path.name})
            prepared[key] = pieces, trades
            results[key] = {"公開CSVと照合した建玉件数": len(trades), "利益円": gain, "損失円": loss, "収支円": net}
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    # ----------------------------------------
    if args.api:
        for key, (pieces, trades) in prepared.items():
            results[key]["配布版"] = audit.verify(args.api, catalog_path, key, pieces, trades)
        exe = ROOT.parent/"SessionTradeViewer/dist/windows-amd64/SessionTradeViewer/session-trade-viewer.exe"
        with exe.open("rb") as stream:
            proof = {"配布版SHA256": file_digest(stream, "sha256").hexdigest(), "照合": results}
        (HERE/"Viewer照合.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2)+"\n", encoding="utf8")


if __name__ == "__main__":
    main()
