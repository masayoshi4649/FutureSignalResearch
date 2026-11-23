"""83の固定再生結果を読み、同実新規の出口差と参加変更を事後に分解する。"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path


MODES = ("S0G1", "S1G1", "S0G2", "S1G2")
PAIRS = (("G1_S1対S0", "S0G1", "S1G1"), ("G2_S1対S0", "S0G2", "S1G2"),
         ("S0_G2対G1", "S0G1", "S0G2"), ("S1_G2対G1", "S1G1", "S1G2"))
CATEGORIES = ("同値", "A黒字からB赤字", "A赤字からB黒字", "両赤字で損失縮小", "両赤字で損失拡大",
              "両黒字で利益増加", "両黒字で利益減少", "A黒字からB同値", "A同値からB赤字",
              "A赤字からB同値", "A同値からB黒字")


def sha(path: Path) -> str:
    """
    機能: 観測入力と診断コードの指紋を求める。
    引数: path (Path) は実ファイル。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def yen(value: int | float) -> int:
    """
    機能: この試行の整数円会計を丸めず検査する。
    引数: value (int | float) は保存損益円。
    返り値: int は同じ円額。不正値・端数は例外。
    """
    assert isinstance(value, (int, float)) and not isinstance(value, bool)
    number = int(value)
    assert number == value, "円の端数又は非有限値"
    return number


def classify(a: int, b: int) -> str:
    """
    機能: 同実新規一玉の費用後成績の変化を排他的に分類する。
    引数: a/b (int) は対照と比較の費用後損益円。
    返り値: str は黒赤・増減・同値を区別した分類。
    """
    if a == b:
        return "同値"
    if a > 0 and b < 0:
        return "A黒字からB赤字"
    if a < 0 and b > 0:
        return "A赤字からB黒字"
    if a < 0 and b < 0:
        return "両赤字で損失縮小" if b > a else "両赤字で損失拡大"
    if a > 0 and b > 0:
        return "両黒字で利益増加" if b > a else "両黒字で利益減少"
    if a > 0:
        return "A黒字からB同値"
    if b < 0:
        return "A同値からB赤字"
    return "A赤字からB同値" if a < 0 else "A同値からB黒字"


def collect(sessions: list[dict]) -> dict[str, dict[tuple, dict]]:
    """
    機能: 完結玉と新規要求を結び、返済理由と構造状態を小型化する。
    引数: sessions (list[dict]) は保存した場再生結果。
    返り値: dict は会計キー別の要求時計・方向で一意な玉。保存会計不整合は例外。
    """
    output = {f"{m}_D{d}": {} for d in (0, 1) for m in MODES}
    for session in sessions:
        for key, chosen in output.items():
            book = session["books"][key]
            assert not book["unresolved"] and book["metrics"]["open_quantity"] == 0
            total = 0
            for lot in book["lots"]:
                orders = [o for o in book["orders"] if o["position_id"] == lot["id"]]
                entries = [o for o in orders if o["kind"] == "entry"]
                assert len(entries) == 1
                closed = [c for c in book["closed"] if c["position_id"] == lot["id"]]
                assert lot["quantity"] == 0 and sum(c["quantity"] for c in closed) == lot["initial_quantity"]
                pnl = yen(lot["net_pnl"])
                assert pnl == sum(yen(c["pnl5"]) for c in closed)
                base_key = (session["session"], entries[0]["request_time"], lot["side"])
                assert base_key not in chosen, "同一場・要求時計・方向の新規重複"
                reasons = Counter()
                reason_pnl = Counter()
                for c in closed:
                    reasons[c["reason"]] += c["quantity"]
                    reason_pnl[c["reason"]] += yen(c["pnl5"])
                chosen[base_key] = {"場": session["session"], "要求時計": entries[0]["request_time"], "方向": lot["side"],
                    "実新規": (lot["entry_time"], lot["entry_price"], lot["initial_quantity"]), "費用後損益円": pnl,
                    "全玉旗": lot["whole_flag"], "残玉旗": lot["flag"],
                    "構造取得時否定": lot["structure_entry_breached"], "構造到達": lot["structure_first_hit_at"] is not None,
                    "構造返済": any(o["kind"] == "exit" and o["reason"] == "固定EMA構造否定" for o in orders),
                    "返済理由枚数": dict(reasons), "返済理由損益円": dict(reason_pnl)}
                total += pnl
            assert total == yen(book["metrics"]["net_pnl_yen"]), key
    return output


