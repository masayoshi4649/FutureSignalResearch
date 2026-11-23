"""固定先頭2場だけのRaw Scalar/ATR5/時計を作り、Source判断を運転しない。"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]
FIXED=ROOT/"scripts/FAR個別利益追尾の監査/原板と保護の照合.py"
FIXED_SHA="1437804124be71ba5254b57b583c8cc4db247f3bbb8749f89a6ac07c55caf5a6"
MANIFEST=ROOT/"study/00080_FAR後期三手法の15分移植と利益保護/入力台帳.json"
MANIFEST_SHA="b939bc91b33fd86e933534c3b991d844b8a0200a5f14710e1bd5004edc1aab42"
ALLOWED=("2026-09-21_Day","2026-09-21_Night")


def need(value: bool,message: str) -> None:
    """
    機能: 欠落を推測で補わず停止する。
    引数: value(bool)、message(str)は判定と理由。
    返り値: None。不成立はValueError。
    """
    if not value:raise ValueError(message)


def sha(path: Path) -> str:
    """
    機能: 許可された明示ファイルの指紋を計算する。
    引数: path(Path)は読取対象。
    返り値: strはSHA256。Source/Featuresを運転しない。
    """
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def load(path: Path) -> dict:
    """
    機能: 非有限を拒否して入力JSONを読む。
    引数: path(Path)は許可された明示保存。
    返り値: dictは保存値。金額の新しい集計は行わない。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"),parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))


need(sha(FIXED)==FIXED_SHA,"固定94Rawの由来SHA差")
SPEC=importlib.util.spec_from_file_location("97が再用する固定RawとATR5",FIXED)
RAW=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(RAW)


