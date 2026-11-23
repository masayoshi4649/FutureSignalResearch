"""追加デイの199_02の全注文について、試行219の固定出口だけを比較する。"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
RULES = {"逆行時の出口.py": ["W31", "W36"], "期限前保護の切り分け.py": ["M34", "M28"],
         "成熟時の出口.py": ["M04"]}


def main() -> None:
    """
    機能：指定した追加デイに元IFDと固定した出口を適用し、同一取得の診断と1枠口座を記録する。
    引数：CLIの母集団・純入口・板索引・出力（Path）、対象の場（str列）、既使用照合（bool）。
    返り値：None。入力・条件の指紋と場ごとの両元帳を指定JSONへ新規保存する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("母集団","純入口","板索引","出力"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--場", nargs="+", required=True)
    parser.add_argument("--既使用照合", action="store_true", help="11月20日以前を既使用データとして再現する")
    args = parser.parse_args()
    dates = sorted(args.場)
    if len(set(dates))!=len(dates) or any(not d.endswith("_Day") for d in dates):
        parser.error("重複のないデイの場名を指定してください。")
    if not args.既使用照合 and dates[0]<="2026-11-20_Day":
        parser.error("既使用期間を検算する場合は --既使用照合 を指定してください。")
    frozen = json.loads((HERE/"次の追加デイの固定条件.json").read_bytes())
    for filename, expected in frozen["SHA256"].items():
        source_bytes = (HERE/filename).read_bytes().replace(b"\r\n",b"\n")
        if sha256(source_bytes).hexdigest()!=expected:
            parser.error(f"固定時からファイルが変わっています。{filename}")
    engine = runpy.run_path(str(HERE/"口座再生.py"))
    source = engine["SOURCE"]
    scenes, arrays, *_ = source["inputs"](args.母集団,args.純入口,"")
    by_day = {scene["session"]:(i,scene) for i,scene in enumerate(scenes)}
    manifests = {s["session"]:s for s in source["read"](args.板索引)["scenes"]}
    if set(dates) - (by_day.keys() & manifests.keys()):
        parser.error("対象日の母集団・板索引がそろっていません。")
    # ----------------------------------------
    policies = {name:runpy.run_path(str(HERE/name)) for name in RULES}
    inputs = [args.純入口,args.板索引,args.母集団/"固定取得入力.json.gz",args.母集団/"当時特徴.json.gz"]
    strategy = [HERE/name for name in [*RULES,"出口候補.py","口座再生.py"]]
    hashes = {p.name:sha256(p.read_bytes()).hexdigest() for p in [*inputs,*strategy]}
    data = {"区分":"既使用の再現" if args.既使用照合 else "219固定後の追加デイ",
            "指紋":hashes, "対象場":dates, "口座再生":{}, "入口固定":{}}
    for day in dates:
        scene_id,scene = by_day[day]
        index = engine["FINANCE"]["load_scene"](args.板索引.parent,manifests[day])
        stream = engine["orders"](arrays,scene_id,scene,index)
        settle = engine["exits"](index,scene,policies["成熟時の出口.py"])
        base,_ = engine["replay"](stream,scene,"IFD",settle)
        for mode in ("入口固定","口座再生"):
            data[mode].setdefault("IFD",[]).extend(base)
        for filename, codes in RULES.items():
            settle = engine["exits"](index,scene,policies[filename])
            for code in codes:
                book,_ = engine["replay"](stream,scene,code,settle)
                data["口座再生"].setdefault(code,[]).extend(book)
                fixed = data["入口固定"].setdefault(code,[])
                for trade in base:
                    result = settle(code,trade["entry_index"],trade["side"],trade["width"],trade["horizon"])
                    fixed.append(dict(trade,**result))
    args.出力.parent.mkdir(parents=True,exist_ok=True)
    with args.出力.open("x",encoding="utf8") as dst:
        json.dump(data,dst,ensure_ascii=False,allow_nan=False)


if __name__=="__main__":
    main()