def aggregate(rows: list[dict]) -> dict:
    """
    機能: 玉群の成績と、重なり得る利益・構造属性の寄与を集約する。
    引数: rows (list[dict]) は小型化した完結玉。
    返り値: dict は数・損益と理由別返済片の会計。
    """
    groups = {
        "全玉": rows,
        "全玉旗後の最終赤字": [r for r in rows if r["全玉旗"] and r["費用後損益円"] < 0],
        "全玉旗未観測": [r for r in rows if not r["全玉旗"]],
        "残玉正益未観測": [r for r in rows if not r["残玉旗"]],
        "残玉正益未観測の最終赤字": [r for r in rows if not r["残玉旗"] and r["費用後損益円"] < 0],
        "構造取得時否定": [r for r in rows if r["構造取得時否定"]],
        "構造到達": [r for r in rows if r["構造到達"]],
        "構造返済": [r for r in rows if r["構造返済"]],
    }
    reasons, pnl = Counter(), Counter()
    for row in rows:
        reasons.update(row["返済理由枚数"])
        pnl.update(row["返済理由損益円"])
    return {"属性別": {k: {"玉数": len(v), "損益円": sum(r["費用後損益円"] for r in v)} for k, v in groups.items()},
            "返済理由別枚数": dict(reasons), "返済理由別損益円": dict(pnl)}


def pair(left: dict[tuple, dict], right: dict[tuple, dict]) -> dict:
    """
    機能: 同実新規の出口差と、取得変更・参加有無を完全分解する。
    引数: left/right (dict) は対照Aと比較Bの要求時計別玉。
    返り値: dict は全差とその内訳。分類漏れ・差の不一致は例外。
    """
    common = left.keys() & right.keys()
    exact = {k for k in common if left[k]["実新規"] == right[k]["実新規"]}
    changed, only_a, only_b = common - exact, left.keys() - right.keys(), right.keys() - left.keys()
    categories = {k: {"玉数": 0, "A損益円": 0, "B損益円": 0, "差円": 0, "例": []} for k in CATEGORIES}
    for key in sorted(exact):
        a, b = left[key]["費用後損益円"], right[key]["費用後損益円"]
        row = categories[classify(a, b)]
        row["玉数"] += 1
        row["A損益円"] += a
        row["B損益円"] += b
        row["差円"] += b - a
        if a != b:
            row["例"].append({"場": key[0], "要求時計": key[1], "方向": key[2], "実新規": left[key]["実新規"], "A損益円": a, "B損益円": b, "差円": b-a})
    for row in categories.values():
        row["例"] = sorted(row["例"], key=lambda e: (-abs(e["差円"]), e["場"], e["要求時計"]))[:2]
    amounts = {"同実新規": (exact, exact), "取得変更": (changed, changed), "Aのみ": (only_a, set()), "Bのみ": (set(), only_b)}
    decomposition = {}
    for name, (a_keys, b_keys) in amounts.items():
        a_sum = sum(left[k]["費用後損益円"] for k in a_keys)
        b_sum = sum(right[k]["費用後損益円"] for k in b_keys)
        decomposition[name] = {"A玉数": len(a_keys), "B玉数": len(b_keys), "A損益円": a_sum, "B損益円": b_sum, "差円": b_sum-a_sum}
    total = sum(r["費用後損益円"] for r in right.values()) - sum(r["費用後損益円"] for r in left.values())
    assert total == sum(v["差円"] for v in decomposition.values())
    assert len(exact) == sum(v["玉数"] for v in categories.values())
    assert decomposition["同実新規"]["差円"] == sum(v["差円"] for v in categories.values())
    return {"全損益差円": total, "内訳": decomposition, "同実新規の分類": categories,
            "同実新規A属性": aggregate([left[k] for k in sorted(exact)]),
            "同実新規B属性": aggregate([right[k] for k in sorted(exact)])}


