"""89のE1G2主・残玉初回正益16玉を保存原行だけから記述する。"""

import argparse
from collections import Counter
from datetime import datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo


KEY = "E1G2_D0"
SOURCES = (
    "scripts/FAR利益床と収穫配分の比較/replay.go",
    "scripts/FAR背景維持と押戻し再開/event.go",
    "scripts/FAR後期15分移植/technical.go",
    "scripts/定時の現在根拠と部分利益保護/entry.go",
    "scripts/チャートの現在性と補助確認/entry.go",
    "../SessionTradeExecuter/internal/strategy/features.go",
    "../SessionTradeExecuter/internal/strategy/selected_day164_features.go",
    "../SessionTradeExecuter/internal/strategy/selected_night_features.go",
    "../SessionTradeExecuter/internal/strategy/selected_night_state.go",
)


def sha(path: Path) -> str:
    """
    機能: 保存正本と定義コードを内容指紋へ結ぶ。
    引数: path (Path) は既存ファイル。
    返り値: str はSHA256。原板本文は開かない。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(path: Path) -> list[dict]:
    """
    機能: 正式共有又は玉診断の圧縮行だけを読む。
    引数: path (Path) はJSONL gzip。
    返り値: list[dict] は保存値。市場への再売買は行わない。
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def latest_record(shared: dict, at: float, index: int, line: int) -> dict:
    """
    機能: 同秒でも後の原行を除き、当時までに公開済みの最新疎記録を選ぶ。
    引数: shared (dict)、at (float)、index/line (int) は共有記録と対象原行。
    返り値: dict は最大ordinalの過去記録。固定Runtimeのtimer→raw順に依存する。
    """
    candidates = []
    for record in shared["entry_observations"]:
        item = record["input"]
        if item["at"] > at:
            continue
        if item["at"] == at and item["origin"] == "quote" and (item["quote"]["index"] > index or item["quote"]["line"] > line):
            continue
        candidates.append(record)
    assert candidates, "当時までの技法公開記録がない"
    return max(candidates, key=lambda r: r["input"]["ordinal"])


def state(known: bool, value: float | None) -> str:
    """
    機能: 既知性と方向符号を未知/同方向/中立/反対へ分ける。
    引数: known (bool)、value (float|None) は既知性と売買方向を掛けた値。
    返り値: str は記述分類。未知に保存される0を中立へ変換しない。
    """
    if not known or value is None:
        return "未知"
    assert math.isfinite(value)
    return "同方向" if value > 0 else "反対" if value < 0 else "中立"


def distribution(values: list[float]) -> dict:
    """
    機能: 境界を探索せず観測値の全範囲と中央値を記録する。
    引数: values (list[float]) は全群の数値。
    返り値: dict は件数/min/median/maxと昇順全値。0件はnull。
    """
    return {"件数": len(values), "最小": min(values) if values else None, "中央値": statistics.median(values) if values else None, "最大": max(values) if values else None, "昇順全値": sorted(values)}


def summarize(cases: list[dict]) -> dict:
    """
    機能: 全16玉と既存最終ラベル群を同じ項目で記述する。
    引数: cases (list[dict]) は事後に選別しない対象群。
    返り値: dict は可用性・同足再利用・値分布。勝敗を条件採用に使わない。
    """
    return {"玉数": len(cases), "最終費用後円": sum(c["最終費用後円"] for c in cases),
        "entryからflag秒": distribution([c["entryからflag秒"] for c in cases]),
        "flag時3分足齢秒": distribution([c["技法"]["flag足齢秒"] for c in cases]),
        "要求足から更新玉": sum(c["技法"]["要求足から更新"] for c in cases),
        "実取得時公開足から更新玉": sum(c["技法"]["実取得時公開足から更新"] for c in cases),
        "同じ実取得足再利用玉": sum(not c["技法"]["実取得時公開足から更新"] for c in cases),
        "MACDとRSIの同方向増分": sum(c["技法"]["MACD方向"] == c["技法"]["RSI方向"] == "同方向" for c in cases),
        "Current存在玉": sum(c["current_available"] for c in cases),
        "5秒方向": dict(Counter(c["短秒"]["five"]["方向"] for c in cases)),
        "15秒方向": dict(Counter(c["短秒"]["fifteen"]["方向"] for c in cases)),
        "OFI方向": dict(Counter(c["支持"]["OFI方向"] for c in cases)),
        "支持Known玉": sum(c["支持"]["raw"] is not None and c["支持"]["raw"]["known"] for c in cases),
        "E08 available玉": sum(c["構造"]["available"] for c in cases),
        "E08 Known玉": sum(c["構造"]["known"] for c in cases),
        "E08 QuantityKnown玉": sum(c["構造"]["quantity_known"] for c in cases),
        "E08自己帯Active玉": sum(c["構造"]["有効自己帯Active"] is True for c in cases),
        "E08反対帯Active玉": sum(c["構造"]["有効反対帯Active"] is True for c in cases),
        "旗原行全fill後残0玉": sum(c["同原行全fill後残量"] == 0 for c in cases),
        "既存正益後赤字玉": sum(c["残玉正益後赤字"] for c in cases)}


