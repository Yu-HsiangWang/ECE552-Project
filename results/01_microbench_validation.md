# 微基準與 OPTgen 驗證（2026-10-29，10-30 修正後重跑）

系統：gem5 v23.0.0.1、X86 SE、O3CPU；L1I/L1D 32 KB 4-way、L2 256 KB 8-way、LLC 2 MB 16-way。
Hawkeye 用 CRC2 預設參數（2K × 5-bit 預測器、OPTgen 容量 14、64 個取樣 set）。
程式：`tools/microbench/llc_patterns.c`，腳本 `tools/microbench/run_micro.sh`。

10-30 修正兩件事後全部重跑（a02da83）：Hawkeye 不再把 L2 的 CleanEvict 通知當成存取；gem5 的 x86-64 `newfstatat` 改用正確的 stat 結構。
基準策略的數字與修正前完全相同；Hawkeye 在 thrash 從 47.1% 變 48.1%、mix 從 87.6% 變 88.3%。

## LLC miss 數（miss 率）

| 模式 | 指令數 | LLC 存取 | LRU | SRRIP | BRRIP | DRRIP | SHiP | Hawkeye |
|---|---|---|---|---|---|---|---|---|
| fit：1 MB × 6 輪 | 5.1 M | 115,691 | 17,343 (15.0%) | 17,343 (15.0%) | 17,343 (15.0%) | 17,343 (15.0%) | 17,343 (15.0%) | 17,343 (15.0%) |
| thrash：3 MB × 6 輪 | 15.2 M | 345,068 | 345,068 (100%) | 345,068 (100%) | 161,639 (46.8%) | 213,061 (61.7%) | 310,681 (90.0%) | 165,951 (48.1%) |
| mix：1 MB 重用＋24 MB 串流 × 6 輪 | 109.3 M | 902,159 | 902,129 (100%) | 902,135 (100%) | 869,366 (96.4%) | 893,886 (99.1%) | 902,143 (100%) | 796,465 (88.3%) |

IPC：thrash 時 LRU 0.82、Hawkeye 1.10；mix 時 LRU 1.14、Hawkeye 1.21。

## 是否符合預期

- **fit**：陣列放得下，所有策略只有第一次的強制 miss，結果完全相同。✅
- **thrash**：每個 set 循環存取 24 行，但只有 16 路。LRU 每次都踢掉下一個要用的行，全部 miss。Hawkeye 和 BRRIP 都能留住一部分，miss 率約 47–48%。✅
- **mix**：只有 Hawkeye 能分辨出「重用陣列」和「只用一次的串流」，留住重用陣列，miss 率最低（88.3%）。LRU、SRRIP、SHiP 全部 miss。✅
- **程式結果**：每種模式在六種策略下的 checksum 都相同（fit 9682944、thrash 29048832、mix 47431680），替換策略沒有改變程式行為。✅

## OPTgen 逐筆驗證

用 `--debug-flags=Hawkeye` 重跑 Hawkeye 的 thrash，再用 `tools/hawkeye_ref.py check` 以 Python 重算 OPTgen 和 sampler：

| 項目 | 結果 |
|---|---|
| log 中的 demand 存取 | 345,074 |
| OPTgen 判斷次數（gem5 / Python） | 9,218 / 9,218 |
| **不一致** | **0** |
| 同一串存取的 LRU miss 率（Python） | 99.95% |
| 同一串存取的 Belady OPT miss 率（Python） | 43.0% |

Hawkeye 在 thrash 上的 miss 率（48.1%）只比 OPT（43.0%）高約 5 個百分點。

## 其他統計（Hawkeye，thrash）

- `noPCAccesses` = 0、`cleanEvicts` = 162：修正前的 161 筆「沒有 PC 的存取」其實就是 CleanEvict 通知，現在已排除。
- `agingSkipped` = 0：老化時記下的 set 每次都和插入的 set 一致，介面上的做法沒有出錯。
- OPTgen 在取樣 set 上的 OPT 命中率：49.9%。
- 在 SPEC mcf 上，CleanEvict 有 870 萬筆，跟真正的存取一樣多，修正前會嚴重污染訓練；微基準因為幾乎沒有這類通知，所以修正前後差不多。
