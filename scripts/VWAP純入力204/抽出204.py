"""201の固定q0へ同原行の配信VWAP・代金・起算を追加する。金融は扱わない。"""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime,timedelta,timezone
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import math
import sys
import time

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'work/pythonlibs'))
import orjson

DEST=ROOT/'inputs/00204_両指数の配信VWAP純入力'
PARENT=ROOT/'inputs/00201_両指数の板数量純特徴/抽出前固定.json.gz'
JST=timezone(timedelta(hours=9));FACTOR={'NK225':1000.,'TOPIX':10000.};TOL=.00010001
IDENTITY=('contract','exchange','exchange_name','opening_time','opening_price')


def ref(path: Path) -> dict:
    """
    機能: 入力の物理指紋と前後statを確認する。
    引数: path(Path)。
    返り値: dictは絶対path・容量・mtime・SHA256。
    """
    before=path.stat()
    with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    after=path.stat();assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
    return {'path':str(path.resolve()),'bytes':after.st_size,'mtime_ns':after.st_mtime_ns,'sha256':digest}


def read(path: Path) -> object:
    """
    機能: JSON又はgzip JSONを読む。
    引数: path(Path)。
    返り値: objectは日本語UTF-8の解析値。
    """
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as f:return orjson.loads(f.read())


def save(path: Path,value: object) -> dict:
    """
    機能: 正式な純結果を新規保存し、既存内容の相違は拒否する。
    引数: path(Path)、value(object)。
    返り値: dictは保存指紋。原板は書き換えない。
    """
    raw=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    body=gzip.compress(raw,mtime=0) if path.suffix=='.gz' else raw
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==body,('既存純結果が相違',path)
    else:path.write_bytes(body)
    return ref(path)


def number(value: object) -> float | None:
    """
    機能: JSON数値の有限値だけを取り出す。0・負値は監査用に残す。
    引数: value(object)。
    返り値: float|None。未知を0へ置かない。
    """
    return float(value) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None


def clock(value: object,cache: dict) -> float | None:
    """
    機能: 時差付きISO時計を再利用付きでUnix秒へ変換する。
    引数: value(object)、cache(dict)。
    返り値: float|None。独自の受信時計は作らない。
    """
    if not isinstance(value,str):return None
    if value not in cache:
        try:
            parsed=datetime.fromisoformat(value);cache[value]=parsed.timestamp() if parsed.utcoffset() is not None else None
        except (ValueError,OverflowError):cache[value]=None
    return cache[value]


def parse(raw: dict,line: int,cache: dict) -> dict:
    """
    機能: 原板の値をその原行のまま小列へ変換する。
    引数: raw(dict)、line(int)、cache(dict)。
    返り値: dict。nativeと代金を足代表価格から作り直さない。
    """
    return {'line':line,'time':clock(raw.get('CurrentPriceTime'),cache),'last':number(raw.get('CurrentPrice')),
            'volume':number(raw.get('TradingVolume')),'volume_time':clock(raw.get('TradingVolumeTime'),cache),
            'native':number(raw.get('VWAP')),'value':number(raw.get('TradingValue')),
            'opening_price':number(raw.get('OpeningPrice')),'opening_time':clock(raw.get('OpeningPriceTime'),cache),
            'contract':str(raw['Symbol']) if raw.get('Symbol') is not None else None,
            'exchange':raw.get('Exchange'),'exchange_name':raw.get('ExchangeName')}


def edges(scene: str) -> tuple:
    """
    機能: 旧17と同じ場範囲と厳密な当日の閉場後基準範囲を作る。
    引数: scene(str)。
    返り値: tuple[float,float,float]は開始・終了・接頭下限。
    """
    day=datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
    if scene.endswith('_Day'):a=day.replace(hour=8,minute=45);b=day.replace(hour=15,minute=45);floor=day.replace(hour=6)
    else:a=day.replace(hour=17);b=(day+timedelta(days=1)).replace(hour=6);floor=day.replace(hour=15,minute=45)
    return a.timestamp(),b.timestamp(),floor.timestamp()


