# 終了前決済の共用数値表

179 F0を固定した後、共用163/167の48byte原行順価格索引から一度だけ生成した。旧正本・原板は変更せず、巨大原板や価格索引を重複保存しない。

- `旧73_overlay179.npz` / `.json`：31,642 caseのcase×実側×幅×期限配列と束縛metadata。
- `追加7_overlay179.npz` / `.json`：3,250 caseの同形式。
- [保存索引](保存索引.json)：Source/F0・サイズ・SHA・無変更領域の照合証拠。

Dayは15:30、Nightは05:45までを対象時間の分母とする。各締切60秒前に全決済要求・新規停止・pending取消を行い、要求1秒後以降かつ締切以下の最初の正常BBOを強制返済に用いる。後で最終/最良価格を選ばない。通常IFD/期限が先なら先の出口、同原行の先置IFDを優先する。通常期限の30秒猶予と価格/BBOの300秒gapを保持する。

金融未知は `known=False`・金額/exit時刻はNaNとして保存する。資料化時は未知の収支をNoneへ変換し、0円にしない。`holding_confirmed_until` は既知ならexit、未知なら有効観測内で最後に正常BBOを確認した時刻であり、欠測空白を保有下限へ足さない。`status` の意味・全shape/dtype・case順/取得/場時計のbindingはmetadataに残す。

Sourceは `work/179終了前決済/early179.py`。`load_overlay(context,new,このdirectory)` により、Source・case順・純取得・軸・manifest・NPZ指紋を確認して読む。179以後はこの一組を共用し、各試行のZIPへNPZを重複保存しない。

生成時の旧既知exitが強制要求より前の全セルで、旧数値表とlabel/known/net/exit_time/index/lineが一致した。旧73は2,574,413セル、追加7は267,438セル。これは無変更領域の算術照合であり、売買手法の成績・順位の評価ではない。
