"""137の保存資料を新規workへ復元し、Rawなしで集計を再現する。"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import zipfile

FORMAL = Path(__file__).resolve().parent.parent
ROOT = FORMAL.parents[1]


def sha(body: bytes) -> str:
    """
    機能: 復元資料の指紋を求める。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def put(destination: Path, name: str, body: bytes) -> None:
    """
    機能: 復元先内へ同体原文を配置する。
    引数: destination(Path)、name(str)、body(bytes)。
    返り値: None。既存は完全同体だけ許す。
    """
    target = (destination / name).resolve(); assert target.is_relative_to(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == body, name
    else:
        with target.open('xb') as handle:
            handle.write(body)


# ----------------------------------------
def main() -> None:
    """
    機能: 90直接源と共有依存を復元し、任意に保存239観測だけを再集計する。
    引数: CLI --destination(Path)、--replay(bool)。
    返り値: None。新F1・Raw走査・Source再実行・金融観測は作らない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args(); destination = args.destination.resolve()
    assert destination.is_relative_to(ROOT / 'work') and not destination.exists()
    destination.mkdir(parents=True)
    m = json.loads((FORMAL / '保管索引.json').read_bytes())
    groups = [('新', m['F1追加資料'])] + [('共有', x) for x in m['F1共有コード群']]
    groups += [('共有', m['継承する再現用共有依存']), ('旧kernel', m['後段の再現用継承源'])]
    for kind, item in groups:
        path = FORMAL / '再現資料' / item['ZIP'] if kind == '新' else ROOT / item['保存元ZIP']
        assert sha(path.read_bytes()) == item['ZIP_SHA256']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            for source in item['格納源']:
                entry = source['path'] if kind in ('新', '旧kernel') else source['ZIP内path']
                target = source['path'] if kind in ('新', '旧kernel') else source['復元先']
                body = z.read(entry); assert sha(body) == source['sha256']
                put(destination, target, body)
    for item in m['F1共有入力'] + m['新金融入力'] + [m['保存済み正逆観測']]:
        body = (ROOT / item['保存元']).read_bytes(); assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body) if item['形式'] == 'gzip' else body
        assert sha(decoded) == item['解凍SHA256']
        put(destination, item['復元先'], decoded)
    original = (FORMAL / '検査/F1.json').read_bytes(); assert sha(original) == m['F1_SHA256']
    put(destination, '原金融前F1.json', original)
    f1 = json.loads(original)
    old_root = next(Path(p).parents[2] for p in f1['ファイル'] if p.endswith('00137_市場終端後の既知回復を公表時点で確認する\\README.md'))
    excluded = {x['path'] for x in m['意図して複製しないF1源']}
    mapped = {}; count = 0
    for p, expected in f1['ファイル'].items():
        relative = Path(p).relative_to(old_root).as_posix()
        if relative in excluded:
            assert not (destination / relative).exists()
            continue
        target = destination / relative; assert sha(target.read_bytes()) == expected, relative
        mapped[str(target)] = expected; count += 1
    assert count == 90
    proof = {'成功': True, '試行': 137, '原F1_SHA256': sha(original), 'F1全93中90源同体': True,
             '意図して複製しない3源': sorted(excluded), '継承共有依存数': 10,
             '旧kernel再現源数': m['後段の再現用継承源']['格納源数'],
             'Source/Raw/177MB/追加2場再読': False, '原F1を書換': False}
    if args.replay:
        ledger = {'用途': '金融後の保存観測再現専用のパス台帳。金融前F1ではない',
                  '原F1_SHA256': sha(original), '未複製3源の省略': True, 'ファイル': mapped}
        ledger_body = (json.dumps(ledger, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        ledger_path = destination / '再現専用パス台帳.json'; put(destination, ledger_path.name, ledger_body)
        fixed = destination / 'work/137既知回復の評価/固定入力/固定取得入力.json'
        metadata = fixed.with_name('方向と出生.json')
        result = destination / m['保存済み正逆観測']['復元先']
        command = [sys.executable, '-X', 'utf8', str(destination / 'work/137既知回復と頻度の集計/集計する.py')]
        for name, path in [('f1', ledger_path), ('fixed-input', fixed), ('metadata', metadata), ('result', result)]:
            command += ['--' + name, str(path), '--' + name + '-sha256', sha(path.read_bytes())]
        output = destination / '再集計'; command += ['--output-dir', str(output)]
        completed = subprocess.run(command, cwd=destination, capture_output=True, text=True, encoding='utf-8', check=True)
        generated = json.loads((output / '集計.json').read_bytes())
        expected = json.loads((FORMAL / '成果物/集計.json').read_bytes())
        assert generated.pop('F1_SHA256') == sha(ledger_body)
        expected.pop('F1_SHA256'); assert generated == expected
        table_sha = sha((output / 'CSV用の表.json').read_bytes())
        assert table_sha == '9c88bea44a03c6c92198f15c5a06410cb2f48b5f63e494fb17814d48ceae6aeb'
        proof.update({'保存観測239件のみを再集計': True, '全金融数値/旧対照/頻度/phase/bootstrap一致': True,
                      '全三表bytes一致_SHA256': table_sha, '変更値は再現用パス台帳SHA参照だけ': True,
                      '再現専用台帳SHA256': sha(ledger_body), '集計CLI成功': completed.returncode == 0})
    put(destination, '保存資料の再現確認.json', (json.dumps(proof, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    main()
