"""63の局面値・mask・枝別52列・教師射影・継承カウンタを人工で照合する。"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象を固有名で読み、旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。実教師・実モデルは開かない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "局面強弱保存監査の人工対象")


def numeric_session(count: int = 45, name: str = "人工場", begin: float = 1000,
                    mirrored: bool = False) -> dict:
    """公開完全15分足の人工入力を作る。

    引数: count(int)は足数、name(str)は場、begin(float)は起点、mirrored(bool)は価格鏡映。
    返り値: dictは固定49銀行形式。実価格・教師は読まない。
    """
    rows = []
    for i in range(count):
        close = 1000 + 2 * i + 3 * (i % 3)
        opening, high, low = close - 2, close + 4, close - 5
        if mirrored:
            opening, high, low, close = 3000-opening, 3000-low, 3000-high, 3000-close
        start = begin + 900 * i
        rows.append({"index": i, "minutes": 15, "start": start, "end": start+900,
            "confirm": start+901, "confirm_line": i, "publish": True, "missing": 0,
            "open": opening, "high": high, "low": low, "close": close})
    return {"session": name, "contract": ("人工限月",), "begin": begin,
        "end": begin+900*count, "frames3": [], "frames15": rows}


def extend_inputs(row: dict) -> tuple:
    """局面追加だけを検査する旧辞書と同時点の枠を作る。

    引数: row(dict)は人工数値15分足。
    返り値: tuple[dict,dict]はslotと旧46辞書。架空付随情報も保持させる。
    """
    slot = {"scheduled": row["end"], "time": row["confirm"], "line": row["confirm_line"],
        "upper": {"source": A.I49.source(row), "plus_di": row["plus_di"], "minus_di": row["minus_di"]}}
    previous = {"ready": True, "reason": "", "atr": 20.0,
        "vectors": {s: [0.0]*46 for s in ("1", "-1")}, "付随状態": {"保持": True}}
    return slot, previous


def numeric_checks(feature, audit) -> None:
    """BB別算、公開現前、未知旗、carry/resetと未来不変を人工照合する。

    引数: feature(ModuleType)は新Fの実装、audit(Audit)は照合記録。
    返り値: None。期待値は独立A算術と明示した母分散例。
    """
    audit.check("20本未満はBB未知", A.band_width([1.0]*19), None)
    audit.check("定幅は既知BB0", A.band_width([1.0]*20), 0.0)
    audit.check("平均2・母分散1のBB幅", A.band_width([1.0,3.0]*10), 4.0)
    scenarios = [[numeric_session()], [numeric_session(40), numeric_session(5,"次場",50000)],
        [numeric_session(mirrored=True)]]
    for key in ("missing", "publish", "high", "end"):
        item = numeric_session(70)
        if key == "missing": item["frames15"][30][key] = 1
        elif key == "publish": item["frames15"][30].update(publish=False,confirm=None,confirm_line=None)
        elif key == "high": item["frames15"][30][key] = 0
        else: item["frames15"][30][key] -= 1
        scenarios.append([item])
    contract = [numeric_session(40), numeric_session(5,"次限月",50000)]
    contract[1]["contract"] = ("別限月",)
    scenarios.append(contract)
    gap = numeric_session(45)
    gap["frames15"].pop(30)
    scenarios.append([gap])
    tail = [numeric_session(40), numeric_session(5,"尾後",50000)]
    tail[0]["end"] += 900
    scenarios.append(tail)
    for index, sessions in enumerate(scenarios):
        saved = deepcopy(sessions)
        independent = A.numeric_context(sessions)
        audit.check("15分全辞書・数量不使用:"+str(index), feature.build_context(sessions), independent)
        audit.check("数値入力非改変:"+str(index), sessions, saved)
        for rows in independent.values():
            for row in rows:
                if not row["valid"] or row["plus_di"] is None:
                    continue
                slot, old = extend_inputs(row)
                before = deepcopy((old,slot,rows))
                expected = A.expected_feature(old,slot,rows)
                audit.check("全公開足の追加54出典・値・mask", feature.extend(slot,old,rows), expected)
                audit.check("旧46射影を厳密保持", A.control_projection(expected), old)
                audit.check("売買の追加8同値", expected["vectors"]["1"][46:],expected["vectors"]["-1"][46:])
                audit.check("局面入力非改変",(old,slot,rows),before)
    full = A.numeric_context([numeric_session()])["人工場"]
    shorter = A.numeric_context([numeric_session(35)])["人工場"]
    audit.check("未来足追加で公開prefix不変",full[:35],shorter)
    slot,old = extend_inputs(full[-1])
    expected = A.expected_feature(old,slot,full)
    audit.check("現在同秒同line公開は可",feature.extend(slot,old,full),expected)
    slot["line"] -= 1
    rejected = False
    try: A.expected_feature(old,slot,full)
    except ValueError: rejected=True
    audit.check("現在同秒後行は拒否",rejected,True)
    slot,old = extend_inputs(full[-1])
    hidden = deepcopy(full)
    hidden[-2]["confirm"] = slot["time"]+1
    independent = A.expected_feature(old,slot,hidden)
    audit.check("未来前足を出典へ残さない",feature.extend(slot,old,hidden),independent)
    audit.check("前足未知のmask",independent["vectors"]["1"][50:],[1,0,1,0])
    audit.check("前足数値も未知へ",[independent["regime"][k] for k in ("previous_source","previous_adx","previous_bb_width")],[None]*3)
    steady = numeric_session()
    for row in steady["frames15"]:row.update(open=1000,high=1005,low=995,close=1000)
    zero_rows=A.numeric_context([steady])["人工場"]
    slot,old=extend_inputs(zero_rows[-1])
    audit.check("既知ADX0・幅0・差0は全mask1",A.expected_feature(old,slot,zero_rows)["vectors"]["1"][46:],[0.]*4+[1]*4)
    slot,old=extend_inputs(full[14])
    audit.check("旧DI準備でも追加未準備を保持",A.expected_feature(old,slot,full)["vectors"]["1"][46:],[0.]*8)
    first=A.numeric_context([numeric_session(40),numeric_session(5,"次場",50000)])["次場"]
    slot,old=extend_inputs(first[0])
    audit.check("場間現値carry・同場前値なし",A.expected_feature(old,slot,first)["vectors"]["1"][50:],[1,0,1,0])
    mirrored=A.numeric_context([numeric_session(mirrored=True)])["人工場"]
    slot,old=extend_inputs(mirrored[-1])
    audit.check("鏡映で無方向8値同値",A.expected_feature(old,slot,mirrored)["vectors"]["1"][46:],expected["vectors"]["1"][46:])
    old={"ready":False,"reason":"旧未準備","vectors":{"1":[],"-1":[]}}
    audit.check("旧未準備を救済しない",feature.extend({},old,[]),A.expected_feature(old,{},[]))


def artificial_rows(source) -> list[dict]:
    """20人工場の800方向をDI/対象kへ分け、反対側kを子分岐に使わせる。

    引数: source(ModuleType)は固定暦の純補助。
    返り値: list[dict]は全46教師。実相場・回収測定は使わない。
    """
    old = load(HERE.parent / "波の区間分離/保存検証人工.py", "局面強弱人工の固定60教師材料")
    rows = old.artificial_rows(source)
    for index, row in enumerate(rows):
        pair = index // 2
        d, k, other = int(row["side"] == 1), (pair // 20) % 2, (pair // 40) % 2
        t_flag, r_flag = (k, other) if d else (other, k)
        row["features"][0], row["features"][17] = 1. if d else -1., (pair // 80) % 2
        row["features"][18:30] = [3, t_flag, t_flag, .1, 0., 0., 4, r_flag, r_flag, .1, 0., 0.]
        row["features"][30:46] = [0.] * 16
        target = 2000 * other + 500 * row["features"][17] + row["side"] * 7.5
        row.update(pnl0=target + 100, pnl5=target, pnl10=target - 100)
    for row in rows:
        row["features"] += [0.5, 0.0, 1.0, 0.0, 1, 1, 1, 1]
    return rows


def self_test() -> dict:
    """紙上教師だけで枝別投影/未知と継承metadataの拒否境界を確認する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物fitは0。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    learner = load(HERE / "学習.py", "局面強弱人工の新学習")
    recovery = load(HERE.parent / "独立追尾回収/回収集計.py", "局面強弱人工の固定回収")
    feature = load(HERE / "特徴.py", "局面強弱人工の同46特徴")
    fixtures = load(HERE.parent / "価格経路の深さと速度/特徴の人工検査.py", "局面強弱人工の紙上SOURCE")
    audit.check("旧46＋8metadata", feature.FEATURES, A.feature_metadata())
    numeric_checks(feature, audit)
    entries, blocks, prepared = [], {}, {}
    for i in range(66):
        name,identity=f"人工{i:02d}",f"枠{i:02d}"
        entries.append({"session":name})
        blocks[name]={"slots":[{"slot_id":identity}]}
        prepared[identity]={"ready":i%2==0,"regime":{"adx_valid":i%4==0,
            "adx_change_valid":i%8==0,"bb_valid":True,"bb_change_valid":i>=20,
            "bb_width":0.0 if i%6==0 else 1.0}}
    audit.check("局面分布はslotを両方向二重計数しない",A.regime_coverage(entries,blocks,prepared)["全66場"],
        {"全枠":66,"準備枠":33,"未準備枠":33,"追加完全準備枠":6,
         "adx_valid":17,"adx_change_valid":9,"bb_valid":33,"bb_change_valid":23,"既知零幅枠":11})
    for changes in (fixtures.t_changes(), fixtures.r_changes(), {}):
        slot, frames = fixtures.fixture(changes, 24)
        base = A.A.expected_feature(slot, frames)
        prior30 = A.R58.expected_feature(base, slot, frames)
        prior38 = A.R59.expected_feature(prior30, slot, frames)
        expected = A.R60.expected_feature(prior38, slot, frames)
        audit.check("固定60独立全46辞書と固定shim", feature.OLD.extract(slot, frames), expected)
    rows = artificial_rows(source)
    evaluation = max(row["recovery_end_time"] for row in rows) + 3600
    used, training = A.recovery_training(rows, evaluation)
    audit.check("54canonicalと旧46六指紋維持", learner.prepare_rows(rows, evaluation), (used, training))
    model = learner.fit(rows, A.feature_metadata(), "J0", "J0_人工", evaluation)
    digest = hashlib.sha256((HERE / "学習.py").read_bytes()).hexdigest()
    A.check_model(model, used, training, A.feature_metadata(), "J0_人工", digest, audit)
    audit.check("四群に方向200行ずつ・枝内pair不要", {key: (part["direction_rows"], part["pair_unique"]) for key, part in model["training"]["partition"].items()},
        {"D0_K0": (200, 200), "D0_K1": (200, 200), "D1_K0": (200, 200), "D1_K1": (200, 200)})
    low = [n for n in model["nodes"][3:] if n["left"] != -1 and n["path"][0]["branch"] == "left"]
    high = [n for n in model["nodes"][3:] if n["left"] != -1 and n["path"][0]["branch"] == "right"]
    audit.check("低側のT旗は候補へ戻る", 20 in A.CHILD_COLUMNS["D0"], True)
    audit.check("高側のR旗は候補へ戻る", 26 in A.CHILD_COLUMNS["D1"], True)
    audit.check("固定DI/対応kだけを枝別除外", (all(n["feature"] not in (0, 26) for n in low), all(n["feature"] not in (0, 20) for n in high)), (True, True))
    audit.check("従来資格を緩和せず固定trend/priceが二系統", all(n["method_support"] for n in model["nodes"] if n["left"] == -1), True)
    prepared = {}
    for row in used:
        paths = prepared.setdefault(row["slot_id"], {"paths": {}})["paths"]
        paths[str(row["side"])] = {role: {"episode_id": role + row["slot_id"],
            "cancel": None if row["features"][index] else {"index": 1}, "r": {"index": 1}, "k": {"index": 2},
            "k_valid": bool(row["features"][index])} for role, index in (("T", 20), ("R", 26))}
    distribution = A.state_distribution(used, prepared)
    audit.check("方向枝と対象k経路を別記", {key: (v["方向枝"], v["対象経路"], v["k有効"], v["方向行"], v["unique枠"], v["日数"], v["場数"]) for key, v in distribution.items()},
        {"D0_K0": ("DI非正", "R", 0, 200, 200, 10, 20), "D0_K1": ("DI非正", "R", 1, 200, 200, 10, 20),
         "D1_K0": ("DI正", "T", 0, 200, 200, 10, 20), "D1_K1": ("DI正", "T", 1, 200, 200, 10, 20)})
    audit.check("k0を未登録へ置換しない", distribution["D0_K0"]["R"],
        {"形成あり": 200, "形成なし": 0, "取消あり": 200, "rあり": 200, "kあり": 200, "k有効": 0, "形成ID数": 200})
    audit.check("対応していない側も分布へ保持", distribution["D1_K1"]["R"]["k有効"], 100)
    measured = {(row["slot_id"], row["side"]): {"session": row["session"], "ready": True, "features": row["features"], "barrier": row,
        "status": "確定完結", "recovery_end_time": row["recovery_end_time"],
        "operation": {"closed": [{f"pnl{fee}": float(Decimal(row[f"pnl{fee}"])) for fee in (0, 5, 10)}]}} for row in used}
    calibration = A.expected_calibration(model, measured, evaluation)
    audit.check("枝別52子の葉回収を独立結合", recovery.aggregate(model, measured, evaluation, learner), calibration)
    for index in range(0, 100, 2):
        vectors = {"1": used[index]["features"], "-1": used[index + 1]["features"]}
        audit.check("両方向全予測", learner.predict(model, vectors), A.predict(model, vectors))
        for policy, mapped in (("J0", "C0"), ("J1", "R0")):
            audit.check("障壁最高側/回収後段/次点救済なし", recovery.predict(model, calibration, vectors, learner, mapped), A.expected_prediction(model, calibration, vectors, policy))
    # ----------------------------------------
    # 極小正DIのfloat32零化は低枝Rを選ぶが、rawによる運用roleを反転へ書き換えない。
    tiny = deepcopy(used[0]["features"])
    tiny[0] = 1e-50
    audit.check("微小正DIはfloat32で非正枝", (A.float32(tiny)[0], A.group_key(tiny)), (0., "D0_K" + str(int(tiny[26]))))
    audit.check("raw順行と低DI枝の例外を許容", (tiny[0] > 0, A.group_key(tiny).startswith("D0")), (True, True))
    # ----------------------------------------
    # 空の正DI枝にもT固定nodeと未知二葉を残す。
    empty_rows = deepcopy(rows)
    for row in empty_rows:
        row["features"][0] = -1.
    empty_used, empty_training = A.recovery_training(empty_rows, evaluation)
    empty = learner.fit(empty_rows, A.feature_metadata(), "J0", "J0_空人工", evaluation)
    A.check_model(empty, empty_used, empty_training, A.feature_metadata(), "J0_空人工", digest, audit)
    vectors = {"1": deepcopy(empty_used[0]["features"]), "-1": deepcopy(empty_used[1]["features"])}
    vectors["1"][0] = 1.
    audit.check("片側未知全予測", learner.predict(empty, vectors), A.predict(empty, vectors))
    audit.check("未知を0率で救済しない", A.predict(empty, vectors)["reason"], "未学習枝WAIT")
    # ----------------------------------------
    # 旧prefixを各固定群内で一定にし、追加値だけに目的値差がある独立人工を作る。
    extra_rows = deepcopy(rows)
    for index,row in enumerate(extra_rows):
        old_values=row["features"][:46]
        d,k=int(old_values[0]>0),int(old_values[20 if old_values[0]>0 else 26])
        values=[0.0]*46
        values[0]=1.0 if d else -1.0
        t,r=(k,0) if d else (0,k)
        values[18:30]=[3,t,t,.1,0.,0.,4,r,r,.1,0.,0.]
        x=(index//2%20)/20
        row["features"]=values+[x,0.,1.,0.,1,1,1,1]
        target=x*4000-1000
        row.update(pnl0=target+100,pnl5=target,pnl10=target-100)
    extra_used,extra_training=A.recovery_training(extra_rows,evaluation)
    extra_model=learner.fit(extra_rows,A.feature_metadata(),"J0","J0_追加値人工",evaluation)
    A.check_model(extra_model,extra_used,extra_training,A.feature_metadata(),"J0_追加値人工",digest,audit)
    audit.check("旧群内一定・追加ADX値を実際に分岐",any(n["feature"]==46 for n in extra_model["nodes"] if n["id"]>=3),True)
    for index in range(0,100,2):
        pair={"1":extra_used[index]["features"],"-1":extra_used[index+1]["features"]}
        audit.check("追加列を通るJSON予測",learner.predict(extra_model,pair),A.predict(extra_model,pair))
    invalid=deepcopy(extra_used[0]["features"])
    invalid[50]=0
    invalid[46]=0.5
    denied=False
    try:A.float32(invalid)
    except ValueError:denied=True
    audit.check("未知maskへ非零値を隠さない",denied,True)
    invalid=deepcopy(extra_used[0]["features"])
    invalid[50]=True
    denied=False
    try:A.float32(invalid)
    except ValueError:denied=True
    audit.check("boolを有効maskへ混ぜない",denied,True)
    # ----------------------------------------
    # 前巡の六キー漏れと、初回/補足経緯を人工で固定してから正式へ進む。
    inherited = {"測定特徴方向一致": 4884, "旧評価特徴完全一致": 3404, "旧18特徴完全一致": 2442,
        "旧38特徴保存一致": 3404, "旧46特徴保存一致": 3404, "同一新規完結一致": 240}
    audit.check("六カウンタ＋追加二キー", A.expected_counts(inherited, 3404, 100), {**inherited, "同一新規完結一致": 100, "旧46射影一致": 2442, "旧62特徴保存一致": 3404})
    missing = deepcopy(inherited)
    missing.pop("旧38特徴保存一致")
    denied = False
    try:
        A.expected_counts(missing, 3404, 100)
    except ValueError:
        denied = True
    audit.check("旧38キー漏れを人工で拒否", denied, True)
    prior = {"全件一致": True, "不一致数": 0, "照合項目数": 127119,
        "初回監査": {"全件一致": False, "照合項目数": 119952, "不一致数": 1, "他の初回成功項目数": 119951, "パス": "initial.json", "SHA256": "0" * 64},
        "限定補足": {"元不一致唯一": True, "元不一致数": 1, "補足解消数": 1, "残不一致数": 0, "旧60旧38保存カウンタ": 3404,
            "同46保存全辞書実数": 3404, "同38射影実数": 3404, "追加照合項目数": 7167, "初回参照SHA不変": True,
            "固定A変更": False, "主結果変更": False, "原監査再実行": False, "市場再生": False, "fit": False,
            "補足コード": {"パス": "supplement.py", "SHA256": "1" * 64}}}
    audit.check("旧61初回/補足二出典を保持", A.prior_supplement(prior), [("initial.json", "0" * 64), ("supplement.py", "1" * 64)])
    wrong = deepcopy(prior)
    wrong["限定補足"]["残不一致数"] = 1
    denied = False
    try:
        A.prior_supplement(wrong)
    except ValueError:
        denied = True
    audit.check("旧61未解消を成功へ昇格しない", denied, True)
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "人工fitAPI回数": 3, "人工回帰器fit数": sum(part["fit_performed"] for m in (model, empty,extra_model) for part in m["training"]["partition"].values()),
        "本物fit": 0, "実教師又はモデル読取": False, "市場戦略再生": False, "新主処理import": False}


if __name__ == "__main__":
    proof = self_test()
    print(json.dumps(proof, ensure_ascii=False, indent=2))
    raise SystemExit(0 if proof["人工成功"] else 1)
