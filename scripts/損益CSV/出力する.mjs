/**
 * 保存済み損益を候補別集計と全セッションのCSVへ出力する。
 * @param {string[]} process.argv - 入力JSON、期待SHA256、新規出力先の順。
 * @returns {Promise<void>} 検算済みCSV二点と確認JSONを保存する。
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {Workbook} from '@oai/artifact-tool';

/**
 * 入力と出力の指紋を計算する。
 * @param {Uint8Array|string} value - 対象データ。
 * @returns {string} SHA256。
 */
function sha(value) { return crypto.createHash('sha256').update(value).digest('hex'); }

/**
 * 有限数値の一致を円の百万分の一以内で確認する。
 * @param {number} actual - 計算値。
 * @param {number} expected - 保存済み値。
 * @param {string} label - 検査対象。
 * @returns {void} 不一致時は例外を送出する。
 */
function equalNumber(actual, expected, label) {
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), label);
  assert.ok(Math.abs(actual - expected) <= 0.000001, `${label}: ${actual} / ${expected}`);
}

/**
 * セル値をRFC4180のCSVフィールドへ変換する。
 * @param {string|number|boolean|null} value - セル値。
 * @returns {string} 必要な引用符を付けたフィールド。
 */
function field(value) {
  const text = value == null ? '' : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/**
 * 表へ転記した値と計算列をCSV化する。
 * @param {Object} sheet - artifact-toolのワークシート。
 * @param {number} rows - 行数。
 * @param {number} cols - 列数。
 * @returns {string} UTF-8 BOM付きCSVテキスト。
 */
function csv(sheet, rows, cols) {
  return '\uFEFF' + sheet.getRangeByIndexes(0, 0, rows, cols).values.map(row => row.map(field).join(',')).join('\r\n') + '\r\n';
}

// ----------------------------------------
// 固定済み結果を読み、候補とセッションの完全性を検査する。

const [inputArg, expectedSHA, outArg] = process.argv.slice(2);
assert.ok(inputArg && /^[a-f0-9]{64}$/.test(expectedSHA) && outArg, '引数は入力JSON・SHA256・新規出力先');
const input = path.resolve(inputArg), out = path.resolve(outArg);
const before = await fs.readFile(input);
assert.equal(sha(before), expectedSHA, '入力SHA256');
const data = JSON.parse(before.toString('utf8').replace(/^\uFEFF/, ''));
assert.equal(data['成功'], true);
assert.equal(data.stage, 'full70');
assert.equal(data['場数'], 70);
assert.equal(data['前後不変'], true);
assert.equal(data['場別'].length, data['会計数']);
const keys = data['主key'];
assert.ok(Array.isArray(keys) && new Set(keys).size === keys.length);
const workbook = Workbook.create();
const detail = workbook.worksheets.add('全セッション');
const total = workbook.worksheets.add('候補別集計');
const detailHeader = ['試行', '候補', '条件ID', '開始日', 'セッション', '片道追加滑りpt', '仮定遅延秒', '新規件数', '新規枚数', '粗損益円', '手数料円', '追加滑り円', '純損益円', '累計収支円', '参加枠', '判断枠', '参加率パーセント'];
const totalHeader = ['試行', '候補', '条件ID', 'セッション数', '片道追加滑りpt', '仮定遅延秒', '新規件数', '新規枚数', '粗損益円', '手数料円', '追加滑り円', '純損益円', '参加枠', '判断枠', '参加率パーセント', '保存点連結時価DD円'];
const detailRows = [], totalRows = [], checks = [];
for (const key of keys) {
  const config = data['Actor設定'][key], aggregate = data['集計'][key];
  const rows = data['場別'].filter(row => row.key === key).sort((a, b) => a.session.localeCompare(b.session));
  assert.equal(rows.length, 70, key);
  assert.equal(new Set(rows.map(row => row.session)).size, 70, key);
  let running = 0;
  const sums = {positions: 0, entry_quantity: 0, gross_yen: 0, fee_yen: 0, slip_yen: 0, net_yen: 0, active: 0, denom: 0};
  for (const row of rows) {
    assert.match(row.session, /^2026-\d{2}-\d{2}_(Day|Night)$/);
    equalNumber(row.gross_yen - row.fee_yen - row.slip_yen, row.net_yen, `${key}/${row.session}/純額`);
    equalNumber(row.closed_net_yen, row.net_yen, `${key}/${row.session}/場内完結`);
    for (const name of ['open_buy', 'open_sell', 'pending_buy', 'pending_sell']) assert.equal(row[name], 0, name);
    const a = row['活動主表'];
    assert.equal(a.active + a.wait + a.unknown, a.denom, '判断枠の内訳');
    assert.ok(a.denom > 0);
    running += row.net_yen;
    const [date, session] = row.session.split('_');
    detailRows.push([data['試行'], config.candidate, key, date, session === 'Day' ? 'デイ' : 'ナイト', config.slip_pts, config.delay_seconds, row.positions, row.entry_quantity, row.gross_yen, row.fee_yen, row.slip_yen, row.net_yen, running, a.active, a.denom, a.active / a.denom * 100]);
    for (const name of ['positions', 'entry_quantity', 'gross_yen', 'fee_yen', 'slip_yen', 'net_yen']) sums[name] += row[name];
    sums.active += a.active; sums.denom += a.denom;
  }
  for (const name of ['positions', 'entry_quantity', 'gross_yen', 'fee_yen', 'slip_yen', 'net_yen']) equalNumber(sums[name], aggregate[name], `${key}/${name}`);
  assert.equal(sums.active, aggregate['活動主表'].active);
  assert.equal(sums.denom, aggregate['活動主表'].denom);
  totalRows.push([data['試行'], config.candidate, key, 70, config.slip_pts, config.delay_seconds, sums.positions, sums.entry_quantity, sums.gross_yen, sums.fee_yen, sums.slip_yen, sums.net_yen, sums.active, sums.denom, sums.active / sums.denom * 100, aggregate['保存点連結時価DD']]);
  checks.push({条件ID: key, 場数: 70, 純損益円: sums.net_yen, 参加枠: sums.active, 判断枠: sums.denom});
}
assert.equal(detailRows.length, data['会計数']);
detail.getRangeByIndexes(0, 0, detailRows.length + 1, detailHeader.length).values = [detailHeader, ...detailRows];
total.getRangeByIndexes(0, 0, totalRows.length + 1, totalHeader.length).values = [totalHeader, ...totalRows];

// ----------------------------------------
// CSVの計算列を表上で独立再計算し、保存値と一致した値だけ出力する。

for (let i = 0; i < detailRows.length; i++) {
  const n = i + 2;
  detail.getRange(`M${n}`).formulas = [[`=J${n}-K${n}-L${n}`]];
  detail.getRange(`N${n}`).formulas = [[i === 0 || detailRows[i - 1][2] !== detailRows[i][2] ? `=M${n}` : `=N${n - 1}+M${n}`]];
  detail.getRange(`Q${n}`).formulas = [[`=O${n}/P${n}*100`]];
}
workbook.recalculate();
const computed = detail.getRangeByIndexes(1, 0, detailRows.length, detailHeader.length).values;
for (let i = 0; i < detailRows.length; i++) for (const c of [12, 13, 16]) equalNumber(computed[i][c], detailRows[i][c], `CSV計算列/${i}/${c}`);
await fs.mkdir(out, {recursive: false});
const outputs = {};
for (const [name, sheet, rows, cols] of [
  ['全セッション.csv', detail, detailRows.length + 1, detailHeader.length],
  ['候補別集計.csv', total, totalRows.length + 1, totalHeader.length],
]) {
  const body = csv(sheet, rows, cols);
  await fs.writeFile(path.join(out, name), body, {encoding: 'utf8', flag: 'wx'});
  outputs[name] = {sha256: sha(body), データ行数: rows - 1};
}
assert.equal(sha(await fs.readFile(input)), expectedSHA, '入力の前後不変');
await fs.writeFile(path.join(out, 'CSVの確認.json'), JSON.stringify({成功: true, 試行: data['試行'], 入力: input, 入力SHA256: expectedSHA, 出力: outputs, 全条件: checks, 入力前後不変: true, 金融再実行: false}, null, 2), {flag: 'wx'});
console.log(JSON.stringify({成功: true, 試行: data['試行'], 出力先: out, 出力: outputs}));
