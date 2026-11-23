"""134の履歴段階・入力・コード・保存観測再現・CSV・条件セルを確認する。"""
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
    for name, expected in [('F0', 'b4729dc22249fe7b8b54937c7b1ff0ce784d546c7e55d3ccf1fe84455628bc40'),
                           ('F1', 'd76eb2017da90f160b1b6c78485a26c28fa63f03954ec7748bc6b49802396eb6')]:
        body = (formal / '検査' / (name + '.json')).read_bytes()
        assert sha(body) == expected
        assert (restored / f'work/134公表時計の評価/{name}.json').read_bytes() == body
        stages[name] = json.loads(body)
    snapshot = json.loads(gzip.decompress((formal / '検査/実行前文書.json.gz').read_bytes()))
    assert len(snapshot['文書']) == 7 and snapshot['段階']['F0']['MD数'] == 6 and snapshot['段階']['F1']['MD数'] == 7
    original_cells = None
    for item in snapshot['文書']:
        body = item['本文'].encode('utf-8')
        assert sha(body) == item['sha256'] and len(body) == item['bytes']
        assert (restored / item['path']).read_bytes() == body
        if item['path'].endswith('/設定と結果.md'):
            original_cells = cells(item['本文'])
    current_cells = cells((formal / '設定と結果.md').read_text('utf-8'))
    correction = json.loads((formal / '検査/設定表の文書訂正.json').read_bytes())
    differences = [(name, i, a, b) for name in original_cells for i, (a,b) in enumerate(zip(original_cells[name],current_cells[name])) if a != b]
    assert len(differences) == correction['文書差分セル数'] == 9
    scales = ['原板・逐次','1分','3分','5分','15分','30分','60分','セッション足','日足']
    assert [{'ID': n, '足幅': scales[i], '退避原文': a, '文書訂正後': b} for n,i,a,b in differences] == correction['文書差分']
    assert not correction['実行条件変更'] and correction['その他495セル不変']
    f1 = stages['F1']
    anchor = next(Path(p) for p in f1['ファイル'] if p.endswith('study\\00134_Raw公表時計で複合入口を再生成する\\README.md'))
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
    assert len(excluded) == 4 and restored_count == 98
    archive_records = {}
    for key in ('共有固定コード', '追加固定コード', '後発コード'):
        index = manifest[key]
        path = root / index['保存元ZIP'] if key == '共有固定コード' else formal / '再現資料' / index['ZIP']
        assert sha(path.read_bytes()) == index['ZIP_SHA256']
        if 'ZIP_bytes' in index: assert path.stat().st_size == index['ZIP_bytes']
        with zipfile.ZipFile(path) as z:
            assert z.testzip() is None
            if key != '共有固定コード': assert len(z.namelist()) == index['格納源数']
            for item in index['格納源']:
                body = z.read(item['path']); assert sha(body) == item['sha256']
                assert (restored / item['path']).read_bytes() == body
        archive_records[key] = {'sha256': index['ZIP_SHA256'], '源数': index['格納源数']}
    for item in manifest['新共用入力'] + [manifest['新正逆観測']] + manifest['共有参照'] + manifest['小型段階証跡']:
        body = (root / item['保存元']).read_bytes(); assert sha(body) == item['保存SHA256']
        decoded = gzip.decompress(body) if item['形式'] == 'gzip' else body
        assert sha(decoded) == item['解凍SHA256'] and (restored / item['復元先']).read_bytes() == decoded
    aggregate_body = (formal / '成果物/集計.json').read_bytes()
    assert sha(aggregate_body) == manifest['集計SHA256'] == 'ac497334c10b7fc5ab3c90bcc82bfb5bc488a5c9e75bfc2cd6ee32d686d2d0f0'
    primary = json.loads(aggregate_body)['集計']['all']['N0']['BBO']['3600']['125']
    assert tuple(primary[k] for k in ('entries','sessions','forward','adverse','neither','censored','ifd_known','ifd_unknown','ifd_net5_profit','ifd_net5_loss','ifd_net5_sum')) == (78,73,24,32,15,7,74,4,337382,502080,-164698)
    independent_body = (formal / '検査/独立確認.json').read_bytes()
    assert sha(independent_body) == '05c1f50c728ca5513b752f99a54897871151179bbedbff119d7708c91a1466df'
    independent = json.loads(independent_body)
    assert independent['success'] and independent['condition_count'] == 300 and independent['old_conditions_identical'] == 120
    replay = json.loads((formal / '検査/保存観測からの再現確認.json').read_bytes())
    assert replay['成功'] and replay['原F1は同体保持'] and replay['その他の全正本フィールド同体']
    assert replay['全三表JSON_SHA256同体'] == '71b4384f73a66325831ff52de3bdeff50dc595dc3a08d9d5f5a68af7671c5208'
    assert replay['再現差はF1_SHA256という台帳参照だけ']
    csv_proof = json.loads((formal / '検査/CSV独立再読.json').read_bytes())
    assert csv_proof['成功'] and csv_proof['全データセル比較数'] == 26662 and csv_proof['数値比較数'] == 13975
    csv_hashes = {}
    for item in csv_proof['表別']:
        path = Path(item['CSV']['path'])
        assert sha(path.read_bytes()) == item['CSV']['sha256']
        with path.open(encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.reader(handle))
        assert len(rows) == item['行数'] + 1 and all(len(row) == item['列数'] for row in rows)
        csv_hashes[path.name] = item['CSV']['sha256']
    documents = list(formal.rglob('*.md')) + [root / 'outputs/01a1889f-f2af-7943-a047-543275ee9ed2/134公表時計CSV/README.md',
                                                  root / 'docs/議論/CSVとRawの形成差と公表時計への依存.md']
    links = 0
    for path in documents:
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text('utf-8')):
            if target.startswith(('http://', 'https://', '#')):
                continue
            assert (path.parent / target.split('#')[0]).resolve().exists(), (path, target)
            links += 1
    for name in ('README.md','docs/README.md','docs/議論/README.md','study/README.md'):
        assert formal.name in (root / name).read_text('utf-8')
    audit_body = (formal / '根拠/足定義の監査.json').read_bytes()
    assert sha(audit_body) == '373e0fa4d8feadb03bd7803efff25d7d36e5f194f79cf8855c3e6dd2d00eb216'
    formation = gzip.decompress((root / manifest['事後形成差']['保存元']).read_bytes())
    assert sha(formation) == manifest['事後形成差']['解凍SHA256'] == '614040bf85aa2d57df5c727eddefae679ce7e4e97eec864dbfdaa87b0edad6da'
    for key in ('共有固定コード','追加固定コード'):
        assert manifest[key]['格納源数'] == (63 if key == '共有固定コード' else 15)
    assert len(manifest['新共用入力']) == 4
    result = {'成功': True, '試行': 134, '確認UTC': datetime.now(timezone.utc).isoformat(),
              'F0_F1原文同体': True, '実行前MD原文': 7, 'F0原文MD': 6, 'F1原文MD': 7,
              'F1実復元源': restored_count, '意図して未複製': sorted(excluded), '全504セル照合': True, '金融後文書訂正9セル以外の495セル不変': True,
              '金融後文書訂正を事前原文と区別': True, 'コードZIP': archive_records,
              '新共用gzip一度保存': 4, '保存観測からの再集計はF1参照以外全正本同体': True,
              '三表JSON同体': replay['全三表JSON_SHA256同体'], '独立条件': 300, '旧条件': 120,
              '独立CSV再読セル': 26662, 'CSV現在bytes': csv_hashes, '相対リンク確認数': links,
              'Raw再走査': False, '83/84MB派生入力本文読取': False, '新仮説の金融実行': False,
              '新CSV生成': False, '重大不足': [], '確認コードSHA256': sha(Path(__file__).read_bytes())}
    destination = args.output.resolve() if args.output else formal / '検査/保管復元の確認.json'
    assert destination.is_relative_to(root) and not destination.exists()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2); handle.write('\n')
    print(json.dumps({'成功': True, '確認SHA256': sha(destination.read_bytes()), 'F1復元': 98,
                      '全504セル照合': True, '金融後文書訂正9セル以外の495セル不変': True, '相対リンク': links, '重大不足': []}, ensure_ascii=False))


if __name__ == '__main__':
    main()