def main() -> None:
    """
    機能: E1G2_D0の全残玉旗を共有contextへ結び小型観測を新規保存する。
    引数: --result/--trades/--grids/--out-json/--out-md (Path) は既存3正本と新規先。
    返り値: None。原板/API/売買/閾値探索は行わず、欠番・未来混入は停止する。
    """
    parser = argparse.ArgumentParser()
    for name in ("result", "trades", "grids", "out-json", "out-md"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    assert not args.out_json.exists() and not args.out_md.exists()
    paths = (args.result, args.trades, args.grids)
    before = {str(p): sha(p) for p in paths}
    code_before = sha(Path(__file__))
    definitions = {p: sha(Path(p)) for p in SOURCES}
    result = json.loads(args.result.read_text(encoding="utf-8"))
    assert result["試行"] == 89 and result["場数"] == 66
    target = [r for r in rows(args.trades) if r["key"] == KEY]
    selected = [r for r in target if r["lot"]["flag"]]
    official = result["比較"][KEY]
    assert len(target) == official["完結玉"] == 33 and len(selected) == official["残玉旗"] == 16
    assert sum(r["lot"]["net_pnl"] for r in target) == official["費用後損益円"]
    shared_rows = rows(args.grids)
    shared_map = {r["session"]: r for r in shared_rows}
    assert len(shared_map) == len(shared_rows) == 66
    cases = []
    for row in selected:
        session, lot, order = row["session"], row["lot"], row["entry_order"]
        shared = shared_map[session]
        eq = shared["technical_equivalence"]
        assert eq["mismatches"] == 0 and len(eq["actual_sha256"]) == 64 and eq["actual_sha256"] == eq["event_sha256"]
        matches = [(c, t) for c in shared["profit_contexts"] for t in c["triggered_by"] if t["book_key"] == KEY and t["position_id"] == lot["id"] and t["flag_kind"] == "residual"]
        assert len(matches) == 1
        context, trigger = matches[0]
        quote, tech = context["quote"], context["technical"]
        assert trigger["reference_id"] == lot["reference_id"] and quote["time"] == lot["flag_time"] and quote["index"] == lot["flag_index"]
        assert quote["time"] >= lot["entry_time"] and quote["line"] >= lot["entry_line"]
        entry_record = latest_record(shared, lot["entry_time"], lot["entry_index"], lot["entry_line"])
        flag_record = latest_record(shared, quote["time"], quote["index"], quote["line"])
        assert flag_record["input"]["technical"] == tech, "疎公開記録と当旗技法の全値差"
        grid = next(g for g in shared["grid_decisions"] if g["at"] == order["request_time"])
        request_tech, entry_tech = grid["c0"]["base"]["technical"], entry_record["input"]["technical"]
        assert 0 < request_tech["bar3_end"] <= order["request_time"] and 0 < entry_tech["bar3_end"] <= lot["entry_time"]
        pieces = [c for c in row["closed"] if c["exit_line"] <= quote["line"]]
        assert all(c["exit_time"] <= quote["time"] for c in pieces)
        assert trigger["remaining_after_fill"] == lot["initial_quantity"] - sum(c["quantity"] for c in pieces)
        assert trigger["closed_net_after_fill"] == sum(c["pnl5"] for c in pieces)
        side = lot["side"]
        histogram = side * (tech["histogram3"] - tech["previous_histogram3"]) if tech["reversal_known"] else None
        rsi = side * (tech["rsi3"] - tech["previous_rsi3"]) if tech["reversal_known"] else None
        current = context["current"]
        assert context["current_available"] == (current is not None)
        short, support, structure = {}, {"raw": None, "OFI方向": "未知", "方向OFI30": None, "有効M": None, "有効T": None, "有効Opp": None}, {"available": False, "known": False, "quantity_known": False, "有効自己帯Active": None, "有効反対帯Active": None, "raw": None}
        for name in ("five", "fifteen"):
            short[name] = {"raw": None, "方向速度pt毎秒": None, "方向": "未知"}
        if current is not None:
            assert current["time"] == current["received"] == quote["time"] and current["source_line"] == quote["line"] and current["reference"] == "NK225"
            assert current["short"]["time"] == quote["time"] and current["short"]["mid"] == quote["bid"] + (quote["ask"] - quote["bid"]) / 2
            for name in ("five", "fifteen"):
                window = current["short"][name]
                value = side * window["speed"] if window["known"] else None
                short[name] = {"raw": window, "方向速度pt毎秒": value, "方向": state(window["known"], value)}
            own = current["buy" if side > 0 else "sell"]
            ofi = side * own["ofi30"] if own["ofi_known"] else None
            support = {"raw": own, "OFI方向": state(own["ofi_known"], ofi), "方向OFI30": ofi, "有効M": own["m"] if own["known"] else None, "有効T": own["t"] if own["known"] else None, "有効Opp": own["opp"] if own["known"] else None}
            night = current["night"]
            known = night["available"] and night["known"] and not night["invalid"] and night["time"] == quote["time"] and night["index"] == current["source_index"]
            structure = {"available": night["available"], "known": night["known"], "quantity_known": night["band"]["quantity_known"], "有効自己帯Active": night["buy" if side > 0 else "sell"]["active"] if known else None, "有効反対帯Active": night["sell" if side > 0 else "buy"]["active"] if known else None, "raw": night}
        label = "最終黒字" if lot["net_pnl"] > 0 else "最終赤字" if lot["net_pnl"] < 0 else "最終同値"
        cases.append({"場": session, "book_key": KEY, "実玉ID": lot["id"], "参照ID": lot["reference_id"], "side": side, "初期量": lot["initial_quantity"], "要求time": order["request_time"], "entry_time": lot["entry_time"], "entry_index": lot["entry_index"], "entry_line": lot["entry_line"], "entryからflag秒": quote["time"] - lot["entry_time"], "要求からflag秒": quote["time"] - order["request_time"], "最終ラベル": label, "最終費用後円": lot["net_pnl"], "残玉正益後赤字": lot["flag"] and lot["net_pnl"] < 0, "全玉正益旗": lot["whole_flag"], "全玉正益後赤字": lot["whole_flag"] and lot["net_pnl"] < 0, "残玉全玉flag同時計": lot["flag_time"] == lot["whole_flag_time"], "context_id": context["id"], "quote": quote, "同原行全fill後残量": trigger["remaining_after_fill"], "同原行実確定純額円": trigger["closed_net_after_fill"], "技法": {"request_bar3_end": request_tech["bar3_end"], "entry公開bar3_end": entry_tech["bar3_end"], "entry公開記録ID": entry_record["id"], "entry公開ordinal": entry_record["input"]["ordinal"], "entry公開記録at": entry_record["input"]["at"], "entry公開元": entry_record["input"]["origin"], "flag公開記録ID": flag_record["id"], "flag_bar3_end": tech["bar3_end"], "flag足齢秒": quote["time"] - tech["bar3_end"], "要求足から更新": tech["bar3_end"] > request_tech["bar3_end"], "実取得時公開足から更新": tech["bar3_end"] > entry_tech["bar3_end"], "MACD方向増分": histogram, "RSI方向増分": rsi, "MACD方向": state(tech["reversal_known"], histogram), "RSI方向": state(tech["reversal_known"], rsi), "raw": tech}, "current_available": context["current_available"], "current出典": None if current is None else {k:current[k] for k in ("reference", "time", "received", "source_index", "source_line")}, "短秒": short, "支持": support, "構造": structure})
    cases.sort(key=lambda c: (c["entry_time"], c["実玉ID"]))
    summaries = {"全残玉正益16玉": summarize(cases)}
    for label in ("最終黒字", "最終赤字", "最終同値"):
        summaries[label] = summarize([c for c in cases if c["最終ラベル"] == label])
    assert summaries["最終黒字"]["玉数"] == 3 and summaries["最終赤字"]["玉数"] == 13
    assert summaries["全残玉正益16玉"]["既存正益後赤字玉"] == official["残玉旗後赤字"]
    assert before == {str(p): sha(p) for p in paths} and definitions == {p: sha(Path(p)) for p in SOURCES} and sha(Path(__file__)) == code_before
    value = {"対象": KEY, "確認日": "2026-11-08", "成功": True, "観測コードSHA256": code_before, "入力SHA256": before, "定義コードSHA256": definitions, "全母集団": {"完結玉": len(target), "残玉正益玉": len(cases), "残玉正益未観測玉": len(target)-len(cases), "残玉正益未観測円": sum(r["lot"]["net_pnl"] for r in target if not r["lot"]["flag"])}, "群統計": summaries, "全16当時値": cases, "入口公開足の復元限定": "疎記録の当時までの最大ordinalと固定Runtime timer→raw順、actual/event全呼出Technical同値に依存。flag原行16件で疎記録Technical全文一致も照合。元EMA/RSI/MACDの独立再算や原板再走査ではない。", "ラベルの限定": "最終黒赤は取引全体の最終純額。正益後赤字は残玉単価strict正旗のある玉の最終赤字。旗後だけの損益フローや将来予測ではない。", "新原板読取": 0, "売買再生": 0, "API": 0, "閾値探索": 0, "新ルール採用": 0, "正式変更": 0}
    text = ["# E1G2主：初回利益で本当に新しい情報が増えていたか", "", "2026-11-08。89正式保存だけを読取。全33玉のうち残玉単価の費用後strict正旗が立った16玉を全件対象とし、新原板・再売買・API・閾値探索・新ルール採用は0。", "", "MACDとRSI増分は16玉とも方向側だが、初回利益の15/16玉は実取得時と同じ確定3分足の再利用だった。足の情報は入口を再確認しただけで、利益後に新たな継続を確認した証拠ではない。", "", "| 群 | 玉 | entry→flag秒 min/中央値/max | flag足齢秒 min/中央値/max | 取得足から更新 | Current存在 | 5秒既知 | 15秒既知 | OFI既知 | E08既知 |", "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for label, group in summaries.items():
        if not group["玉数"]:
            continue
        elapsed, age = group["entryからflag秒"], group["flag時3分足齢秒"]
        known = lambda name: group["玉数"] - group[name].get("未知", 0)
        text.append(f"| {label} | {group['玉数']} | {elapsed['最小']}/{elapsed['中央値']}/{elapsed['最大']} | {age['最小']}/{age['中央値']}/{age['最大']} | {group['実取得時公開足から更新玉']} | {group['Current存在玉']} | {known('5秒方向')} | {known('15秒方向')} | {known('OFI方向')} | {group['E08 Known玉']} |")
    text += ["", "最終黒字3・最終赤字13は記述用の事後ラベルであり、そこから閾値を選んでいない。正益未観測17玉は本16玉の保護切替で直接説明できる母数ではない。", "", "## 全件の入口とflag", "", "| 場/玉末尾 | 方向 | 初期量 | entry→flag秒 | 3分足更新 | flag足齢秒 | 5秒/15秒/OFI | E08/数量known | 最終ラベル |", "| --- | --- | ---: | ---: | --- | ---: | --- | --- | --- |"]
    for c in cases:
        text.append(f"| {c['場']}/{c['実玉ID'].rsplit('_',1)[-1]} | {'買' if c['side']>0 else '売'} | {c['初期量']} | {c['entryからflag秒']} | {'更新' if c['技法']['実取得時公開足から更新'] else '同足'} | {c['技法']['flag足齢秒']} | {c['短秒']['five']['方向']}/{c['短秒']['fifteen']['方向']}/{c['支持']['OFI方向']} | {c['構造']['known']}/{c['構造']['quantity_known']} | {c['最終ラベル']} |")
    text += ["", "0秒の1玉は価格時計が同じでも取得の次の物理原行（73513→73514）で初回正益になっている。新規と同じ原行で利益が確定した意味ではない。"]
    text += ["", "## 既知性の定義", "", "- `current_available` は当原行のCurrent抜粋pointerがあること。16/16存在しても、全指標既知・全量支持を意味しない。Current time/received/物理行はflag Quoteと全件一致。SourceIndexとQuote.Indexは別番号として保持。", "- Shortは自己BBO中央の5/15秒窓のpt/実秒。目標時刻以前の過去端、許容遅延15秒以内、正の実経過、Bad累計差なしが必要。Supportの窓別bp換算値とは異なる。Known=falseのmove/speed=0は未知の保存値で、中立へ置き換えない。", "- OFI30は最良BBO価格・表示数量の更新から作る正規化OFI差分の窓平均。現在差分成立・30秒履歴・Bad差なし・有効差分2件以上等が必要。約定出来高でも買い手だけの契約数でもない。本文JSONでは方向符号を掛け、未知はnullと理由を残す。", "- Support.Knownは自己5/15/120/300秒窓が揃うこと。OFI/相手120秒は個別の補助。ProfitCurrentにはOwnKnown/PeerKnownとWindows mapが保存されないため、Known=falseの自己欠測窓を本記録だけで特定しない。M/T/Oppは価格窓・相手・OFIを元尺度で合成した未校正量で、確率ではない。未知時の保存0は有効な支持0としない。", "- `night` は名称に反して当場NKで更新されるE08価格構造。Availableは特徴器の当行出力、Knownは選択窓の価格既知、Invalidは不良板を区別する。Band.QuantityKnownは窓内BadQuantity=0で、別途QuantityEvents/CommonDepthEventsも見る。OFIとは対象窓・品質要件が異なる。", "- 自己/反対帯Active、QuantitySupport、SupplyPassed、Pressuredは価格帯状態と数量回復の履歴。Activeでない古い帯に残るtrueの数量旗を現在支持へ読み替えない。帯のTime/Index/Event、Barrier/Supportの各Known/時点はJSONへ残す。価格帯Holdは実建玉・Source所有ではない。", "", "## 解釈と残る観測", "", "3分MACD/RSIの同方向だけでは、この16玉の伸ばす/収穫を新たに判別できない。15玉で同足だからである。短秒・OFI・E08は新しい原行情報を含み得るが、未知がそれぞれ別にあり、最終黒赤群双方に既知/未知がある。未知を弱さ・反対・中立に変換して切替ルールにはしない。", "", "次の観測では、初回だけでなく保護を継続した各時点で、価格位置の維持/否定、初回後に公開された勢い、当原行の量・短秒の既知性を分ける必要がある。このメモから条件・閾値・収穫比率を採用しない。", "", "実取得時の足は疎event公開記録と固定actual/event全呼出同値に依存して復元した。要求時C0足とは別にJSONへ保存し、同秒の後原行を除外した。flag16原行ではこの復元Technicalが保存context全文と一致する。独立した原板指標再計算とは呼ばない。", "", "[全16当時値と指紋](初回正益の現在性.json)にQuote、Technical、Shortの端点と未知理由、OFI、M/T/Opp、E08状態を残す。"]
    text += ["", "定義の読取先：[Current抜粋を作る89Runtime](../../scripts/FAR利益床と収穫配分の比較/replay.go)、[81の支持/E08型と抽出](../../scripts/定時の現在根拠と部分利益保護/entry.go)、[82のShort型と抽出](../../scripts/チャートの現在性と補助確認/entry.go)、[元支持・OFI・短秒](../../../SessionTradeExecuter/internal/strategy/selected_day164_features.go)、[元E08窓](../../../SessionTradeExecuter/internal/strategy/selected_night_features.go)、[元帯状態](../../../SessionTradeExecuter/internal/strategy/selected_night_state.go)。当時の版はJSON内のSHAへ固定した。"]
    text += ["", "元Mは自己120/300秒と相手120秒の方向別bpを重み.45/.35/.20でclip合成した非負量。元Tは自己15/5秒とOFIを重み.45/.35/.20でclip合成した非負量で、Oppは同じ合成の反対側。補助未知は元式の0寄与で重み再正規化なし。Support.Knownでも全補助が観測済みとは限らない。これらの係数を新しく採用したものではない。", "", "E08は直近8価格イベントを基準とする窓で、8秒ではない。Band.Line/StartLineは元特徴Index代理であり、Current.source_lineの原板物理行と区別する。帯Activeの期限・反対側移動による失効と、数量旗の残存は別の状態である。"]
    with args.out_json.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    with args.out_md.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(text) + "\n")
    print(json.dumps({"成功": True, "対象玉": len(cases), "全体": summaries["全残玉正益16玉"], "入力前後不変": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
