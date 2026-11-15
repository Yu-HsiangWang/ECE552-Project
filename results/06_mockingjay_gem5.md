# Mockingjay 在 gem5 的實作、驗證與結果統整（2026-11-14）

- **來源**：Endong 在 11-12 推上 `mockingjay` 分支，11-14 快轉合併進 main。
  - 6e49a8d：gem5 實作與驗證工具。
  - eea17c9：微基準與 SPEC 結果。
- **原始資料**：放在 `results/mockingjay/`。
  - `comparison.md`：英文完整表格。
  - `mj_*.csv`：各次 run 的數字。
  - `runs/`、`micro*/`：每次 run 的 stats、config 與 log。
- **統整表**：所有策略、三種 LLC 大小的 SPEC 結果都在 `06_all_policies.csv`，由 `tools/combine_results.py` 從各來源合併。合併時會檢查重疊的列是否一致，目前全部一致。

## 實作

- `gem5/src/mem/cache/replacement_policies/mockingjay_rp.{hh,cc}`（630 行），照 [05_mockingjay_ref.md](05_mockingjay_ref.md) 的做法接進 gem5：
  - **不能 bypass**：會被 bypass 的行照常插入，成為下一個 victim。
  - **老化**：每個 set 一個老化計數，讀 ETR 時再推算（lazy aging）。
  - **L2 的通知與寫回**：忽略 CleanEvict 通知。寫回造成的插入設 ETR = −15，寫回命中不更新。
- **安裝**：先跑 `install_hawkeye.py`（它也會套用兩個策略都需要的 gem5 修正），再跑 `gem5/install_mockingjay.py <gem5 目錄>`。
- **使用**：`hk_se.py --rp=Mockingjay`，或 `--rp=MockingjayI`。
  - MockingjayI 是對應 HawkeyeI 的變體，論文中沒有。
  - 指令抓取的行一律以 ETR 0 插入，而且不進 sampled cache。
- **統計**：記錄原設計會 bypass 的填入數、victim 是否已過期（ETR < 0）、沒有 PC 的存取數等。

## 審查結果（11-14）

- **與 ChampSim 版和參考模型逐項一致**：
  - 參數推導：取樣 set、INF_RD 127、MAX_RD 105、ETR ±15。
  - PC 簽名：3 步 CRC。
  - sampled cache 的索引、取代與反向訓練。
  - temporal difference：差距滿 16 才移動 1。
  - 老化順序：先訓練、再老化、再設定 ETR。
  - victim 選擇：|ETR| 最大的行；|ETR| 相同時優先選已過期的行。
  - 原設計 bypass 條件的判斷時機：在本次存取訓練之前判斷。
- **`mockingjay_ref.py check` 是獨立比對，不是用 gem5 的值自己比自己**：
  - 只從 gem5 log 取存取順序，以及 gem5 選用的 way 和 hit/miss。
  - RDP 訓練、ETR 計算、老化和 victim 選擇都由模型自己算，再逐筆跟 gem5 比對。
  - 如果 gem5 命中一個模型裡不存在的行，也會被抓出來。
- **數字可以重現**：
  - `comparison.md` 的每一格都能從 CSV 重算出來，結果一致。
  - 微基準的 miss 率也能從 stats.txt 重算，結果一致。
  - 各策略的 LLC 存取數與 LRU 相差不到 0.3%，比較的是同一串存取。
  - config 與 LRU 的 run 相同：LLC 2 MB、16-way、mostly inclusive。每次 run 都跑完 fast-forward、暖身和量測。
- **SPEC 的 `noPCAccesses` 全部是 0**：修正預取遺失 PC 之後，SPEC 上的 demand 存取確實都帶 PC。

## 功能驗證

`check` 比對了三個微基準 6 輪的全部 victim 和 ETR，0 不一致。比對的 victim 數與 gem5 統計的 victim 總數（invalid＋過期＋未過期）完全相同，表示 log 中每一筆都有比到：

| 微基準 | 比對的 victim 數 |
|---|---|
| fit | 17,343 |
| thrash | 289,499 |
| mix | 1,347,381 |

### 微基準 LLC miss 率（%）

| | fit | thrash | mix |
|---|---|---|---|
| LRU，6 輪 | 15.0 | 100 | 100 |
| BRRIP／DRRIP／SHiP，6 輪 | 15.0 | 46.8／61.7／90.0 | 96.4／99.1／100 |
| Hawkeye，6 輪 | 15.0 | 48.1 | 88.3 |
| **Mockingjay，6 輪（gem5）** | 15.0 | 58.3 | 96.5 |
| Mockingjay 不 bypass，6 輪（模型） | 14.3 | 55.4 | 96.4 |
| OPT，6 輪（模型） | 14.3 | 42.9 | 87.3 |
| LRU，20 輪 | 5.0 | 100 | 100 |
| **Mockingjay，20 輪（gem5）** | 5.0 | 44.5 | 91.2 |
| Mockingjay 不 bypass，20 輪（模型） | 4.8 | 41.7 | 91.2 |
| OPT，20 輪（模型） | 4.8 | 36.5 | 88.4 |

