"""144の先行保管51源と保存観測を復元し、Rawを走査せず金融だけ再現する。"""
from pathlib import Path, PureWindowsPath
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL=Path(__file__).resolve().parents[1]
ROOT=FORMAL.parent.parent


def sha(raw: bytes) -> str:
    """
    機能: 原文bytesの指紋を求める。
    引数: raw(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------
def relative(original: str) -> str:
    """
    機能: 元Windows絶対pathをrepository相対pathへ変換する。
    引数: original(str)。
    返り値: strはwork/study/inputs配下の安全な相対path。
    """
    parts=PureWindowsPath(original).parts;at=next(i for i,x in enumerate(parts) if x in ('work','study','inputs'))
    result=Path(*parts[at:]);assert not result.is_absolute() and '..' not in result.parts;return result.as_posix()


# ----------------------------------------
def main() -> None:
    """
    機能: 固定原文を復元し、任意で保存133観測から300比較を再集計する。
    引数: --destination(Path)は未作成work宛先、--replay(bool)。
    返り値: None。Source/Raw/価格CSV/177MB/2exe再生成や新金融観測は行わない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True);parser.add_argument('--replay',action='store_true');args=parser.parse_args()
    dest=(ROOT/args.destination).resolve() if not args.destination.is_absolute() else args.destination.resolve()
    assert dest.is_relative_to((ROOT/'work').resolve()) and not dest.exists()
    m=json.loads((FORMAL/'保管索引.json').read_bytes());bodies={};excluded={}
    def put(rel: str, raw: bytes, expected: str) -> None:
        """
        機能: 保存指紋と相対pathの安全性を確認して復元登録する。
        引数: rel(str)、raw(bytes)、expected(str)。
        返り値: None。
        """
        p=Path(rel);assert not p.is_absolute() and '..' not in p.parts and sha(raw)==expected
        assert rel not in bodies or bodies[rel]==raw;bodies[rel]=raw
    def restore(item: dict) -> None:
        """
        機能: shared ZIP/gzip/原文snapshotを同bytesで解決する。
        引数: item(dict)は保存参照。
        返り値: None。
        """
        if '保存元ZIP' in item:
            zp=ROOT/item['保存元ZIP'];assert sha(zp.read_bytes())==item['ZIP_SHA256']
            with zipfile.ZipFile(zp) as z:raw=z.read(item['ZIP内path'])
            put(item['復元先'],raw,item['sha256']);return
        p=ROOT/item['保存元'];raw=p.read_bytes()
        if item['形式']=='文書snapshot':
            doc=json.loads(gzip.decompress(raw));r=next(d for d in doc['文書'] if d['path']==item['抽出キー'])
            put(item['復元先'],r['本文'].encode('utf-8'),item['sha256']);return
        assert sha(raw)==item['保存SHA256'];decoded=gzip.decompress(raw) if item['形式']=='gzip' else raw
        put(item['復元先'],decoded,item['解凍SHA256'])
    for stage in ('F0復元参照','F1増分復元参照'):
        group=m[stage]
        for kind in ('文書snapshot','共有入力','共有コード','保存済み参照'):
            for item in group[kind]:restore(item)
        archive=group['固定ZIP'];zp=FORMAL/'再現資料'/archive['ZIP'];assert sha(zp.read_bytes())==archive['ZIP_SHA256']
        with zipfile.ZipFile(zp) as z:
            for item in archive['格納源']:put(item['path'],z.read(item['path']),item['sha256'])
        for item in group['意図して非複製']:excluded[item['path']]=item
    f1raw=(FORMAL/'検査/F1金融前.json').read_bytes();assert sha(f1raw)==m['F1_SHA256'];f1=json.loads(f1raw)
    declared={relative(name):h for name,h in f1['ファイル'].items()};assert len(declared)==54 and len(excluded)==3
    assert set(declared)==set(bodies)|set(excluded)
    for name,h in declared.items():
        if name not in excluded:assert sha(bodies[name])==h
    assert len(bodies)==51
    restore(m['保存済み正逆観測'])
    put('work/144旧strongの全成立評価/F1金融前.json',f1raw,m['F1_SHA256'])
    for name,raw in bodies.items():
        p=dest/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write(raw)
    proof={'成功':True,'試行':144,'全54参照を解決/保存51源同bytes':True,'非複製':list(excluded),
        '177MB/2exeの実bytes復元を主張':False,'新Source/Raw/価格CSV/出生/新金融観測/追加2場読取':False,
        '元F0/F1/正式MDの固定原文を復元':True,'元F1_SHA256':m['F1_SHA256']}
    if args.replay:
        ledger={'試行':144,'用途':'金融後の保存観測再集計専用path台帳。金融前F1の後造りではない',
            '元F1_SHA256':m['F1_SHA256'],'ファイル':{str(dest/name):h for name,h in declared.items()}}
        path=dest/'再現専用path台帳.json';path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        fixed=dest/'work/144旧strongの全成立評価/固定入力/固定取得入力.json';metadata=dest/'work/144旧strongの全成立評価/固定入力/入口参照.json'
        result=dest/'work/144旧strongの全成立評価/固定取得の正逆観測.json';output=dest/'再集計'
        command=[sys.executable,'-X','utf8',str(dest/'work/144旧strongの全成立集計/集計する.py')]
        for name,p in [('f1',path),('fixed-input',fixed),('metadata',metadata),('result',result)]:command += ['--'+name,str(p),'--'+name+'-sha256',sha(p.read_bytes())]
        command += ['--output-dir',str(output)]
        run=subprocess.run(command,cwd=dest,text=True,encoding='utf-8',capture_output=True);assert run.returncode==0,run.stderr+run.stdout
        old=json.loads((FORMAL/'成果物/集計.json').read_bytes());new=json.loads((output/'集計.json').read_bytes())
        assert old.pop('F1_SHA256')==m['F1_SHA256'];new.pop('F1_SHA256');assert old==new
        assert sha((output/'CSV用の表.json').read_bytes())==m['表JSON再現期待SHA256']
        proof.update({'全300/参加頻度/union/phase/旧C0同体':True,'三表JSON全bytes同体':True,'集計差は再現台帳F1指紋だけ':True,
            '保存観測再集計でSource/原板を再生しない':True,'再現台帳SHA256':sha(path.read_bytes())})
    p=dest/'保存観測からの再現確認.json';p.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'成功':True,'確認SHA256':sha(p.read_bytes()),'保存51源同体':True,'再集計':args.replay},ensure_ascii=False))


if __name__=='__main__':main()
