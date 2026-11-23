"""停止Go型14場面と取得ATR境界を照合し、新risk fieldの破損を拒否する。"""

import copy
import importlib.util
import json
from pathlib import Path
import sys


ROOT=Path(__file__).resolve().parents[2]
CODE=Path(__file__).with_name("初期ATR追尾の金融照合.py")
spec=importlib.util.spec_from_file_location("独立初期risk98人工",CODE)
M=importlib.util.module_from_spec(spec);sys.modules[spec.name]=M;spec.loader.exec_module(M)


def rejected(name,value,change):
    """
    機能: 実Go型人工の一部を破損させ、独立全経路の拒否を確認する。
    引数: name(str)、value(dict)、change(callable)は名称・元値・変更関数。
    返り値: dictは拒否の結果。元金融を作り直さず、元人工を変更しない。
    """
    broken=copy.deepcopy(value);change(broken)
    try:M.inspect_fixture(broken)
    except (ValueError,KeyError,AssertionError) as error:return {"種類":name,"拒否":True,"理由":str(error)[:350]}
    raise AssertionError("破損を受理:"+name)


def boundary(folder,original):
    """
    機能: 小型境界証拠の取得ATR128件を独立算術で比較し、Force32は由来を分離する。
    引数: folder(Path)、original(dict[int,dict])は停止境界根と同じBBO/Sourceの元人工。
    返り値: dictは128の数値照合と32のGo参照。未保存の全callをPython成功に補完しない。
    """
    variants={"既知値変化":(20,100,60),"未知から既知":(0,20,80),"既知から未知":(80,0,0),"D0未知D1既知":(0,0,100)}
    count,forces=0,[]
    for side in (-1,1):
        value=original[side]
        for name,(request,d0,d1) in variants.items():
            data=M.BASE.load(folder/f"方向{side}_{name}_ATR.json")
            expected={k for k in M.KEYS if k.startswith(("R05_","R10_"))}
            assert len(data["cases"])==16 and {r["key"] for r in data["cases"]}==expected
            for row in data["cases"]:
                delay=int(row["key"][-1]);atr=d1 if delay else d0
                multiplier=.5 if row["key"].startswith("R05_") else 1.0
                width=max(20.0,min(125.0,multiplier*atr)) if atr>0 else 125.0
                q,_=M.BASE.observation_quote(value["steps"][2+delay]["observation"],value["steps"][2+delay]["source_line"])
                assert row["request_atr"]==request and row["acquisition_atr"]==atr
                assert row["width"]==width and row["known"]==(atr>0) and row["entry_quote"]==q
                count+=1
        for pending in (False,True):
            data=M.BASE.load(folder/f"方向{side}_pending{str(pending).lower()}_Force.json")
            assert data["new98_direct_api"] is True and data["market_raw"]==0 and len(data["cases"])==8
            assert {r["key"] for r in data["cases"]}=={k for k in M.KEYS if k.startswith("H0_")}
            assert all(r["pending_cancel"]==pending and r["prior97_full_equal"] is True and r["final_zero"] is True for r in data["cases"])
            forces.extend(data["cases"])
    return {"取得ATR/幅/既知/取得Quoteの独立照合":count,"全金融callの再照合":False,
            "ForceのGo由来参照系列":len(forces),"Goが全文比較したsnapshot回数":sum(r["snapshots_compared"] for r in forces),
            "限定":"境界JSONはsummaryのみ。128件の取得幅算術/出典は比較するが、未保存の各Actor全callをPythonが再照合したとは呼ばない。Force32は停止Goの除外0比較への由来参照。"}


def main():
    """
    機能: 実型人工の破損拒否と境界scopeを新規証拠へまとめる。
    引数: なし。停止済み手製APIと小型境界だけを使用する。
    返り値: None。市場/原板/新Goを実行しない。
    """
    root=ROOT/"work/98初期ATR追尾案/人工/停止版"
    a=M.BASE.load(root/"方向1_幅と次板悪化.json")
    unknown=M.BASE.load(root/"方向1_未知後既知.json")
    profitable=M.BASE.load(root/"方向1_利益移行.json")
    key="R05_H0_AB_B5Q_P0_C0_D0";book=a["actors"][key]
    oi=next(i for i,o in enumerate(book["orders"]) if "initial_risk_point" in o)
    fi=next(i for i,f in enumerate(book["fills"]) if f["order_id"]==book["orders"][oi]["id"])
    changes=[
        ("取得幅+0.5",a,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("width",50.5)),
        ("未知幅を後ATRで再固定",unknown,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("width",20)),
        ("未知を既知へ偽装",unknown,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("atr_known",True)),
        ("取得出典を要求Indexへ",a,lambda v:v["actors"][key]["positions"][0]["initial_risk"]["entry_quote"].__setitem__("index",0)),
        ("架空初期peak",a,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("peak_gain",0)),
        ("初期床を緩和",a,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("floor_gain",-126)),
        ("firsthit欠落",a,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("first_hit",None)),
        ("要求をpre_fillへ",a,lambda v:v["actors"][key]["orders"][oi]["initial_risk_point"]["mark"].__setitem__("phase","pre_fill")),
        ("risk要求point欠落",a,lambda v:v["actors"][key]["orders"][oi].pop("initial_risk_point")),
        ("riskをH要求pointへ",a,lambda v:v["actors"][key]["orders"][oi].__setitem__("protection_point",v["actors"][key]["orders"][oi]["initial_risk_point"]["mark"])),
        ("riskcounter欠落",a,lambda v:v["actors"][key]["metrics"].pop("initial_risk_exit_requests")),
        ("riskcounterをSourceへ混入",a,lambda v:v["actors"][key]["metrics"].__setitem__("source_exit_requests",v["actors"][key]["metrics"]["source_exit_requests"]+1)),
        ("同原行risk約定",a,lambda v:v["actors"][key]["fills"][fi].__setitem__("quote",copy.deepcopy(v["actors"][key]["orders"][oi]["request_quote"]))),
        ("risk専用理由を書換え",a,lambda v:v["actors"][key]["orders"][oi].__setitem__("reason",M.FIN.HARVEST_REASON)),
        ("H移行時u=0へ偽装",profitable,lambda v:v["actors"][key]["positions"][0]["activation"].__setitem__("unit_net",0)),
        ("H移行を消去",profitable,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("profit_transition",None)),
        ("未知のrisk新field",a,lambda v:v["actors"][key]["positions"][0]["initial_risk"].__setitem__("未知field",123)),
        ("Source比率数量を破壊",a,lambda v:v["actors"][key]["source_events"][0].__setitem__("actual_accepted",999)),
    ]
    rejects=[rejected(name,value,change) for name,value,change in changes]
    original={side:M.BASE.load(root/f"方向{side}_幅と次板悪化.json") for side in (-1,1)}
    result={"成功":True,"破損拒否":rejects,"境界":boundary(ROOT/"work/98境界人工/人工/停止版",original),
            "コードSHA256":M.digest(CODE),"検査コードSHA256":M.digest(Path(__file__)),
            "市場/原板/新Go実行":0,"旧正式/固定155変更":0}
    path=Path(__file__).with_name("破損と境界.json")
    with path.open("x",encoding="utf-8",newline="\n") as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print(json.dumps({"成功":True,"破損拒否":len(rejects),"取得ATR境界":result["境界"]["取得ATR/幅/既知/取得Quoteの独立照合"]},ensure_ascii=False))


if __name__=="__main__":main()
