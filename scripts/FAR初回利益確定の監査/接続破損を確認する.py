"""現在文脈・候補・callback・Tape配送を壊した少数の接続反証。"""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys


def main() -> None:
    """
    機能: 固定production人工の接続境界だけを壊し、各拒否を新規保存する。
    引数: --fixture/--out(Path)は一つのGo型人工と新規証拠先。
    返り値: None。受理された破損があれば非0で止める。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("新規出力先")
    code = Path(__file__).with_name("Tapeと金融の照合.py")
    spec = importlib.util.spec_from_file_location("97独立Tape破損", code)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    original = module.BASE.load(args.fixture)
    before = module.digest(args.fixture)
    rejected = []
    kinds = ("共有Current出典を両保存で変更", "現在候補量", "保存採否", "保存個別check", "callback欠落", "callback未知tag",
             "同時刻gridと原行を逆転", "空Source配送手法の欠落", "非空Source物理行", "H0床緩和", "同原行fill", "公開ATR未来")
    for kind in kinds:
        value = copy.deepcopy(original)
        tape, output = value["tape"], value["output"]
        record = output["gate_assessments"][0]
        if kind == "共有Current出典を両保存で変更":
            grid = next(e for e in tape["events"] if e["kind"] == "grid")
            grid["context"]["current"]["source_line"] += 1
            saved = next(x for x in output["chart_grids"] if x["snapshot_id"] == grid["context"]["snapshot_id"])
            saved["current"]["source_line"] += 1
        elif kind == "現在候補量":
            record["candidate"]["quantity"] += 1
        elif kind == "保存採否":
            record["assessment"]["decision"]["allowed"] = not record["assessment"]["decision"]["allowed"]
        elif kind == "保存個別check":
            item = record["assessment"]["checks"][0]
            item["passed"] = not item["passed"]
        elif kind == "callback欠落":
            output["gate_assessments"].pop(0)
        elif kind == "callback未知tag":
            record["未知判断根拠"] = True
        elif kind == "同時刻gridと原行を逆転":
            events = tape["events"]
            index = next(i for i in range(len(events)-1) if events[i]["kind"] == "grid"
                         and events[i+1]["kind"] == "quote" and events[i]["at"] == events[i+1]["at"])
            events[index], events[index+1] = events[index+1], events[index]
            for i, event in enumerate(events, 1):
                event["ordinal"] = i
        elif kind == "空Source配送手法の欠落":
            event = next(e for e in tape["events"] if e["kind"] == "quote" and e.get("methods") and not e.get("non_empty"))
            event["methods"].pop()
        elif kind == "非空Source物理行":
            event = next(e for e in tape["events"] if e.get("non_empty"))
            event["non_empty"][0]["delta"]["source_line"] += 1
        elif kind == "H0床緩和":
            book = next(b for k,b in output["books"].items() if k.startswith("H0_") and b["positions"])
            book["positions"][0]["floor_gain"] = 0
        elif kind == "同原行fill":
            book = next(b for k,b in output["books"].items() if k.startswith("H0_") and any(o["protection_point"] for o in b["orders"]))
            order = next(o for o in book["orders"] if o["protection_point"])
            fill = next(f for f in book["fills"] if f["order_id"] == order["id"])
            fill["quote"] = copy.deepcopy(order["request_quote"])
            for allocation in fill["allocations"]:
                allocation["exit_quote"] = copy.deepcopy(order["request_quote"])
        else:
            quote = next(e["quote"] for e in tape["events"] if e["kind"] == "quote" and e["quote"]["atr"] > 0)
            quote["atr_available"] = quote["time"]+1
        try:
            module.inspect_tape(tape, output)
        except (ValueError, AssertionError) as error:
            rejected.append({"種類":kind, "拒否":str(error)})
        else:
            raise AssertionError("破損を受理:"+kind)
    assert module.digest(args.fixture) == before
    result = {"成功":True, "拒否数":len(rejected), "反証":rejected,
              "監査コードSHA256":module.digest(code), "人工SHA256前後":before,
              "原板/市場/Go再生":0, "限定":"保存型の接続破損。自然Source/チャート/ATR生成の反証ではない。"}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"成功":True, "拒否数":len(rejected), "codeSHA256":module.digest(code)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
