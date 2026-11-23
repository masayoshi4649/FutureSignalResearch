"""114の要求時保存値だけでEMAの同足恒等式と浮動小数境界を記述監査する。"""
from collections import Counter
from decimal import Decimal
from pathlib import Path
import gzip
import hashlib
import json

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
REQUEST=ROOT/"work/114進行/full70_同入口診断要求.json"
REQUEST_SHA="b4c47a33e578b08d81159cb73d69f5f432d41dbb7588341d5c3f2bafa1aa96f0"


def digest(path: Path) -> str:
    """
    機能: 明示された入力のSHA256を求める。
    引数: path(Path)。返り値: str。Rawは読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(ref: dict,before: dict) -> dict:
    """
    機能: Root解禁済みRefを認証して保存JSONだけを読む。
    引数: ref/before(dict)。返り値: dictはDecimal原値。
    """
    p=Path(ref["path"]).resolve();sha=digest(p)
    if sha!=ref["sha256"]:raise ValueError("Ref SHA差")
    before[str(p)]=sha;opener=gzip.open if p.suffix==".gz" else open
    with opener(p,"rt",encoding="utf-8-sig") as f:return json.load(f,parse_float=Decimal)


def serial(value):
    """
    機能: Decimalの小残差を数値として保存する。
    引数: value(object)。返り値: int/float。対応外はTypeError。
    """
    if isinstance(value,Decimal) and value.is_finite():return int(value) if value==value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def sign(value) -> int:
    """
    機能: 保存値の正/零/負を補正せず符号化する。
    引数: value(Decimal/int)。返り値: intは1/0/-1。
    """
    return 1 if value>0 else -1 if value<0 else 0


def main() -> None:
    """
    機能: 全70のA0_C0_D0要求票を同足EMA恒等式へ照合し新しい小証拠を保存する。
    引数: なし。返り値: None。条件削除・新金融計算・最適化は行わない。
    """
    before={};q=read({"path":str(REQUEST),"sha256":REQUEST_SHA},before)
    if not(q["trial"]==114 and q["stage"]=="full70" and q["market_native_read_authorized"]):raise ValueError("Root解禁差")
    condition=read(q["condition"],before);complete=read(q["completion"],before);code=ROOT/"work/可変追尾向けの公開チャート/numeric.go";code_sha=digest(code)
    if condition["code_sha256"].get(str(code))!=code_sha:raise ValueError("公表EMA停止code差")
    before[str(code)]=code_sha
    stop=read(q["comparison_stop"],before)
    for path,sha in stop["所有ファイルSHA256"].items():
        if digest(Path(path))!=sha:raise ValueError("停止所有code差")
        before[path]=sha
    totals=Counter();details={name:{"対象":0,"distinct公表":set(),"最大絶対残差pt":Decimal(0),"残差1e-10超":0,"符号差":[],"左辺零":0,"右辺基準零":0,"最小非零左辺絶対pt":None,"最大残差の証拠":None} for name in ("a8=2x8/7","a21=(x8+G)/10")};implications=Counter();unknown=Counter()
    for scene in complete["results"]:
        n=read(scene["native"],before);sid=scene["session"]
        for rec in n["actual"]["books"]["A0_C0_D0"]["entry_gate"]["records"] or []:
            d=rec["decision"];v=d["values"];totals["全要求"]+=1
            cur,prev=d["current"],d["previous"];continuous=cur is not None and prev is not None and d["continuous"] and cur["frame"]["data_known"] and prev["frame"]["data_known"] and cur["frame"]["end"]-prev["frame"]["end"]==180
            witness={"session":sid,"signal_id":rec["request"]["signal_id"],"要求原行":rec["request"]["at"],"公表ID":None if cur is None else cur["frame"]["id"],"値":v}
            if not continuous:unknown["現在/前足既知連続の不足"]+=1
            for name,fields,factor in (("a8=2x8/7",("a8","x8"),Decimal(2)/7),("a21=(x8+G)/10",("a21","x8","g"),Decimal(1)/10)):
                if not continuous or any(v[k] is None for k in fields):unknown[name]+=1;continue
                left=v[fields[0]];base=v["x8"] if len(fields)==2 else v["x8"]+v["g"];res=left-factor*base;item=details[name];item["対象"]+=1;item["distinct公表"].add((sid,cur["frame"]["id"]));item["左辺零"]+=left==0;item["右辺基準零"]+=base==0;item["残差1e-10超"]+=abs(res)>Decimal("1e-10")
                if sign(left)!=sign(base):item["符号差"].append({**witness,"残差pt":res})
                if abs(res)>item["最大絶対残差pt"]:item["最大絶対残差pt"]=abs(res);item["最大残差の証拠"]={**witness,"残差pt":res}
                if left!=0:item["最小非零左辺絶対pt"]=abs(left) if item["最小非零左辺絶対pt"] is None else min(item["最小非零左辺絶対pt"],abs(left))
            if continuous and all(v[k] is not None for k in ("g","x8","a8","a21")):
                totals["両式対象"]+=1
                if v["g"]>0 and v["x8"]>0:implications["TのG/x8正対象"]+=1;implications["Tの二傾き含意不一致"]+=not(v["a8"]>0 and v["a21"]>0)
                if v["x8"]>0:implications["x8正対象"]+=1;implications["x8からfast傾き含意不一致"]+=v["a8"]<=0
            totals["T真"]+=d["trend"]==2;totals["R真"]+=d["reversal"]==2
    for item in details.values():item["distinct公表ID数"]=len(item.pop("distinct公表"))
    after={p:digest(Path(p)) for p in before}
    if before!=after:raise ValueError("入力前後差")
    result={"試行":114,"成功":True,"記述監査のみ":True,"Root要求":{"path":str(REQUEST),"sha256":REQUEST_SHA},"式の一次コード":{"path":str(code),"sha256":code_sha,"行":29},"全要求":dict(totals),"式別":details,"情報不足":dict(unknown),"符号含意":dict(implications),"数式":"更新E_t=E_p+alpha(C_t-E_p)からE_t-E_p=alpha/(1-alpha)*(C_t-E_t)。N8なら2/7、N21なら1/10。符号sideを掛けても成立。","限界":["同一足・既知連続EMAの1本差についての恒等式。初期SMA seed/欠測/未知を一般化しない。","表示JSONとIEEE754に由来する小残差は保存し、境界の符号は値を補正せず比較。1e-10は照合精度で金融閾値ではない。","Sourceの1分slope3や別時間軸の方向一致は別。独立の技法票だと見なさない。","114固定条件を削除/再実行せず、新条件の効果や閾値最適化を主張しない。"],"入力SHA256前":before,"入力SHA256後":after,"前後不変":True,"監査コード":{"path":str(Path(__file__).resolve()),"sha256":digest(Path(__file__))},"Raw/新金融再走/新閾値最適化":False}
    p=HERE/"EMA同足の数式確認.json"
    with p.open("x",encoding="utf-8",newline="\n") as f:f.write(json.dumps(result,ensure_ascii=False,indent=2,default=serial)+"\n")
    print(json.dumps({"成功":True,"結果":{"path":str(p),"sha256":digest(p)},"全要求":totals,"式別":{k:{f:v for f,v in val.items() if f not in ("最大残差の証拠","符号差")} for k,val in details.items()},"符号含意":implications},ensure_ascii=False,default=serial))


if __name__=="__main__":main()