- MockingjayI 的結果與 Mockingjay 相同。checksum 全部與 LRU 一致。
- **thrash 比模型預期高約 3 點，原因在存取串流，不在策略**：
  - `pass()` 每輪都會寫每一行，所以 L2 每輪都把每行寫回 LLC（6 輪 thrash 有 340,373 次寫回、345,068 次 demand 存取）。
  - 其中 88,340 次寫回的行已經不在 LLC，要重新插入並淘汰一行。
  - 模型的 `micro_stream` 沒有這些寫回。由於 `check` 用 gem5 自己的事件序列重播時 0 不一致，差距只來自串流。
- Mockingjay 學得慢：6 輪時 thrash 和 mix 都不如 Hawkeye。20 輪時與 OPT 的差距縮小，thrash 從差 15.4 點縮到 8.0 點，mix 從差 9.2 點縮到 2.8 點。
  - Hawkeye 與內建策略目前只跑了 6 輪。期末報告要比較 20 輪，得補跑這些策略。

## SPEC CPU2017 結果

每格是「LLC miss 相對同大小 LRU 減少的比例 / IPC speedup」，粗體是該列 IPC 最高的策略。
「最佳內建」指 SRRIP、BRRIP、DRRIP、SHiP 中 IPC 最高的一個。

| 測項 | LLC | LRU MPKI | 最佳內建 | Hawkeye | HawkeyeI | Mockingjay | MockingjayI |
|---|---|---|---|---|---|---|---|
| mcf | 2 MB | 25.98 | SRRIP +1.0% / 1.000 | +6.3% / 1.014 | +6.3% / 1.014 | **+11.6% / 1.040** | +11.6% / 1.040 |
| omnetpp | 2 MB | 0.69 | SHiP **−3.0% / 1.000** | −20.4% / 0.986 | −11.6% / 0.991 | −9.2% / 0.992 | −5.7% / 0.994 |
| gcc | 2 MB | 0.55 | SRRIP +0.5% / 1.000 | −6.2% / 0.997 | **+3.1% / 1.003** | −1.7% / 0.999 | +2.3% / 1.002 |
| xalancbmk | 2 MB | 0.52 | BRRIP **+37.4% / 1.023** | +11.5% / 1.006 | +16.5% / 1.009 | +28.7% / 1.017 | +29.6% / 1.018 |
| xz | 2 MB | 0.35 | SHiP +0.8% / 1.001 | +5.5% / 1.003 | **+5.5% / 1.003** | +2.4% / 1.001 | +2.5% / 1.001 |
| deepsjeng | 2 MB | 0.26 | SHiP **+0.2% / 1.000** | +0.8% / 1.000 | +0.6% / 1.000 | −0.7% / 0.999 | −0.6% / 1.000 |
| mcf | 1 MB | 32.08 | SHiP +7.8% / 1.012 | **+6.3% / 1.016** | +6.3% / 1.016 | +8.3% / 1.010 | +8.3% / 1.010 |
| omnetpp | 1 MB | 0.96 | SHiP **−15.5% / 1.000** | −12.8% / 0.988 | −4.1% / 0.995 | −17.3% / 0.986 | −8.1% / 0.994 |
| xalancbmk | 1 MB | 4.74 | BRRIP **+52.8% / 1.213** | +19.5% / 1.061 | +22.6% / 1.075 | +45.6% / 1.172 | +46.6% / 1.180 |
| mcf | 4 MB | 22.27 | SRRIP +2.7% / 1.015 | +10.8% / 1.076 | +10.8% / 1.076 | **+19.2% / 1.144** | +19.2% / 1.144 |
| omnetpp | 4 MB | 0.68 | SHiP **−0.2% / 0.997** | −9.9% / 0.989 | −5.6% / 0.991 | −1.8% / 0.990 | −1.7% / 0.990 |
| xalancbmk | 4 MB | 0.15 | DRRIP +2.2% / 1.000 | +1.3% / 1.000 | **+4.5% / 1.001** | −30.0% / 0.995 | −29.8% / 0.995 |

### 指令／資料 miss（LRU / Hawkeye / HawkeyeI / Mockingjay / MockingjayI）

