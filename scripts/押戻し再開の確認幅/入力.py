"""固定76の親波を継承し、T未確認枝だけを最初の終値反応へ変える。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OLD_PATH = ROOT / "scripts/局所波の出生と切替/入力.py"
OLD_SHA256 = "afd040f6a1f0be721b26bfcf0634b8885b92226c91bcb66e5a42e5fff90a3664"
if hashlib.sha256(OLD_PATH.read_bytes()).hexdigest() != OLD_SHA256:
    raise ValueError("77が継承する固定76入力のSHA不一致")
SPEC = importlib.util.spec_from_file_location("確認幅77の固定76親波", OLD_PATH)
OLD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OLD)
SOURCE_FIELDS, SLOT_FIELDS, VALUE_FIELDS = OLD.SOURCE_FIELDS, OLD.SLOT_FIELDS, OLD.VALUE_FIELDS
POLICIES, LEGACY = ("E0", "E1"), {"E0": "L0", "E1": "L1"}
CONFIRMATION_FIELDS = ("confirmation_rule", "confirmation_previous", "confirmation_line")
finite, exact, canonical = OLD.finite, OLD.exact, OLD.canonical
RULES = deepcopy(OLD.RULES)
RULES.update({"T": "最初逆終値r後の別足でs(Ci-Cprevious)>0かつs(Ci-premise)>0の最初k。固定r端は診断",
    "確認出典": "Tだけrule=終値反応/previous=直前SOURCE13/line=そのclose。未確認previous/lineはnull、k後固定",
    "政策": "同じ親履歴のE0はT限定/E1はT-R。旧76helpers呼出し時だけ局所コピーをL0/L1へ対応",
    "継承": "固定76MachineのT-r済k未確認枝だけ変更。元globals/ソース変更なし、Rの全辞書は同値"})


# ----------------------------------------
class Machine(OLD.Machine):
    """親・出生・Rを継承し、Tの確認だけ終値反応へ差し替える。"""

    def formation(self, parent: dict, kind: str, row: dict | None = None) -> dict:
        """元形成を作り、Tだけに確認規約と未確認出典を付す。

        引数: parent(dict)は親、kind(str)はT/R、row(dict|None)はRのf。
        返り値: dictは元の親・形成一覧と参照を共有する形成。Rは追加項目なし。
        """
        result = super().formation(parent, kind, row)
        if kind == "T":
            result.update(confirmation_rule="終値反応", confirmation_previous=None, confirmation_line=None)
        return result

    def step_parent(self, row: dict) -> None:
        """Tのr済・k未確認・origin維持の枝だけ新確認を適用する。

        引数: row(dict)はstepが品質・隣接・期限を検査した公開SOURCE13。
        返り値: None。他の出生・r・f・R・取消は元76へ委譲する。
        """
        parent = self.parent
        t = parent["T"]
        changed_branch = (parent["f"] is None and parent["R"] is None and t["cancel"] is None
                          and t["r"] is not None and t["k"] is None)
        side, close = parent["direction"], exact(row["close"])
        if not changed_branch or side * (close - exact(parent["origin"])) <= 0:
            super().step_parent(row)
            return
        parent["current_tip"] = OLD.extreme([parent["current_tip"]["source"], row], side)
        if self.previous is None:
            raise ValueError("77のT確認直前SOURCEがない")
        if side * (close - exact(self.previous["close"])) > 0 and side * (close - exact(t["premise_line"])) > 0:
            previous = {key: deepcopy(self.previous[key]) for key in SOURCE_FIELDS}
            t.update(k=deepcopy(row), active=True, status="有効", confirmation_previous=previous,
                     confirmation_line=previous["close"])
            parent["status"] = "T有効"
            self.trace(parent, OLD.event_ref(row), "T再開k")


def policy_choice(candidates: list[dict], qualifications: dict, policy: str, ready: bool, reason: str) -> dict:
    """元の資格選択へ政策名を引数だけで対応させる。

    引数: candidates/qualificationsは現在形成/資格、policy(str)はE0/E1、ready/reasonは準備。
    返り値: dictは純選択。旧moduleのPOLICIESや関数globalsを書き換えない。
    """
    if policy not in LEGACY:
        raise ValueError("77政策はE0/E1")
    return OLD.policy_choice(candidates, qualifications, LEGACY[policy], ready, reason)


def extract(slot: dict, history: list[dict], visible_birth_rows: list[dict], quote: dict | None, band: dict | None) -> dict:
    """固定76の検査と新Machineから政策共通観測を純再構成する。

    引数: slot(dict)は旧73判断、history(list)は全当場SOURCE、visible_birth_rows(list)は可視ATR、quote/bandは当時気配/場所診断。
    返り値: dictはselected_by_policy E0/E1を持つ共通観測。価格・教師・市場ファイルを開かない。
    """
    OLD.SHARED.clock(slot)
    feature = slot.get("feature")
    if not isinstance(feature, dict) or type(feature.get("ready")) is not bool or feature["ready"] is not slot["ready"]:
        raise ValueError("旧特徴と純判断の準備差")
    result = {"base_ready": feature["ready"], "ready": False, "reason": "旧73特徴が未準備", "source_count": 0,
        "source_sha256": None, "atr_source_sha256": None, "history": {"current": None, "resets": [], "birth_buffer": [],
            "preparation": {"ready": False, "count": 0, "required": 3, "reason": "旧73特徴が未準備"}, "rejected_births": []},
        "parents": [], "formations": [], "candidates": [], "qualifications": {}, "selected_by_policy": {},
        "band": None, "location": None, "side": 0, "role": "待機", "selected": None}
    if not feature["ready"]:
        for policy in POLICIES:
            result["selected_by_policy"][policy] = policy_choice([], {}, policy, False, result["reason"])
        return result
    if (not finite(slot.get("atr")) or slot["atr"] <= 0 or not finite(slot.get("D")) or slot["D"] <= 0
            or feature.get("atr") != slot["atr"] or feature.get("D") != slot["D"]):
        raise ValueError("旧現在ATR/Dの不整合")
    prefix = OLD.SHARED.visible_prefix(slot, history, feature)
    atr_rows, values = OLD.bind_atr(prefix, visible_birth_rows), OLD.SHARED.values_for(feature)
    machine = Machine(slot["session"])
    for row, atr in zip(prefix, atr_rows):
        machine.step(row, atr)
    machine.expire(OLD.event_ref(None, slot))
    normal = OLD.SHARED.quote_view(slot, quote)
    ready, parent = machine.prepared and normal, machine.parent
    reason = "出生準備待ち" if not machine.prepared else "現在BBO又はLastの観測不足" if not normal else parent["status"] if parent else "出生待ち"
    if not parent and machine.parents and machine.parents[-1]["terminal"] is not None:
        reason = machine.parents[-1]["terminal"]["reason"] if not machine.buffer else "出生待ち"
    if (not parent and not machine.buffer and machine.rejected_births
            and machine.rejected_births[-1]["b"]["index"] == prefix[-1]["index"]):
        reason = "出生公開が寿命後"
    if not machine.prepared:
        reason = "出生準備待ち"
    elif not normal:
        reason = "現在BBO又はLastの観測不足"
    candidates = [deepcopy(f) for f in machine.formations if f["active"]]
    if len(candidates) > 1:
        raise ValueError("一親でT/R同時activeの矛盾")
    for candidate in candidates:
        candidate["k_age_seconds"] = slot["time"] - candidate["k"]["confirm"]
        candidate["k_end_age_seconds"] = slot["scheduled"] - candidate["k"]["end"]
        candidate["tip_distance"] = float(candidate["side"] * (exact(parent["tip_before_r"]["price"]) - exact(candidate["k"]["close"])))
        if normal:
            result["qualifications"][candidate["id"]] = OLD.qualification(candidate, values[str(candidate["side"])], quote)
    if candidates and normal and not any(q["qualified"] for q in result["qualifications"].values()):
        reason = "局所波の現在複合条件不適格"
    band_view, location = OLD.location_for(slot, band, quote, normal)
    result.update(ready=ready, reason=reason, source_count=len(prefix), source_sha256=OLD.digest(prefix, True), atr_source_sha256=OLD.digest(atr_rows),
        history={"current": deepcopy(prefix[-1]), "resets": machine.resets, "birth_buffer": [OLD.event_ref(r) for r in machine.buffer],
            "preparation": {"ready": machine.prepared, "count": len(machine.buffer), "required": 3,
                "reason": "出生入力準備済み" if machine.prepared else "出生準備待ち"}, "rejected_births": machine.rejected_births},
        parents=machine.parents, formations=machine.formations, candidates=candidates, band=band_view, location=location)
    for policy in POLICIES:
        policy_reason = "R形成はE0で採用対象外" if policy == "E0" and candidates and candidates[0]["kind"] == "R" and ready else reason
        result["selected_by_policy"][policy] = policy_choice(candidates, result["qualifications"], policy, ready, policy_reason)
    result.update({key: deepcopy(result["selected_by_policy"]["E1"][key]) for key in ("side", "role", "selected", "reason")})
    return result


def choose(slot: dict, observation: dict, policy: str) -> dict:
    """旧純射影を局所コピーで再用し、T採用だけ確認出典を追加する。

    引数: slot/observation(dict)は元判断/共通観測、policy(str)はE0/E1。
    返り値: dictは純10と由来。R/WAITは新確認fieldsを持たず、元引数を変更しない。
    """
    if policy not in LEGACY:
        raise ValueError("77政策はE0/E1")
    local = deepcopy(observation)
    local["selected_by_policy"] = {LEGACY[name]: deepcopy(value) for name, value in observation["selected_by_policy"].items()}
    result = OLD.choose(slot, local, LEGACY[policy])
    result["policy"] = policy
    if result["formation"] == "T":
        selected = observation["selected_by_policy"][policy]["selected"]
        result.update({key: deepcopy(selected[key]) for key in CONFIRMATION_FIELDS})
    return result


# ----------------------------------------
def self_test() -> dict:
    """架空足だけで新確認・不変R・時計・鏡像・永久取消を検査する。

    引数: なし。
    返り値: dictは成功/テスト件数/照合項目数/不一致数。市場・教師・fitは0。
    """
    tests = checks = 0
    old_class, old_policies = OLD.Machine, tuple(OLD.POLICIES)

    def check(actual: object, expected: object) -> None:
        """型を含む固定JSONで人工値を比べる。

        引数: actual/expected(object)は実値/期待。
        返り値: None。差はAssertionError。
        """
        nonlocal checks
        checks += 1
        assert canonical(actual, True) == canonical(expected, True), (actual, expected)

    def observe(case: tuple) -> dict:
        """入力不変・共通親投影・全R・政策包含を一式確認する。

        引数: case(tuple)は人工extract5引数。
        返り値: dictは77共通観測。
        """
        before = canonical(case, True)
        new, old = extract(*case), OLD.extract(*case)
        check(canonical(case, True), before)
        check([{k: v for k, v in p.items() if k not in ("T", "status", "trace")} for p in new["parents"]],
              [{k: v for k, v in p.items() if k not in ("T", "status", "trace")} for p in old["parents"]])
        check([f for f in new["formations"] if f["kind"] == "R"], [f for f in old["formations"] if f["kind"] == "R"])
        for parent in new["parents"]:
            t = parent["T"]
            check(t, next(f for f in new["formations"] if f["id"] == t["id"]))
            check(t["confirmation_rule"], "終値反応")
            if t["k"] is None:
                check((t["confirmation_previous"], t["confirmation_line"]), (None, None))
            else:
                check(t["confirmation_previous"]["index"], t["k"]["index"] - 1)
                check(t["confirmation_line"], t["confirmation_previous"]["close"])
        a, b = choose(case[0], new, "E0"), choose(case[0], new, "E1")
        if a["side"]:
            check({k: a[k] for k in SLOT_FIELDS}, {k: b[k] for k in SLOT_FIELDS})
            check(a["formation"], "T")
            check({k: a[k] for k in CONFIRMATION_FIELDS}, {k: new["selected"][k] for k in CONFIRMATION_FIELDS})
        if b["formation"] == "R":
            reference = OLD.choose(case[0], old, "L1")
            check({k: v for k, v in b.items() if k != "policy"}, {k: v for k, v in reference.items() if k != "policy"})
            check(any(k in b for k in CONFIRMATION_FIELDS), False)
            check(new["candidates"], old["candidates"])
        return new

    base = OLD.synthetic([100, 103, 106, 104, 105])
    got = observe(base)
    check((got["selected"]["k"]["index"], got["selected"]["trigger_line"], got["selected"]["confirmation_line"]), (4, 105, 104))
    check(OLD.extract(*base)["selected"], None)
    tests += 1
    for closes in ([100, 103, 106, 104, 104], [100, 103, 106, 104, 102, 103]):
        got = observe(OLD.synthetic(closes))
        check(got["parents"][0]["T"]["k"], None)
    got = observe(OLD.synthetic([100, 103, 106, 104, 102, 103, 104]))
    check(got["selected"]["k"]["index"], 6)
    tests += 1
    lost = OLD.synthetic([100, 103, 106, 104, 105, 103, 107])
    got = observe(lost)
    check((got["parents"][0]["T"]["k"]["index"], got["parents"][0]["T"]["cancel"]["index"], got["selected"]), (4, 5, None))
    check(OLD.extract(*lost)["selected"]["k"]["index"], 6)
    check(got["parents"][0]["T"]["confirmation_line"], 104)
    tests += 1
    for closes in ([100, 103, 106, 104, 98, 100], [100, 103, 106, 98, 96], [100, 103, 106, 104, 105, 103, 98, 96]):
        observe(OLD.synthetic(closes, -1, -1))
    tests += 1
    for case in (base, lost, OLD.synthetic([100, 103, 106, 98, 96], -1, -1)):
        a, b = observe(case), observe(OLD.reflected(case))
        check((b["side"], b["role"], b["ready"]), (-a["side"], a["role"], a["ready"]))
    tests += 1
    for delay, selected in ((1620, True), (1621, False)):
        case = deepcopy(base)
        end = case[1][2]["end"] + delay
        case[1][-1]["confirm"] = end
        case[0]["time"] = end
        OLD.refresh(case)
        check(observe(case)["selected"] is not None, selected)
    tests += 1
    future = deepcopy(base)
    suffix = deepcopy(future[1][-1])
    suffix.update(index=5, start=suffix["end"], end=suffix["end"] + 180, confirm=None, high=float("nan"))
    future[1].append(suffix)
    check(observe(future), extract(*base))
    hidden = deepcopy(base)
    hidden[0]["time"] = hidden[1][-1]["confirm"]
    hidden[0]["line"] = hidden[1][-1]["confirm_line"] - 1
    hidden[0]["feature"]["base"]["base"]["sources"]["current"] = deepcopy(hidden[1][-2])
    hidden[2].pop()
    hidden[3]["line"] = hidden[0]["line"]
    hidden[3]["now"] = hidden[0]["time"]
    check(observe(hidden)["parents"][0]["T"]["k"], None)
    tests += 1
    longer = observe(OLD.synthetic([100, 103, 106, 104, 105, 106, 107]))
    check(longer["parents"][0]["T"]["confirmation_previous"], base[1][3])
    unknown = deepcopy(base)
    unknown[2][3].update(atr=None, ready=False, reason="出生ATR未準備")
    check(observe(unknown)["ready"], False)
    before = hashlib.sha256(OLD_PATH.read_bytes()).hexdigest()
    check(before, OLD_SHA256)
    check((OLD.Machine is old_class, tuple(OLD.POLICIES)), (True, old_policies))
    tests += 1
    return {"成功": True, "テスト件数": tests, "照合項目数": checks, "不一致数": 0,
            "旧76コードSHA256": OLD_SHA256, "本物入力読取": False, "fit": 0, "市場再生": False, "新計測": 0}


if __name__ == "__main__":
    print(json.dumps(self_test(), ensure_ascii=False, allow_nan=False))
