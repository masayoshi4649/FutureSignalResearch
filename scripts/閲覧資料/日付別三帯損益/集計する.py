"""172の固定取得をセッション開始日・q0三帯ごとの閲覧入力へ集計する。"""
from pathlib import Path
from datetime import date
import gzip
import hashlib
import json
import zipfile
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
TRIAL = ROOT / 'study/00172_デイを固定しナイト米国前後の複合入口を探索する'
WORK = ROOT / 'work/172日付別三帯損益'
FILES = ('デイ', 'ナイト_米前', 'ナイト_米後')
HEADERS = ['日付', '利益（円）', '損失（円）', '収支（円）', '建玉回数',
           '主入口回数', '補完入口回数', '観測不足件数', '集計状態']


def fingerprint(path: Path) -> dict:
    """
    機能: 共用入力を複製せず位置・サイズ・物理SHA256を記録する。
    引数: path(Path)は存在するファイル。
    返り値: dictはpath/bytes/sha256。
    """
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': path.relative_to(ROOT).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest}


def main() -> None:
    """
    機能: 正式172のB05_11取得と恒久数値を結び、三帯各40日を集計する。
    引数: なし。金融・入口・数量は再探索しない。
    返り値: None。workへ型付きJSONを保存し、正式閲覧用CSV著作へ渡す。
    """
    archive_path = TRIAL / '再現資料/出生と比較正本.zip'
    expected = json.loads((TRIAL / '検査/共用入力の指紋.json').read_bytes())
    rows = {name: [] for name in FILES}
    evidence = [fingerprint(archive_path)]
    with zipfile.ZipFile(archive_path) as archive:
        reports = json.loads(archive.read('work/172ナイト入口探索/全80の固定比較.json'))
        control = next(r for r in reports['rows'] if r['id'] == 'B05_11')['periods']['全80既使用加法']
        for period, directory, proof_key in (
            ('旧73', ROOT / 'inputs/00163_任意幅の共用価格索引/数値表', '旧73数値表'),
            ('追加7', ROOT / 'inputs/00167_追加七場の入口と共用価格索引/自然数値表', '追加7数値表')):
            refs = json.loads(gzip.decompress(archive.read(f'work/172ナイト入口探索/{period}の全取得.json.gz')))
            selected = next(r for r in refs['rows'] if r['id'] == 'B05_11')
            for filename, ref in expected[proof_key].items():
                physical = fingerprint(directory / filename)
                assert physical['bytes'] == ref['bytes'] and physical['sha256'] == ref['sha256']
                evidence.append(physical)
            metadata = json.loads(gzip.decompress((directory / '任意幅識別.json.gz').read_bytes()))
            with np.load(directory / '任意幅配列.npz', allow_pickle=False) as table:
                cases = np.array(selected['cases'], dtype=int)
                sides = np.array(selected['sides'], dtype=int)
                widths = np.array(selected['widths'], dtype=int)
                horizons = np.array(selected['horizons'], dtype=int)
                phases = np.array(selected['phases'], dtype=int)
                origins = np.array(selected['origins'], dtype=int)
                key = (cases, sides, widths, horizons)
                known, net = table['known'][key], table['net5'][key]
                sessions = np.array(metadata['sessions'])[cases]
                assert len(np.unique(cases)) == len(cases)
                for session in metadata['session_order']:
                    day = session.endswith('_Day')
                    session_date = session[:10]
                    assert date.fromisoformat(session_date).isoformat() == session_date
                    for band in ((0,) if day else (1, 2)):
                        mask = (sessions == session) & (phases == band)
                        observed = mask & known
                        profit = int(np.maximum(net[observed], 0).sum())
                        loss = int(np.maximum(-net[observed], 0).sum())
                        count = int(mask.sum())
                        main_count = int((mask & (origins == 0)).sum())
                        fallback_count = int((mask & (origins == 2)).sum())
                        missing = int((mask & ~known).sum())
                        assert count == main_count + fallback_count
                        status = '既知分のみ' if missing else '全件既知' if count else '建玉なし'
                        rows[FILES[band]].append([session_date, profit, loss, profit-loss, count,
                            main_count, fallback_count, missing, status])
    # ----------------------------------------
    totals = {}
    for band, name in enumerate(FILES):
        rows[name].sort(key=lambda r: r[0])
        assert len(rows[name]) == len({r[0] for r in rows[name]}) == 40
        summary = [sum(row[i] for row in rows[name]) for i in range(1, 8)]
        q = control[('DAY', 'PRE', 'POST')[band]]['全部']
        assert summary == [q['profit'], q['loss'], q['net'], q['count'], q['core_count'], q['technical_count'], q['C']]
        totals[name] = dict(zip(HEADERS[1:8], summary, strict=True))
    result = {'対象候補': 'B05_11（デイは171固定同体）',
        '定義': {'日付': '当該デイ/ナイトのセッション開始日。ナイト翌朝分も開始日に帰属。',
            '帯': 'q0判断のNY09:30夏冬変換前/以後。境界を跨ぐ保有の損益も入口帯へ全額帰属。',
            '金額': '費用後の既知決済。利益は正の損益合計、損失は負の損益の絶対値合計、収支は両者の差。',
            '建玉回数': '追加建てを含む取得回数。各要求mini1枚、主と補完を含む。注文要求や保有枚数ではない。',
            '観測不足': '不足がある行は既知分のみの利益/損失/収支。未知を0円の決済と認定しない。',
            '費用': '1pt100円、片道税込38.5円、追加片道5pt。実BBOspreadを含む。'},
        '出典': evidence, '集計Source': fingerprint(Path(__file__)), '合計': totals,
        '表': {name: {'見出し': HEADERS, '行': rows[name]} for name in FILES}}
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / '型付き入力.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'成功': True, '各CSVの日付行数': 40, '合計': totals}, ensure_ascii=False))


if __name__ == '__main__':
    main()
