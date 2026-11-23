"""固定83のG1利益旗後赤字を、要求・部分約定・残量予約・費用へ読取分解する。"""

from __future__ import annotations

# 派生元: work/83正益赤字原因/診断する.py
# 派生元SHA256: 45a695e20cbe361264730b33f6add2a19f39035b0c76c6d3ea08f9a517ae1b53
# 算術・群分類・原行照合は変更せず、入出力を明示CLIへ派生します。


import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path.cwd()
KEYS = ("S0G1_D0", "S1G1_D0", "S0G1_D1", "S1G1_D1")


def digest(path: Path) -> str:
    """
    機能: 読取前後の実ファイル指紋を計算する。
    引数: path (Path) は既存ファイル。
    返り値: str はSHA256。
    """
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def distribution(values: list[float]) -> dict:
    """
    機能: 全観測群を除外せず、要約分布を求める。
    引数: values (list[float]) は既知の値。
    返り値: dict は件数・合計・平均・順序統計。空群は件数0。
    """
    if not values:
        return {"件数": 0}
    v = sorted(values)
    return {"件数": len(v), "合計": sum(v), "平均": sum(v)/len(v), "最小": v[0],
            "第1四分位順序値": v[(len(v)-1)//4], "中央値順序値": v[(len(v)-1)//2],
            "第3四分位順序値": v[3*(len(v)-1)//4], "最大": v[-1]}


def stamp(at: float | None) -> str | None:
    """
    機能: 保存時計を読める日本時間へ変換する。
    引数: at (float | None) は価格時計秒。
    返り値: str | None は日本時間ISO文字列。
    """
    return None if at is None else datetime.fromtimestamp(at, timezone(timedelta(hours=9))).isoformat()


def make_case(session: str, key: str, lot: dict, orders: list[dict], closed: list[dict]) -> dict:
    """
    機能: 一玉を保存約定片へ結び、要求価格損益と実損益の差を計算する。
    引数: session/key (str) は場と会計、lot (dict) は玉、orders/closed (list[dict]) は該当記録。
    返り値: dict は因果を断定しない段階別の観測。算術矛盾は例外。
    """
    exits = [o for o in orders if o["kind"] == "exit"]
    harvest = [o for o in exits if o["harvest"]]
    assert len(harvest) == 1
    h = harvest[0]
    hc = [c for c in closed if c["harvest"]]
    other = [c for c in closed if not c["harvest"]]
    assert len(hc) == 1 and len(other) == 1 and len(exits) == 2
    final = next(o for o in exits if not o["harvest"])
    assert all(o["status"] == "filled" and o["remaining"] == 0 for o in exits)
    assert all(o["net_per_unit"] is not None and o["mark"] is not None for o in exits)
    q = lot["initial_quantity"]
    wh = lot["flag_net_per_unit"] * q
    request_pnl = sum(o["net_per_unit"]*o["quantity"] for o in exits)
    execution = sum(c["request_to_fill_adverse_yen"] for c in closed)
    net = sum(c["pnl5"] for c in closed)
    assert net == lot["net_pnl"] == request_pnl-execution
    h_realized = sum(c["pnl5"] for c in hc)
    rem = q-h["quantity"]
    nominal_floor_net = h_realized-122*rem
    budget = h_realized-222*rem
    assert (budget < 1) == lot["funding_failed"]
    assert h["request_index"] == lot["flag_index"] == lot["whole_flag_index"]
    assert h["request_line"] == lot["whole_flag_line"]
    assert h["request_time"] == lot["flag_time"] == lot["whole_flag_time"]
    labels = {
        "部分利確は初回益の同原行で要求": True,
        "部分利確約定が要求より不利": sum(c["request_to_fill_adverse_yen"] for c in hc) > 0,
        "部分利確自体が費用後赤字": h_realized < 0,
        "実部分利確後の10pt余裕予算不足": budget < 1,
        "実部分利確後の建値返済で費用を賄えない": nominal_floor_net < 0,
        "残量返済は部分利確の約定前に予約": final["request_line"] < h["fill_line"],
        "残量返済は部分利確の約定と同原行に予約": final["request_line"] == h["fill_line"],
        "残量要求床0": final["floor"] == 0,
        "残量要求時に正の床を既に割込": final["floor"] > 0 and final["gain"] < final["floor"],
        "残量要求時の全玉費用後評価が負": final["whole_net"] < 0,
        "各返済の要求価格の合算なら黒字": request_pnl > 0,
        "各返済の要求価格の合算でも赤字": request_pnl < 0,
        "残量の要求から約定も不利": sum(c["request_to_fill_adverse_yen"] for c in other) > 0,
    }
    return {"場": session, "会計": key, "玉ID": lot["id"], "売買方向": lot["side"], "新規価格": lot["entry_price"],
        "初回正益": {"時計": lot["flag_time"], "日本時間": stamp(lot["flag_time"]), "原行": lot["whole_flag_line"],
                    "採用Index": lot["flag_index"], "返済側気配": lot["flag_mark"], "1枚費用後円": lot["flag_net_per_unit"], "全玉評価円": wh},
        "部分返済": {"要求時計": h["request_time"], "要求原行": h["request_line"], "要求Index": h["request_index"],
                    "要求返済側気配": h["mark"], "数量": h["quantity"], "要求時の計画純益円": h["quantity"]*h["net_per_unit"],
                    "実約定時計": h["fill_time"], "実約定原行": h["fill_line"], "実約定価格": h["fill_price"],
                    "要求から秒": h["fill_time"]-h["request_time"], "原行差": h["fill_line"]-h["request_line"],
                    "実確定純益R円": h_realized, "要求から約定の悪化円": sum(c["request_to_fill_adverse_yen"] for c in hc),
                    "残量": rem, "残量建値返済を仮定した全玉純益円": nominal_floor_net, "10pt悪化余裕後の予算円": budget},
        "床": {"初回益時の床pt": lot["flag_floor"], "確定益予算床起動": lot["cash_floor_active"],
                "確定益予算床pt": lot["cash_floor"], "起動時計": lot["cash_floor_at"], "予算不足記録": lot["funding_failed"]},
        "残量返済": {"要求時計": final["request_time"], "要求原行": final["request_line"], "要求Index": final["request_index"],
                    "理由": final["reason"], "要求返済側気配": final["mark"], "要求時の幅pt": final["gain"], "要求時の床pt": final["floor"],
                    "要求時の確定損益円": final["closed_net"], "要求時の全玉評価円": final["whole_net"],
                    "実約定時計": final["fill_time"], "実約定原行": final["fill_line"], "実約定価格": final["fill_price"],
                    "要求から秒": final["fill_time"]-final["request_time"], "原行差": final["fill_line"]-final["request_line"],
                    "実純益円": sum(c["pnl5"] for c in other), "要求から約定の悪化円": sum(c["request_to_fill_adverse_yen"] for c in other)},
        "会計分解": {"初回益全玉評価W円": wh, "段階別要求価格を合算した純益P円": request_pnl,
                    "要求までの評価変更P引くW円": request_pnl-wh, "要求後の合計悪化A円": execution, "実最終純益P引くA円": net,
                    "実粗損益円": sum(c["gross_pnl"] for c in closed), "往復手数料円": sum(c["commission"] for c in closed),
                    "想定滑り円": sum(c["slippage"] for c in closed)}, "重なり得る観測分類": labels}


def raw_points(session: str, source: Path, cases: list[dict], clock_module: object) -> dict:
    """
    機能: 負玉の旗・要求・約定を原板の物理行と採用Indexへ結ぶ。
    引数: session (str) は場、source (Path) は原板gzip、cases (list[dict]) は負玉、clock_module (object) は固定80時計関数。
    返り値: dict は必要原行のみの気配。全軌跡や新戦略を再生しない。
    """
    wanted = set()
    for c in cases:
        wanted.add(c["初回正益"]["原行"])
        for field in ("部分返済", "残量返済"):
            wanted.update((c[field]["要求原行"], c[field]["実約定原行"]))
    points = {}
    start, end = clock_module.bounds(session)
    previous, index = start, -1
    with gzip.open(source, "rt", encoding="utf-8") as stream:
        for line, text in enumerate(stream, 1):
            row = json.loads(text)
            at = clock_module.clock(row.get("CurrentPriceTime"))
            if at is None or not start <= at < end or at < previous:
                assert line not in wanted, "対象行が不採用"
                continue
            previous = at
            index += 1
            if line not in wanted:
                continue
            bid, ask = row["Buy1"]["Price"], row["Sell1"]["Price"]
            assert row["CurrentPrice"] > 0 and 0 < bid < ask
            points[line] = {"時計": at, "日本時間": stamp(at), "採用Index": index, "買気配": bid, "売気配": ask}
            if len(points) == len(wanted):
                break
    assert set(points) == wanted
    for c in cases:
        s = c["売買方向"]
        flag = c["初回正益"]
        f = points[flag["原行"]]
        assert (f["時計"], f["採用Index"]) == (flag["時計"], flag["採用Index"])
        assert flag["返済側気配"] == f["買気配" if s > 0 else "売気配"]
        assert flag["1枚費用後円"] == s*(flag["返済側気配"]-c["新規価格"])*10-122
        for field in ("部分返済", "残量返済"):
            o = c[field]
            req, fill = points[o["要求原行"]], points[o["実約定原行"]]
            assert (req["時計"], req["採用Index"]) == (o["要求時計"], o["要求Index"])
            assert o["要求返済側気配"] == req["買気配" if s > 0 else "売気配"]
            assert o["実約定価格"] == fill["買気配" if s > 0 else "売気配"]
            assert o["実約定時計"] == fill["時計"] and fill["採用Index"] > req["採用Index"]
        if c["床"]["確定益予算床起動"]:
            assert c["床"]["起動時計"] == c["部分返済"]["実約定時計"]
            assert c["残量返済"]["要求原行"] >= c["部分返済"]["実約定原行"]
    return {str(k): v for k, v in sorted(points.items())}


def main() -> None:
    """
    機能: 全G1旗玉を対照群に残し、旗後赤字全群だけ原板へ結ぶ。
    引数: --input/--manifest/--result/--raw-audit/--out-json/--out-md (Path) を全て明示する。
    返り値: None。小型MD/JSONを新規保存し、既存入力・金融条件を変更しない。
    """
    parser = argparse.ArgumentParser()
    for name in ("input", "manifest", "result", "raw-audit", "out-json", "out-md"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    assert not args.out_json.exists() and not args.out_md.exists(), "出力は新規である必要があります"
    ledger_path = args.manifest.resolve()
    official_path = args.result.resolve()
    audit_path = args.raw_audit.resolve()
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    official = json.loads(official_path.read_text(encoding="utf-8"))
    inputs = [args.input.resolve() / f"{s['id']}.json" for s in ledger["sessions"]]
    before = {str(p): digest(p) for p in [ledger_path,official_path,audit_path,*inputs]}
    assert {p.name: before[str(p)] for p in inputs} == official["再生結果SHA256"]
    groups = {key: {"全玉": [], "全玉旗後黒字": [], "全玉旗後同値": [], "全玉旗後赤字": []} for key in KEYS}
    cases = []
    for p in inputs:
        result = json.loads(p.read_text(encoding="utf-8"))
        for key in KEYS:
            b = result["books"][key]
            for lot in b["lots"]:
                groups[key]["全玉"].append({"net":lot["net_pnl"], "予算不足":lot["funding_failed"]})
                if not lot["whole_flag"]:
                    continue
                os = [o for o in b["orders"] if o["position_id"] == lot["id"]]
                cs = [c for c in b["closed"] if c["position_id"] == lot["id"]]
                hs = [o for o in os if o["harvest"]]
                summary = {"net": lot["net_pnl"], "予算不足": lot["funding_failed"], "cash床": lot["cash_floor"],
                    "初回益1枚円": lot["flag_net_per_unit"], "harvest要求遅れIndex": hs[0]["request_index"]-lot["flag_index"] if hs else None,
                    "harvest要求約定秒": hs[0]["fill_time"]-hs[0]["request_time"] if hs else None,
                    "harvest悪化円": sum(c["request_to_fill_adverse_yen"] or 0 for c in cs if c["harvest"]),
                    "残量悪化円": sum(c["request_to_fill_adverse_yen"] or 0 for c in cs if not c["harvest"])}
                group = "全玉旗後黒字" if lot["net_pnl"] > 0 else "全玉旗後赤字" if lot["net_pnl"] < 0 else "全玉旗後同値"
                groups[key][group].append(summary)
                if lot["net_pnl"] < 0:
                    cases.append(make_case(result["session"],key,lot,os,cs))
    summary = {}
    for key, gs in groups.items():
        summary[key] = {}
        for name, rows in gs.items():
            metrics = {f: distribution([r[f] for r in rows if r.get(f) is not None]) for f in ("net","cash床","初回益1枚円","harvest要求遅れIndex","harvest要求約定秒","harvest悪化円","残量悪化円")}
            summary[key][name] = {"玉数":len(rows),"損益円":sum(r["net"] for r in rows),"予算不足玉":sum(r.get("予算不足",False) for r in rows),"分布":metrics}
        assert summary[key]["全玉旗後赤字"]["玉数"] == official["比較"][key]["全玉旗後赤字"]
    # ----------------------------------------
    # 旗後赤字の原行だけを抽出し、同秒の別行を潰さず要求と約定を結びます。
    clock_path = ROOT / "scripts/FAR後期15分移植/原板照合.py"
    spec = importlib.util.spec_from_file_location("固定80時計",clock_path)
    clock_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(clock_module)
    raw = {}
    raw_before = {}
    by_session = defaultdict(list)
    for case in cases:
        by_session[case["場"]].append(case)
    for session in ledger["sessions"]:
        name = session["id"]
        if name not in by_session:
            continue
        source = Path(ledger["source_root"])/session["files"]["NK225_book"]["path"]
        raw_before[str(source)] = digest(source)
        assert raw_before[str(source)] == session["files"]["NK225_book"]["sha256"]
        raw[name] = {"原板":str(source),"SHA256":raw_before[str(source)],"原行気配":raw_points(name,source,by_session[name],clock_module)}
    assert all(digest(Path(p)) == v for p,v in {**before,**raw_before}.items())
    counts = {key: {} for key in KEYS}
    for key in KEYS:
        chosen = [c for c in cases if c["会計"] == key]
        for label in chosen[0]["重なり得る観測分類"]:
            rows = [c for c in chosen if c["重なり得る観測分類"][label]]
            counts[key][label] = {"玉数":len(rows),"最終損益円":sum(c["会計分解"]["実最終純益P引くA円"] for c in rows)}
    value = {"試行":83,"確認日":"2026-11-07","対象":"G1・全66場・二構造二遅延の全玉旗群と旗後赤字全群",
        "新再生":0,"金融条件変更":0,"入力前後変更数":0,"診断コードSHA256":digest(Path(__file__)),
        "固定時計コードSHA256":digest(clock_path),"観測入力SHA256":before,"全群分布":summary,
        "負玉の重なる分類":counts,"全42会計玉":cases,"該当原板との結合":raw,
        "限定":"保存した要求と約定の会計分解。全原行の最初床到達・義務要求0不足は別の成功した原板監査を参照。約定はラージBBO代理であり実板消費・実通信を保証しない。黒字対照群の全経路は再走査していない。"}
    args.out_json.parent.mkdir(parents=True,exist_ok=True)
    args.out_md.parent.mkdir(parents=True,exist_ok=True)
    with args.out_json.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write("\n")
    lines = ["# G1正益後赤字の要求・約定・費用分解", "", "固定83を変更しない事後診断。新再生0、金融変更0、正式入力前後変更0。確認日：2026-11-07。数値正本は[正益後赤字の診断.json](正益後赤字の診断.json)。", "",
        "全玉正益旗後の最終赤字42会計玉を漏れなく収録した。S0/S1・両遅延には同じ局面が重複するため42件の独立事象とは数えない。黒字・同値の全旗玉も対照群として分布を残した。", "",
        "## 全群", "", "| 会計 | 全玉 | 旗後黒字玉 | 同損益円 | 旗後赤字玉 | 同損益円 | 赤字玉の予算不足 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for key,g in summary.items():
        lines.append(f"| {key} | {g['全玉']['玉数']} | {g['全玉旗後黒字']['玉数']} | {g['全玉旗後黒字']['損益円']:,} | {g['全玉旗後赤字']['玉数']} | {g['全玉旗後赤字']['損益円']:,} | {g['全玉旗後赤字']['予算不足玉']} |")
    lines += ["", "## 確認できたこと", "", "全42玉で、残玉の費用後正益・全玉正益の初回原行と部分利確要求原行が一致した。部分返済は要求価格では黒字でも、次の適格板で不利に約定し、全玉利益を保つ予定の確定益予算が不足した。全42玉の旗・部分要求/約定・残量要求/約定を原板の物理行、採用Index、時計、返済側BBOへ結合した。", "",
        "要求済み返済は取り消して待ち続けたものではない。1秒条件でも実約定がちょうど1秒後とは限らず、同じ価格時計の異なる原行もある。原板監査の要求不足0という結果と合わせ、赤字だけを根拠に利益保護の放置と分類しない。", "",
        "玉ごとの正確な算術は N=P−A=W+(P−W)−A。Wは初回正益全玉評価、Pは各返済要求時の気配で該当数量を決済した計画純益を合算した額、Aは要求気配から実約定への方向付き悪化額。Pは異なる時点の要求を合算した会計上の反実仮想であり、同時に全玉を確実に決済できた価格ではない。Aには想定滑り5ptを含めず、別計上の往復122円/枚と二重計上しない。", "",
        "75枚を20ptで利確する計画なら純益5,850円だが、10pt不利な実約定では純損1,650円となる。残25枚が10pt順行で返済されても純損550円、合計−2,200円。実確定益Rが変わったため、残量の建値返済で必要な費用を賄えず、計算された確定益予算床が30ptへ上がる。現在10ptなら既に床を割り、部分約定と同じ原行に残量返済を要求する。床を引き上げても過去の不利約定を取り消せない。", "",
        "部分利確の未約定中に残25枚の建値床へ到達した例では、その残量も先に予約済みとなる。両注文が同じ後続原行で約定して玉がゼロになれば、その後で確定益床を起動する残玉はなく、cash_floor=nullは放置を意味しない。", "", "## 赤字群の重なる機構", "", "| 会計 | 観測機構 | 玉数 | その最終損益円 |", "|---|---|---:|---:|"]
    for key,groups2 in counts.items():
        for label,g in groups2.items():
            if g["玉数"]:
                lines.append(f"| {key} | {label} | {g['玉数']} | {g['最終損益円']:,} |")
    lines += ["", "各機構は重なるため件数・損益を合計しない。全42玉の各原行、初回益、確定R、床、残量要求の気配とfill、W/P/A会計をJSONに収録した。黒字対照群の分布も省略していない。", "", "## 改善余地と保証できないこと", "",
        "部分利確計画は将来の実確定益ではない。10ptの悪化余裕を計画しても、先に売る部分自体が10pt不利に約定すると予算は変わる。残量保護だけに悪化余裕を積む方式では、初回部分返済の約定リスクが残る。今後は初回返済数量・全量即時回収・約定前の既予約残量を含めて比較する必要がある。", "",
        "ただしG2全量追尾の総損益改善と旗後赤字増加は既に観測され、単純な全量継続では利益保全の要件が弱まった。入口の支持・否定構造で利益の伸びを分類し配分を切り替える案、初回返済に対する余裕を増やす案は別の固定試行で検証する。後から実現した損益を入口条件へ混ぜない。", "",
        "すべてを最初の益気配で全量返済要求しても、次の適格原行が同価格とは限らない。指値は約定しない可能性があり、逆指値も発動価格での決済を保証しない。現時点では含み益の赤字化を絶対に防ぐとはいえない。今回確定できたのは、観測した赤字群で最初の部分要求が即時に出て、予定益と実確定Rの差・床を跨ぐ原行変化・費用が残っていたことである。", ""]
    lines += ["## 入力と再現", "", f"事後診断コードSHA256：`{digest(Path(__file__))}`。", "",
        "保存した66場、固定80台帳、83の正式集計と原板監査を明示して実行する。原板監査は参照指紋を固定し、この診断が全原行の義務要求を再検査したとは扱わない。", "",
        "```powershell",
        "& work/venvs/technical-tree/Scripts/python.exe -B -X utf8 scripts/構造否定と利益配分/正益後赤字の診断.py " + " ".join(f'--{name} "{getattr(args,name.replace("-","_")).as_posix()}"' for name in ("input","manifest","result","raw-audit","out-json","out-md")),
        "```", "", "再現時は新規の出力名を指定し、既存正式結果を上書きしない。固定13の金融コード・条件は変更していない。", ""]
    with args.out_md.open("x",encoding="utf-8",newline="\n") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({"負玉":len(cases),"該当原板":len(raw),"原行点":sum(len(r['原行気配']) for r in raw.values()),"入力変更":0,"全群":{k:{n:{f:v[f] for f in ('玉数','損益円','予算不足玉')} for n,v in g.items()} for k,g in summary.items()}},ensure_ascii=False))


if __name__ == "__main__":
    main()
