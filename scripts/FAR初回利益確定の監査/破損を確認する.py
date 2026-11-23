"""Go型人工の出典/床/予約/時刻を壊し、独立監査の拒否を確認する。"""

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys


def main() -> None:
    """
    機能: 停止Go人工から少数の反証を作り、元の金融を改変せず拒否証拠を保存する。
    引数: --fixtures/--out(Path)はGo人工根と新規証拠。
    返り値: None。受理された破損があれば非0で停止する。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("新規証拠先")
    code = Path(__file__).with_name("初回利益確定の金融照合.py")
    spec = importlib.util.spec_from_file_location("97H金融人工監査", code)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    normal = module.BASE.load(args.fixtures/"1_通常.json")
    partial = module.BASE.load(args.fixtures/"1_同原行Source部分.json")
    key = "H0_B5Q_P0_C0_D0"
    rejected = []
    kinds = ("H床0へ緩和", "初u0へ改変", "初u証拠未来", "要求phaseをpreへ", "同原行fill出典", "Source優先の注文順を逆転",
             "予約超過のH要求", "H専用reasonを旧reasonへ", "Harvest不一致key", "未定義config追加", "未定義金融trace追加")
    for kind in kinds:
        value = copy.deepcopy(partial if kind == "Source優先の注文順を逆転" else normal)
        book = value["actors"][key]
        position = book["positions"][0]
        order = next(o for o in book["orders"] if o["reason"] == module.HARVEST_REASON)
        if kind == "H床0へ緩和":
            position["floor_gain"] = 0
        elif kind == "初u0へ改変":
            position["activation"]["unit_net"] = 0
            position["marks"]["first_unit_positive"]["unit_net"] = 0
        elif kind == "初u証拠未来":
            position["activation"]["quote"]["index"] += 100
        elif kind == "要求phaseをpreへ":
            order["protection_point"]["phase"] = "pre_fill"
        elif kind == "同原行fill出典":
            fill = next(f for f in book["fills"] if f["order_id"] == order["id"])
            fill["quote"] = copy.deepcopy(order["request_quote"])
            for allocation in fill["allocations"]:
                allocation["exit_quote"] = copy.deepcopy(order["request_quote"])
            position["closed_quote"] = copy.deepcopy(order["request_quote"])
        elif kind == "Source優先の注文順を逆転":
            ix = [i for i, o in enumerate(book["orders"]) if o["kind"] == "exit"]
            assert len(ix) >= 2
            book["orders"][ix[0]], book["orders"][ix[1]] = book["orders"][ix[1]], book["orders"][ix[0]]
        elif kind == "予約超過のH要求":
            order["quantity"] += 1
        elif kind == "H専用reasonを旧reasonへ":
            order["reason"] = "最低建値床と固定2ATR追尾"
        elif kind == "Harvest不一致key":
            book["key"] = book["key"].removeprefix("H0_")
        elif kind == "未定義config追加":
            book["config"]["未知保護設定"] = True
        else:
            book["未知金融trace"] = []
        try:
            module.inspect_fixture(value)
        except (ValueError, AssertionError) as error:
            rejected.append({"種類": kind, "拒否": str(error)})
        else:
            raise AssertionError("破損を受理:"+kind)
    result = {"成功": True, "拒否数": len(rejected), "反証": rejected, "監査コードSHA256": module.digest(code),
              "入力": {p.name:module.digest(p) for p in sorted(args.fixtures.glob("*.json"))},
              "限定": "既存Go型人工の保存値を意図的に壊す反証。u=0は保存起動証拠の改変であり、Source自然生成の境界到達を主張しない。",
              "市場/原板/金融再生": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
    print(json.dumps({"成功": True, "拒否数": len(rejected), "codeSHA256": module.digest(code)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