| 測項 | LLC | 指令 miss | 資料 miss |
|---|---|---|---|
| omnetpp | 1 MB | 6,382 / 23,780 / 2,558 / 20,380 / 4,880 | 186,581 / 193,826 / 198,340 / 205,966 / 203,673 |
| omnetpp | 2 MB | 662 / 11,113 / 577 / 4,271 / 637 | 136,741 / 154,327 / 152,788 / 145,707 / 144,628 |
| omnetpp | 4 MB | 474 / 5,070 / 474 / 972 / 480 | 136,019 / 144,883 / 143,696 / 137,952 / 138,320 |
| gcc | 2 MB | 3,282 / 10,952 / 1,161 / 4,963 / 1,444 | 106,980 / 106,122 / 105,706 / 107,215 / 106,233 |
| xalancbmk | 1 MB | 33,000 / 66,318 / 18,344 / 41,927 / 16,905 | 915,430 / 697,277 / 715,805 / 473,897 / 489,661 |
| xalancbmk | 2 MB | 2,078 / 6,193 / 1,574 / 2,933 / 1,626 | 101,439 / 85,451 / 84,897 / 70,889 / 71,257 |
| xalancbmk | 4 MB | 88 / 809 / 90 / 375 / 294 | 30,575 / 29,445 / 29,181 / 39,473 / 39,509 |

### Mockingjay 的計數器（Mockingjay，不含 MockingjayI）

| 測項 | 原設計會 bypass 的填入（1 / 2 / 4 MB） | 已過期的 victim（1 / 2 / 4 MB） |
|---|---|---|
| mcf | 64% / 80% / 95% | 17% / 19% / 5% |
| omnetpp | 14% / 4.5% / 1.4% | 44% / 53% / 56% |
| xalancbmk | 34% / 41% / 37% | 22% / 49% / 66% |
| gcc（2 MB） | 80% | 33% |
| xz（2 MB） | 52% | 41% |
| deepsjeng（2 MB） | 98% | 40% |

## 觀察

1. **mcf 上 Mockingjay 明顯最好**：
   - 2 MB 時減少 11.6% miss、IPC +4.0%，4 MB 時減少 19.2%、IPC +14.4%。miss 減少量都接近 Hawkeye 的兩倍（Hawkeye 是 6.3%、10.8%）。
   - 1 MB 時 Mockingjay 減少最多 miss（8.3%），但 IPC 仍是 Hawkeye 最高（1.016 對 1.010）。
2. **xalancbmk**：
   - 1 MB、2 MB 時，Mockingjay 的資料 miss 遠少於 Hawkeye（1 MB：473,897 對 697,277）。能排出重用的先後順序確實有幫助，但仍不如 BRRIP。
   - 4 MB 時 Mockingjay 反而比 LRU 多 30% miss。不過 MPKI 只從 0.15 升到 0.20，IPC 只少 0.5%。
     - 多出來的幾乎都是資料 miss（39,473 對 30,575；指令 miss 只多 287 次）。
     - 66% 的 victim 是已過期的行（2 MB 時是 49%）。
     - 推測：快取夠大時，很多行超過預測的重用時間後仍會被用到。LRU 留得住這些行，Mockingjay 卻把它們當成已過期先淘汰。這點待分析。
3. **omnetpp**：
   - 所有策略都輸 LRU，Mockingjay 輸得比 Hawkeye 少（2 MB：−9.2% 對 −20.4%）。
   - Mockingjay 也有指令行的問題，但比 Hawkeye 輕（2 MB 指令 miss：4,271 對 11,113，LRU 是 662）。
   - MockingjayI 把指令 miss 降回 LRU 的水準，剩下的損失都是資料 miss，這點和 HawkeyeI 相同。
4. **gcc、xz、deepsjeng**：
   - gcc 上 MockingjayI（+2.3%）接近 HawkeyeI（+3.1%）。
   - xz 上 Hawkeye（+5.5%）比 Mockingjay（+2.4%）好。
   - deepsjeng 上所有策略都在 ±1% 內。
5. **不能 bypass 的影響可能比微基準估的大**：
   - mcf 有 64–95% 的填入、deepsjeng 有 98%，在原設計中都會被 bypass。
   - gem5 版把這些行插入成下一個 victim，它們會占住一路，直到下一次填入把它淘汰。
   - 微基準估計最多只差 1.2 點，但 SPEC 上這類填入多得多，所以 gem5 版可能低估了 Mockingjay 在 mcf 上的效果。
   - LLC 的 demand 存取串流幾乎不受 LLC 策略影響（存取數與 LRU 相差不到 0.3%），所以可以把 gem5 的 LLC 存取 log 餵給參考模型，離線比較 bypass 與不 bypass。

## 期末報告前的待辦

- [ ] Hawkeye 的預測器、RRPV、victim 逐筆比對，達到 Mockingjay `check` 的程度（status report 承諾 11/22 前完成）。
- [ ] 內建策略與 Hawkeye 補跑 20 輪微基準，跟 Mockingjay 一起比。
- [ ] 用 SPEC 的 LLC 存取 log 離線估計 Mockingjay 真正 bypass 時的 miss（mcf、deepsjeng、gcc 最值得做）。
- [ ] 分析 xalancbmk 4 MB 的損失（已過期 victim 的重用情形）。
- [ ] 期末報告的分工要照實際情形更新（Mockingjay 的 gem5 程式由 Endong 提交）。
