"""66監査の順位と両方向資格を本物入力・fitなしで確認する。"""

from copy import deepcopy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(path: Path, name: str):
    """人工対象を固有名で読み旧大域値を変更しない。

    引数: path(Path)はPython、name(str)は固有名。
    返り値: ModuleTypeは読込結果。本物入力・木は読まない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load(HERE / "保存検証.py", "適格方向66監査人工対象")


def fixture() -> tuple:
    """固定三内部node・四葉の人工木と両側回収・60列を作る。

    引数: なし。
    返り値: tuple[dict,dict,dict]はmodel/calibration/vectors。fitを実行しない。
    """
    model = {"schema_version": 1, "policy": "U0", "model_id": "U0_人工", "feature_meta": A.R65.feature_metadata(60), "nodes": []}
    for index, feature, left, right in ((0, 0, 1, 2), (1, 25, 3, 4), (2, 19, 5, 6)):
        model["nodes"].append({"id": index, "feature": feature, "threshold": 0.0 if index == 0 else 0.5, "left": left, "right": right})
    for index in range(3, 7):
        model["nodes"].append({"id": index, "feature": -2, "threshold": -2.0, "left": -1, "right": -1,
            "score": 0.6 if index < 5 else 0.7, "data_absent": False, "direction_rows": 60,
            "unique_slots": 60, "days": 6, "sessions": 10, "path": []})
    vectors = {}
    for side in (1, -1):
        values = [0.0] * 60
        values[0] = float(side)
        values[18] = values[24] = 1
        values[19] = values[25] = 1
        values[21] = values[27] = -1
        vectors[str(side)] = values
        for valid in (0, 1):
            probe = list(values)
            probe[19 if side == 1 else 25] = valid
            leaf, path, _ = A.R65.walk(model, probe)
            model["nodes"][leaf]["path"] = path
    leaves = {str(index): {"leaf": index, "direction_rows": 60, "unique_slots": 60, "days": 6, "sessions": 10,
        "sum_yen": {"0": "600", "5": "120", "10": "-480"}, "mean_yen": {"0": 10.0, "5": 2.0, "10": -8.0},
        "support": True, "positive": True} for index in range(3, 7)}
    return model, {"model_id": model["model_id"], "leaves": leaves}, vectors


def self_test() -> dict:
    """順位・資格・未知・同点・反射を独立人工で確認する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。本物入力とfitは0。
    """
    source, _, _ = A.A.helpers()
    audit = source.Audit()
    selector = load(HERE / "選択.py", "適格方向66人工の実装比較")
    learner = load(HERE.parent / "現在状態と量価格/学習.py", "適格方向66人工の固定65純予測")
    model, cal, vectors = fixture()
    snapshot = deepcopy((model, cal, vectors))
    for policy in A.POLICIES:
        audit.check(policy + "通常最高側", A.qualified_sides(model, cal, vectors, policy)["side"], 1)
        audit.check(policy + "全prediction比較", selector.predict(model, cal, vectors, learner, policy), A.expected_prediction(model, cal, vectors, policy))
    # ----------------------------------------
    # 正回収のみの政策では、低い側が適格ならE0と反対方向も成立する。
    cal["leaves"]["6"].update(sum_yen={"0": "0", "5": "-60", "10": "-660"},
        mean_yen={"0": 0.0, "5": -1.0, "10": -11.0}, positive=False)
    audit.check("E0とE1の方向逆転", [A.qualified_sides(model, cal, vectors, policy)["side"] for policy in A.POLICIES], [1, -1])
    for policy in A.POLICIES:
        audit.check("逆転時の全prediction:" + policy, selector.predict(model, cal, vectors, learner, policy), A.expected_prediction(model, cal, vectors, policy))
    audit.check("旧65なら正回収失格で待ち", A.R65.expected_prediction(model, cal, vectors, "U1")["side"], 0)
    original = deepcopy(model)
    model["nodes"][6]["unique_slots"] = 59
    audit.check("旧支持不適格の次点採用", A.qualified_sides(model, cal, vectors, "E0")["side"], -1)
    audit.check("葉支持理由の全辞書", selector.predict(model, cal, vectors, learner, "E0"), A.expected_prediction(model, cal, vectors, "E0"))
    model = original
    # ----------------------------------------
    # 同点は片側だけ資格があっても解消しない。未知も既知側へ救済しない。
    model["nodes"][6]["score"] = .6
    for policy in A.POLICIES:
        audit.check("raw同点維持:" + policy, (A.qualified_sides(model, cal, vectors, policy)["side"], A.qualified_sides(model, cal, vectors, policy)["boundary"]), (0, "tie"))
        audit.check("同点で資格差があっても全辞書一致:" + policy, selector.predict(model, cal, vectors, learner, policy), A.expected_prediction(model, cal, vectors, policy))
    model["nodes"][6].update(score=None, direction_rows=0, data_absent=True)
    audit.check("片側未知は既知適格でも待ち", (A.qualified_sides(model, cal, vectors, "E0")["side"], A.qualified_sides(model, cal, vectors, "E0")["boundary"]), (0, "unknown"))
    audit.check("片側未知の全辞書", selector.predict(model, cal, vectors, learner, "E0"), A.expected_prediction(model, cal, vectors, "E0"))
    for policy in A.POLICIES:
        audit.check("両空未準備の全辞書:" + policy, selector.predict(model, cal, {'1': [], '-1': []}, learner, policy), A.expected_prediction(model, cal, {'1': [], '-1': []}, policy))
    model, cal, vectors = fixture()
    model["nodes"][6]["score"] = .2
    model["nodes"][4]["score"] = .1
    audit.check("両側score不足", A.qualified_sides(model, cal, vectors, "E0")["boundary"], "empty")
    audit.check("両側score不適格の全辞書", selector.predict(model, cal, vectors, learner, "E0"), A.expected_prediction(model, cal, vectors, "E0"))
    model["nodes"][6]["score"] = 1 / 3
    audit.check("score等号と支持60日6場10を採用", A.qualified_sides(model, cal, vectors, "E1")["side"], 1)
    audit.check("下限等号の全辞書", selector.predict(model, cal, vectors, learner, "E1"), A.expected_prediction(model, cal, vectors, "E1"))
    model, cal, vectors = fixture()
    cal["leaves"]["6"].update(direction_rows=59, unique_slots=59, support=False)
    audit.check("回収支持不足は下位を検査", A.qualified_sides(model, cal, vectors, "E0")["side"], -1)
    audit.check("回収支持不足の全辞書", selector.predict(model, cal, vectors, learner, "E0"), A.expected_prediction(model, cal, vectors, "E0"))
    for field, value in (("sum_yen", {"5": "0"}), ("sum_yen", {"5": "-0.0000000000000000001"})):
        changed = deepcopy(cal)
        changed["leaves"]["4"].update({field: value, "positive": False, "mean_yen": {"5": float(value["5"])}})
        audit.check("正回収strict:" + value["5"], A.qualified_sides(model, changed, vectors, "E1")["side"], 0)
        audit.check("正回収strict全辞書:" + value['5'], selector.predict(model, changed, vectors, learner, "E1"), A.expected_prediction(model, changed, vectors, "E1"))
    # ----------------------------------------
    # 本物の鏡像と別に、方向正規化後の二vector交換で売買選択を反射する。
    model, cal, vectors = fixture()
    for policy in A.POLICIES:
        left = A.qualified_sides(model, cal, vectors, policy)
        right = A.qualified_sides(model, cal, {"1": vectors["-1"], "-1": vectors["1"]}, policy)
        audit.check("売買vector交換:" + policy, right["side"], -left["side"])
        actual = selector.predict(model, cal, {'1': vectors['-1'], '-1': vectors['1']}, learner, policy)
        audit.check("反射の全辞書:" + policy, actual, A.expected_prediction(model, cal, {'1': vectors['-1'], '-1': vectors['1']}, policy))
    audit.check("人工基準素材の非改変", (model, cal, vectors), snapshot)
    # ----------------------------------------
    # 支持各軸・手法分類・回収未知を別に落とし、次点適格を確認する。
    for field, value in (("unique_slots", 59), ("days", 5), ("sessions", 9)):
        changed = deepcopy(model)
        changed['nodes'][6][field] = value
        audit.check("葉支持の各軸:" + field, selector.predict(changed, cal, vectors, learner, 'E0'), A.expected_prediction(changed, cal, vectors, 'E0'))
        audit.check("葉支持各軸の下位選択:" + field, A.qualified_sides(changed, cal, vectors, 'E0')['side'], -1)
    changed = deepcopy(model)
    changed['feature_meta'][19]['family'] = 'trend'
    for side in (1, -1):
        for valid in (0, 1):
            probe = list(vectors[str(side)])
            probe[19 if side == 1 else 25] = valid
            leaf, path, _ = A.R65.walk(changed, probe)
            changed['nodes'][leaf]['path'] = path
    audit.check("多family不足でも旧他方向が適格", A.qualified_sides(changed, cal, vectors, 'E0')['side'], -1)
    # selectorの旧learnerは正本metadata改竄を拒否するため、この人工分類は独立核だけを検査する。
    unknown_cal = deepcopy(cal)
    unknown_cal['leaves']['6'].update(direction_rows=0, unique_slots=0, days=0, sessions=0, support=False, positive=False,
        sum_yen={'0':'0','5':'0','10':'0'}, mean_yen={'0':None,'5':None,'10':None})
    for policy in A.POLICIES:
        audit.check("回収未知とscore未知の分離:" + policy, selector.predict(model, unknown_cal, vectors, learner, policy), A.expected_prediction(model, unknown_cal, vectors, policy))
    audit.check("回収未知理由を保持", A.expected_prediction(model, unknown_cal, vectors, 'E1')['rescue_reasons'], ['回収支持不足', '過去回収平均未知'])
    same = deepcopy(cal)
    same['leaves']['4'].update(sum_yen={'0':'0','5':'600000','10':'0'},mean_yen={'0':0.,'5':10000.,'10':0.})
    audit.check("回収平均で方向rankしない", A.expected_prediction(model, same, vectors, 'E1')['side'], 1)
    unchanged = deepcopy((model, cal, vectors))
    for policy in A.POLICIES:
        selector.predict(model, cal, vectors, learner, policy)
    audit.check("選択実装の入力非改変", (model, cal, vectors), unchanged)
    for args in ((3403, 3404, 0), (3404, 3403, 0), (3404, 3404, -1)):
        denied = False
        try:
            A.expected_counts(*args)
        except ValueError:
            denied = True
        audit.check("今回カウンタ拒否:" + str(args), denied, True)
    audit.check("今回三カウンタ", A.expected_counts(3404, 3404, 17),
        {"旧65特徴保存一致": 3404, "旧65純判断一致": 3404, "同一新規完結一致": 17})
    # ----------------------------------------
    # 保存純判断の集合比較は方向別ラベルと一建玉参加から独立に確認する。
    old = [{'slot_id':'甲','side':0,'ready':True,'reason':'過去回収平均非正WAIT','prediction':None},
        {'slot_id':'乙','side':1,'ready':True,'reason':'採用','prediction':None},
        {'slot_id':'丙','side':0,'ready':False,'reason':'未準備','prediction':None}]
    new = deepcopy(old)
    new[0].update(side=-1,reason='適格な他方向を採用',prediction={'rescued':True,'side':-1})
    expected = {'全予定枠':3,'特徴準備枠':2,'旧純採用':1,'新純採用':2,'共通同方向':1,
        '追加純候補':1,'除外純候補':0,'反対変更':0,'追加時旧理由':{'過去回収平均非正WAIT':1},'予測救済':1,'DI同値で拒否':0}
    audit.check("保存純候補比較の明示値", A.selection_statistics(new,old), expected)
    denied = False
    try:
        A.selection_statistics(new, old[:-1])
    except ValueError:
        denied = True
    audit.check("保存比較の枠欠落拒否", denied, True)
    guarded = deepcopy(new)
    guarded[0]['side'] = 0
    result = A.selection_statistics(guarded,old)
    audit.check("予測救済とDI拒否後純追加は別", (result['予測救済'],result['DI同値で拒否'],result['追加純候補']), (1,1,0))
    session = '2026-10-01_Day'
    sides = {'E0':[{'session':session,'slot_id':str(i),'side':s} for i,s in enumerate((1,1,-1,0,0))],
        'E1':[{'session':session,'slot_id':str(i),'side':s} for i,s in enumerate((1,-1,0,1,0))]}
    audit.check("二政策方向差の明示分母", A.direction_comparison(sides,'学習',source),
        {'全予定枠':5,'両採用同方向':1,'両採用逆方向':1,'E0のみ採用':1,'E1のみ採用':1})
    return {"人工成功": audit.bad == 0, "照合項目数": audit.count, "不一致数": audit.bad, "不一致": audit.examples,
        "本物fit": 0, "人工fit": 0, "実教師又はモデル読取": False, "特徴算術再計算": False, "市場戦略再生": False}


if __name__ == "__main__":
    import json
    payload = self_test()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload["人工成功"] else 1)
