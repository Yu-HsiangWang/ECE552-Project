# Hawkeye 重現計畫（gem5）

論文：A. Jain and C. Lin, "Back to the Future: Leveraging Belady's Algorithm for Improved Cache Replacement," ISCA 2016。
參考碼：CRC2（2nd Cache Replacement Championship）ChampSim 版 Hawkeye。
**不做 Verilog PPA**（使用者 10-29 決定）。

> 10-29 已對照論文原文核對：OPTgen 8× 歷史、16-way 以 4 次存取為一格共 32 格×4 bit、64 個取樣 set、Sampled Cache 2400 項（部分 tag＋PC＋1-byte timestamp，LRU，12KB）、預測器 8K×3-bit、13-bit PC hash、friendly 插入時其他行 <6 才 +1、總預算約 16KB／2MB LLC。原文評估：CRC（CMP$im）4-wide OoO、128 ROB；L1 32KB 4-way、L2 256KB 8-way、LLC 2MB 16-way 20 cycles、DRAM 200 cycles；SPEC2006 SimPoint 250M 指令（暖身 50M、量 200M）；基準 LRU/DRRIP/SHiP/SDBP/DSB/OPT；Hawkeye 相對 LRU miss −17.0%、IPC +8.4%（4 核 +15.0%）。

## 1. 機制

**目標**：Belady OPT（踢掉未來最晚才會再被用到的那一行）是最佳替換，但需要知道未來。Hawkeye 用「過去的 OPT 決策」來預測未來。

1. **OPTgen（只在取樣的 set 上跑）**
   - 每個取樣 set 保存最近約 8×associativity 次存取的歷史 ⚠，以及一個 occupancy vector：記錄每個時間點，OPT 會在這個 set 裡放了幾行。
   - 某一行 X 再次被存取時，檢查從 X 上次存取到這次之間，occupancy 是否都還小於 associativity：
     - 是：OPT 在這段期間留得住 X，所以 OPT 會命中。把這段期間的 occupancy 都加 1。
     - 否：OPT 會 miss。
   - 這個結果用來給 X **上一次**存取的 PC 貼標籤：命中代表 cache-friendly，miss 代表 cache-averse。
2. **PC 預測器**
   - 一張以 PC 雜湊為索引的 3-bit 飽和計數器表（約 8K 項 ⚠）。
   - OPTgen 判為命中就加 1，判為 miss 就減 1。
   - 計數器最高位為 1 時預測 friendly。
3. **替換（RRIP 式，3-bit RRPV）**
   - 預測 averse：插入時 RRPV = 7，最先被踢掉。
   - 預測 friendly：插入或命中時 RRPV = 0，並讓其他 friendly 行老化，但上限 6，所以 friendly 行不會變成 7 ⚠。
   - 選 victim：優先踢 RRPV = 7 的行。如果沒有，就踢 RRPV 最大的 friendly 行，並對該行的 PC **反向訓練**（計數器減 1）。
4. **CRC2 版本的延伸** ⚠：demand 和 prefetch 分開預測；多核心時用 PC 加 core ID 當索引。

## 2. gem5 實作

- 新增 `src/mem/cache/replacement_policies/hawkeye_rp.{hh,cc}`，在 `ReplacementPolicies.py` 註冊，參考 `ship_rp.cc`。
  - `instantiateEntry()`：每行的替換資料存 RRPV、PC 簽名、是否 friendly。
  - `reset(data, pkt)`（插入）和 `touch(data, pkt)`（命中）：從 `pkt->req->getPC()` 取 PC，查預測器、設定 RRPV。如果 `pkt->getAddr()` 落在取樣 set，就餵給 OPTgen。
  - `getVictim(candidates)`：沒有封包，只能用替換資料裡存的 PC 簽名做反向訓練。它是 const 函式，預測器要宣告成 `mutable`。
  - 沒有 PC 的請求（預取、寫回）：先比照 SHiP 用一個固定簽名，之後再看要不要分開處理。
- **第一個要確認的技術點**：L1 miss 傳到 L2/LLC 的封包是否還帶著 PC，以及沒有 PC 的請求佔多少比例。做法：先在 LLC 用內建的 `SHiPRP`（PC 版）跑一次，加統計算出無 PC 的比例。
- 比較基準全部用 gem5 內建：`LRURP`、`BRRIPRP`、DRRIP（用 `DuelingRP` 組 SRRIP 和 BRRIP）、`SHiPRP`。Belady OPT 本身用離線的 Python 模擬器跑 trace，當作上限。

## 3. 系統與工作負載

- gem5 SE 模式、O3CPU，三層快取：L1 32 KB、L2 256 KB、LLC 2 MB 16-way。替換策略只換 LLC 的。⚠ 對照論文設定再定。
- 工作負載：SPEC CPU2017 中對記憶體敏感的子集，例如 mcf、lbm、omnetpp、xalancbmk、gcc。先快轉，再跑一段固定的指令數。⚠ 要確認 Duke 有沒有 SPEC 授權。
- 指標：LLC MPKI、IPC、相對 LRU 的加速比，以及跟 Belady OPT 的差距。
- 敏感度分析（時間夠才做）：取樣 set 數、預測器大小、LLC 容量。

## 4. 驗證（老師要求 µBench 加逐步輸出）

- **OPTgen 單元驗證**：同一條位址 trace 同時餵給 Python 版 Belady OPT 和 gem5 的 OPTgen，逐筆比對命中或 miss 的標籤。
- **微基準**（自寫 C 程式）：
  - 循環掃描超過容量的陣列：LRU 命中率接近 0，OPT 和 Hawkeye 應該留住一部分。
  - 有重用的小工作集混上串流：測試抗掃描能力。
  - 完全放得下的工作集：所有策略都應該命中。
- **除錯輸出**：開一個 debug flag，每次存取印出 set、PC、預測結果、RRPV、OPTgen 標籤和 victim，用來逐步對照。
- 跟 CRC2 ChampSim 版用同一條 trace 對照決策，可行就做。

## 5. 時程草案（12/3 截止）

| 項目 | 日期 | 內容 |
|---|---|---|
| M1 | 10/29–11/4 | 讀論文和 CRC2 程式碼；建好 gem5 和 LLC 設定；確認 PC 傳得到 LLC；重交 proposal |
| M2 | 11/3–11/12 | 實作 Hawkeye（OPTgen、預測器、替換策略）和 Python OPT 參考 |
| M3 | 11/10–11/17 | 微基準和 OPTgen 逐筆驗證 |
| M4 | 11/14–11/26 | SPEC 跑分、基準比較、敏感度分析 |
| M5 | 11/24–12/3 | 期末報告和簡報 |

## 6. 跟往年課程專案的差別

往年有一組做「DRRIP and BRRIP Caching」（見課程規定原文）。那組實作 RRIP 系列，本專案則把 RRIP 當基準，實作以 Belady OPT 為學習目標、用 PC 預測的 Hawkeye。
