/**
 * 確定JSONの先頭だけから、CSVを変更せず四表の支援画像を再描画する。
 * @param {string[]} process.argv - --input JSON --sha256 指紋 --folder CSV先 --output-check 新規確認先。
 * @returns {Promise<void>} 画像四点を置換し、金融JSON・CSV不変の確認を保存する。
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';
import {Workbook} from '@oai/artifact-tool';

const NAMES = ['候補別集計', '幅別先着率', '全候補明細', '全70場集計'];

/**
 * 全bytesのSHA256を求める。
 * @param {Uint8Array|string} data - 検査対象。
 * @returns {string} 小文字16進の指紋。
 */
function sha(data) { return crypto.createHash('sha256').update(data).digest('hex'); }

/**
 * 数式開始に見える文字を、表示用の文字として設定する。
 * @param {string|number|boolean|null} value - 元JSON値。
 * @returns {string|number|boolean|null} 型を保つ表示用値。
 */
function literal(value) {
  return typeof value === 'string' && /^[=']/.test(value) ? "'" + value : value;
}

// ----------------------------------------
const args = {};
for (let i = 2; i < process.argv.length; i += 2) {
  assert.ok(['--input', '--sha256', '--folder', '--output-check'].includes(process.argv[i]));
  assert.ok(process.argv[i + 1] && args[process.argv[i]] === undefined);
  args[process.argv[i]] = process.argv[i + 1];
}
assert.equal(Object.keys(args).length, 4);
assert.equal(process.version, 'v24.22.1');
const input = path.resolve(args['--input']);
const folder = path.resolve(args['--folder']);
const proofPath = path.resolve(args['--output-check']);
assert.match(args['--sha256'], /^[a-f0-9]{64}$/);
await assert.rejects(fs.stat(proofPath), error => error.code === 'ENOENT');
const bytes = await fs.readFile(input);
assert.equal(sha(bytes), args['--sha256']);
const source = JSON.parse(bytes.toString('utf8').replace(/^\uFEFF/, ''));
assert.equal(source['試行'], 120);
assert.deepEqual(source.tables.map(t => t.name), NAMES);
const before = {[input]: sha(bytes)};
for (const name of NAMES) {
  const file = path.join(folder, name + '.csv');
  before[file] = sha(await fs.readFile(file));
}
const workbook = Workbook.create();
const views = [];
for (const table of source.tables) {
  const original = [table.headers, ...table.rows].slice(0, 5).map(row => row.slice(0, 7));
  assert.ok(original.every(row => row.length === 7));
  const sheet = workbook.worksheets.add(table.name);
  const range = sheet.getRangeByIndexes(0, 0, original.length, 7);
  range.values = original.map(row => row.map(literal));
  range.format.font = {name: 'Arial', size: 10};
  range.format.verticalAlignment = 'center';
  range.format.wrapText = true;
  sheet.showGridLines = false;
  [60, 180, 120, 120, 120, 120, 120].forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, original.length, 1).format.columnWidthPx = width;
  });
  sheet.getRange('A1:G1').format = {fill: '#334155', font: {name: 'Arial', size: 10, bold: true, color: '#FFFFFF'}, horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true};
  range.format.autofitRows();
  sheet.getRange('A1:G1').format.rowHeight = 60;
  views.push({sheet, rows: original.length, name: table.name});
}
workbook.recalculate();
const images = [];
for (const view of views) {
  const imagePath = path.join(folder, '支援画像', view.name + '.png');
  const old = await fs.readFile(imagePath);
  const range = `A1:G${view.rows}`;
  const image = await workbook.render({sheetName: view.name, range, scale: 1, format: 'png'});
  const rendered = new Uint8Array(await image.arrayBuffer());
  await fs.writeFile(imagePath, rendered);
  assert.equal(sha(await fs.readFile(imagePath)), sha(rendered));
  images.push({path: imagePath, range, before_sha256: sha(old), after_sha256: sha(rendered), bytes: rendered.length});
}
const after = {};
for (const file of Object.keys(before)) after[file] = sha(await fs.readFile(file));
assert.deepEqual(after, before);
const proof = {試行: 120, 成功: true, 用途: '同一CSV作成操作の支援画像QA修正。金融・CSVを変更しない。', 金融JSONとCSV前SHA256: before, 金融JSONとCSV後SHA256: after, 前後不変: true, 画像: images, 自然CSV再生成: false, 金融再計算: false, xlsx生成: false, marker再実行: false, コードSHA256: sha(await fs.readFile(new URL(import.meta.url))), 視認: '本確認は描画成功と不変照合。画像の視認は別途実施する。'};
await fs.writeFile(proofPath, JSON.stringify(proof, null, 2) + '\n', {flag: 'wx'});
console.log(JSON.stringify({成功: true, 画像数: images.length, JSONとCSV不変: true, 確認: proofPath}));
