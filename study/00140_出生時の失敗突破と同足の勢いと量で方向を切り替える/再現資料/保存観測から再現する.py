"""140を恒久保存と共有参照から新規workへ復元し、保存正逆観測だけで再集計する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL=Path(__file__).resolve().parent.parent
ROOT=FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 保存原文の指紋を求める。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(root: Path,name: str,body: bytes) -> None:
    """
    機能: 復元先の内側だけへ原文を保存する。
    引数: root(Path)、name(str)、body(bytes)。
    返り値: None。既存先は同体だけ許す。
    """
    path=(root/name).resolve();assert path.is_relative_to(root)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==body
    else:
        with path.open('xb') as f:f.write(body)


# ----------------------------------------
def main() -> None:
    """
    機能: 固定原文40/42源と継承源を復元し、任意で全金融表を再現する。
    引数: CLI --destination(Path)、--replay/--with-post(bool)。
    返り値: None。新Source/Raw/巨大入力/実約定は生成しない。
    """
    p=argparse.ArgumentParser()
    p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--replay',action='store_true');p.add_argument('--with-post',action='store_true')
    args=p.parse_args();dest=args.destination.resolve();assert dest.is_relative_to(ROOT/'work') and not dest.exists()
    dest.mkdir(parents=True);m=json.loads((FORMAL/'保管索引.json').read_bytes())
    groups=[m['追加固定資料']]+m['共有固定コード群']+[m['後段再現用継承源']]
    if args.with_post:groups.append(m['後発資料'])
    for item in groups:
        archive=ROOT/item['保存元ZIP'] if '保存元ZIP' in item else FORMAL/'再現資料'/item['ZIP']
        assert sha(archive.read_bytes())==item['ZIP_SHA256']
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for x in item['格納源']:
                body=z.read(x.get('ZIP内path',x.get('path')));assert sha(body)==x['sha256']
                put(dest,x.get('復元先',x.get('path')),body)
    for x in m['共有入力']+m['新共用入力']:
        body=(ROOT/x['保存元']).read_bytes();assert sha(body)==x['保存SHA256']
        raw=gzip.decompress(body) if x['形式']=='gzip' else body;assert sha(raw)==x['解凍SHA256']
        put(dest,x['復元先'],raw)
    original=(FORMAL/'検査/F1金融前.json').read_bytes();assert sha(original)==m['F1_SHA256']
    f1=json.loads(original);put(dest,'元F1金融前.json',original)
    source_root=next(Path(n).parents[2] for n in f1['ファイル'] if n.endswith('00140_出生時の失敗突破と同足の勢いと量で方向を切り替える\\README.md'))
    excluded={x['path'] for x in m['意図して複製しない固定源']};mapped={}
    for name,h in f1['ファイル'].items():
        relative=Path(name).relative_to(source_root).as_posix()
        if relative in excluded:assert not (dest/relative).exists();continue
        target=dest/relative;assert sha(target.read_bytes())==h;mapped[str(target)]=h
    assert len(mapped)==40
    proof={'成功':True,'試行':140,'元F0_SHA256':m['F0_SHA256'],'元F1_SHA256':sha(original),'F1直接40/42源同体':True,
        '意図した非複製':sorted(excluded),'Raw/177MB/77MB/追加2場読取':False,'新自然抽出/金融観測':False,'事前固定の偽造':False}
    if args.replay:
        choices=dest/'work/140失敗突破の評価/方向票/全752の方向.json'
        fixed=json.loads(choices.read_bytes());original_choices_sha=sha(choices.read_bytes())
        fixed['sources']={str(dest/Path(n).relative_to(source_root)):h for n,h in fixed['sources'].items()}
        adapted=(json.dumps(fixed,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        adapted_path=dest/'再現用のパス変更方向票.json';put(dest,adapted_path.name,adapted)
        mapped[str(adapted_path)]=sha(adapted)
        ledger={'試行':140,'用途':'金融後の保存観測再現用。金融前F1ではない','元F1_SHA256':sha(original),
            '方向票変更':'sourcesの絶対パスだけ復元先へ移す。全752方向/9gate/取得/数値は不変','ファイル':mapped}
        ledger_raw=(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        ledger_path=dest/'再現専用パス台帳.json';put(dest,ledger_path.name,ledger_raw)
        model=dest/'work/140失敗突破の方向票と集計/固定条件.json';output=dest/'再集計'
        command=[sys.executable,'-X','utf8',str(dest/'work/140失敗突破の方向票と集計/集計する.py')]
        for name,path in [('f1',ledger_path),('model',model),('choices',adapted_path)]:
            command += ['--'+name,str(path),'--'+name+'-sha256',sha(path.read_bytes())]
        command += ['--output-dir',str(output)]
        run=subprocess.run(command,cwd=dest,text=True,encoding='utf-8',capture_output=True)
        assert run.returncode==0,run.stderr+run.stdout
        new=json.loads((output/'集計.json').read_bytes());old=json.loads((FORMAL/'成果物/集計.json').read_bytes())
        assert old['方向SHA256']==original_choices_sha and old['F1_SHA256']==sha(original)
        for key in ('方向SHA256','F1_SHA256'):new.pop(key);old.pop(key)
        assert new==old
        assert sha((output/'CSV用の表.json').read_bytes())=='6e15f4899b32d70c1b1844c9f336e375f27055f2a077c20b564975e328bd6d40'
        proof.update({'保存全正逆から全180金融条件同体':True,'39_685表セルと三表JSONbytes同体':True,
            '相違は金融後台帳/方向票sourcesパスの2指紋だけ':True,'主320/303/76/53とC5差引同体':True,'再現台帳SHA256':sha(ledger_raw),
            '再現方向票SHA256':sha(adapted),'元方向票SHA256':original_choices_sha})
    raw=(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode('utf-8');put(dest,'保存観測の再現確認.json',raw)
    print(json.dumps({'成功':True,'再現確認SHA256':sha(raw),'金融再現':args.replay},ensure_ascii=False))


if __name__=='__main__':main()