def build(session: str,native_dir: Path,out: Path) -> dict:
    """
    機能: Raw全正常/異常BBOを保ち、Source取消Originを元G0と予定時計へ結ぶ。
    引数: session(str)、native_dir/out(Path)は許可先頭2場と新規保存先。
    返り値: dictは構築範囲/指紋。HやSource戦略は再生しない。
    """
    need(session in ALLOWED,"許可した先頭2場だけ")
    need(sha(MANIFEST)==MANIFEST_SHA,"固定80台帳SHA")
    manifest=load(MANIFEST);entry=next(s for s in manifest["sessions"] if s["id"]==session)
    native_path=(native_dir/(session+".json")).resolve();completion_path=native_dir/"完了.json"
    completion=load(completion_path)
    need(completion["場数"]==2 and set(completion["結果SHA256"])=={s+".json" for s in ALLOWED},"元96の接続2場完了")
    need(sha(native_path)==completion["結果SHA256"][session+".json"],"元96Native SHA")
    value=load(native_path);g0=value["books"]["B5Q_P0_C0_D0"];clock=g0["session"]
    need(value["session"]==session and value["shadow_match"]["all"] is True and value["baseline95_match"]["all"] is True,"元96の明示対照")
    raw_path=Path(manifest["source_root"])/entry["files"]["NK225_book"]["path"]
    csv_path=Path(manifest["source_root"])/entry["files"]["NK225_candle_300"]["path"]
    before={str(p.resolve()):sha(p) for p in (MANIFEST,FIXED,Path(__file__),native_path,completion_path,raw_path,csv_path)}
    for tag,path in (("NK225_book",raw_path),("NK225_candle_300",csv_path)):
        need(before[str(path.resolve())]==entry["files"][tag]["sha256"] and path.stat().st_size==entry["files"][tag]["size"],"原入力の固定:"+tag)
    cfg=value["feature_config"]
    need(cfg["atr_period"]==12 and cfg["atr_min_bars"]==3 and cfg["candle_delay_seconds"]==60,"ATR5の固定条件")
    atr=RAW.ATRSeries(RAW.candles_from_csv(csv_path,session),clock["start"])
    grids={c["at"]:c for c in value["chart_grids"]}
    need(len(grids)==len(value["chart_grids"]),"共有grid重複")
    forces=[clock["force_close"]]+([clock["us_open"]-900] if clock["kind"]=="Night" else [])
    pending=sorted([(t,"force") for t in forces]+[(t,"grid") for t in grids],key=lambda x:(x[0],0 if x[1]=="force" else 1))
    events=[];pointer=0;last=None;force_quotes={};quote_by_line={};quality={}
    needed={r["quote"]["source_line"] for ledger in value["shadows"].values() for category in ("signals","fills","cancellations") for r in ledger[category]}

    def methods(at):
        """
        機能: 固定96の生成済み手法順だけを復元する。
        引数: at(float)は配送時計。
        返り値: list[str]はP Force後も空Pを残した元順序。
        """
        return ["D164_15"] if clock["kind"]=="Day" else ["P164_06"]+(["U165_03"] if at>=clock["us_open"]+900 and "U165_03" in value["shadows"] else [])

    def append_clock(at,kind):
        """
        機能: Force→gridをrawより先に記録する。
        引数: at(number)、kind(str)は確定した元時計。
        返り値: None。古いquoteを再時刻化しない。
        """
        e={"ordinal":len(events)+1,"kind":kind,"at":at}
        if kind=="force":e["methods"]=methods(at);force_quotes[at]=last
        else:e["context"]=grids[at]
        events.append(e)

    for q in RAW.walk_raw(raw_path,session,quality):
        while pointer<len(pending) and pending[pointer][0]<=q["time"]:
            append_clock(*pending[pointer]);pointer+=1
        width=atr.asof(q["time"])
        scalar={**q,"received":q["time"],"atr":width["value"],"atr_available":width["available"],"atr_nominal":width["nominal"]}
        events.append({"ordinal":len(events)+1,"kind":"quote","at":q["time"],"quote":scalar,"methods":methods(q["time"])})
        last=q
        if q["source_line"] in needed:quote_by_line[q["source_line"]]=q
    for at,kind in pending[pointer:]:
        append_clock(at,kind)
    need(quality==value["quality"]["NK225"],"固定loaderの品質/採用規則")
    need(quality["contracts"]==[entry["contract"]] and value["contract"]==entry["contract"],"限月")
    traces=g0["source_events"];routes=[]
    for method,ledger in value["shadows"].items():
        for c in ledger["cancellations"]:
            rows=[e for e in traces if e["kind"]=="cancel" and e["method"]=="NK225_"+method and e["signal_id"]==c["signal_id"] and e["at"]==c["at"] and e["quote"]==c["quote"] and e["reason"]==c["reason"] and e["phase"]=="before_fill"]
            need(len(rows)==1,"取消のG0明示出典が一意でない")
            candidates=[]
            q=quote_by_line.get(c["quote"]["source_line"])
            if c["at"]==c["quote"]["time"] and q==c["quote"]:candidates.append(("quote",q["source_line"]))
            if c["at"] in force_quotes and force_quotes[c["at"]]==c["quote"]:candidates.append(("timer",c["quote"]["source_line"]))
            need(len(candidates)==1,"元配送Originが欠落/曖昧。推測しない")
            origin,line=candidates[0]
            routes.append({"method":method,"signal_id":c["signal_id"],"origin":origin,"at":c["at"],"source_line":line})
    need(all(sha(Path(p))==v for p,v in before.items()),"構築入力の前後指紋")
    payload={"version":1,"native_path":str(native_path),"native_sha256":before[str(native_path)],"session":clock,"cancel_routes":routes,"events":events,"input_sha256":before}
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("xb") as stream:
        with gzip.GzipFile(filename="",mode="wb",fileobj=stream,mtime=0) as zipped:zipped.write(json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode())
    return {"成功":True,"session":session,"Scalar行":sum(e["kind"]=="quote" for e in events),"grid":len(grids),"Force":len(forces),"取消Origin":len(routes),"構築元SHA256":before,"入力前後不変":True,"構築入力SHA256":sha(out),"構築入力bytes":out.stat().st_size,
            "Source判断/Features運転":0,"scope":"固定先頭2場内の一場。既存96 ChartGridsの再利用。両市場clock/助走の新規再計算ではない。Receivedは固定loaderの価格時刻複写で実受信時計ではない。"}


def main() -> None:
    """
    機能: 許可済先頭2場だけの構築入力と証拠を新規保存する。
    引数: --session/--native/--out/--proofは場ID/96保存dir/構築入力/証拠。
    返り値: None。不整合や上書きは停止する。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session",choices=ALLOWED,required=True);parser.add_argument("--native",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True);parser.add_argument("--proof",type=Path,required=True)
    args=parser.parse_args();need(not args.out.exists() and not args.proof.exists(),"新規保存先だけ")
    result=build(args.session,args.native,args.out);args.proof.parent.mkdir(parents=True,exist_ok=True)
    args.proof.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("成功","session","Scalar行","grid","Force","取消Origin","構築入力bytes")},ensure_ascii=False))


if __name__=="__main__":main()
