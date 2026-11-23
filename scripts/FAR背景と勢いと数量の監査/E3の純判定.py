"""固定96のPython入力検査/check算術を再用し、E3/E3S本名の採否を独立計算する。"""

import copy
import hashlib
import importlib.util
from pathlib import Path
import sys


ROOT=Path(__file__).resolve().parents[2]
TECH_PATH=ROOT/"scripts/FAR5分枠の技法判定の監査/技法の保存照合.py"
TECH_SHA="b5d1af7fb85d4446a47573a4389abfa433177189cb01d901bdd53a8a38b8d5e6"
SPEC_GO_SHA="057715922b6c5b6a72b678eca8c969f292104d05db1aa0ed2a21e7533d683990"
SELECTED=("共通.現在価格時計","共通.確定3分","共通.確定15分","共通.EMA背景既知","共通.MACD増分","共通.現在量支持","A.3分EMA方向","A.15分EMA方向")


def technical():
    """
    機能: 停止した独立Pythonの入力validatorとcheck計算だけを読み込む。
    引数: なし。
    返り値: moduleは固定96部品。Go/Source/市場は呼ばない。
    """
    if hashlib.sha256(TECH_PATH.read_bytes()).hexdigest()!=TECH_SHA:raise ValueError("固定96技法Python SHA差")
    spec=importlib.util.spec_from_file_location("固定96check計算E3",TECH_PATH)
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


TECH=technical()


def assess(incoming,candidate,policy):
    """
    機能: 当時公開input/candidateから必要8/9checkだけでE3/E3Sを独立計算する。
    引数: incoming/candidate(dict)、policy(str,E3/E3S)は元公開入力と現在候補。
    返り値: dictは本名Decisionと順序付き全使用check。保存Go採否を読み戻さない。
    """
    TECH.need(policy in ("E3","E3S"),"E3/E3Sの政策")
    # Aは固定入力validator/check bankのAPI名だけ。金融や返却DecisionをAへ偽装しない。
    base=TECH.assess(incoming,candidate,"A")
    by_id={row["id"]:row for row in base["checks"]}
    TECH.need(len(by_id)==len(base["checks"]),"固定check ID重複")
    names=SELECTED+(("共通.同時スパイク警戒",) if policy=="E3S" else ())
    TECH.need(all(name in by_id for name in names),"固定必要check不足")
    checks=[copy.deepcopy(by_id[name]) for name in names]
    refused=any(row["known"] and not row["passed"] for row in checks)
    all_known=all(row["known"] for row in checks)
    known,allowed=all_known or refused,all_known and not refused
    role,reason=("順行","公開済み複合テクニカルが成立") if allowed else ("待機","公開済みの必要条件が不成立") if known else ("判定不能","既知の否定条件はなく採否に必要な値が未知")
    return {"decision":{"policy":policy,"snapshot_id":incoming["snapshot_id"],"known":known,"allowed":allowed,"role":role,"reason":reason},"checks":checks}
