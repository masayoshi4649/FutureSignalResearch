"""固定24の価格状態を保ち、単足MACDと公開SAR方向持続を対照する。"""

from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("SAR持続の固定24価格状態", ROOT/"scripts/終値切替/入口.py")
BASE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BASE
SPEC.loader.exec_module(BASE)
OLD_CONFIG = json.loads((ROOT/"study/00024_終値の内復帰と外回復による順行反転/条件.json").read_text(encoding="utf-8"))
POLICIES = ("Q0", "Q1")
finite = BASE.finite
RULES = {"初期AF": 0.02, "増分AF": 0.02, "上限AF": 0.2,
    "初期方向": "連続二本close差strict正買/負売、同値は未確定で次連続ペア待ち",
    "時間足分": 3, "比較本数": 2, "出口使用": False,
    "初期表示": "買min(前low,現low)/売max(前high,現high)、EP現high/low、AF初期",
    "当足線": "前足nextを当足有効線、買low<線/売high>線で先に反転、等号非反転",
    "非反転": "当足線を前2low以下/前2high以上へclamp、その後EPstrict更新時AF増分上限",
    "反転": "新買min(旧EP,現low)/新売max(旧EP,現high)、EP現、AF初期",
    "次線": "表示+AF*(EP-表示)、next自体clampなし",
    "公開": "完全幅末尾NPは銀行のみ更新carry、当足/局所前足の公開条件へ使わない",
    "reset": "欠枠/不正/尾部完全欠枠/限月変更、同限月場間carry",
    "照合": "原OHLC別実装、人工上下反射/seed同値/strict境界/AF上限/NP/欠枠/carry"}


def validate_config(config: dict) -> None:
    """二案と固定24から継承する実数値を検査する。

    引数: config(dict)は25条件。
    返り値: None。不一致は例外。記述用設定だけを変えて実装へ反映しないことを防ぐ。
    """
    if config["時間足分"] != [3] or config["戦略"] != list(POLICIES):
        raise ValueError("固定3分・Q0/Q1だけ")
    inherited = ("対象", "全65場既使用", "運用", "必須追尾", "発動条件", "指標", "局面改訂", "逆行pt", "順行pt",
        "残り時間下限分", "確認遅延上限秒", "入口支持", "費用支持", "目標確認率", "間引き必要件数", "分割", "出口", "終値切替")
    if any(config.get(k) != OLD_CONFIG.get(k) for k in inherited):
        raise ValueError("固定24の実数値と設定表示が不一致")
    if config["SAR"] != RULES:
        raise ValueError("固定SAR数値と設定表示が不一致")


def classify(higher: list[dict], session: str, config: dict) -> tuple[list[dict], dict]:
    """固定24の15分準備をそのまま読み取り再用する。

    引数: higher(list[dict])は15足、session(str)は場、config(dict)は25条件。
    返り値: tuple[list[dict],dict]は固定24の分類と品質。値によるQ選別は行わない。
    """
    validate_config(config)
    return BASE.classify(higher, session, OLD_CONFIG)


def context_with_sar(old: dict, current: dict | None, previous: dict | None) -> dict:
    """旧M24と公開現前SARの数値準備を分けて保存する。

    引数: old(dict)は旧当時情報、current/previous(dict|None)はSAR現前参照。
    返り値: dictは新M25。同方向かは準備条件にしない。
    """
    now_ready = bool(current and current["SAR公開可"] and current["SAR方向"] in (-1, 1))
    prior_ready = bool(previous and previous["SAR公開可"] and previous["SAR方向"] in (-1, 1)
        and current and previous["index"]+1 == current["index"])
    reasons = list(old["M除外理由"])
    if not now_ready:
        reasons.append("現在公開SAR未準備")
    if not prior_ready:
        reasons.append("同場隣接公開前SAR未準備")
    return {**deepcopy(old), "旧24共通M準備": old["共通M準備"], "旧24M除外理由": deepcopy(old["M除外理由"]),
        "SAR参照": deepcopy(current), "前SAR参照": deepcopy(previous), "SAR現在有効": now_ready,
        "SAR前値有効": prior_ready, "SAR現前準備": now_ready and prior_ready, "SAR現方向": current["SAR方向"] if now_ready else 0,
        "SAR前方向": previous["SAR方向"] if prior_ready else 0,
        "共通M準備": not reasons, "共通M25準備": not reasons, "M除外理由": reasons}


def decisions(context: dict, side: int) -> dict:
    """同じ準備で単足ヒスト差と二本SAR方向を対照する。

    引数: context(dict)は新M25と当時値、side(int)は実新規方向。
    返り値: dictはQ0/Q1正本採否。上位値選別と事後ラベルは使わない。
    """
    reasons = list(context["M除外理由"])
    if not context["時間条件可"]:
        reasons.append("要求時間条件外")
    momentum = finite(context.get("MACDヒスト変化")) and side*context["MACDヒスト変化"] > 0
    persistent = context["SAR現在有効"] and context["SAR前値有効"] and context["SAR現方向"] == context["SAR前方向"] == side
    a = reasons+([] if momentum else ["実方向MACD勢い不成立"])
    b = reasons+([] if persistent else ["実方向SAR二本持続不成立"])
    return {"Q0": BASE.verdict(not a, a or ["価格と実方向MACD採用"]),
        "Q1": BASE.verdict(not b, b or ["価格と実方向SAR二本持続採用"])}


