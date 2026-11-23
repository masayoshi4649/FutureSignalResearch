"""固定96正式gzip許可集合から一場だけのScalar/ATR/通知構築入力を作る。"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
COMPLETION=ROOT/"study/00096_5分枠の順行反転と現在数量/完了記録.json"
COMPLETION_SHA="33deeae84c68de0ecce21023e95732db22a658c9a832cb456d446e221276d483"
OLD_PATH=Path(__file__).with_name("先頭2場の入力を作る.py")
OLD_SHA="fd3df28f62e3a09958bdf81557c9bf04ecabc9aa6bb29c377790387eadd166de"
if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest()!=OLD_SHA:raise ValueError("停止2場loaderの由来SHA差")
SPEC=importlib.util.spec_from_file_location("停止済み2場のRaw部品",OLD_PATH)
OLD=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(OLD)
ROOT,FIXED,FIXED_SHA,MANIFEST,MANIFEST_SHA,RAW=OLD.ROOT,OLD.FIXED,OLD.FIXED_SHA,OLD.MANIFEST,OLD.MANIFEST_SHA,OLD.RAW
need,sha=OLD.need,OLD.sha


def load(path: Path) -> dict:
    """
    機能: JSON又は圧縮Nativeを一つ読み非有限を拒否する。
    引数: path(Path)は固定完了記録又は許可されたNative。
    返り値: dictは保存値。Source/Featuresを運転しない。
    """
    if path.suffix==".gz":
        with gzip.open(path,"rt",encoding="utf-8-sig") as stream:
            return json.load(stream,parse_constant=lambda x:(_ for _ in ()).throw(ValueError(x)))
    return OLD.load(path)


def selected_catalog(completion: Path) -> dict[str,str]:
    """
    機能: 正式96完了記録を指紋で束縛しNative54場だけを列挙する。
    引数: completion(Path)は完了記録。
    返り値: dict[str,str]は場IDからgzipSHA256への許可集合。
    """
    need(sha(completion)==COMPLETION_SHA,"固定96完了SHA差")
    record=load(completion);need(record["比較保存完了"] is True and record["場数"]==54,"96完了54場")
    result={}
    for path,value in record["自己を除く正式指紋"].items():
        matched=re.fullmatch(r"成果物/(\d{4}-\d{2}-\d{2}_(?:Day|Night))\.json\.gz",path.replace("\\","/"))
        if matched:
            need(matched[1] not in result and len(value)==64,"Native許可重複/指紋長")
            result[matched[1]]=value
    need(len(result)==54,"固定54場許可集合")
    return result


def build(session: str,native_dir: Path,out: Path) -> dict:
    """
    機能: 許可済み一場だけを旧計算本文へ渡しScalar/ATR/配送時計を作る。
    引数: session(str)、native_dir/out(Path)は場ID/正式96成果物/新規構築入力。
    返り値: dictは構築範囲と前後指紋。新しいH損益を計算しない。
    """
    completion_path=COMPLETION
    catalog=selected_catalog(completion_path)
    need(session in catalog,"固定54許可集合に無い場")
    need(native_dir.resolve()==(COMPLETION.parent/"成果物").resolve(),"固定96正式Native配置")
    need(sha(MANIFEST)==MANIFEST_SHA,"固定80台帳SHA")
    manifest=load(MANIFEST);entry=next(s for s in manifest["sessions"] if s["id"]==session)
    native_path=(native_dir/(session+".json.gz")).resolve()
    need(sha(native_path)==catalog[session],"元96圧縮Native SHA")
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
            "Source判断/Features運転":0,"scope":"固定96完了54許可集合内の一場。既存ChartGridsを再用しSource/Features/助走を再運転しない。Receivedは価格時計複写で実受信時計でない。"}


def main() -> None:
    """
    機能: 明示--run時だけ一場の構築入力を新規保存する。
    引数: CLI --session/--native/--out/--proofは対象と保存先。
    返り値: None。未指定又は上書き/対象外は停止。
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true",required=True)
    parser.add_argument("--session",required=True);parser.add_argument("--native",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True);parser.add_argument("--proof",type=Path,required=True)
    args=parser.parse_args();need(not args.out.exists() and not args.proof.exists(),"新規保存先だけ")
    result=build(args.session,args.native,args.out)
    args.proof.parent.mkdir(parents=True,exist_ok=True)
    args.proof.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("成功","session","Scalar行","grid","Force","取消Origin")},ensure_ascii=False))


if __name__=="__main__":main()