# ----------------------------------------
class State:
    """原行までの累積区間・当場基準・観測障害を保持する純状態。"""

    def __init__(self,scene: str,symbol: str) -> None:
        """
        機能: 一つの商品・場だけの起算監視を初期化する。
        引数: scene(str)、symbol(str)。
        返り値: None。前場の状態を持ち越さない。
        """
        self.start,self.end,self.floor=edges(scene);self.factor=FACTOR[symbol]
        self.high=-math.inf;self.previous=None;self.identity={};self.base=None;self.epoch=0
        self.continuity=0;self.uncertain=False;self.counts=Counter();self.changes=[]
        self.native_previous=None;self.native_changed_line=None;self.current=None;self.status=None

    def add(self,event: dict) -> None:
        """
        機能: 現在原行だけで時計・比率・区間変更・既知基準を更新する。
        引数: event(dict)は同原行の小列。
        返り値: None。後退や一時欠測を過去値で補完しない。
        """
        self.current=event;self.counts['全原行']+=1;reasons=[]
        t,q,v,qt=event['time'],event['volume'],event['value'],event['volume_time']
        native=event['native'];comparable=q is not None and q>0 and v is not None and v>=0 and native is not None and native>0
        ratio=v/q/self.factor if comparable else None;error=abs(native-ratio) if comparable else None
        ratio_ok=comparable and error<=TOL
        self.counts['内部比較']+=int(comparable);self.counts['内部不整合']+=int(comparable and not ratio_ok)
        if native!=self.native_previous:self.native_changed_line=event['line'];self.native_previous=native
        if t is None:reasons.append('価格時計不明')
        elif t<self.high:reasons.append('価格時計後退')
        else:self.high=t
        if qt is None:reasons.append('数量時計不明')
        elif t is not None and qt>t:reasons.append('数量時計先行')
        if q is None or v is None or q<0 or v<0:reasons.append('累積数量代金不正')
        usable=not reasons
        present={k:event[k] is not None and (event[k]>0 if k in ('opening_time','opening_price') else True) for k in IDENTITY}
        identity_ok=all(present.values()) and t is not None and event['opening_time']<=t
        if usable:
            changed=[]
            if self.previous is not None:
                for field in ('volume','value','volume_time'):
                    if event[field]<self.previous[field]:changed.append(field+'減少')
            for key in IDENTITY:
                if not present[key]:continue
                if key in self.identity and self.identity[key]!=event[key]:changed.append(key+'変更')
                self.identity[key]=event[key]
            if changed:
                self.epoch+=1;self.base=None;self.continuity+=1;self.counts['区間変更']+=1
                if len(self.changes)<12:self.changes.append({'line':event['line'],'time':t,'理由':changed})
            self.previous=event
            candidate=identity_ok and (ratio_ok or q==v==0)
            if candidate and self.floor<=t<self.start and self.floor<=qt<self.start:self.base=dict(event)
            if candidate and t==self.start and qt<=self.start and q==v==0:self.base=dict(event)
        # ----------------------------------------
        # 当時不明な途中区間を、後で正常になった事実から滑らかにつながない。
        if not usable or not identity_ok or not (ratio_ok or q==v==0):
            if not self.uncertain:self.continuity+=1
            self.uncertain=True
        else:
            if self.uncertain:self.continuity+=1
            self.uncertain=False
        inside=t is not None and self.start<=t<self.end
        quantity_inside=qt is not None and t is not None and self.start<=qt<=t
        if not inside:reasons.append('価格時計場外')
        if not quantity_inside:reasons.append('数量時計場外または先行')
        if not ratio_ok:reasons.append('内部比率不明または不整合')
        if not identity_ok:reasons.append('起算識別未確認')
        if event['last'] is None or event['last']<=0:reasons.append('現在価格不正')
        self.status={'ratio':ratio,'ratio_error':error,'ratio_ok':bool(ratio_ok),'quantity_inside':quantity_inside,
                     'native_known':not reasons,'reasons':sorted(set(reasons))}
        for reason in set(reasons):self.counts['理由:'+reason]+=1

    def snapshot(self) -> dict:
        """
        機能: 当時q0の値・可否・出典を独立した小さなレコードへ固定する。
        引数: なし。
        返り値: dict。未来の区間変更や後続同秒値を含めない。
        """
        event=self.current;result={**event,**self.status,'epoch':self.epoch,'continuity':self.continuity,
            'native_changed_line':self.native_changed_line,'base':None,'session_delta':None,'delta_volume':None,'delta_value':None}
        if self.base is not None:
            result['base']={k:self.base[k] for k in ('line','time','volume_time','volume','value')}
            same=all(self.base[k]==event[k] for k in IDENTITY)
            if self.status['native_known'] and same:
                dq=event['volume']-self.base['volume'];dv=event['value']-self.base['value']
                result.update(delta_volume=dq,delta_value=dv)
                if dq>0 and dv>0:result['session_delta']=dv/dq/self.factor
        return result


