# 方向付き数量の測定入力

2026-11-12。Rootが自然測定を1回実行し、別担当の全件独立照合合格後に物理gzipを同体で一度保存した。新Raw/CSV/追加2場の読取、新売買採否・容量・損益・モデル変更は行っていない。100特徴と旧固定源は不変更。

## 正本と指紋

- 正本：`方向付き数量の入力.json.gz`、schema `directional_volume_v1`。
- 物理：8,215,183 bytes / SHA256 `947dd612858e5560debe0c350c73eda2a12d821f515bd6f9627c2040676901d3`。
- 解凍：190,388,567 bytes / SHA256 `9b8ace0d3ec2649ab484762d3bf8dc35b0a229ebe3c384a6e875cc74252be4f0`。
- 全73場・全40,544q0・適格35,339・元1分43,124足。元/保存gzipとも全CRC・解凍SHAが一致し、解凍副本は残していない。
- 独立全件票：`work/方向付き数量の自然独立確認/独立確認.json`、SHA256 `dec9d2238fb7d571c88dd21352903aee6d281f738e7240e4538dfd48b15faf7d`。その原票は[再現用小源ZIP](再現用の小源.zip)にも収録。

## 由来・式・時計

147の既知1分量と153のcanonical1分価格・全q0を全足ID/OHLC/品質/Stampで結合する。価格未知は双方の未知maskを照合し、内部0を既知価格とは扱わない。147JSON内の旧注文/取得属性は復号されるが、計算へ渡すのはbars/context.atだけ。旧events/選択/金融は採用しない。

OBV変化5/15/30はr含むw本の `Σ sign(C_i−C_prev)×V_i`。前Close用のw+1価格・当w本量が必要で、同値Closeは加減0。比はΣV>0時だけ。CMF20はr含む20本の `Σ((2C−H−L)/(H−L)×V)/ΣV`、H=LはMFM既知0、ΣV=0は値未定義。前CMFは同q0知得prefixの1分ずらした市場窓、Δは両値defined時のみ。入替えΔを新規資金流入そのものとは呼ばない。

各windowは実時間格子・known/defined・null・0・品質counts・窓端refsを分離。未知を0に補わず、欠分を詰めず、同場/同限月だけを使う。rの初配送Stamp=q0、過去足も全End/AvailableAt/Stamp.Time/Index/Line≤q0。CSV足モデルAvailableAt=End+60と実Raw初配送Stampを区別し、Rawネイティブ/実受信時刻の再現とは呼ばない。

## 再現

小源ZIP SHA256 `fd9f46c889947d2cbe5eaf1a0dc592758e026ed8c633b2e526bef40ccd0e8cbc`。既存研究リポジトリの別作業コピーへ元の相対パスで展開し、源の指紋を確認する。巨大元入力147/153は下記共用gzipを参照し、ZIPへ重ねない。`work/方向付き数量の入力準備/生成する.py` を `--prepare-sha256 f2c8c4caaecfd6bc4333f3a595b5060d73e112681ed57c82a80fbea1186ee154 --output-dir work/方向付き数量の再現入力 --execute-after-review` で未作成先へ実行する。子Pythonは `work/複合テクニカル学習環境/Scripts/python.exe -X utf8`。元準備・停止票は過去の自然未実行時点を記録した原文であり、本保存後の状態へ書き換えない。

旧29 OBV/42-43 CMF/47-48 Forceの未達は保持する。今回は広い1分母集団への因果測定で、数量単独有効性の証明でも売買条件でもない。

## 共用元入力

```json
{
  "source147": {
    "path": "inputs/00147_中位価格位置と実体回復/Sourceの出生と取得.json.gz",
    "sha256": "b99c49f06fe7e2306e59733b1cff26e3bb351f64edee220c98bc30b62c016d77",
    "decoded_sha256": "d42d25ec0fe41e8358c1227fd71b4377ffa90c96a8cf582f1ee4537ebf455d63"
  },
  "source153": {
    "path": "inputs/00153_先行高安の独立出生/先行高安の入力.json.gz",
    "sha256": "2c020fed5b336ed0b417d8e72a07c6336ea475b09b9a2ff37f26ec4ce4d56bf8",
    "decoded_sha256": "8e145275dda385e4c2f87500978716654d10efb0903a4011f2bcc304a7906b14"
  }
}
```


## 155新生成3JSON（F1後の追加）

元の数量測定案内は全bytes保持し、この節だけ追記した。新モデルはない。

| 保存 | 物理bytes | 物理SHA256 | 解凍bytes | 解凍SHA256 |
| --- | ---: | --- | ---: | --- |
| [q0の判断.json.gz](q0の判断.json.gz) | 10,688,481 | `dd182e14a0c1da508fb266fb3fe91bfaf4a1da3f8bd308da11877060ade82e2e` | 501,666,963 | `ba3087f704758a37dd4842196c7bfa74d01e48166e670b4ada1b571eaf0c8d9b` |
| [選択対応.json.gz](選択対応.json.gz) | 361,654 | `b1d7730dc93f51d1fcfecae2de0d382fd54fff57e3a96a022daa8830768ba445` | 10,411,569 | `79287fd455e74d418e2a9bb9c34baec40aa800ec02c2705ce166aae96ee2e5ff` |
| [選択の確認.json.gz](選択の確認.json.gz) | 2,505 | `2aaf0cce8e10f6e7d1671ab72dc6e090f75d21db9c0968a04ed52afb9668a1ea` | 6,563 | `5968314374ebc0565d27f93371c51a76fede72a88b0c4e2af08ace4c38501cc9` |

147/148/152/153/154・数量測定・100X/大観測は共有し、新3JSON以外は再コピーしていない。[正式結果](../../study/00155_方向付き数量で既存入口を補正し順行入口を加える/README.md)・[保管索引](../../study/00155_方向付き数量で既存入口を補正し順行入口を加える/保管索引.json)。
