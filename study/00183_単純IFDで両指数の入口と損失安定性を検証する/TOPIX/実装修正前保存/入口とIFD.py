"""TOPIX自身の公開済み複合入口を、単一建玉の単純IFDで比較する。"""
from pathlib import Path
from collections import deque,Counter
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import argparse,gzip,hashlib,importlib.util,json,math,sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent
JST=timezone(timedelta(hours=9));NY=ZoneInfo('America/New_York')
NAMES=('T0_二足順行','T1_順行位置量','T2_三足整合','T3_押戻し回復','T4_量付き突破',
       'R0_弱トレンド反転','R1_端失敗回復','R2_元圧力失速','M0_順行と端回復','M1_三足と失速',
       'M2_ADX局面切替','M3_構造統合','M4_広い複合とスパイク除外')
WIDTHS=(5.,10.,15.);SLIPS=(0.,.25,.5)


def read(path):
    """
    機能: UTF-8 JSONを読む。
    引数: path(Path)は入力。
    返り値: objectは保存値。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    """
    機能: 指紋を計算する。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def save(path,value):
    """
    機能: JSONをNaNなしで保存する。
    引数: path(Path),value(object)。
    返り値: None。
    """
    data=(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(gzip.compress(data,mtime=0) if path.suffix=='.gz' else data)


def bounds(session):
    """
    機能: 場の開始・研究終了・強制要求時計を返す。
    引数: session(str)。
    返り値: tuple[float,float,float]は開始/終了/終了一分前。
    """
    d=datetime.fromisoformat(session[:10]).replace(tzinfo=JST)
    start=d+timedelta(hours=8,minutes=45) if session.endswith('Day') else d+timedelta(hours=17)
    end=d+timedelta(hours=15,minutes=30) if session.endswith('Day') else d+timedelta(days=1,hours=5,minutes=45)
    return start.timestamp(),end.timestamp(),end.timestamp()-60


def band(t,session):
    """
    機能: 当時時計で基本三帯を付ける。
    引数: t(float),session(str)。
    返り値: strはDAY/PRE/POST。
    """
    if session.endswith('Day'):return 'DAY'
    start,_,_=bounds(session);local=datetime.fromtimestamp(start,JST)
    ny_date=local.astimezone(NY).date()
    opening=datetime.combine(ny_date,datetime.min.time(),NY)+timedelta(hours=9,minutes=30)
    return 'PRE' if t<opening.timestamp() else 'POST'


class Channel:
    """同限月で確定足だけから価格・動力・値幅を更新する。"""
    def __init__(self):
        """
        機能: 指標履歴を初期化する。
        引数: なし。
        返り値: None。
        """
        self.n=0;self.e={8:None,12:None,21:None,26:None};self.signal=None
        self.atr=None;self.up=None;self.down=None;self.pdm=None;self.mdm=None;self.adx=None
        self.prev=None;self.hist=None;self.last=None;self.closes=deque(maxlen=20)

    def update(self,b,published):
        """
        機能: 一つの完全足を公表時計付きで更新する。
        引数: b(dict)はOHLC/時刻、published(float)は確認時計。
        返り値: dictは当時の有限値又はNone。
        """
        old=self.last;prior=self.prev;c=b['close'];self.n+=1
        ep=self.e[21]
        for length in self.e:
            self.e[length]=c if self.e[length] is None else self.e[length]+2/(length+1)*(c-self.e[length])
        macd=self.e[12]-self.e[26]
        self.signal=macd if self.signal is None else self.signal+.2*(macd-self.signal)
        hist=macd-self.signal;hd=None if self.hist is None else hist-self.hist
        self.hist=hist
        tr=b['high']-b['low'] if prior is None else max(b['high']-b['low'],abs(b['high']-prior['close']),abs(b['low']-prior['close']))
        up=max(c-prior['close'],0) if prior else 0;down=max(prior['close']-c,0) if prior else 0
        hu=b['high']-prior['high'] if prior else 0;ld=prior['low']-b['low'] if prior else 0
        pdm=hu if hu>ld and hu>0 else 0;mdm=ld if ld>hu and ld>0 else 0
        for name,value in [('atr',tr),('up',up),('down',down),('pdm',pdm),('mdm',mdm)]:
            previous=getattr(self,name);setattr(self,name,value if previous is None else previous+(value-previous)/14)
        total=self.pdm+self.mdm;dx=100*abs(self.pdm-self.mdm)/total if total else 0
        self.adx=dx if self.adx is None else self.adx+(dx-self.adx)/14
        rsi=100*self.up/(self.up+self.down) if self.up+self.down else 50
        self.closes.append(c);sigma=float(np.std(self.closes)) if len(self.closes)==20 else None
        mean=float(np.mean(self.closes)) if sigma is not None else None
        z=(c-mean)/sigma if sigma and sigma>0 else None
        self.last={'count':self.n,'close':c,'ema8':self.e[8],'ema21':self.e[21],
          'slope':None if ep is None else self.e[21]-ep,'hist':hist,'hist_delta':hd,'rsi':rsi,
          'rsi_delta':None if old is None else rsi-old['rsi'],'atr':self.atr,'adx':self.adx,
          'di':(self.pdm-self.mdm)/self.atr if self.atr else 0,'bbz':z,'published':published,'end':b['end'],'tr':tr}
        self.prev=b
        return self.last


def bars_and_features(entry,channels):
    """
    機能: 原順キャッシュから確定1/5/15/30分と当時特徴を構築する。
    引数: entry(dict)は入力参照、channels(dict[int,Channel])は同限月履歴。
    返り値: tuple[list[dict],dict]は純q0と品質。未来OHLCは読まない。
    """
    session=entry['session'];start,end,force=bounds(session)
    cache=np.load(entry['cache_absolute'],allow_pickle=False)
    q=Counter();rows=[];current=None;previous_clock=-np.inf;parts={};minutes=deque(maxlen=20)
    previous_vol=None;previous_vt=None
    fields=('now','line','last','bid','ask','valid','volume','volume_time')
    for t,line,last,bid,ask,valid,vol,vt in zip(*(cache[k] for k in fields)):
        if not np.isfinite(t):q['時計欠測']+=1;continue
        if t<previous_clock:q['時計後退破棄']+=1;continue
        previous_clock=t
        if not start<=t<end:continue
        idx=int((t-start)//60)
        if current is not None and idx>current['index']:
            b=current;delay=t-b['end'];b['published']=float(t)
            complete=b['has_price'] and delay<=30
            q['1分公開数']+=1;q['30秒超確認遅延']+=delay>30
            if complete:
                for size in (5,15,30):
                    group=b['index']//size
                    bucket=parts.setdefault(size,[])
                    if bucket and (bucket[0]['index']//size!=group or bucket[-1]['index']+1!=b['index']):bucket.clear()
                    bucket.append(b)
                    if b['index']%size==size-1:
                        if len(bucket)==size and bucket[0]['index']%size==0:
                            merged={'open':bucket[0]['open'],'high':max(x['high'] for x in bucket),'low':min(x['low'] for x in bucket),
                             'close':bucket[-1]['close'],'end':b['end']}
                            channels[size].update(merged,float(t))
                        bucket.clear()
                contiguous=bool(minutes) and minutes[-1]['index']+1==b['index']
                if not contiguous:minutes.clear()
                c5=channels[5].last;c15=channels[15].last;c30=channels[30].last
                # ----------------------------------------
                # 公開された価格構造と過去だけの相対量。準備不足は0にしない。
                prior=list(minutes)[-3:];prior20=list(minutes)
                rv=None
                if len(prior20)==20 and b['volume_ok'] and all(x['volume_ok'] for x in prior20):
                    avg=sum(x['volume'] for x in prior20)/20
                    rv=b['volume']/avg if avg>0 else None
                fresh=lambda x,size:x is not None and t-x['published']<=size*60+30
                if c5 is not None and c5['count']>=21 and fresh(c5,5) and fresh(c15,15) and c15['count']>=8 and len(prior)==3 and valid and t<force:
                    atr=c5['atr'];r=b['high']-b['low']
                    if atr>0:
                        row={'session':session,'time':float(t),'line':int(line),'band':band(float(t),session),
                          'close':b['close'],'body':(b['close']-b['open'])/atr,'progress':(b['close']-prior[-1]['close'])/atr,
                          'position':(b['close']-b['low'])/r if r else .5,'high':b['high'],'low':b['low'],
                          'prior_high':max(x['high'] for x in prior),'prior_low':min(x['low'] for x in prior),
                          'prior_close':prior[-1]['close'],'atr':atr,'range':r/atr,'rvol':rv,
                          'live':(last-b['close'])/atr if np.isfinite(last) else None,'spread':float(ask-bid),
                          'm5':dict(c5),'m15':dict(c15),'m30':dict(c30) if fresh(c30,30) and c30['count']>=8 else None}
                        rows.append(row)
                minutes.append(b)
            else:
                minutes.clear();parts.clear()
            current=None
        if current is None:
            current={'index':idx,'start':start+idx*60,'end':start+(idx+1)*60,'open':None,'high':-np.inf,'low':np.inf,'close':None,
              'volume':0.,'volume_ok':previous_vol is not None,'has_price':False}
        if np.isfinite(last) and last>0:
            if current['open'] is None:current['open']=float(last)
            current['high']=max(current['high'],float(last));current['low']=min(current['low'],float(last));current['close']=float(last);current['has_price']=True
        if np.isfinite(vol) and np.isfinite(vt) and vol>=0 and vt<=t:
            if previous_vol is not None and vol>=previous_vol and vt>=previous_vt:current['volume']+=float(vol-previous_vol)
            else:current['volume_ok']=False
            previous_vol=float(vol);previous_vt=float(vt)
        elif not np.isfinite(vol) or not np.isfinite(vt):current['volume_ok']=False
    q['q0数']=len(rows);q['観測終端']=float(previous_clock) if np.isfinite(previous_clock) else None
    return rows,{key:(value.item() if isinstance(value,np.generic) else value) for key,value in q.items()}


def roles(row,side):
    """
    機能: 売買対称の複合入口13案を当時特徴から判定する。
    引数: row(dict),side(int)は+1/-1。
    返り値: list[bool]は候補順の成立。
    """
    m5,m15,m30=row['m5'],row['m15'],row['m30'];a=row['atr'];c=row['close'];rv=row['rvol']
    slope=lambda m:m is not None and m['slope'] is not None and side*m['slope']>0
    bg=slope(m5) and slope(m15);long=slope(m30)
    motion=side*row['body']>0 and side*row['progress']>0
    hist=side*m5['hist'];hd=side*(m5['hist_delta'] or 0);rd=side*(m5['rsi_delta'] or 0)
    rsi=m5['rsi'] if side==1 else 100-m5['rsi'];dist=side*(c-m5['ema8'])/a
    quality=0<row['spread']<=1.5 and row['range']<=2.5 and row['live'] is not None and side*row['live']>=-.25
    if not quality:return [False]*len(NAMES)
    t0=bg and hist>=0 and 45<=rsi<=78 and motion
    t1=t0 and -.25<=dist<=1.5 and row['range']<=1.5 and rv is not None and rv>=.5
    t2=t1 and long and hd>=0 and rsi<=75
    t3=bg and motion and side*(row['prior_close']-m5['ema8'])<=0<side*(c-m5['ema8']) and hd>=0 and 40<=rsi<=72 and rv is not None and rv>=.5
    edge=row['prior_high'] if side==1 else row['prior_low'];beyond=side*(c-edge)/a
    t4=bg and motion and 0<beyond<=.5 and 0<=dist<=1.5 and hist>=0 and rv is not None and rv>=1.2 and rsi<=78
    pos=row['position'] if side==1 else 1-row['position']
    bz=m5['bbz'];weak=m5['adx']<25
    r0=weak and bz is not None and side*bz<=-.5 and motion and pos>=.6 and rd>0 and hd>=0 and rsi<=55
    back=row['prior_low'] if side==1 else row['prior_high'];extreme=row['low'] if side==1 else row['high']
    r1=side*(extreme-back)<=0 and side*(c-back)>0 and motion and pos>=.65 and hd>=0 and rd>=0 and rsi<=60 and rv is not None and rv>=.5
    r2=hist<0 and hd>0 and rd>0 and motion and pos>=.65 and 0<dist<=1 and rsi<=60 and rv is not None and rv>=.5
    return [t0,t1,t2,t3,t4,r0,r1,r2,t1 or r1,t2 or r2,(t1 if m5['adx']>=25 else r0 or r1),t3 or t4 or r1,(t0 or r0) and row['range']<=1.5]


def config():
    """
    機能: 金融前の候補・商品・執行・選択を固定する。
    引数: なし。
    返り値: dictは研究条件。
    """
    return {'試行':183,'対象':'TOPIX','商品':'ミニTOPIX1枚換算、ラージBBO代用','候補':list(NAMES),'IFD同幅pt':list(WIDTHS),
      '保有期限秒':3600,'費用':{'乗数':1000,'mini呼値':.25,'片道手数料':41.8,'片道滑り主':.25,'滑り感度':list(SLIPS)},
      '足':'原板価格時計の確定1分を最初の後続観測で公開。遅延30秒超は不採用。5/15/30分は完全連続足のみ。同限月で指標carry、場の価格構造/量窓reset。',
      '指標':'EMA8/21、MACD12/26/9、Wilder14 ATR/RSI/DI/ADX、BB20σ。EMA初値は最初終値、Wilder初値は最初値。5分21本/15分8本/30分使用時8本の最低履歴。',
      '注文':'q0+1秒以上の最初正常BBOで新規、TTL30秒。保有・予約合計1、退出後の後続q0へ再参加。IFD利確は常設指値、触れた原行で目標価格へ保守的に約定代用。損切りは触れた1秒後正常BBO、期限も1秒後正常BBOで返済。',
      '終端':'15:29/05:44に新規・予約停止と全返済要求、15:30/05:45まで。正常板空白300秒超で金融未知、未知枠は場末まで保持。未到達/金融未知を区別。',
      '順位':'適合(両中央値下限正・全場取得・保有下限20%・同幅T0より未知非増加)を先に、赤字場率上限/最悪連続5場/最悪場/連続赤字上限/赤字取引率上限/損失取得比/DD/参加の順。金額は未知を除く既知寄与。総利益最大化はしない。',
      '期間':'全81既使用の研究として扱う。前48選択と全80選択を分離、後25/追加7/本日1は診断。TOPIXで旧66補助参照があり未見性能とは呼ばない。',
      '公式':'https://www.jpx.co.jp/derivatives/products/domestic/mini-topix-futures/01.html','確認日':'2026-11-17'}


def pure():
    """
    機能: 損益を読む前に全場純特徴・入口と条件を保存する。
    引数: なし。
    返り値: None。
    """
    manifest=read(HERE/'入力台帳.json');channels={s:Channel() for s in (5,15,30)};contract=None
    result=[];qualities=[]
    for e in manifest['entries']:
        if contract!=e['in_session_contract_codes']:
            channels={s:Channel() for s in (5,15,30)};contract=e['in_session_contract_codes']
        rows,q=bars_and_features(e,channels)
        for r in rows:
            plus=roles(r,1);minus=roles(r,-1)
            r['signals']=[1 if a and not b else -1 if b and not a else 0 for a,b in zip(plus,minus)]
        result+=rows;qualities.append({'session':e['session'],**q})
        print(e['session'],len(rows),flush=True)
    save(HERE/'純特徴.json.gz',result);save(HERE/'入力品質.json',qualities)
    cfg=config();cfg['SourceSHA']=sha(Path(__file__));cfg['入力台帳SHA']=sha(HERE/'入力台帳.json');cfg['純特徴SHA']=sha(HERE/'純特徴.json.gz')
    assert not (HERE/'条件.json').exists()
    save(HERE/'条件.json',cfg)
    save(HERE/'純成立数.json',{'全q0':len(result),'候補':{name:{'全体':sum(r['signals'][i]!=0 for r in result),
      '成立場数':len({r['session'] for r in result if r['signals'][i]})} for i,name in enumerate(NAMES)}})


class Route:
    """単純IFDの原行経路を一場一度だけ索引化する。"""
    def __init__(self,entry):
        """
        機能: 原順の正常BBOを保持し、区間木を構築する。
        引数: entry(dict)は入力。
        返り値: None。
        """
        spec=importlib.util.spec_from_file_location('topix183tree',ROOT/'scripts/入口分析/分析.py')
        mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
        self.session=entry['session'];self.start,self.end,self.force=bounds(self.session)
        z=np.load(entry['cache_absolute'],allow_pickle=False)
        t=z['now'];finite=np.isfinite(t);prior=np.maximum.accumulate(np.where(finite,t,-np.inf))
        mask=finite&(t>=self.start)&(t<self.end)&(t>=prior)&z['valid']
        self.t=t[mask];self.line=z['line'][mask];self.bid=z['bid'][mask];self.ask=z['ask'][mask]
        self.trees=[mod.到達木(self.bid),mod.到達木(self.ask)]
        self.gaps=np.flatnonzero(np.diff(self.t)>300)+1

    def cell(self,q0,line,side,width):
        """
        機能: 一注文から単純IFDの実BBO返済を評価する。
        引数: q0(float),line(int),side(int),width(float)。
        返り値: dict|Noneは取得後結果又はTTL失効。
        """
        i=int(np.searchsorted(self.t,q0+1));limit=min(q0+30,self.force)
        if i>=len(self.t) or self.t[i]>limit or self.t[i]>=self.force:return None
        opened=float(self.t[i]);price=float(self.ask[i] if side==1 else self.bid[i]);mark=self.bid if side==1 else self.ask
        deadline=min(opened+3600,self.force);last=int(np.searchsorted(self.t,deadline,side='right'))
        tree=self.trees[0 if side==1 else 1]
        touch=tree.first(i+1,last,price-width,price+width)
        reason='期限';j=None;target=deadline;label='N';exit_price=None
        if touch is not None:
            favorable=side*(mark[touch]-price)>=width;label='F' if favorable else 'A'
            if favorable:
                reason='IFD利確';j=touch;target=float(self.t[touch]);exit_price=price+side*width
            else:
                reason='IFD損切';target=float(self.t[touch]);j=int(np.searchsorted(self.t,target+1))
        else:j=int(np.searchsorted(self.t,target+1))
        maxfill=min(target+30,self.end)
        valid=j<len(self.t) and self.t[j]<=maxfill
        if valid and exit_price is None:exit_price=float(mark[j])
        stop_index=j if valid else min(int(np.searchsorted(self.t,maxfill)),len(self.t)-1)
        gaps=self.gaps[(self.gaps>i)&(self.gaps<=stop_index)]
        unknown=not valid or bool(len(gaps))
        if len(gaps):known_until=float(self.t[gaps[0]-1]);why='正常板300秒超空白'
        elif not valid:known_until=float(self.t[-1]) if len(self.t) else opened;why='返済時計不足'
        else:known_until=float(self.t[j]);why=None
        if unknown and touch is not None and len(gaps) and gaps[0]<=touch:label='C'
        elif unknown and touch is None:label='C'
        return {'session':self.session,'side':side,'request_time':q0,'request_line':line,'entry_time':opened,'entry_line':int(self.line[i]),'entry_price':price,
          'exit_time':None if unknown else float(self.t[j]),'exit_line':None if unknown else int(self.line[j]),'exit_price':None if unknown else exit_price,
          'width':width,'label':label,'reason':reason,'unknown':unknown,'unknown_reason':why,'known_until':min(max(known_until,opened),self.end),
          'gross_pt':None if unknown else side*(exit_price-price),'band':band(q0,self.session)}


def main():
    """
    機能: 純生成又は固定条件の金融評価を選ぶ。
    引数: CLI --pure(bool)。
    返り値: None。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--pure',action='store_true');args=parser.parse_args()
    if args.pure:pure()
    else:raise SystemExit('金融評価は別runnerから固定Sourceを参照する')


if __name__=='__main__':main()