# ----------------------------------------
def prepare(symbol: str) -> None:
    """
    機能: 201の固定原板・q0と純抽出仕様だけを実行前固定する。
    引数: symbol(str)。
    返り値: None。金融候補の条件は作らない。
    """
    parent=read(PARENT);assert parent['financial_labels_used'] is False
    artificial=read(HERE/'人工確認.json');assert artificial['成功'] and artificial['金融未使用']
    assert artificial['SourceSHA']==ref(Path(__file__))['sha256']
    entries=[e for e in parent['scenes'] if e['symbol']==symbol];assert len(entries)==83
    plan={'schema':'VWAP原行204_v1','symbol':symbol,'financial_labels_used':False,'201入力票':ref(PARENT),
          'Source':[ref(HERE/n) for n in ('抽出204.py','人工確認.py','人工確認.json','仕様.md')],
          'scenes':entries,'factor':FACTOR[symbol],'tolerance':TOL,'原板複製':False,'出力':'同じ原行q0のみ。開始前基準等はその時点までの原行状態。',
          '環境':{'Python':sys.version,'orjson':orjson.__version__}}
    save(DEST/('抽出前固定_'+symbol+'.json.gz'),plan)
    print(symbol,'83場',sum(len(e['q0']) for e in entries),'q0を固定',flush=True)


def extract(entry: dict) -> dict:
    """
    機能: 原板を一度原順に読み、q0だけのnative・累積・起算を保存する。
    引数: entry(dict)は201で固定された商品場。
    返り値: dictは全原板指紋・q0数・純品質。損益・先着は参照しない。
    """
    symbol,scene=entry['symbol'],entry['session'];path=Path(entry['raw']['path']);before=path.stat()
    assert (before.st_size,before.st_mtime_ns)==(entry['raw']['bytes'],entry['raw']['mtime_ns'])
    target={q['line']:q for q in entry['q0']};state=State(scene,symbol);clock_cache={};rows=[];h=hashlib.sha256();counts=Counter();start=time.perf_counter()
    first_inside=None;last_inside=None;prefix=None
    with gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb') as f:
        for line,body in enumerate(f,1):
            h.update(body);raw=orjson.loads(body);event=parse(raw,line,clock_cache);state.add(event)
            if event['time'] is not None:
                if event['time']<state.start:prefix=event
                elif event['time']<state.end:
                    if first_inside is None:first_inside=dict(event)
                    last_inside=dict(event)
            if line not in target:continue
            q=target[line]
            assert event['time']==q['time'] and event['last']==q['last']
            assert (raw.get('Buy1') or {}).get('Price')==q['bid'] and (raw.get('Sell1') or {}).get('Price')==q['ask']
            row=state.snapshot();rows.append(row)
            counts['q0']+=1;counts['native既知']+=int(row['native_known']);counts['比率比較']+=int(row['ratio'] is not None)
            counts['比率不整合']+=int(row['ratio'] is not None and not row['ratio_ok']);counts['当場差分既知']+=int(row['session_delta'] is not None)
            counts['始値時計場前']+=int(row['opening_time'] is not None and row['opening_time']<state.start)
            counts['始値時計場内']+=int(row['opening_time'] is not None and state.start<=row['opening_time']<state.end)
            for reason in row['reasons']:counts['q0理由:'+reason]+=1
    assert len(rows)==len(target) and h.hexdigest()==entry['uncompressed_sha256']
    assert ref(path)==entry['raw']
    output=save(DEST/symbol/(scene+'.json.gz'),{'schema':'VWAP原行204_v1','symbol':symbol,'session':scene,'financial_labels_used':False,'factor':state.factor,'rows':rows})
    proof={'symbol':symbol,'session':scene,'raw':entry['raw'],'uncompressed_sha256':h.hexdigest(),'q0_counts':dict(counts),
           '全原行診断':dict(state.counts),'区間変更例':state.changes,'prefix最終':prefix,'最初場内':first_inside,'最後場内':last_inside,'output':output}
    save(DEST/symbol/(scene+'.検査.json'),proof)
    print(scene,'q0',len(rows),'native',counts['native既知'],'差分',counts['当場差分既知'],'秒',round(time.perf_counter()-start,1),flush=True)
    return proof


def run(symbol: str,workers: int) -> None:
    """
    機能: 固定された83場を並列抽出し、全件完了後だけ入力台帳を保存する。
    引数: symbol(str)、workers(int)。
    返り値: None。途中で入力やSourceが変われば拒否する。
    """
    path=DEST/('抽出前固定_'+symbol+'.json.gz');plan=read(path)
    assert all(ref(Path(r['path']))==r for r in plan['Source']) and ref(PARENT)==plan['201入力票']
    results=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(extract,e) for e in plan['scenes']]
        for future in as_completed(futures):results.append(future.result())
    results.sort(key=lambda r:r['session']);assert len(results)==83
    assert all(ref(Path(r['path']))==r for r in plan['Source'])
    save(DEST/('完了_'+symbol+'.json'),{'成功':True,'financial_labels_used':False,'入力票':ref(path),'scenes':results})


if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('--stage',choices=('prepare','extract'),required=True)
    cli.add_argument('--symbol',choices=tuple(FACTOR),default='TOPIX');cli.add_argument('--workers',type=int,default=3);args=cli.parse_args()
    if args.stage=='prepare':prepare(args.symbol)
    else:run(args.symbol,args.workers)
