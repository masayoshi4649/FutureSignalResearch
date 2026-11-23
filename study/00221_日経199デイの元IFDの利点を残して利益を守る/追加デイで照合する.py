"""固定した日経199_02の出口を、追加デイの純入口・原板索引から再生する。"""
import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
RULES = HERE/"元IFDの寄与"
PREVIOUS = next(HERE.parent.glob("00220_*"))


def main() -> None:
    """
    機能：各デイの同一注文要求を全候補で再生し、予約込み1枚口座と元取得固定の双方を記録する。
    引数：CLIの母集団・純入口・板索引・出力（Path）、場（str列）、既使用照合（bool）。
    返り値：None。追加日の取引・入力指紋を新規JSONへ保存し、既使用照合なら基準元帳と全項目を比較する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--場",nargs="+",required=True)
    parser.add_argument("--既使用照合",action="store_true")
    args = parser.parse_args()
    frozen = json.loads((HERE/"追加デイの固定条件.json").read_bytes())
    days = sorted(args.場)
    if len(days)!=len(set(days)) or any(day!=date.fromisoformat(day[:10]).isoformat()+"_Day" for day in days):
        parser.error("日付は重複しないYYYY-MM-DD_Dayを指定してください。")
    if args.既使用照合 and any(day not in frozen["既使用照合"] for day in days):
        parser.error("既使用照合の対象は11月18〜20日です。")
    if not args.既使用照合 and any(day<=frozen["既使用最終場"] for day in days):
        parser.error("追加日は固定後の新しいデイを指定してください。")
    for file,digest in frozen["ソースSHA256"].items():
        if sha256((HERE/file).read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=digest:
            parser.error(f"固定済みのソースが変化しています。{file}")
    # ----------------------------------------
    policy = runpy.run_path(str(RULES/"期限延長と追尾を組み合わせる.py"))
    engine = policy["ENGINE"]
    source = engine["SOURCE"]
    digest = runpy.run_path(str(PREVIOUS/"追加デイへ適用.py"))["digest"]
    selective = runpy.run_path(str(HERE/"入口別の保護/出口条件.py"))
    scenes,arrays,*_ = source["inputs"](args.母集団,args.純入口,"")
    lookup = {scene["session"]:(i,scene) for i,scene in enumerate(scenes)}
    manifests = {s["session"]:s for s in source["read"](args.板索引)["scenes"]}
    if set(days)-(lookup.keys() & manifests.keys()):
        parser.error("対象日の固定入口と原板索引が必要です。")
    inputs = (args.板索引,args.純入口,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz")
    output = {"区分":"既使用照合" if args.既使用照合 else "追加日固定適用","対象":days,
              "入力SHA256":{str(path):sha256(path.read_bytes()).hexdigest() for path in inputs},
              "口座再生":{},"入口固定":{}}
    for day in days:
        i,scene = lookup[day]
        index = engine["FINANCE"]["load_scene"](args.板索引.parent,manifests[day])
        orders = engine["orders"](arrays,i,scene,index)
        static = engine["exits"](index,scene,policy["STATIC"])
        deadline = policy["ORIGINAL"]["extend"](static)
        time_protection = policy["by_scene"](index,scene,static)
        narrow = engine["exits"](index,scene,selective)
        base,_ = engine["replay"](orders,scene,"IFD",static)
        for code in frozen["候補"]:
            if code=="IFD":
                account,fixed = base,base
            else:
                settle = {"F01":narrow,"D04":deadline}.get(code,time_protection)
                policy_id = code+"_1" if code.startswith("T") else code
                account,_ = engine["replay"](orders,scene,policy_id,settle)
                fixed = [dict(t,**settle(policy_id,t["entry_index"],t["side"],t["width"],t["horizon"])) for t in base]
                if code.startswith("T"):
                    account,fixed = ([dict(t,exit_strategy=code) for t in book] for book in (account,fixed))
            for mode,rows in (("口座再生",account),("入口固定",fixed)):
                if args.既使用照合 and digest(rows)!=frozen["既使用照合"][day][mode][code]:
                    raise ValueError(f"{day}の{code}の{mode}が既存元帳と一致しません。")
                output[mode].setdefault(code,[]).extend(rows)
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    with args.出力.open("x",encoding="utf8") as stream:
        json.dump(output,stream,ensure_ascii=False,allow_nan=False)


if __name__=="__main__":
    main()
