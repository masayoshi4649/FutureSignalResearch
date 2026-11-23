"""141の保存入力と保存実正逆だけで300比較と三表を再現する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys

FORMAL=Path(__file__).resolve().parent.parent
ROOT=FORMAL.parents[1]


def sha(raw: bytes) -> str:
    """
    機能: 原文の指紋を求める。
    引数: raw(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------
def main() -> None:
    """
    機能: 復元専用台帳に保存観測を結び、固定算術だけを再実行する。
    引数: CLI --destination(Path)は未作成のwork先。
    返り値: None。Raw/CSV/Source/新金融観測を生成しない。
    """
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True);args=p.parse_args()
    dest=args.destination.resolve();assert dest.is_relative_to(ROOT/'work') and not dest.exists()
    subprocess.run([sys.executable,'-X','utf8',str(FORMAL/'再現資料/F1保存資料を復元する.py'),'--destination',str(dest)],check=True)
    m=json.loads((FORMAL/'保管索引.json').read_bytes());item=m['保存済み正逆観測'];body=(ROOT/item['保存元']).read_bytes();assert sha(body)==item['保存SHA256']
    observed=gzip.decompress(body);assert sha(observed)==item['解凍SHA256'];result=dest/item['復元先'];result.parent.mkdir(parents=True,exist_ok=True);result.write_bytes(observed)
    ledger=json.loads((dest/'F1復元だけの参照台帳.json').read_bytes());ledger={'試行':141,'用途':'金融後の保存観測再集計専用。金融前F1ではない','元F1_SHA256':m['F1_SHA256'],'ファイル':ledger['ファイル']}
    path=dest/'再集計専用パス台帳.json';path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    fixed=dest/'work/141VWMA独立入口の評価/固定入力/固定取得入力.json';meta=fixed.with_name('入口参照.json');output=dest/'再集計'
    command=[sys.executable,'-X','utf8',str(dest/'work/141独立入口とunionの集計/集計する.py')]
    for n,x in [('f1',path),('fixed-input',fixed),('metadata',meta),('result',result)]:command += ['--'+n,str(x),'--'+n+'-sha256',sha(x.read_bytes())]
    command += ['--output-dir',str(output)]
    run=subprocess.run(command,cwd=dest,text=True,encoding='utf-8',capture_output=True);assert run.returncode==0,run.stderr+run.stdout
    actual=json.loads((output/'集計.json').read_bytes());original=json.loads((FORMAL/'成果物/集計.json').read_bytes())
    assert original['F1_SHA256']==m['F1_SHA256'];actual.pop('F1_SHA256');original.pop('F1_SHA256');assert actual==original
    assert sha((output/'CSV用の表.json').read_bytes())==m['表JSON再現期待SHA256']
    proof={'成功':True,'試行':141,'全300比較/参加/頻度/旧81/phase同体':True,'三表JSON全bytes同体':True,'唯一の集計差':'金融後再現専用パス台帳のF1_SHA256',
        '原F0/F1改変/事前固定の後造り':False,'新Raw/CSV/Source/金融観測':False,'元F1_SHA256':m['F1_SHA256'],
        '再現台帳SHA256':sha(path.read_bytes()),'三表JSON_SHA256':m['表JSON再現期待SHA256']}
    p=dest/'保存観測の再現確認.json';p.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'成功':True,'保存観測の再現確認SHA256':sha(p.read_bytes()),'300比較/三表bytes同体':True},ensure_ascii=False))


if __name__=='__main__':main()
