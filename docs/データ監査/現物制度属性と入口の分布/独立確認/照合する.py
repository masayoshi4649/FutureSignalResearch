"""固定4BASEの制度別集計と寄付前10取得を、分類コードを呼ばず照合する。"""
from pathlib import Path
from datetime import datetime,timedelta,timezone,date,time
from collections import Counter
import gzip,json,hashlib,math
ROOT=Path(__file__).resolve().parents[4];HERE=Path(__file__).parent;PARENT=HERE.parent
JST=timezone(timedelta(hours=9))
HOLIDAYS={'2026-09-21','2026-09-22','2026-09-23','2026-10-12','2026-11-03'}
NAMES=('現物終日休場','現物寄付前','現物前場','現物昼休み','現物後場ザラバ','現物引け板寄せ受付')


def read(path):
    """
    機能: 原資料を読み、固定条件や金融を変更しない。
    引数: path(Path)。
    返り値: object。
    """
    raw=path.read_bytes();return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def sha(path):
    """
    機能: 読取資源のSHA256を求める。
    引数: path(Path)。
    返り値: str。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bucket(scene,stamp):
    """
    機能: JST実取得の時刻を秒単位で別分類する。
    引数: scene(str),stamp(float)。
    返り値: str。休日と通常営業日を先に分ける。
    """
    moment=datetime.fromtimestamp(stamp,JST);day=moment.date();assert str(day)==scene[:10] and day.weekday()<5
    if str(day) in HOLIDAYS:return NAMES[0]
    clock=moment.time().replace(tzinfo=None)
    assert time(8,45)<=clock<time(15,30)
    for i,edge in enumerate((time(9),time(11,30),time(12,30),time(15,25),time(15,30)),1):
        if clock<edge:return NAMES[i]
    raise AssertionError(scene)


def aggregate(rows):
    """
    機能: 取得群の費用後既知額と件数を再集計する。
    引数: rows(list[dict])。
    返り値: dict。後続枠や新金融の計算はしない。
    """
    values=[r['net'] for r in rows if r['known']]
    return {'取得':len(rows),'支持場':len({r['scene'] for r in rows}),'未知':len(rows)-len(values),
      '利益':round(sum(v for v in values if v>0),1),'損失':round(-sum(v for v in values if v<0),1),
      '既知収支':round(sum(values),1),'赤字取引':sum(v<0 for v in values)}


def equal(actual,expected):
    """
    機能: 説明JSONの全数値を別集計へ照合する。
    引数: actual/expected(dict)。
    返り値: intは検査属性数。
    """
    assert set(actual)==set(expected)
    for k in actual:assert math.isclose(actual[k],expected[k],abs_tol=1e-6),(k,actual[k],expected[k])
    return len(actual)


def main():
    """
    機能: 全4BASE・全期間・README表と寄付前個票を監査し根拠票だけ保存する。
    引数: なし。
    返り値: None。既存資料の記述を上書きしない。
    """
    sealed=read(PARENT/'分類前固定.json');reported=read(PARENT/'既存取得の制度別診断.json');assert set(sealed['現物休場日'])==HOLIDAYS
    assert sha(ROOT/sealed['Source']['path'])==sealed['Source']['sha256'];checks=0;results=[];before={};all_pre=[]
    for source,written in zip(sealed['入力'],reported,strict=True):
        path=ROOT/source['path'];before[str(path)]=sha(path);assert before[str(path)]==source['sha256'];pack=read(path);assert pack['id']==written['id'];l=pack['ledger'];rows=[];pre=[]
        scenes=[s['scene'] for s in pack['sessions'] if s['kind']=='DAY'];assert len(scenes)==42 and len(set(scenes))==42
        assert {s[:10] for s in scenes if s[:10] in HOLIDAYS}==HOLIDAYS
        current=date.fromisoformat(scenes[0][:10]);last=date.fromisoformat(scenes[-1][:10]);weekdays=set()
        while current<=last:
            if current.weekday()<5:weekdays.add(str(current))
            current+=timedelta(days=1)
        assert {s[:10] for s in scenes}==weekdays
        for i,s in enumerate(l['scene']):
            if not s.endswith('_Day'):continue
            regime=bucket(s,l['entry_time'][i]);rows.append({'scene':s,'known':l['known'][i],'net':l['net'][i],'制度':regime})
            if regime=='現物寄付前':
                entry=datetime.fromtimestamp(l['entry_time'][i],JST);exit_=datetime.fromtimestamp(l['exit_time'][i],JST)
                assert s[:10] not in HOLIDAYS and l['known'][i] and l['net'][i]>0 and exit_.time()>=time(9)
                pre.append({'session':s,'取得':entry.isoformat(),'決済':exit_.isoformat(),'幅':l['width'][i],'期限':l['horizon'][i],
                  '費用後収支':l['net'][i],'case_id':l['case_id'][i],'side':l['side'][i],'entry_line':l['entry_line'][i],'exit_line':l['exit_line'][i]})
        checks+=equal(aggregate(rows),written['全体'])
        groups={n:aggregate([r for r in rows if r['制度']==n]) for n in NAMES}
        for n in NAMES:checks+=equal(groups[n],written['制度別'][n])
        for name,start,stop in (('前48',0,48),('後25',48,73),('追加7',73,80),('本日1',80,81),('追加2',81,83)):
            subset={s['scene'] for s in pack['sessions'][start:stop]}
            for n in NAMES:checks+=equal(aggregate([r for r in rows if r['scene'] in subset and r['制度']==n]),written['期間別'][name][n])
        results.append({'id':pack['id'],'取得':len(rows),'Day分母':len(scenes),'通常営業日':37,'現物休場':5,'全制度別と全期間別':True,'元入力SHA':source['sha256']})
        if pack['id'].startswith('NK225'):
            assert len(pre)==10 and Counter((r['幅'],r['期限']) for r in pre)=={(400,'SESSION'):9,(350,'H60'):1}
            assert sum(r['費用後収支'] for r in pre)==377230.;all_pre.append(pre)
        else:assert not pre
    assert all_pre[0]==all_pre[1]==all_pre[2]
    # ----------------------------------------
    # 表は日経05とTOPIXの同じ群を参照していることまで確認する。
    named={r['id']:r for r in reported};table_checks=0
    for line in (PARENT/'README.md').read_text('utf-8').splitlines():
        c=[v.strip() for v in line.strip('|').split('|')]
        if len(c)!=9 or c[0] not in NAMES:continue
        for offset,identity in ((1,'NK225206_E199_05_BASE'),(5,'TOPIX206_I00_BASE')):
            g=named[identity]['制度別'][c[0]];assert c[offset]==f"{g['取得']}/{g['支持場']}";table_checks+=1
            for j,name in enumerate(('利益','損失','既知収支'),1):
                number=float(c[offset+j].replace(',','').replace('−','-').replace('+',''));assert math.isclose(number,g[name],abs_tol=1e-6);table_checks+=1
    assert table_checks==48
    # ----------------------------------------
    # 211はC0/M208と独立Fで共通取得寄与が異なるため、適用範囲を分ける。
    cause_path=ROOT/'study/00211_固定TOPIX入口に対するIFD期限の寄与を調べる/監査/期限差の実取得分解.json.gz';cause=read(cause_path);scopes=[]
    for row in cause['比較']:
        g=row['帯別']['DAY'];scopes.append({'母体':row['母体'],'期限':row['比較'],'共通取得':g['共通H60']['取得'],
          '共通既知寄与差':g['共通既知寄与差'],'集合差の既知寄与差':g['集合差の既知寄与差']})
    assert all(sha(Path(p))==s for p,s in before.items())
    report={'確認日':'2026-11-18','新条件又は新金融':False,'独立方式':'元分類する.pyをimportせず、JST時刻比較と固定台帳から全群を再集計。休日はJPX一次資料を別途確認。',
      '集計一致':True,'JSON数値属性':checks,'README表属性':table_checks,'固定4BASE':results,
      '寄付前10取得の3母体同体':True,'寄付前個票':all_pre[0],'寄付前期限':{'SESSION_幅400':9,'H60_幅350':1},'全件通常営業日':True,'全件現物寄付後決済':True,
      '制度一次資料':{'確認日':'2026-11-18','休日':'https://www.jpx.co.jp/corporate/about-jpx/calendar/index.html','立会':'https://www.jpx.co.jp/equities/trading/domestic/01.html','15時25分からの引け受付':'https://www.jpx.co.jp/english/systems/equities-trading/01.html'},
      '数値訂正':[],'解釈の限定推奨':[{'箇所':'docs/議論/価格線への試行と定着を分けて入口を考える.md の211項',
        '内容':'Day増益の大半が取得集合差、Night未知増加という説明はC0/208主3へ限定する。F207のDayは共通6件の期限差で、取得集合差0。F207の未知は0のまま。',
        '影響':'現数値・候補条件の誤りではなく適用範囲の明確化。'}],
      '211根拠':scopes,'211根拠SHA':sha(cause_path),'元分類SourceSHA':sealed['Source']['sha256'],'レビューSourceSHA':sha(Path(__file__)),
      '因果説明':'制度別取得群の記述と除外後口座を区別する注意、q0と実取得時刻の区別、為替研究とOSEの区別、旧新枝と後続枠の区別はいずれも妥当。'}
    (HERE/'確認結果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({'集計一致':True,'JSON属性':checks,'表属性':table_checks,'寄付前個票':10,'新金融':False,'解釈の限定推奨':1},ensure_ascii=False))


if __name__=='__main__':main()
