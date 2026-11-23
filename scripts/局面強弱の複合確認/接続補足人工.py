"""旧50完全枠接続の欠落・重複・未来・改竄と局所差替えを人工検査する。"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import FunctionType


def load(path: Path, name: str):
    """補足コードだけを固有名で読み込む。

    引数: path(Path)はコード、name(str)は読込名。
    返り値: ModuleTypeは人工対象。正式入力・モデルは開かない。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S=load(Path(__file__).with_name("接続を補足する.py"),"接続補足人工の対象")


def fixture() -> tuple:
    """縮約枠・完全枠・旧46内の二重base出典を明示構成する。

    引数: なし。
    返り値: tuple[dict,list[dict],dict]は一件の人工入力。
    """
    source={"session":"2026-10-05_Day","index":0,"minutes":15,"start":1000.0,"end":1900.0,
        "confirm":1901.0,"confirm_line":10,"publish":True,"missing":0,"open":1000.0,
        "high":1010.0,"low":990.0,"close":1005.0}
    slot={"session":source["session"],"slot_id":"人工1","scheduled":1900.0,"time":1901.0,"line":10,
        "upper":{"ready":True,"source":source,"plus_di":25.0,"minus_di":10.0},"任意状態":{"保持":True}}
    thin={"人工1":{k:slot[k] for k in S.A63.BINDING}}
    feature={"人工1":{"ready":True,"base":{"base":{"sources":{"upper":deepcopy(source)},
        "diagnostic":{"plus_di":25.0,"minus_di":10.0}}}}}
    return thin,[slot],feature


def original_value() -> str:
    """局所差替え前の固定関数を人工化する。

    引数: なし。
    返り値: strは元の識別子。
    """
    return "元の準備"


def adapted_value() -> str:
    """新しい準備関数を人工化する。

    引数: なし。
    返り値: strは補足後の識別子。
    """
    return "接続補足"


def probe() -> str:
    """関数の大域名解決だけを人工で呼ぶ。

    引数: なし。
    返り値: strは名前空間内の準備関数の返り値。
    """
    return prepare_features()


def self_test() -> dict:
    """接続の不正と凍結大域値非改変を人工だけで検査する。

    引数: なし。
    返り値: dictは人工成功/照合項目数/不一致数/不一致。
    """
    source,_,_=S.A63.A.helpers()
    audit=source.Audit()
    thin,full,features=fixture()
    saved=deepcopy((thin,full,features))
    joined=S.bind_full_slots(thin,full,features)
    audit.check("旧50完全枠の接続",joined,{"人工1":full[0]})
    audit.check("純接続は入力非改変",(thin,full,features),saved)
    joined["人工1"]["任意状態"]["保持"]=False
    audit.check("返却辞書も深い複写",full,saved[1])
    cases=[]
    cases.append(("重複",deepcopy(thin),deepcopy(full)*2,deepcopy(features)))
    cases.append(("欠落",deepcopy(thin),[],deepcopy(features)))
    for key in S.A63.BINDING:
        changed=deepcopy(full)
        changed[0][key]=changed[0][key]+1 if isinstance(changed[0][key],(int,float)) else changed[0][key]+"変更"
        cases.append(("BINDING値:"+key,deepcopy(thin),changed,deepcopy(features)))
    changed=deepcopy(full)
    changed[0]["line"]=10.0
    cases.append(("BINDING型",deepcopy(thin),changed,deepcopy(features)))
    changed=deepcopy(full)
    changed[0]["upper"]["source"]["confirm"]+=1
    cases.append(("未来upper",deepcopy(thin),changed,deepcopy(features)))
    changed=deepcopy(full)
    changed[0]["upper"]["source"]["confirm_line"]+=1
    cases.append(("同秒後行upper",deepcopy(thin),changed,deepcopy(features)))
    changed=deepcopy(full)
    changed[0]["upper"]["source"]["close"]+=1
    cases.append(("upper価格改竄",deepcopy(thin),changed,deepcopy(features)))
    changed=deepcopy(full)
    changed[0]["upper"]["plus_di"]+=1
    cases.append(("upperDI改竄",deepcopy(thin),changed,deepcopy(features)))
    changed=deepcopy(full)
    changed[0]["upper"]=None
    cases.append(("準備済みupper欠落",deepcopy(thin),changed,deepcopy(features)))
    for label,left,middle,right in cases:
        denied=False
        try:S.bind_full_slots(left,middle,right)
        except ValueError:denied=True
        audit.check("不正接続拒否:"+label,denied,True)
    not_ready=deepcopy(features)
    not_ready["人工1"]={"ready":False}
    unready_full=deepcopy(full)
    unready_full[0]["upper"]=None
    audit.check("未準備は上位値を要求せず記録",S.bind_full_slots(thin,unready_full,not_ready),{"人工1":unready_full[0]})
    namespace={"prepare_features":original_value}
    original=FunctionType(probe.__code__,namespace,"元の人工run")
    cloned=S.cloned_run(original,adapted_value)
    audit.check("同一code_object",cloned.__code__ is original.__code__,True)
    audit.check("元の大域値維持",(original(),namespace["prepare_features"] is original_value),("元の準備",True))
    audit.check("新名前空間だけ接続差替え",cloned(),"接続補足")
    audit.check("差替え対象は準備一関数",[k for k in cloned.__globals__ if cloned.__globals__[k] is not namespace.get(k)],["prepare_features"])
    return {"人工成功":audit.bad==0,"照合項目数":audit.count,"不一致数":audit.bad,"不一致":audit.examples,
        "本物入力読取":False,"モデル読取":False,"fit":False,"市場再生":False,"凍結コード変更":False}


if __name__=="__main__":
    payload=self_test()
    print(json.dumps(payload,ensure_ascii=False,indent=2))
    raise SystemExit(0 if payload["人工成功"] else 1)