# ----------------------------------------
# 価格監視は固定24で生成し、保存時の新しい採否だけを純変換する。

def generate(frames: list[dict], higher: list[dict], session: str, cutoff: float, deadline: float,
             config: dict, states: list[dict] | None = None, channels: list[dict] | None = None,
             quantity: dict | None = None, sar_rows: list[dict] | None = None) -> tuple[dict, dict]:
    """全価格イベントを保ち、新しい二案の準備・採否・事例を作る。

    引数: frames/higher/sar_rows(list[dict]|None)は3/15足とSAR、session(str)は場、
    cutoff/deadline(float)は時限、config(dict)は25条件、states/channels/quantityは固定24入力。
    返り値: tuple[dict,dict]はQ純入口と全context/価格監視/段階品質。旧正本は変更しない。
    """
    validate_config(config)
    _, original = BASE.generate(frames, higher, session, cutoff, deadline, OLD_CONFIG, states, channels, quantity)
    quality = deepcopy(original)
    sar = {r["index"]: r for r in sar_rows or []}
    if len(sar) != len(sar_rows or []):
        raise ValueError("SAR足番号の重複")
    contexts, by_index, previous = [], {}, None
    for old in original["複合context記録"]:
        current = sar.get(old["index"])
        if current is not None and any(current[k] != old[k] for k in ("index", "end", "confirm", "confirm_line", "publish")):
            raise ValueError("SAR参照と当足の公開時点が不一致")
        prior = previous if previous is not None and previous["publish"] and previous["index"]+1 == old["index"] else None
        context = context_with_sar(old, current, prior)
        contexts.append(context)
        by_index[old["index"]] = context
        previous = current if current is not None and current["publish"] else None
    records = []
    for old in original["全Q発動記録"]:
        row = {**deepcopy(old), **deepcopy(by_index[old["index"]])}
        row["旧24戦略判定"] = deepcopy(old["戦略判定"])
        row["戦略判定"] = decisions(row, row["side"])
        records.append(row)
    chosen = defaultdict(list)
    for row in records:
        for p in POLICIES:
            if row["戦略判定"][p]["採用"]:
                chosen[p, row["要求時計秒"], row["要求原板行"]].append(row)
    for (p, _, _), rows in chosen.items():
        if len(rows) > 1:
            for row in rows:
                row["戦略判定"][p] = {"採用": False, "理由": ["同判断複数信号見送り"], "同時競合": True}
    output = {"3分_"+p: [] for p in POLICIES}
    for (p, _, _), rows in chosen.items():
        if len(rows) == 1:
            row, source = rows[0], "3分_"+p
            output[source].append({**deepcopy(row), "入口ID": source, "戦略": p,
                "複合判定": deepcopy(row["戦略判定"][p]), "イベントID": row["発動ID"]+"_"+p})
    canonical = {r["発動ID"]: r for r in records}
    for t in quality["監視trace"]:
        for a in t["動作"]:
            if "戦略採否" in a:
                a["戦略採否"] = deepcopy(canonical[a["発動ID"]]["戦略判定"])
    quality.update(全Q発動記録=records, 複合context記録=contexts,
        旧24共通M準備足数=sum(r["旧24共通M準備"] for r in contexts),
        共通M準備足数=sum(r["共通M準備"] for r in contexts),
        SAR現在準備足数=sum(r["SAR現在有効"] for r in contexts),
        SAR現前準備足数=sum(r["SAR現在有効"] and r["SAR前値有効"] for r in contexts),
        戦略採否理由別={p: dict(Counter(z for r in records for z in r["戦略判定"][p]["理由"])) for p in POLICIES},
        イベントM除外理由別=dict(Counter(z for r in records for z in r["M除外理由"])),
        戦略別役割発動数={p: dict(Counter(r["役割"] for r in v)) for p, v in output.items()},
        戦略別発動数={p: len(v) for p, v in output.items()})
    quality["イベント段階"] = []
    for role in ("反転", "順行"):
        own = [r for r in records if r["役割"] == role]
        quality["イベント段階"].append({"役割": role, "原価格イベント数": len(own),
            "時間可数": sum(r["時間条件可"] for r in own), "確認遅延可数": sum(r["確認遅延条件可"] for r in own),
            "先着評価対象数": sum(r["先着評価対象"] for r in own),
            "M24時間通過数": sum(r["旧24共通M準備"] and r["時間条件可"] for r in own),
            "M25時間通過数": sum(r["共通M準備"] and r["時間条件可"] for r in own),
            "旧24E0数": sum(r["旧24戦略判定"]["E0"]["採用"] for r in own),
            "SAR準備でQ0除外数": sum(r["旧24戦略判定"]["E0"]["採用"] and not r["共通M準備"] for r in own),
            "Q0採用数": sum(r["戦略判定"]["Q0"]["採用"] for r in own),
            "Q1採用数": sum(r["戦略判定"]["Q1"]["採用"] for r in own)})
    return output, quality
