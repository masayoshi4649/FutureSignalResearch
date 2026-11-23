"""固定済み入口のデイ実取得を、事前の現物制度属性で事後記述する。"""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import defaultdict
import gzip
import hashlib
import json

ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).parent
TRIAL=ROOT/'study/00206_指数間の相対変化を複合入口へ加える'
IDS=('NK225206_E199_00_BASE','NK225206_E199_02_BASE','NK225206_E199_05_BASE','TOPIX206_I00_BASE')
JST=timezone(timedelta(hours=9))
HOLIDAYS=('2026-09-21','2026-09-22','2026-09-23','2026-10-12','2026-11-03')
BUCKETS=((525,540,'現物寄付前'),(540,690,'現物前場'),(690,750,'現物昼休み'),
         (750,925,'現物後場ザラバ'),(925,930,'現物引け板寄せ受付'))


def read(path: Path) -> object:
    """
    機能: 既存の固定済みJSONを読む。
    引数: path(Path)。
    返り値: objectは解析値。
    """
    raw=path.read_bytes();return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


# ----------------------------------------
def ref(path: Path) -> dict:
    """
    機能: 入力の相対位置と物理SHAを記録する。
    引数: path(Path)。
    返り値: dictはpath/bytes/sha256。
    """
    return {'path':path.relative_to(ROOT).as_posix(),'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


# ----------------------------------------
def save(path: Path,value: object) -> None:
    """
    機能: 同体以外の上書きをせずUTF-8資料を保存する。
    引数: path(Path)、value(object)。
    返り値: None。
    """
    raw=(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
    if path.exists():assert path.read_bytes()==raw,path
    else:path.write_bytes(raw)


# ----------------------------------------
def classify(scene: str,stamp: float) -> str:
    """
    機能: 実取得時の制度上の市場状態を重複なく分類する。
    引数: scene(str)、stamp(float)はJSTへ変換する取得時計。
    返り値: str。祝日は通常の寄付/昼休みへ分類しない。
    """
    moment=datetime.fromtimestamp(stamp,JST);assert moment.date().isoformat()==scene[:10]
    if scene[:10] in HOLIDAYS:return '現物終日休場'
    minute=moment.hour*60+moment.minute+moment.second/60
    for a,b,name in BUCKETS:
        if a<=minute<b:return name
    raise AssertionError((scene,stamp,moment.isoformat()))


# ----------------------------------------
def summary(rows: list) -> dict:
    """
    機能: 既存取引の群を費用後損益・支持日数で記述する。
    引数: rows(list[dict])は群内の実取得。
    返り値: dict。除外後の口座成績を計算したものではない。
    """
    known=[r['net'] for r in rows if r['known']]
    return {'取得':len(rows),'支持場':len({r['scene'] for r in rows}),'未知':sum(not r['known'] for r in rows),
            '利益':round(sum(max(x,0) for x in known),1),'損失':round(sum(-min(x,0) for x in known),1),
            '既知収支':round(sum(known),1),'赤字取引':sum(x<0 for x in known)}


# ----------------------------------------
def main() -> None:
    """
    機能: 制度分類を損益群開封前に記録し、全デイ取引の分布を保存する。
    引数: なし。
    返り値: None。売買条件・金融・分母・旧正本を変更しない。
    """
    paths=[TRIAL/'金融正本'/(identity+'.json.gz') for identity in IDS]
    design={'区分':'既使用83場・固定正本の事後診断。新入口/未知性能/除外後口座の検証ではない。',
        '取得時計分類':True,'現物休場日':HOLIDAYS,'通常日分境界':BUCKETS,'Source':ref(Path(__file__)),
        '入力':[ref(p) for p in paths],
        '制度出典':{'確認日':'2026-11-18','立会':'https://www.jpx.co.jp/equities/trading/domestic/01.html',
            '現物引け':'https://www.jpx.co.jp/english/systems/equities-trading/01.html',
            '休業日':'https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html',
            '祝日先物':'https://www.jpx.co.jp/derivatives/rules/holidaytrading/index.html'},
        '解釈':'取得時計による群の記述。次の注文仮説に使うならq0で再分類して全後続枠を再生する。'}
    save(HERE/'分類前固定.json',design);result=[]
    for identity,path in zip(IDS,paths):
        pack=read(path);ledger=pack['ledger'];rows=[]
        for i,scene in enumerate(ledger['scene']):
            if not scene.endswith('_Day'):continue
            rows.append({'scene':scene,'known':ledger['known'][i],'net':ledger['net'][i],
                         '制度':classify(scene,ledger['entry_time'][i]),'entry_time':ledger['entry_time'][i]})
        all_scenes=[s['scene'] for s in pack['sessions'] if s['kind']=='DAY'];assert len(all_scenes)==42
        assert len([s for s in all_scenes if s[:10] in HOLIDAYS])==5
        grouped={name:summary([r for r in rows if r['制度']==name]) for name in ('現物終日休場',)+tuple(x[2] for x in BUCKETS)}
        assert sum(g['取得'] for g in grouped.values())==len(rows)
        assert math_close(sum(g['既知収支'] for g in grouped.values()),summary(rows)['既知収支'])
        dates=sorted(all_scenes);periods={'前48':pack['sessions'][:48],'後25':pack['sessions'][48:73],
            '追加7':pack['sessions'][73:80],'本日1':pack['sessions'][80:81],'追加2':pack['sessions'][81:]}
        per={p:{name:summary([r for r in rows if r['scene'] in {s['scene'] for s in scenes} and r['制度']==name])
                for name in grouped} for p,scenes in periods.items()}
        result.append({'id':identity,'全Day分母':len(dates),'現物休場Day':5,'全体':summary(rows),'制度別':grouped,'期間別':per})
    save(HERE/'既存取得の制度別診断.json',result)
    assert design['入力']==[ref(p) for p in paths]
    print(json.dumps(result,ensure_ascii=False))


# ----------------------------------------
def math_close(a: float,b: float) -> bool:
    """
    機能: 円集計の浮動小数誤差を許して同体を判定する。
    引数: a/b(float)。
    返り値: boolは絶対差1e-6以下。
    """
    return abs(a-b)<=1e-6


# ----------------------------------------
if __name__=='__main__':main()
