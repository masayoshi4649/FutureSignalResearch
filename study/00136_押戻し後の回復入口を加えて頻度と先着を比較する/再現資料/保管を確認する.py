"""136の非金融同体試行の原文・復元・Source・原因・リンクを確認する。"""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import argparse
import gzip
import hashlib
import json
import re
import zipfile


def sha(body: bytes) -> str:
    """
    機能: 確認する原文の指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def cells(text: str) -> dict:
    """
    機能: 56手法と9尺度の504セルを抽出する。
    引数: text(str)。
    返り値: dictはIDごとの9セル。
    """
    out={}
    for line in text.splitlines():
        if re.match(r'^\| [A-Z][0-9]{2} ',line):
            p=[x.strip() for x in line.split('|')[1:-1]]
            if len(p)==11:out[p[0]]=p[2:]
    assert len(out)==56
    return out


# ----------------------------------------
def main() -> None:
    """
    機能: 新金融を作らなかった136の正本と復元先を照合し、最終確認を保存する。
    引数: CLI --restored(Path)、--output(Path|None)。
    返り値: None。Raw/177MB/追加場・新先着/損益を読まず計算しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--restored',type=Path,required=True);parser.add_argument('--output',type=Path)
    args=parser.parse_args();formal=Path(__file__).resolve().parent.parent;root=formal.parents[1]
    restored=args.restored.resolve();assert restored.is_relative_to(root/'work')
    m=json.loads((formal/'保管索引.json').read_bytes())
    f0body=(formal/'検査/F0.json').read_bytes();assert sha(f0body)==m['F0_SHA256']=='3fe3ceae426787b689145fd7aa7730b4bc27ea1dfbb918c93f3d66eb463211ba'
    assert (restored/'work/136押戻し回復の評価/F0.json').read_bytes()==f0body
    f0=json.loads(f0body);old_root=next(Path(p).parents[2] for p in f0['ファイル'] if p.endswith('study\\00136_押戻し後の回復入口を加えて頻度と先着を比較する\\README.md'))
    excluded={x['path'] for x in m['意図して複製しないF0源']};restored_count=0
    for p,h in f0['ファイル'].items():
        relative=Path(p).relative_to(old_root).as_posix()
        if relative in excluded:
            assert not (restored/relative).exists();continue
        assert sha((restored/relative).read_bytes())==h,relative;restored_count+=1
    assert restored_count==61 and len(excluded)==2
    archive_records={}
    for key in ('F0追加資料','F0共有コード','間接固定の共有依存','後発資料'):
        item=m[key];path=formal/'再現資料'/item['ZIP'] if 'ZIP' in item else root/item['保存元ZIP']
        assert sha(path.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            if 'ZIP' in item:assert len(z.namelist())==item['格納源数']
            for source in item['格納源']:
                name=source.get('path',source.get('ZIP内path'));target=source.get('復元先',name)
                body=z.read(name);assert sha(body)==source['sha256']
                assert (restored/target).read_bytes()==body
        archive_records[key]={'sha256':item['ZIP_SHA256'],'源数':item['格納源数']}
    assert m['F0追加資料']['格納源数']==47 and m['F0共有コード']['格納源数']==13 and m['間接固定の共有依存']['格納源数']==10
    snap=json.loads(gzip.decompress((formal/'検査/実行前文書_F0.json.gz').read_bytes()))
    assert len(snap['文書'])==12 and snap['正式文書数']==4
    for item in snap['文書']:
        body=item['本文'].encode('utf-8');assert sha(body)==item['sha256'] and len(body)==item['bytes']
        assert (restored/item['path']).read_bytes()==body
        if item['path'].endswith('/設定と結果.md'):assert cells(item['本文'])==cells((formal/'設定と結果.md').read_text('utf-8'))
    for item in m['F0共有入力']+[m['新Source入力']]:
        body=(root/item['保存元']).read_bytes();assert sha(body)==item['保存SHA256']
        decoded=gzip.decompress(body);assert sha(decoded)==item['解凍SHA256']
        assert (restored/item['復元先']).read_bytes()==decoded
    source=json.loads(gzip.decompress((root/m['新Source入力']['保存元']).read_bytes()))
    old=json.loads(gzip.decompress((root/m['F0共有入力'][0]['保存元']).read_bytes()))
    assert source['success'] and source['scene_count']==len(source['scenes'])==len(old['scenes'])==73
    assert not source['financial_labels_used'] and not source['portfolio_pnl']
    distribution=Counter();session_kinds=Counter();total=0
    for scene,prior in zip(source['scenes'],old['scenes']):
        assert scene['success'] and scene['raw_passes']==1 and scene['legacy']==prior
        assert not scene['e1_events'] and not scene['e1_candidates']
        a=scene['selection']['C0'];assert a==scene['selection']['S0']==scene['frequency_A0']
        assert len(a)>=1;distribution[len(a)]+=1;total+=len(a)
        session_kinds[scene['session'].rsplit('_',1)[1]]+=1
    assert total==79 and distribution=={1:68,2:4,3:1}
    seconds=session_kinds['Day']*415*60+session_kinds['Night']*775*60
    assert seconds==2595300 and 79/(seconds/3600)==0.1095827072014796
    checks=[('Source非金融の確認.json','006e38a423d2bdb68167e1f5803f1ba46fed7a9ad23b0911f23ed48699dd23e3'),
            ('全方向同体の確認.json','f6d9a5c43202d625b1e88facb298df28dcd17c5e2582d9e3bb4952ff824d1b0e')]
    for name,expected in checks:assert sha((formal/'検査'/name).read_bytes())==expected
    build=json.loads((formal/'検査/F0保存資料の復元確認.json').read_bytes());assert build['成功'] and build['共有依存だけでSourceビルド成功'] and not build['Sourceを起動']
    assert '原因資料' in m and m['原因資料']
    for item in m['原因資料']:
        body=(root/item['保存元']).read_bytes();assert sha(body)==item['保存SHA256']
        decoded=gzip.decompress(body) if item['形式']=='gzip' else body;assert sha(decoded)==item['原文SHA256']
    assert not (formal/'検査/F1.json').exists() and not (formal/'成果物/集計.json').exists()
    assert not (root/'work/136押戻し回復の評価/F1.json').exists()
    assert not any((root/'outputs/01a1889f-f2af-7943-a047-543275ee9ed2').glob('136*'))
    docs=list(formal.rglob('*.md'))+[root/'inputs/00136_E1のSource接続/README.md',root/'docs/議論/押戻し回復の出生ゼロと段階別の原因.md']
    links=0
    for path in docs:
        for target in re.findall(r'\]\(([^)]+)\)',path.read_text('utf-8')):
            if target.startswith(('http://','https://','#')):continue
            assert (path.parent/target.split('#')[0]).resolve().exists(),(path,target);links+=1
    for name in ('README.md','docs/README.md','docs/議論/README.md','study/README.md'):assert formal.name in (root/name).read_text('utf-8')
    result={'成功':True,'試行':136,'状態':'非金融同体試行として保管完了','確認UTC':datetime.now(timezone.utc).isoformat(),
            'F0原文同体':True,'F0直接61源実復元':True,'間接固定共有依存':10,'原文MD':12,'正式MD':4,'504セル不変':True,
            'コードZIP':archive_records,'保存Sourceを一度gzip':True,'旧73scene辞書全値同体':True,
            'C0_S0_A0全参照同体':True,'全取得':79,'全場':73,'最低取得':1,'場別取得数':dict(distribution),
            'E1出生/取得':0,'全ザラバ秒':seconds,'平均取得毎時':79/(seconds/3600),
            '新金融F1/新集計/新CSVなし':True,'旧成績は今回新計算ではなく継承参照':True,
            '保存源からのビルド成功':True,'Source再起動/新Raw走査':False,'177MB本文/追加2場読取':False,
            '相対リンク確認数':links,'重大不足':[],'確認コードSHA256':sha(Path(__file__).read_bytes())}
    target=args.output.resolve() if args.output else formal/'検査/保管復元の確認.json'
    assert target.is_relative_to(root) and not target.exists()
    with target.open('x',encoding='utf-8') as handle:handle.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'成功':True,'確認SHA256':sha(target.read_bytes()),'F0直接復元':61,'504セル不変':True,'リンク':links,'重大不足':[]},ensure_ascii=False))


if __name__=='__main__':
    main()
