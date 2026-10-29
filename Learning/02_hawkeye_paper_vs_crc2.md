# Hawkeye：論文和 CRC2 程式碼的差異

Hawkeye 有兩個版本：

- **論文**：Jain & Lin, ISCA 2016。
- **CRC2 程式碼**：作者參加 2nd Cache Replacement Championship（2017）時交的版本，放在 CRC2 模擬器套件的 `example/hawkeye_final.cc`、`optgen.h`、`hawkeye_predictor.h`。

這個程式碼是 UT Austin 的研究授權：學術使用可以，散佈不行，所以**不放進本 repo**。我們的 gem5 版本（`gem5/src/mem/cache/replacement_policies/hawkeye_rp.*`）是照演算法自己寫的。

## 參數差異

| 項目 | 論文 | CRC2 程式碼 | 我們的預設 |
|---|---|---|---|
| 預測器大小 | 8K 項 | 2K 項 | 2K（可調） |
| 計數器位元 | 3 bit | 5 bit | 5（可調） |
| PC 雜湊 | 13-bit hash | CRC-32 後取餘數 | CRC-32 |
| 計數器初始值 | 沒寫 | 中間值（第一次碰到的 PC 預測為 friendly） | 中間值 |
| OPTgen 時間粒度 | 每格 4 次存取，共 32 格 | 每格 1 次存取，共 128 格 | 128 格 |
| OPTgen 容量上限 | associativity（16） | **ways − 2**（14） | 14（可調） |
| 取樣 set 數 | 64 個隨機 set | 由位元比對巨集決定，2048 個 set 時實際是 32 個 | 64 個（斜向分布） |
| Sampler | 2400 項、LRU | 2800 項，分成 350 組 × 8 路，tag 是 `CRC(addr>>12) % 256` | 同 CRC2 |
| 每 set 計時器 | 1 byte timestamp | 10 bit（範圍 1024），會檢查是否繞回 | 同 CRC2 |

## 行為差異

1. **反向訓練**：論文說被踢掉的 friendly 行「如果在 sampler 裡」就反向訓練；CRC2 是「如果它所在的 set 是取樣 set」就反向訓練。我們照 CRC2。
2. **老化**：friendly 行在 miss 時插入，如果 set 裡已經有行的 RRPV 等於 6，就整個 set 都不老化；否則所有 RRPV < 6 的行加 1。論文沒寫「有 6 就不老化」這條，我們照 CRC2。
3. **平手時選哪一行**：沒有 RRPV = 7 的行時，選 RRPV 最大的；如果有好幾行一樣大，CRC2 選最後一個。我們照 CRC2。
4. **Writeback**：CRC2 完全不處理 writeback（不訓練，也不改 RRPV）。gem5 的 LLC 會因為 L2 的 writeback 而插入新行，所以我們讓 writeback 插入的行一律當 cache-averse（RRPV = 7），而且不訓練。
5. **Prefetch**：CRC2 另有一套給 prefetch 用的預測器。我們的系統沒有預取器，所以只做 demand 這套。

## gem5 介面帶來的差異

gem5 的 `reset()` 只拿得到正在插入的那一行，但 Hawkeye 插入 friendly 行時要讓同 set 的其他行老化。
gem5 每次插入前一定會先對同一個 set 呼叫 `getVictim()`，所以我們在 `getVictim()` 記下這個 set，`reset()` 再拿來老化，並檢查 set 編號是否一致。
不一致的次數記在統計 `agingSkipped`，正常應該是 0。
