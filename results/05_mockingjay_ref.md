# Mockingjay 參考模型與 gem5 設計（2026-11-10）

gem5 實作之前先完成的部分：Python 參考模型 `tools/mockingjay_ref.py`、硬體成本、微基準的預期值，以及接進 gem5 介面的做法。

## 參考模型

- 依照公開的 ChampSim 單核心 Mockingjay 實作（Apache 2.0）重寫，沒有複製程式碼。參數由 LLC 大小推出，2 MB、16-way 時：
  - 取樣 set 32 個，每個取樣 set 配 16 組 × 5 路的 sampled cache。
  - 時間戳 8 bit，PC 簽名 11 bit，簽名包含 hit 位元。
  - RDP 的 INF_RD = 127、MAX_RD = 105，以 temporal difference 訓練（差距滿 16 才移動 1）。
  - 每行一個 5-bit 有號 ETR（±15），每 8 次 set 存取老化一次。
- 用法：
  - `python3 tools/mockingjay_ref.py micro [--passes N] [--check-lazy]`：跑微基準的存取串流。
  - `python3 tools/mockingjay_ref.py log <gem5 Hawkeye debug log>`：重播 gem5 的 LLC 存取。
  - `python3 tools/mockingjay_ref.py storage --sets 2048`：算硬體成本。

## 硬體成本

| 結構 | 2 MB | 1 MB | 4 MB |
|---|---|---|---|
| 每行 ETR（5 bit） | 20.00 KB | 10.00 KB | 40.00 KB |
| 每 set 老化計數（3 bit） | 0.75 KB | 0.38 KB | 1.50 KB |
| RDP（7 bit） | 1.75 KB | 0.88 KB | 3.50 KB |
| Sampled cache（每項 30 bit） | 9.38 KB | 4.69 KB | 18.75 KB |
| 取樣 set 時間戳 | 0.03 KB | 0.02 KB | 0.06 KB |
| **合計** | **31.91 KB** | 15.95 KB | 63.81 KB |

2 MB 的 31.91 KB 與論文相同，可確認參數無誤。Hawkeye 是 30.0 KB（見 [03_hawkeye_storage.md](03_hawkeye_storage.md)）。

## 微基準的預期值（LLC miss 率 %）

串流照 `llc_patterns.c` 與 `run_micro.sh` 的參數產生。每輪每行在 LLC 存取一次，`alloc()` 先寫一遍也算一輪。
GCC -O2 會把 `pass()` 展開成三份，所以 mix 的重用陣列與串流 PC 不同。

| | fit | thrash | mix |
|---|---|---|---|
| 存取數（6 輪；gem5 實測） | 114,688（115,691） | 344,064（345,068） | 901,120（902,159） |
| LRU，6 輪 | 14.3 | 100 | 100 |
| OPT，6 輪 | 14.3 | 42.9 | 87.3 |
| Mockingjay，6 輪 | 14.3 | 54.2 | 96.4 |
| Mockingjay 不 bypass，6 輪 | 14.3 | 55.4 | 96.4 |
| OPT，20 輪 | 4.8 | 36.5 | 88.4 |
| Mockingjay，20 輪 | 4.8 | 41.3 | 91.2 |
| Mockingjay 不 bypass，20 輪 | 4.8 | 41.7 | 91.2 |

- 存取數與 gem5 實測只差 0.3%。thrash 的 OPT（42.9%）也與從 gem5 log 算出的 43.0% 一致，所以這些串流足以代表 gem5 的微基準。
- **學得慢**：一行要在取樣 set 經過 127 次存取還沒被重用，才會判定為不重用。mix 每輪每 set 約 40 次存取，串流的預測要到第 3 輪才變成 127。在那之前，串流看起來比重用陣列更快會被用到，反而是重用陣列被 bypass。第 4 輪起才留住重用陣列，第 5 輪起全部命中。所以 gem5 上的 Mockingjay 微基準要跑 20 輪。
- **不能 bypass 的代價**：最多 1.2 個百分點（thrash 6 輪），20 輪時只有 0.4。
- 學到的預測：fit 的 pass PC 是 8，thrash 是 24，mix 的重用陣列是 40、串流是 127（不重用）。

## 接進 gem5 的做法

| 問題 | 做法 |
|---|---|
| gem5 的替換策略不能拒絕插入 | 照常插入。會被 bypass 的行，ETR 一定是 set 中最大的（rd/8 大於其他行，或 rd > MAX_RD 時為 15），所以會成為下一個 victim。 |
| reset()/touch() 只拿得到被存取的那一行，無法每 8 次存取把整個 set 的 ETR 減 1 | 每 set 一個老化計數器。每行記下設定 ETR 時的計數，比較時再算「目前 ETR = max(ETR − 經過的次數, −15)」，±15 的行不變。模型用 `--check-lazy` 比對兩種做法，在 6 輪的 136 萬次存取上決策完全相同（bypass 與不 bypass 兩種模式）。 |
| getVictim() 沒有封包 | ETR 存在每行的 replacement data，set 由 candidates 取得，與 Hawkeye 相同。 |
| L2 寫回 | 照 ChampSim：寫回造成的插入設 ETR = −15，寫回命中不更新。 |
| CleanEvict 通知 | 忽略（Hawkeye 已修過同樣的問題）。 |
| 指令抓取 | PC 就是抓取位址。先照原設計跑，再測一個指令行特別處理的版本（對應 HawkeyeI）。 |
| 驗證 | 加 debug flag 印出每次存取的 set、位址、簽名、量到的重用距離與 ETR，再擴充參考模型逐筆比對，與 Hawkeye 的 `check` 相同。 |
