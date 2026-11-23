"""寿命延長と到達後回復を、登録・技術発動・要求・仮約定で対応する。"""

import argparse
from collections import Counter, defaultdict
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT/"study/00035_CCI突破の到達後回復"
WORK = ROOT/"work/回復監視/00035"
HELPER = ROOT/"scripts/突破指値/対応診断.py"
POLICIES = ("E1", "E2", "E3")
CANDIDATES = tuple("3分_"+p+"_XF" for p in POLICIES)
PERIODS = ("学習", "条件選択", "後続検査")

spec = importlib.util.spec_from_file_location("回復35の保存統計補助", HELPER)
F = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = F
spec.loader.exec_module(F)
H, entry_summary, fill_key, strict_identity = F.H, F.entry_summary, F.fill_key, F.strict_identity


def source_key(source: dict) -> tuple:
    """正常BBO出典を秒だけでなく原行まで識別する。

    引数: source(dict)は保存snapshot。
    返り値: tupleは価格時計秒/原板行。同秒後行を同keyにしない。
    """
    return source["時計秒"], source["原板行"]


def analyze_entries(cases: list[dict]) -> dict:
    """三案の保存先着と回復観測を元登録で分解する。

    引数: cases(list[dict])は35最小case。旧C0イベントIDとE3回復観測を持つ。
    返り値: dictは照合/延長群/回復四群/未約定機会/時計価格。先着・監視を再生しない。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """保存された対応の不一致を残す。

        引数: name(str)は項目、actual/expected(object)は保存値。
        返り値: None。巨大な差を全件転記せず指紋へ置き換える。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            small = []
            for value in (actual, expected):
                text = H.json.dumps(value, ensure_ascii=False, default=str)
                small.append(value if len(text) <= 1500 else {"内容SHA256": H.canonical(value)})
            errors.append({"項目": name, "実値": small[0], "期待値": small[1]})

    maps = {p: {r["旧C0イベントID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    for policy in POLICIES:
        check(policy+":元登録一意", len(maps[policy]), sum(r["入口ID"] == "3分_"+policy for r in cases))
        check(policy+":元登録全集合", sorted(maps[policy]), sorted(maps["E1"]))
    check("三案イベント一意", len({r["イベントID"] for r in cases}), len(cases))
    for origin in maps["E1"].keys() & maps["E2"].keys() & maps["E3"].keys():
        old, limit, recovered = (maps[p][origin] for p in POLICIES)
        for other in (limit, recovered):
            for field in ("場", "期間", "side", "要求時計秒", "要求原板行", "atr", "新規指値価格", "指値根拠", "登録出典"):
                check(origin+":同登録:"+field, other[field], old[field])
        check(origin+":30秒約定は180秒約定のsubset", old["新規価格"] is None or limit["新規価格"] is not None, True)
        if old["新規価格"] is not None and limit["新規価格"] is not None:
            for field in ("ラベル", "理由", "新規価格", "新規時計秒", "新規原板行", "判定時計秒", "判定原板行", "判定気配", "最大順行pt", "最大逆行pt", "所要分"):
                check(origin+":30秒共通群先着同値:"+field, old[field], limit[field])
        elif limit["新規価格"] is not None:
            check(origin+":延長追加は30秒超", limit["新規時計秒"] > limit["要求時計秒"]+30, True)
        observation = recovered["回復観測"]
        touch, reaction = observation["初回到達出典"], observation["初回回復出典"]
        requested = observation["新規要求時計秒"] is not None
        check(origin+":E2約定とE3到達対応", touch is not None, limit["新規価格"] is not None)
        check(origin+":絶対失効固定", observation["絶対失効時計秒"], recovered["要求時計秒"]+180)
        for field in ("新規要求時計秒", "新規要求原板行"):
            check(origin+":新要求別列:"+field, recovered[field], observation[field])
        if touch is not None:
            check(origin+":到達はE2新規key", source_key(touch), fill_key(limit))
            check(origin+":到達はE2新規BBO価格", touch["ask"] if recovered["side"] == 1 else touch["bid"], limit["新規価格"])
        if reaction is not None:
            check(origin+":回復には先行到達", touch is not None, True)
            if touch is not None:
                check(origin+":回復strict後続key", source_key(reaction) > source_key(touch), True)
            mark = reaction["bid"] if recovered["side"] == 1 else reaction["ask"]
            check(origin+":返済側気配の水準回復", recovered["side"]*(mark-recovered["新規指値価格"]) > 0, True)
        else:
            check(origin+":無回復で発注しない", requested, False)
        check(origin+":時間可否と新要求", requested, reaction is not None and observation["回復時間可"] is True)
        if requested and reaction is not None:
            check(origin+":要求は回復key", (recovered["新規要求時計秒"], recovered["新規要求原板行"]), source_key(reaction))
            check(origin+":有効化まで絶対期限内", recovered["新規要求時計秒"]+1 <= observation["絶対失効時計秒"], True)
        if recovered["新規価格"] is not None:
            check(origin+":回復新規には市場要求", requested, True)
            if requested:
                check(origin+":市場新規は要求1秒後から", recovered["新規時計秒"] >= recovered["新規要求時計秒"]+1, True)
            check(origin+":市場新規も元期限内", recovered["新規時計秒"] <= observation["絶対失効時計秒"], True)

    # ----------------------------------------
    # 全登録と、結果後の価格発動・時間/市場約定選別を分ける。
    totals, stages, extension, recovery, missed, timing = [], [], [], [], [], []
    for period in PERIODS:
        own = {p: {k: r for k, r in maps[p].items() if r["期間"] == period} for p in POLICIES}
        old, limit, recovered = (own[p] for p in POLICIES)
        existing = [k for k in old if old[k]["新規価格"] is not None]
        added = [k for k in old if old[k]["新規価格"] is None and limit[k]["新規価格"] is not None]
        touched = [k for k in recovered if recovered[k]["回復観測"]["初回到達出典"] is not None]
        reacted = [k for k in recovered if recovered[k]["回復観測"]["初回回復出典"] is not None]
        requested = [k for k in reacted if recovered[k]["新規要求時計秒"] is not None]
        filled = [k for k in recovered if recovered[k]["新規価格"] is not None]
        stages.append({"期間": period, "共通元登録数": len(old), "30秒既存仮約定数": len(existing), "延長追加仮約定数": len(added),
            "E2仮約定数": sum(r["新規価格"] is not None for r in limit.values()), "E3到達数": len(touched),
            "E3回復技術発動数": len(reacted), "E3回復時間可数": sum(recovered[k]["回復観測"]["回復時間可"] is True for k in reacted),
            "E3新規要求数": len(requested), "E3仮約定数": len(filled)})
        for policy in POLICIES:
            totals.append({"期間": period, "入口": policy, **entry_summary(list(own[policy].values()))})
        for name, rows in (("E1全登録", list(old.values())), ("30秒共通群のE1", [old[k] for k in existing]),
                           ("30秒共通群のE2", [limit[k] for k in existing]), ("30秒超のE2追加群", [limit[k] for k in added]), ("E2全登録", list(limit.values()))):
            extension.append({"期間": period, "群": name, **entry_summary(rows)})
        for name, rows in (("A_E2全登録", list(limit.values())), ("B_回復技術群のE2", [limit[k] for k in reacted]),
                           ("C_E3仮約定群のE2", [limit[k] for k in filled]), ("D_同群のE3", [recovered[k] for k in filled])):
            recovery.append({"期間": period, "群": name, **entry_summary(rows)})
        missing = [k for k in recovered if recovered[k]["新規価格"] is None]
        classified = Counter()
        for k in missing:
            obs = recovered[k]["回復観測"]
            reason = "未到達" if obs["初回到達出典"] is None else "到達後未回復" if obs["初回回復出典"] is None else "回復時間不可・未発注" if recovered[k]["新規要求時計秒"] is None else "要求後未約定"
            classified[reason] += 1
        missed.append({"期間": period, "E3未約定登録数": len(missing), "段階別未約定数": dict(classified),
            "同登録E2の先着": entry_summary([limit[k] for k in missing]),
            "限界": "未約定群のE2仮250は機会であり、E3の実現損失/回収可能利益ではない"})
        timing.append({"期間": period, "回復技術発動数": len(reacted), "E3仮約定数": len(filled),
            "到達から回復秒": H.distribution([recovered[k]["回復観測"]["初回回復出典"]["時計秒"]-recovered[k]["回復観測"]["初回到達出典"]["時計秒"] for k in reacted]),
            "同秒後行の到達回復数": sum(recovered[k]["回復観測"]["初回回復出典"]["時計秒"] == recovered[k]["回復観測"]["初回到達出典"]["時計秒"] for k in reacted),
            "回復からE3新規秒": H.distribution([recovered[k]["新規時計秒"]-recovered[k]["回復観測"]["初回回復出典"]["時計秒"] for k in filled]),
            "E2からE3新規秒": H.distribution([recovered[k]["新規時計秒"]-limit[k]["新規時計秒"] for k in filled]),
            "実方向新規価格差pt_E3引くE2": H.distribution([recovered[k]["side"]*(recovered[k]["新規価格"]-limit[k]["新規価格"]) for k in filled]),
            "元水準からE3新規の実方向距離pt": H.distribution([recovered[k]["side"]*(recovered[k]["新規価格"]-recovered[k]["新規指値価格"]) for k in filled])})
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "モデル再計算": False, "先着再計算": False, "運用再生": False, "新閾値選別": False,
        "全登録の三入口先着": totals, "登録と価格発動と要求と仮約定": stages, "寿命延長の入口群": extension,
        "回復確認の四入口群": recovery, "E3未約定のE2機会": missed, "回復時計と価格": timing}


def analyze(cases: list[dict], details: list[dict], result: dict | None = None) -> dict:
    """純監視と実占有を分け、二段比較の全費用差を対応する。

    引数: cases/details(list[dict])は35保存case/運用詳細、result(dict|None)は正式集計又は人工時未指定。
    返り値: dictは純発動・実予約・実参加・回収/品質の小診断。モデルを再生しない。
    """
    output = analyze_entries(cases)
    checks, errors = output["照合項目数"], output["不一致"]

    def check(name: str, actual: object, expected: object) -> None:
        """対応相違を省略せず小さく保存する。

        引数: name(str)は項目、actual/expected(object)は保存値。
        返り値: None。大明細自体は内容指紋で示す。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            values = []
            for value in (actual, expected):
                text = H.json.dumps(value, ensure_ascii=False, default=str)
                values.append(value if len(text) <= 1500 else {"内容SHA256": H.canonical(value)})
            errors.append({"項目": name, "実値": values[0], "期待値": values[1]})

    case_map = {r["イベントID"]: r for r in cases}
    origins = {p: {r["旧C0イベントID"]: r for r in cases if r["入口ID"] == "3分_"+p} for p in POLICIES}
    trade_rows = [{**t, "候補ID": d["候補ID"]} for d in details for t in d["取引"]]
    check("場候補一意", len({(d["候補ID"], d["場"]) for d in details}), len(details))
    for trade in trade_rows:
        own = case_map[trade["入口イベントID"]]
        for field in ("新規時計秒", "新規原板行", "新規価格"):
            check("実新規と新case:"+field, trade[field], own[field])
        check("実登録ATRとcase", trade["入口ATR"], own["atr"])
        if trade["候補ID"] == "3分_E3_XF":
            obs = own["回復観測"]
            for field, expected in (("元登録時計秒", own["要求時計秒"]), ("元登録原板行", own["要求原板行"]),
                ("絶対失効時計秒", obs["絶対失効時計秒"]), ("監視水準価格", own["新規指値価格"]),
                ("監視登録出典", own["指値根拠"]), ("初回到達出典", obs["初回到達出典"]),
                ("初回回復出典", obs["初回回復出典"]), ("新規実効TTL秒", obs["絶対失効時計秒"]-own["新規要求時計秒"])):
                check("実回復出典:"+field, trade[field], expected)
        else:
            check("実指値とcase", trade["新規指値価格"], own["新規指値価格"])
            check("実指値根拠とcase", trade["指値根拠"], own["指値根拠"])

    # ----------------------------------------
    # 実監視の状態変化は全登録の仮監視へ加算せず、取扱文字列も別に残す。
    real_watch = []
    handling = {(d["候補ID"], s["イベントID"]): s["取扱"] for d in details for s in d["入口取扱"]}
    for detail in details:
        if detail["候補ID"] != "3分_E3_XF":
            check("E1/E2へ監視記録を足さない", "監視記録" not in detail, True)
            continue
        records, quality = detail["監視記録"], detail["品質"]
        actions = Counter(r["動作"] for r in records)
        for field, action in (("監視予約数", "監視受理"), ("監視初回到達数", "初回到達"),
                ("監視初回回復数", "初回回復"), ("監視終了数", "監視終了"), ("監視中抑止数", "監視中抑止")):
            check(detail["場"]+field, quality[field], actions[action])
        reasons = Counter(r["終了理由"] for r in records if r["動作"] == "監視終了")
        check(detail["場"]+"監視終了理由文字列対応", quality["監視終了理由数"], dict(reasons))
        for row in records:
            watch = row["監視"]
            if watch is None:
                check("監視変化には監視snapshot", watch is not None, True)
                continue
            original = case_map[watch["元登録イベントID"]]
            check("実監視は元登録key", (watch["元登録時計秒"], watch["元登録原板行"]), (original["要求時計秒"], original["要求原板行"]))
            check("実監視の元期限", watch["絶対失効時計秒"], original["要求時計秒"]+180)
            if row["動作"] in ("初回到達", "初回回復"):
                source = "初回到達出典" if row["動作"] == "初回到達" else "初回回復出典"
                check("実監視と同元仮出典:"+source, watch[source], original["回復観測"][source])
            if row["動作"] == "監視中抑止":
                check("監視抑止の被抑止IDが元監視と別", row["被抑止イベントID"] != watch["元登録イベントID"], True)
                check("被抑止IDも登録case", row["被抑止イベントID"] in case_map, True)
    for period in PERIODS:
        own = [d for d in details if d["候補ID"] == "3分_E3_XF" and d["品質"]["期間"] == period]
        records = [r for d in own for r in d["監視記録"]]
        actions = Counter(r["動作"] for r in records)
        real_watch.append({"期間": period, "原登録取扱数": sum(len(d["入口取扱"]) for d in own),
            "監視受理数": actions["監視受理"], "初回到達数": actions["初回到達"], "初回回復数": actions["初回回復"],
            "監視終了数": actions["監視終了"], "監視中抑止数": actions["監視中抑止"],
            "新規要求列あり数": sum(s["新規要求時計秒"] is not None for d in own for s in d["入口取扱"]),
            "実新規注文数": sum(o["区分"] == "新規" for d in own for o in d["注文"]),
            "実完結数": sum(len(d["取引"]) for d in own), "終了監視数": sum(d["品質"]["終了監視"] for d in own),
            "監視終了理由数": dict(Counter(r["終了理由"] for r in records if r["動作"] == "監視終了")),
            "入口取扱別": dict(Counter(s["取扱"] for d in own for s in d["入口取扱"]))})

    # ----------------------------------------
    # 同じ元登録の別約定と、同key/価格/ATR/Dの共通出口は別の対応にする。
    participation, episodes, recovery, qualities = [], [], [], []
    for period in PERIODS:
        trades = {cid: [t for t in trade_rows if t["候補ID"] == cid and t["期間"] == period] for cid in CANDIDATES}
        strict = {cid: {strict_identity(t): t for t in trades[cid]} for cid in CANDIDATES}
        by_origin = {cid: {case_map[t["入口イベントID"]]["旧C0イベントID"]: t for t in trades[cid]} for cid in CANDIDATES}
        for cid in CANDIDATES:
            check(cid+period+":実新規一意", len(strict[cid]), len(trades[cid]))
            check(cid+period+":実元登録一意", len(by_origin[cid]), len(trades[cid]))
        for name, left_id, right_id in (("寿命延長", CANDIDATES[0], CANDIDATES[1]), ("回復確認", CANDIDATES[1], CANDIDATES[2])):
            left, right = strict[left_id], strict[right_id]
            common, removed, added = left.keys() & right.keys(), left.keys()-right.keys(), right.keys()-left.keys()
            costs = []
            for fee in (0, 5, 10):
                field = f"追加滑り{fee}pt純損益円"
                same = sum(right[k][field]-left[k][field] for k in common)
                total = H.cash(trades[right_id], fee)-H.cash(trades[left_id], fee)
                removed_cash, added_cash = H.cash([left[k] for k in removed], fee), H.cash([right[k] for k in added], fee)
                check(period+name+str(fee)+":全費用差分解", total, same-removed_cash+added_cash)
                costs.append({"片道追加pt": fee, "総差円_右引く左": total, "同約定ATR共通出口差円": same,
                    "左のみ損益円": removed_cash, "右のみ損益円": added_cash})
            def counterpart(rows: list[dict], cid: str) -> dict:
                """片側取引の同元登録に対応する相手取扱をまとめる。

                引数: rows(list[dict])は取引、cid(str)は相手運用。
                返り値: dictは保存取扱の件数。予約抑止を別名へ置換しない。
                """
                policy = cid.split("_")[1]
                return dict(Counter(handling.get((cid, origins[policy][case_map[t["入口イベントID"]]["旧C0イベントID"]]["イベントID"]), "取扱記録なし") for t in rows))
            participation.append({"期間": period, "比較": name, "左": left_id, "右": right_id,
                "同約定ATR共通実新規数": len(common),
                "共通の元登録相違数": sum(case_map[left[k]["入口イベントID"]]["旧C0イベントID"] != case_map[right[k]["入口イベントID"]]["旧C0イベントID"] for k in common),
                "共通出口属性差数": sum(any(left[k][f] != right[k][f] for f in ("返済時計秒", "返済原板行", "返済価格", "返済理由")) for k in common),
                "左のみ": H.operation_summary([left[k] for k in removed]), "右のみ": H.operation_summary([right[k] for k in added]),
                "左のみの相手取扱": counterpart([left[k] for k in removed], right_id), "右のみの相手取扱": counterpart([right[k] for k in added], left_id), "費用別": costs})
            lm, rm = by_origin[left_id], by_origin[right_id]
            shared = lm.keys() & rm.keys()
            episodes.append({"期間": period, "比較": name, "左": left_id, "右": right_id,
                "両実参加元登録数": len(shared), "同約定ATR数": sum(strict_identity(lm[k]) == strict_identity(rm[k]) for k in shared),
                "左のみ元登録数": len(lm.keys()-rm.keys()), "右のみ元登録数": len(rm.keys()-lm.keys()),
                "新規価格差pt_右引く左": H.distribution([(1 if lm[k]["方向"] == "買い" else -1)*(rm[k]["新規価格"]-lm[k]["新規価格"]) for k in shared]),
                "新規待機秒_右引く左": H.distribution([rm[k]["新規時計秒"]-lm[k]["新規時計秒"] for k in shared]),
                "追加5pt純額差円_右引く左": H.distribution([rm[k]["追加滑り5pt純損益円"]-lm[k]["追加滑り5pt純損益円"] for k in shared])})
        for cid in CANDIDATES:
            rows = trades[cid]
            successes = [t for t in rows if case_map[t["入口イベントID"]]["ラベル"] == "順行先着"]
            armed = [t for t in rows if t["追尾起動"]]
            reds = [t for t in armed if t["起動後純赤字"]]
            zero = sum(t["返済価格"] == t["新規価格"] for t in reds)
            adverse = sum((1 if t["方向"] == "買い" else -1)*(t["返済価格"]-t["新規価格"]) < 0 for t in reds)
            check(cid+period+":起動後基準赤字内訳", len(reds), zero+adverse)
            recovery.append({"候補ID": cid, "期間": period, **H.operation_summary(rows),
                "対応仮250数": len(successes), "仮250判定前返済数": sum((t["返済時計秒"], t["返済原板行"]) < (case_map[t["入口イベントID"]]["判定時計秒"], case_map[t["入口イベントID"]]["判定原板行"]) for t in successes),
                "実保有MFE250数": sum(t["観測最大順行pt"] >= 250 for t in rows), "起動数": len(armed),
                "起動後基準赤字数": len(reds), "名目同値費用赤字数": zero, "不利返済赤字数": adverse})
    if result is not None:
        check("三運用順", [r["候補ID"] for r in result["結果"]], list(CANDIDATES))
        check("三入口順", [r["入口ID"] for r in result["入口評価"]], ["3分_"+p for p in POLICIES])
        for source in result["入口評価"]:
            for period in PERIODS:
                summary = entry_summary([r for r in cases if r["入口ID"] == source["入口ID"] and r["期間"] == period])
                for field in ("候補数", "約定候補数", "順行先着", "逆行先着", "期限未達", "観測不足", "未約定", "確認率"):
                    check(source["入口ID"]+period+field, source[period][field], summary[field])
        for candidate in result["結果"]:
            for period in PERIODS:
                op = candidate[period]["運用"]
                rows = [t for t in trade_rows if t["候補ID"] == candidate["候補ID"] and t["期間"] == period]
                check(candidate["候補ID"]+period+":完結数", op["完結取引数"], len(rows))
                for fee in (0, 5, 10):
                    check(candidate["候補ID"]+period+str(fee)+":会計合計", op[f"追加{fee}pt純損益円"], H.cash(rows, fee))
                qualities.append({"候補ID": candidate["候補ID"], "期間": period,
                    **{k: op[k] for k in ("品質注意場数", "未解消場数", "EOF期限未達場数")},
                    "観測純額円": {str(f): op[f"追加{f}pt純損益円"] for f in (0, 5, 10)},
                    "全体確定対象円": {str(f): op[f"追加{f}pt確定対象円"] for f in (0, 5, 10)}})
    output.update(全件一致=not errors, 照合項目数=checks, 不一致数=len(errors), 不一致=errors,
        実E3監視と新規要求=real_watch, 実参加比較=participation, 同元登録の実参加対応=episodes,
        候補別回収=recovery, 品質と確定額=qualities,
        限界=["全登録の独立仮監視と、実一予約/注文/建玉の占有を分ける。",
            "E1→E2は寿命延長、E2→E3は確認群/時間/市場約定選別と時計/価格を含む全方針差。",
            "厳密同約定key/価格/ATR/Dだけを共通出口比較とし、異約定同episodeを価格単独/出口単独効果にしない。",
            "監視終了理由は保存監視・品質の文字列対応で、ここで全気配から独立再生成した取消理由ではない。",
            "未約定群の別案仮250は取り逃した機会で、回収可能な利益とはしない。",
            "回復や実完結の群は結果後。新しい距離閾値や未来MFEで採否を作らない。"])
    return output


def compare_control(cases: list[dict], details: list[dict], trace: list[dict], control: dict,
                    old_cases: list[dict], old_details: list[dict], old_trace: list[dict]) -> dict:
    """同IDのE1を旧34全case/運用/追尾へ属性除外なしで接続する。

    引数: cases/details/trace(list[dict])は新保存物、control(dict)は主証明、old_cases/old_details/old_trace(list[dict])は旧34。
    返り値: dictは小型照合。識別子も置き換えず全dictを直接比較する。
    """
    checks, errors = 0, []

    def check(name: str, actual: object, expected: object) -> None:
        """全件差は小さな内容指紋で残す。

        引数: name(str)は項目、actual/expected(object)は保存値。
        返り値: None。不一致を丸めない。
        """
        nonlocal checks
        checks += 1
        if actual != expected:
            errors.append({"項目": name, "実値内容SHA256": H.canonical(actual), "期待値内容SHA256": H.canonical(expected)})

    new_case = {r["イベントID"]: r for r in cases if r["入口ID"] == "3分_E1"}
    old_case = {r["イベントID"]: r for r in old_cases if r["入口ID"] == "3分_E1"}
    check("E1旧全case集合", sorted(new_case), sorted(old_case))
    for key in new_case.keys() & old_case.keys():
        check("E1全case:"+key, new_case[key], old_case[key])
    new = {d["場"]: d for d in details if d["候補ID"] == CANDIDATES[0]}
    old = {d["場"]: d for d in old_details if d["候補ID"] == CANDIDATES[0]}
    nl, ol = defaultdict(list), defaultdict(list)
    for row in trace:
        if row["候補ID"] == CANDIDATES[0]:
            nl[row["場"]].append(row)
    for row in old_trace:
        if row["候補ID"] == CANDIDATES[0]:
            ol[row["場"]].append(row)
    proofs = {r["場"]: r for r in control["照合"]}
    check("E1旧全場集合", sorted(new), sorted(old))
    check("E1主対照全場集合", sorted(new), sorted(proofs))
    check("E1主対照成功", control["全件一致"], True)
    check("E1旧先着成功", control["旧先着全件同値"], True)
    check("E1主対照場数", control["場候補数"], len(new))
    for session in new.keys() & old.keys() & proofs.keys():
        check(session+":E1全ledger", new[session], old[session])
        check(session+":E1全trace", nl[session], ol[session])
        check(session+":主ledgerSHA", proofs[session]["旧識別子全運用内容SHA256"], H.canonical(new[session]))
        check(session+":主traceSHA", proofs[session]["旧識別子追尾内容SHA256"], H.canonical(nl[session]))
        check(session+":主ledger成功", proofs[session]["全運用同値"], True)
        check(session+":主trace成功", proofs[session]["全追尾同値"], True)
    return {"全件一致": not errors, "照合項目数": checks, "不一致数": len(errors), "不一致": errors,
        "全case数": len(new_case), "場候補数": len(new), "識別子変換": False, "属性除外": []}


def run(study: Path = STUDY, work: Path = WORK) -> dict:
    """正式結果完成後だけ保存物を読み、小型診断を出力する。

    引数: study/work(Path)は35正式/作業先。
    返り値: dictは診断。不一致は保存してから例外にする。
    """
    if not (study/"結果.json").is_file():
        raise ValueError("正式結果完成前に対応診断を実行しません")
    reference = H.read(study/"対照参照.json")
    shared = {Path(r["パス"]).name: ROOT/r["パス"] for r in reference["共有明細"]}
    for item in reference["共有明細"]:
        if H.sha(ROOT/item["パス"]) != item["圧縮SHA256参考"]:
            raise ValueError("旧34対照の保存版差")
    names = ("入口事例.jsonl.gz", "全運用詳細.jsonl.gz", "追尾.jsonl.gz")
    cases, details, trace = (H.read(work/n) for n in names)
    control = H.read(study/"E1対照同値.json")
    if control["対照参照SHA256"] != H.sha(study/"対照参照.json"):
        raise ValueError("E1対照の参照版差")
    output = analyze(cases, details, H.read(study/"結果.json"))
    comparison = compare_control(cases, details, trace, control, *(H.read(shared[n]) for n in names))
    output["E1旧34全属性対照"] = {k: v for k, v in comparison.items() if k not in ("全件一致", "不一致")}
    output["照合項目数"] += comparison["照合項目数"]
    output["不一致"] += comparison["不一致"]
    output["不一致数"] = len(output["不一致"])
    output["全件一致"] = not output["不一致"]
    output["全66場既使用"] = True
    paths = [Path(__file__), HELPER, *[study/n for n in ("条件.json", "固定.json", "結果.json", "入力台帳.json", "入口参照.json", "対照参照.json", "E1対照同値.json")],
        *[work/n for n in ("診断予定.json", *names)], *shared.values()]
    output["ファイルSHA256"] = {p.relative_to(ROOT).as_posix(): H.sha(p) for p in paths}
    output["入口参照SHA256"] = H.sha(study/"入口参照.json")
    output["対照参照SHA256"] = H.sha(study/"対照参照.json")
    (work/"対応診断.json").write_text(H.json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    if not output["全件一致"]:
        raise RuntimeError("保存物の対応に不一致")
    return output


def main() -> None:
    """正式保存物の後段診断だけを起動する。

    引数: なし。CLIは--study/--work。
    返り値: None。市場prepare/監視/先着/運用は再計算しない。
    """
    parser = argparse.ArgumentParser(description="CCI突破の寿命延長と到達後回復・保存対応診断")
    parser.add_argument("--study", type=Path, default=STUDY)
    parser.add_argument("--work", type=Path, default=WORK)
    args = parser.parse_args()
    output = run(args.study.resolve(), args.work.resolve())
    print(H.json.dumps({k: output[k] for k in ("全件一致", "照合項目数", "不一致数")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
