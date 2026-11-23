"""133の履歴段階・入力・コード・保存観測再現・CSV・条件セルを確認する。"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import csv
import gzip
import hashlib
import json
import re
import zipfile


def sha(body: bytes) -> str:
    """
    機能: 照合対象bytesの指紋を返す。
    引数: body(bytes)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(body).hexdigest()


# ----------------------------------------
def cells(text: str) -> dict[str, list[str]]:
    """
    機能: 元と現行の全504設定セルを取り出す。
    引数: text(str)はMarkdown。
    返り値: dict[str,list[str]]は56手法の9尺度。
    """
    output = {}
    for line in text.splitlines():
        if re.match(r'^\| [A-Z][0-9]{2} ', line):
            parts = [x.strip() for x in line.split('|')[1:-1]]
            if len(parts) == 11:
                assert parts[0] not in output
                output[parts[0]] = parts[2:]
    assert len(output) == 56
    return output


# ----------------------------------------
def main() -> None:
    """
    機能: 正式保存と実復元済みworkを照合し、新規確認票を作る。
    引数: CLI --restored(Path)は復元済み先、--output(Path|None)は新規証跡先。
    返り値: None。Raw/177MB/新仮説の金融/CSV生成は実行しない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--restored', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    formal = Path(__file__).resolve().parent.parent
    root = formal.parents[1]
    restored = args.restored.resolve()
    assert restored.is_relative_to(root / 'work') and restored.is_dir()
    manifest = json.loads((formal / '保管索引.json').read_bytes())
    stages = {}
    for name, expected in [('F0', '4b581c827391405db747f4c043f5252378ec21ce78ffec89d4339eb81aace01c'),
                           ('F1', '98379bf9359ab918db931f649298fec88826bb2df71330c459612eec786c70a3')]:
        body = (formal / '検査' / (name + '.json')).read_bytes()
        assert sha(body) == expected
        assert (restored / f'work/133探索期限の評価/{name}.json').read_bytes() == body
        stages[name] = json.loads(body)
    snapshot = json.loads(gzip.decompress((formal / '検査/実行前文書.json.gz').read_bytes()))
    assert len(snapshot['文書']) == 6 and snapshot['段階']['F0']['MD数'] == 4 and snapshot['段階']['F1']['MD数'] == 6
    original_cells = None
    for item in snapshot['文書']:
        body = item['本文'].encode('utf-8')
        assert sha(body) == item['sha256'] and len(body) == item['bytes']
        assert (restored / item['path']).read_bytes() == body
        if item['path'].endswith('/設定と結果.md'):
            original_cells = cells(item['本文'])
    assert original_cells == cells((formal / '設定と結果.md').read_text('utf-8'))
    f1 = stages['F1']
    anchor = next(Path(p) for p in f1['ファイル'] if p.endswith('study\\00133_全場参加を維持して強い入口の探索期限を延ばす\\README.md'))
    old_root = anchor.parents[2]
    excluded = {item['path'] for item in manifest['意図して複製しない固定源']}
    restored_count = 0
    for name, expected in f1['ファイル'].items():
        relative = Path(name).relative_to(old_root).as_posix()
        if relative in excluded:
            assert not (restored / relative).exists()
            continue
        assert sha((restored / relative).read_bytes()) == expected, relative
        restored_count += 1
    assert len(excluded) == 3 and restored_count == 89
    archive_records = {}
    for key in ('固定コード', '後発コード'):
        index = manifest[key]; path = formal / '再現資料' / index['ZIP']
        assert sha(path.read_bytes()) == index['ZIP_SHA256'] and path.stat().st_size == index['ZIP_bytes']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None and len(z.namelist()) == index['格納源数']
            for item in index['格納源']:
                body = z.read(item['path']); assert sha(body) == item['sha256']
                assert (restored / item['path']).read_bytes() == body
        archive_records[key] = {'sha256': index['ZIP_SHA256'], '源数': index['格納源数']}
    for item in manifest['新共用入力'] + [manifest['新正逆観測']] + manifest['共有参照'] + manifest['小型段階証跡']:
        body = (root / item['保存元']).read_bytes(); assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body) if item['形式'] == 'gzip' else body
        assert sha(decoded) == item['解凍SHA256'] and (restored / item['復元先']).read_bytes() == decoded
    v1 = restored / 'work/133Source取得を固定入力へ渡す.py'
    v2 = restored / 'work/133Source取得を固定入力へ渡す_版2.py'
    assert sha(v1.read_bytes()) == stages['F0']['ファイル'][str(old_root / 'work/133Source取得を固定入力へ渡す.py')]
    assert sha(v2.read_bytes()) == f1['ファイル'][str(old_root / 'work/133Source取得を固定入力へ渡す_版2.py')]
    assert v1.read_bytes() != v2.read_bytes()
    aggregate_body = (formal / '成果物/集計.json').read_bytes()
    assert sha(aggregate_body) == manifest['集計SHA256'] == '21e686aa350f6b093ae83b0503acecc006df38905b74478315967648f2d5858b'
    primary = json.loads(aggregate_body)['集計']['all']['L1']['BBO']['3600']['125']
    assert tuple(primary[k] for k in ('entries','sessions','forward','adverse','neither','censored','ifd_known','ifd_unknown','ifd_net5_profit','ifd_net5_loss','ifd_net5_sum')) == (79,73,38,22,10,9,75,4,479689,378464,101225)
    independent_body = (formal / '検査/独立確認.json').read_bytes()
    assert sha(independent_body) == '103f5338124f8465c1d7b3f7ce093c8933d5e02fc807c7237eded6b9c07eac04'
    independent = json.loads(independent_body)
    assert independent['success'] and independent['condition_count'] == 300 and independent['old_conditions_identical'] == 140
    replay = json.loads((formal / '検査/保存観測からの再現確認.json').read_bytes())
    assert replay['成功'] and replay['原F1は同体保持'] and replay['その他の全正本フィールド同体']
    assert replay['全三表JSON_SHA256同体'] == 'eab6af830eb9c68f68dfb4cc594d0c2f8e5f3f057e3997a92a1d056a7f00c59b'
    assert replay['再現差はF1_SHA256という台帳参照だけ']
    csv_proof = json.loads((formal / '検査/CSV独立再読.json').read_bytes())
    assert csv_proof['成功'] and csv_proof['全データセル比較数'] == 22123 and csv_proof['数値比較数'] == 13105
    csv_hashes = {}
    for item in csv_proof['表別']:
        path = Path(item['CSV']['path'])
        assert sha(path.read_bytes()) == item['CSV']['sha256']
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == item['行数'] + 1 and all(len(row) == item['列数'] for row in rows)
        csv_hashes[path.name] = item['CSV']['sha256']
    documents = list(formal.rglob('*.md')) + [root / 'outputs/01a1889f-f2af-7943-a047-543275ee9ed2/133期限別CSV/README.md',
                                                  root / 'docs/議論/強い入口を長く探した比較と時系列の違い.md']
    links = 0
    for path in documents:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text('utf-8')):
            if target.startswith(('http://', 'https://', '#')):
                continue
            assert (path.parent / target.split('#')[0]).resolve().exists(), (path, target)
            links += 1
    for name in ('README.md','docs/README.md','docs/議論/README.md','study/README.md'):
        assert formal.name in (root / name).read_text('utf-8')
    result = {'成功': True, '試行': 133, '確認UTC': datetime.now(timezone.utc).isoformat(),
              'F0_F1原文同体': True, '実行前MD原文': 6, 'F0原文MD': 4, 'F1原文MD': 6,
              'F1実復元源': restored_count, '意図して未複製': sorted(excluded), '504セル不変': True,
              'v1_F0とv2_F1の原文を区別': True, 'コードZIP': archive_records,
              '新共用gzip一度保存': 3, '保存観測からの再集計はF1参照以外全正本同体': True,
              '三表JSON同体': replay['全三表JSON_SHA256同体'], '独立条件': 300, '旧条件': 140,
              '独立CSV再読セル': 22123, 'CSV現在bytes': csv_hashes, '相対リンク確認数': links,
              'Raw再走査': False, '177MB本文読取': False, '新仮説の金融実行': False,
              '新CSV生成': False, '重大不足': [], '確認コードSHA256': sha(Path(__file__).read_bytes())}
    destination = args.output.resolve() if args.output else formal / '検査/保管復元の確認.json'
    assert destination.is_relative_to(root) and not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2); handle.write('\n')
    print(json.dumps({'成功': True, '確認SHA256': sha(destination.read_bytes()), 'F1復元': 89,
                      '504セル不変': True, '相対リンク': links, '重大不足': []}, ensure_ascii=False))


if __name__ == '__main__':
    main()