def diagnose(sessions: list[dict]) -> dict:
    """
    機能: 八会計の属性と四比較・二遅延を同じ定義で診断する。
    引数: sessions (list[dict]) は順序固定の場結果。
    返り値: dict は全会計と比較の小型事後診断。
    """
    books = collect(sessions)
    comparisons = {}
    for d in (0, 1):
        for label, a, b in PAIRS:
            ka, kb = f"{a}_D{d}", f"{b}_D{d}"
            comparisons[f"{label}_D{d}"] = {"比較": [ka, kb], **pair(books[ka], books[kb])}
    return {"会計別属性": {k: aggregate(list(v.values())) for k, v in books.items()}, "出口差比較": comparisons}


def verify_summary(value: dict, result: dict) -> None:
    """
    機能: 独立診断の総額と同実新規分解を正式集計へ接続する。
    引数: value/result (dict) は診断と正式結果。
    返り値: None。不一致では例外。
    """
    for key, row in value["会計別属性"].items():
        official = result["比較"][key]
        assert row["属性別"]["全玉"] == {"玉数": official["完結玉"], "損益円": official["費用後損益円"]}
        assert row["属性別"]["全玉旗後の最終赤字"]["玉数"] == official["全玉旗後赤字"]
        assert row["属性別"]["残玉正益未観測"]["損益円"] == official["正益未観測の損益円"]
    for key, row in value["出口差比較"].items():
        old = result["出口間の同実新規分解"][key]
        d = row["内訳"]
        assert d["同実新規"] == {"A玉数": old["同実新規"], "B玉数": old["同実新規"], "A損益円": old["同実新規A損益円"], "B損益円": old["同実新規B損益円"], "差円": old["同実新規出口差円"]}
        assert d["取得変更"]["A玉数"] == d["取得変更"]["B玉数"] == old["共通だが取得変更"]
        for name, prefix in (("取得変更", "取得変更"), ("Aのみ", "Aのみ"), ("Bのみ", "Bのみ")):
            for side in ("A", "B"):
                field = f"{prefix}{side}損益円" if name == "取得変更" else f"{prefix}損益円"
                if name == "取得変更" or name[0] == side:
                    assert d[name][f"{side}損益円"] == old[field]
        a, b = row["比較"]
        assert row["全損益差円"] == result["比較"][b]["費用後損益円"] - result["比較"][a]["費用後損益円"]


