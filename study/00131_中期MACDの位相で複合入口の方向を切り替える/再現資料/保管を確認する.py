"""131の保存・復元・表の不変性を検査する。金融算術やRawは再実行しない。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import gzip
import hashlib
import json
import re
import zipfile

NAME = '00131_中期MACDの位相で複合入口の方向を切り替える'


def sha(body: bytes) -> str:
    """
    機能: ファイル内容の指紋を求める。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def table(text: str) -> dict[str, list[str]]:
    """
    機能: 汎用表56行の全設定セルを取り出す。
    引数: text(str)はMarkdown本文。
    返り値: dict[str,list[str]]はIDから9尺度セルへの対応。
    """
    result = {}
    for line in text.splitlines():
        if re.match(r'^\| [A-Z][0-9]{2} ', line):
            fields = [s.strip() for s in line.split('|')[1:-1]]
            if len(fields) == 11:
                assert fields[0] not in result
                result[fields[0]] = fields[2:]
    assert len(result) == 56
    return result


# ----------------------------------------
def main() -> None:
    """
    機能: 既存正式資源と新規復元先を照合し最終確認を一度保存する。
    引数: CLI --repository(Path)は元repo、--restored(Path)は公式復元済み先、--output(Path|None)は新規証跡先。
    返り値: None。Raw走査・金融再計算・CSV再作成は行わない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--restored', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root, restored = args.repository.resolve(), args.restored.resolve()
    formal = root / 'study' / NAME
    assert restored.is_relative_to(root / 'work') and restored.is_dir()
    f1_body = (formal / '検査/金融前F1.json').read_bytes()
    assert sha(f1_body) == '8694a553430b66032dd733c06fa166803d470d488a8810fbe6a29310e3f66882'
    f1 = json.loads(f1_body)
    restored_sources = {}
    for name, expected in f1['ファイル'].items():
        relative = Path(name).relative_to(root)
        body = (restored / relative).read_bytes()
        assert sha(body) == expected, relative
        restored_sources[relative.as_posix()] = expected
    assert len(restored_sources) == 21
    before = json.loads(gzip.decompress((formal / '検査/実行前文書.json.gz').read_bytes()))
    assert before['F1SHA'] == sha(f1_body) and len(before['文書']) == 6
    for item in before['文書']:
        body = item['本文'].encode('utf-8')
        assert len(body) == item['bytes'] and sha(body) == item['sha256']
        assert f1['ファイル'][str(root / item['path'])] == item['sha256']
    setting = next(x['本文'] for x in before['文書'] if x['path'].endswith('/設定と結果.md'))
    assert table(setting) == table((formal / '設定と結果.md').read_text('utf-8'))
    archives = {}
    for index_name in ('コード復元索引.json', '追補コード索引.json'):
        index = json.loads((formal / '再現資料' / index_name).read_bytes())
        p = formal / '再現資料' / index['ZIP']
        assert sha(p.read_bytes()) == index['ZIP_SHA256'] and p.stat().st_size == index['ZIP_bytes']
        with zipfile.ZipFile(p) as z:
            assert z.testzip() is None and len(z.namelist()) == index['格納源数']
            for item in index['格納源']:
                body = z.read(item['path'])
                assert len(body) == item['bytes'] and sha(body) == item['sha256']
                assert (restored / item['path']).read_bytes() == body
                assert Path(item['path']).suffix in ('.py', '.md', '.mjs')
        archives[index['ZIP']] = {'sha256': index['ZIP_SHA256'], '源数': index['格納源数']}
    manifest = json.loads((formal / '保管索引.json').read_bytes())
    item = manifest['新方向票']; packed = (root / item['path']).read_bytes()
    assert len(packed) == item['bytes'] and sha(packed) == item['sha256']
    assert sha(gzip.decompress(packed)) == item['decoded_sha256']
    for item in manifest['共有参照']:
        assert sha(gzip.decompress((root / item['保存元']).read_bytes())) == item['解凍SHA']
    aggregate_body = (formal / '成果物/集計.json').read_bytes()
    assert sha(aggregate_body) == manifest['集計SHA'] == '252a8d1744fe340b57a23db5c46d7dc7abd467fdfa59d273ce42f497b04843f3'
    assert aggregate_body == (root / 'work/131既存入口の位相切替評価/集計.json').read_bytes()
    a = json.loads(aggregate_body)
    primary = a['集計']['all']['H0']['BBO']['3600']['125']
    assert tuple(primary[k] for k in ('entries','sessions','forward','adverse','neither','censored','ifd_known','ifd_unknown','ifd_net5_profit','ifd_net5_loss','ifd_net5_sum')) == (79,73,35,22,16,6,76,3,458612,369464,89148)
    independent = json.loads((formal / '検査/独立検算.json').read_bytes())
    assert sha((formal / '検査/独立検算.json').read_bytes()) == 'c7bbfcab94ffd1f6572474143096eb784ee7b7063608c5894954588678fa7255'
    assert independent['成功'] and independent['比較値総数'] == 32067
    csv_proof = json.loads((formal / '検査/CSV独立再読.json').read_bytes())
    assert csv_proof['成功'] and csv_proof['全データセル比較数'] == 16574 and csv_proof['数値比較数'] == 12011
    csv_files = {}
    for item in csv_proof['表別']:
        path = Path(item['CSV']['path'])
        assert sha(path.read_bytes()) == item['CSV']['sha256']
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == item['行数'] + 1 and all(len(row) == item['列数'] for row in rows)
        csv_files[path.name] = item['CSV']['sha256']
    documents = list(formal.rglob('*.md')) + [root / 'outputs/01a1889f-f2af-7943-a047-543275ee9ed2/131既存入口CSV/README.md']
    link_count = 0
    for p in documents:
        for target in re.findall(r'\]\(([^)]+)\)', p.read_text('utf-8')):
            if re.match(r'https?://|#', target):
                continue
            target = target.split('#')[0]
            assert (p.parent / target).resolve().exists(), (p, target)
            link_count += 1
    for name in ('README.md', 'docs/README.md', 'docs/議論/README.md', 'study/README.md'):
        assert '00131_' in (root / name).read_text('utf-8')
    proof = {'成功': True, '試行': 131, '確認UTC': datetime.now(timezone.utc).isoformat(),
             '金融前23源の実復元SHA': restored_sources, '実行前MD原文数': 6,
             '504セル金融前から不変': True, 'ZIP': archives, '相対リンク確認数': link_count,
             '正本集計SHA256': sha(aggregate_body), '独立検算既存証跡の比較値': 32067,
             'CSV既存再読証跡のセル数': 16574, 'CSV現在bytes': csv_files,
             '重大不足': [], '原板読取': False, '金融再計算': False,
             'CSV再作成': False, '条件変更': False,
             '検査コードSHA256': sha(Path(__file__).read_bytes())}
    destination = (args.output.resolve() if args.output is not None else formal / '検査/保管復元の確認.json')
    assert destination.is_relative_to(root) and not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(proof, handle, ensure_ascii=False, indent=2); handle.write('\n')
    print(json.dumps({'成功': True, '確認': str(destination), 'SHA256': sha(destination.read_bytes()),
                      '復元源': 21, '相対リンク': link_count, '重大不足': []}, ensure_ascii=False))


if __name__ == '__main__':
    main()