def markdown(value: dict) -> str:
    """
    機能: 出口改善と利益取り逃しを比較する日本語資料を作る。
    引数: value (dict) は照合済み診断。
    返り値: str はMarkdown本文。
    """
    lines = ["# 83の出口差と利益の取り逃し", "", "[正式レポート](README.md)／[設定と結果](設定と結果.md)／[数値正本](出口差の診断.json)。確認日：2026-11-07。", "",
        "全66場は既使用で、この診断は固定済みの四出口の事後分解である。新規条件・価格系列・返済処理は変更していない。Aを対照、Bを比較とし、差円はB−A。黒字・赤字は往復手数料と片道5ptの想定滑りを控除した玉全体の損益で分類する。", "",
        "同実新規は場・新規要求時計・売買方向・実新規時計・実新規価格・数量の全一致。要求が同じでも取得時計等が異なれば取得変更とする。候補の15分判断が同じでも、早い返済で後続枠へ再参加でき、実新規は変わり得る。その差を出口だけの効果に含めない。", "",
        "## 全差と参加の分解", "", "| 比較A→B | 同実新規玉 | 同実新規差円 | 取得変更差円 | Aのみ損益円 | Bのみ損益円 | 全差円 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in value["出口差比較"].values():
        d = row["内訳"]
        lines.append(f"| {'→'.join(row['比較'])} | {d['同実新規']['A玉数']} | {d['同実新規']['差円']:,} | {d['取得変更']['差円']:,} | {d['Aのみ']['A損益円']:,} | {d['Bのみ']['B損益円']:,} | {row['全損益差円']:,} |")
    lines += ["", "Aのみの差寄与はA損益の符号反転、BのみはB損益そのもの。四寄与の合計と正式総損益差を照合した。", "", "## 同実新規の変化", "", "| 比較A→B | 分類 | 玉数 | A損益円 | B損益円 | 差円 |", "|---|---|---:|---:|---:|---:|"]
    for row in value["出口差比較"].values():
        for category, group in row["同実新規の分類"].items():
            if group["玉数"]:
                lines.append(f"| {'→'.join(row['比較'])} | {category} | {group['玉数']} | {group['A損益円']:,} | {group['B損益円']:,} | {group['差円']:,} |")
    lines += ["", "A黒字からB赤字は、対照で勝った玉を変更後に失った例。A赤字からB黒字は損失を救った例。両赤字の損失縮小も改善だが黒字化とは区別する。これは保存した二つの出口の比較であり、未来の勝敗を入口時点に判別できたことを意味しない。", "", "## 利益保護と構造状態", "", "| 会計 | 全玉数 | 全玉旗後最終赤字数 | 同損益円 | 残玉正益未観測数 | 同損益円 | 構造取得時否定数 | 構造到達数 | 構造返済数 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, row in value["会計別属性"].items():
        g = row["属性別"]
        lines.append(f"| {key} | {g['全玉']['玉数']} | {g['全玉旗後の最終赤字']['玉数']} | {g['全玉旗後の最終赤字']['損益円']:,} | {g['残玉正益未観測']['玉数']} | {g['残玉正益未観測']['損益円']:,} | {g['構造取得時否定']['玉数']} | {g['構造到達']['玉数']} | {g['構造返済']['玉数']} |")
    lines += ["", "全玉旗は確定済み返済片と残玉評価を合わせた費用後正益を観測した印。残玉旗は現在残玉の費用後正益起動で、両者は別の条件である。未観測は観測できた正常板上の記録であり、板間の価格経路を保証しない。", "",
        "取得時否定は実新規時に固定構造線の否定側へ入った玉、構造到達はその後も含め否定線へ到達した玉、構造返済は理由が固定EMA構造否定の注文を持つ玉。属性は互いに重なり、合計しない。構造到達があっても、先に予約した返済やより厳しい利益床が拘束することがある。構造理由の損益は返済片の帰属であり、それ単独が生んだ因果効果ではない。全属性損益・同実新規属性・返済理由別は数値正本へ収録した。", "",
        "新たな再生・閾値探索・群選別は行っていない。最大差の各分類2例だけをJSONへ残し、原板や全玉の重複転記を避けた。診断は保存結果の集計であり、独立原板監査と基準・入口同値検査を代替しない。", ""]
    return "\n".join(lines)


def self_test(fixtures: Path) -> dict:
    """
    機能: 手計算場面・全分類・参加変更・破損検出で診断算術を検査する。
    引数: fixtures (Path) は固定手計算10場面の根。
    返り値: dict は成功証拠。市場原板・正式結果は使用しない。
    """
    expected = {"大順行": (27800, 27800, 87800, 87800), "小利確": (2800, 2800, -12200, -12200),
                "構造先行": (2800, -32200, -12200, -32200), "取得時否定": (27800, 7800, 87800, 7800),
                "構造未知": (27800, 27800, 87800, 87800)}
    count = 0
    sample = None
    for name, values in expected.items():
        for sign in (-1, 1):
            path = fixtures / f"{name}_{sign}/2026-09-21_Day.json"
            r = json.loads(path.read_text(encoding="utf-8"))
            value = diagnose([r])
            for d in (0, 1):
                for mode, amount in zip(MODES, values):
                    assert value["会計別属性"][f"{mode}_D{d}"]["属性別"]["全玉"] == {"玉数": 1, "損益円": amount}
                for label, a, b in PAIRS:
                    row = value["出口差比較"][f"{label}_D{d}"]
                    aa, bb = values[MODES.index(a)], values[MODES.index(b)]
                    assert row["全損益差円"] == bb-aa
                    assert row["同実新規の分類"][classify(aa,bb)]["玉数"] == 1
            sample = collect([r])["S0G1_D0"]
            count += 1
    observed = {classify(a,b) for a in (-20,-10,0,10,20) for b in (-20,-10,0,10,20)}
    assert observed == set(CATEGORIES)
    left = deepcopy(sample)
    right = deepcopy(sample)
    old_key = next(iter(left))
    left[old_key]["費用後損益円"] = -10
    right[old_key]["費用後損益円"] = 20
    new_key = ("別場", old_key[1], old_key[2])
    right[new_key] = deepcopy(right[old_key])
    right[new_key]["費用後損益円"] = 30
    changed_key = ("取得変更場", old_key[1], old_key[2])
    left[changed_key] = deepcopy(left[old_key])
    right[changed_key] = deepcopy(right[old_key])
    right[changed_key]["実新規"] = (0, 1, 100)
    only_key = ("対照だけ場", old_key[1], old_key[2])
    left[only_key] = deepcopy(left[old_key])
    p = pair(left,right)
    assert p["全損益差円"] == 100 and p["内訳"]["取得変更"]["差円"] == 30
    assert p["同実新規の分類"]["A赤字からB黒字"]["玉数"] == 1
    bad = json.loads((fixtures / "小利確_1/2026-09-21_Day.json").read_text(encoding="utf-8"))
    bad["books"]["S0G1_D0"]["lots"][0]["net_pnl"] += 1
    try:
        diagnose([bad])
    except AssertionError:
        pass
    else:
        raise AssertionError("玉と返済片の1円不整合を検出しませんでした")
    return {"手計算場面": count, "会計": count*8, "全分類": len(observed), "参加取得変更人工": True, "1円破損検出": True, "正式再生読取": 0}


def main() -> None:
    """
    機能: 完成した66場と正式集計を固定し、診断を新規保存する。
    引数: --input/--manifest/--result/--out-json/--out-md (Path) 又は --self-test/--fixtures を明示する。
    返り値: None。既存資料は変更せず、入力の前後指紋を照合する。
    """
    parser = argparse.ArgumentParser()
    for name in ("input", "manifest", "result", "out-json", "out-md", "fixtures"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        assert args.fixtures and args.out_json
        value = {"診断コードSHA256": sha(Path(__file__)), **self_test(args.fixtures)}
    else:
        assert all((args.input, args.manifest, args.result, args.out_json, args.out_md))
        assert not args.out_json.exists() and not args.out_md.exists()
        ledger = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = json.loads(args.result.read_text(encoding="utf-8"))
        assert len(ledger["sessions"]) == result["場数"] == 66 and result["試行"] == 83
        inputs = [args.input / f"{r['id']}.json" for r in ledger["sessions"]]
        before = {str(p): sha(p) for p in [*inputs, args.result, args.manifest]}
        assert {p.name: before[str(p)] for p in inputs} == result["再生結果SHA256"]
        sessions = [json.loads(p.read_text(encoding="utf-8")) for p in inputs]
        assert [r["session"] for r in sessions] == [r["id"] for r in ledger["sessions"]]
        value = {"試行": 83, "診断": "固定出口比較の事後分解", "全場既使用": True, "場数": len(sessions),
                 "診断コードSHA256": sha(Path(__file__)), "観測入力SHA256": before, **diagnose(sessions)}
        verify_summary(value, result)
        assert all(sha(Path(p)) == wanted for p, wanted in before.items())
        value["正式集計との不一致数"] = 0
        value["入力前後変更数"] = 0
        with args.out_md.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown(value))
    with args.out_json.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"保存": str(args.out_json), "場数": value.get("場数"), "比較数": len(value.get("出口差比較", {})), "人工": value.get("会計")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
