# SPEC CPU2017 主實驗（2026-10-31，tag v2）

系統：gem5 v23.0.0.1、X86 SE、O3CPU；L1I/L1D 32 KB 4-way、L2 256 KB 8-way、LLC 2 MB 16-way（mostly inclusive）。
Hawkeye 用 CRC2 預設參數（2K × 5-bit 預測器、OPTgen 容量 14、64 個取樣 set）。
每個測項：atomic CPU fast-forward 10 億條指令 → O3 暖身 5000 萬條 → 量測 2 億條（原論文是 50M 暖身 + 200M 量測）。
腳本：`gem5/scripts/run_all_spec.sh`；原始數字：[02_spec_main.csv](02_spec_main.csv)（`tools/collect_stats.py` 產生）。

## 測項選擇

| 測項 | 說明 |
|---|---|
| 605.mcf_s、623.xalancbmk_s、620.omnetpp_s | speed 版 |
| 502.gcc_r、531.deepsjeng_r、557.xz_r | rate 版：speed 版要 7–15 GB 記憶體，EC2（15 GB、無 swap）跑不了 |
| 607.cactuBSSN_s | 不列入：每次 LLC 存取都 miss（純串流），所有策略結果相同 |

## LLC miss 相對 LRU 的變化（正值 = miss 變少）與 IPC speedup

| 測項 | LRU MPKI | SRRIP | BRRIP | DRRIP | SHiP | Hawkeye |
|---|---|---|---|---|---|---|
| 605.mcf_s | 25.98 | +1.0% / 1.000 | −8.3% / 0.933 | −1.3% / 0.975 | +2.4% / 0.982 | **+6.3% / 1.014** |
| 623.xalancbmk_s | 0.52 | +21.0% / 1.012 | **+37.4% / 1.023** | +33.9% / 1.020 | +17.8% / 1.010 | +11.5% / 1.006 |
| 620.omnetpp_s | 0.69 | −0.5% / 0.999 | −39.2% / 0.991 | −10.2% / 0.997 | −3.0% / 1.000 | −20.4% / 0.986 |
| 502.gcc_r | 0.55 | +0.5% / 1.000 | −13.9% / 0.990 | −3.2% / 0.998 | −1.4% / 0.999 | −6.2% / 0.997 |
| 557.xz_r | 0.35 | +0.3% / 1.000 | −7.4% / 0.996 | −1.7% / 0.999 | +0.8% / 1.001 | **+5.5% / 1.003** |
| 531.deepsjeng_r | 0.26 | +0.3% / 1.000 | −2.3% / 0.999 | −0.4% / 1.000 | +0.2% / 1.000 | +0.8% / 1.000 |

每格是「miss 變化 / IPC speedup」。

## 觀察

- **mcf**（唯一 MPKI 高的測項）：Hawkeye 是唯一 miss 和 IPC 都贏 LRU 的策略。
- **xalancbmk**：BRRIP/DRRIP 最好。工作集接近 LLC 容量，「新進的行先低優先」就很有效；Hawkeye 也贏 LRU，但幅度較小。
- **omnetpp**：Hawkeye 比 LRU 多 20% miss。其中 LLC 的**指令** miss 從 662（LRU）變成 11,113，指令行被踢掉是主要原因，待分析。
- **gcc_r、xz_r、deepsjeng_r**：MPKI 都低於 0.6，LLC 影響很小，IPC 差異都在 1% 以內。
- 原論文在 SPEC2006 上平均減少 17% miss。我們的差距可能來自：不同測項、gem5 的 mostly-inclusive LLC（LLC 只看到 L2 的 miss 和寫回）、只量 2 億條指令。

## 實驗：L2 驅逐時刷新（HawkeyeR，2026-11-01）

假設：gem5 的 LLC 是 mostly inclusive，行留在 L2 的期間 LLC 看不到它被使用。LRU 把 L2 的驅逐通知（CleanEvict、寫回）當成一次使用，Hawkeye 則完全忽略。
HawkeyeR：收到驅逐通知時，若該行的 PC 仍預測為 friendly，就把它的 RRPV 設為 0（不訓練）。選項預設關閉，不影響 Hawkeye 本身的結果。

| 測項 | Hawkeye | HawkeyeR | 刷新次數 |
|---|---|---|---|
| 605.mcf_s | +6.3% / 1.014 | +6.3% / 1.014 | 5,884,681 |
| 623.xalancbmk_s | +11.5% / 1.006 | +11.7% / 1.006 | 3,236,621 |
| 620.omnetpp_s | −20.4% / 0.986 | −18.6% / 0.987 | 1,104,754 |
| 502.gcc_r | −6.2% / 0.997 | −6.1% / 0.997 | 214,181 |
| 557.xz_r | +5.5% / 1.003 | +5.5% / 1.003 | 32,243 |
| 531.deepsjeng_r | +0.8% / 1.000 | +0.6% / 1.000 | 7,366 |

結果：幾乎沒有差別。omnetpp 的 LLC 指令 miss 只從 11,113 降到 10,314（LRU 是 662）。只刷新 friendly 的行不足以解釋與 LRU 的差距。
omnetpp 的 OPTgen 判定 99.9% 的重用是 OPT hit（38,338 / 38,382），但仍有 135,634 次 averse 預測。

## 實驗：不論預測都刷新（HawkeyeA）與指令／資料分開統計

HawkeyeA：收到 L2 的驅逐通知時，不論預測，一律把該行的 RRPV 設為 0。

| 測項 | Hawkeye | HawkeyeR | HawkeyeA |
|---|---|---|---|
| 605.mcf_s | +6.3% / 1.014 | +6.3% / 1.014 | +5.2% / 1.005 |
| 623.xalancbmk_s | +11.5% / 1.006 | +11.7% / 1.006 | +8.4% / 1.004 |
| 620.omnetpp_s | −20.4% / 0.986 | −18.6% / 0.987 | −11.8% / 0.992 |
| 502.gcc_r | −6.2% / 0.997 | −6.1% / 0.997 | −8.2% / 0.994 |
| 557.xz_r | +5.5% / 1.003 | +5.5% / 1.003 | +2.9% / 1.001 |
| 531.deepsjeng_r | +0.8% / 1.000 | +0.6% / 1.000 | +0.0% / 1.000 |

HawkeyeA 讓 omnetpp 少輸一半，但其他測項都變差：把 averse 的行也刷新，等於丟掉 Hawkeye 的預測。不是可行的修正。

另外加了統計（`isInstFetch()` 判斷指令抓取；只加統計的 Hawkeye 重跑，結果與原本完全相同）。LLC miss 依指令／資料拆開：

| 測項 | 指令 miss：LRU / SRRIP / DRRIP / SHiP / Hawkeye | 資料 miss：LRU / Hawkeye |
|---|---|---|
| 502.gcc_r | 3,282 / 3,291 / 4,226 / 5,004 / **10,952** | 106,980 / **106,122** |
| 620.omnetpp_s | 662 / 806 / 822 / 815 / **11,113** | 136,741 / 154,327 |
| 623.xalancbmk_s | 2,078 / 1,679 / 1,134 / 1,932 / **6,193** | 101,439 / 85,451 |

Hawkeye 的指令 victim 幾乎都是被預測為 averse 的行：

| 測項 | 指令抓取預測為 averse | 指令 victim 中 averse 的比例 |
|---|---|---|
| 502.gcc_r | 13,674 / 85,019（16%） | 10,055 / 11,433（88%） |
| 620.omnetpp_s | 25,461 / 188,525（14%） | 10,583 / 10,976（96%） |
| 623.xalancbmk_s | 39,602 / 386,787（10%） | 4,811 / 6,224（77%） |

觀察：
- gcc 的**資料** miss 其實比 LRU 少，輸 LRU 完全是因為指令 miss（10,952 vs 3,282）。omnetpp 多出的 28,037 次 miss 中，10,451 次來自指令；xalancbmk 的指令 miss 也是 LRU 的 3 倍。
- 指令抓取的「PC」就是抓取位址本身，不是 load 指令。每個指令行有各自的 PC，與資料的 PC 共用 2K 項的預測器，所以一部分指令行被預測為 averse，以 RRPV 7 插入，最先被踢掉。
- 原論文的模擬器是否把指令抓取送進 LLC 還沒查證；若沒有，這就是 gem5 與原論文差異的來源之一。

## 實驗：指令行一律 friendly（HawkeyeI）

HawkeyeI：指令抓取帶進來的行一律以 friendly 插入；指令抓取位址不訓練預測器，也不反向訓練（OPTgen 仍計入它們的占用）。選項預設關閉。

| 測項 | Hawkeye | HawkeyeI | 指令 miss：LRU / Hawkeye / HawkeyeI |
|---|---|---|---|
| 605.mcf_s | +6.3% / 1.014 | +6.3% / 1.014 | 0 / 1 / 1 |
| 623.xalancbmk_s | +11.5% / 1.006 | **+16.5% / 1.009** | 2,078 / 6,193 / 1,574 |
| 620.omnetpp_s | −20.4% / 0.986 | **−11.6% / 0.991** | 662 / 11,113 / 577 |
| 502.gcc_r | −6.2% / 0.997 | **+3.1% / 1.003** | 3,282 / 10,952 / 1,161 |
| 557.xz_r | +5.5% / 1.003 | +5.5% / 1.003 | 62 / 44 / 27 |
| 531.deepsjeng_r | +0.8% / 1.000 | +0.6% / 1.000 | 84 / 31 / 16 |

觀察：
- 指令 miss 降到比 LRU 還少；gcc 從輸 LRU 變成贏，xalancbmk 從 +11.5% 升到 +16.5%，其他測項不變。
- gcc、xalancbmk 的**資料** miss 也略降（106,122 → 105,706；85,451 → 84,897）：指令抓取位址不再占用預測器的項目。
- omnetpp 仍輸 LRU 11.6%，剩下的全是資料 miss（152,788 vs 136,741），原因待查。
- xalancbmk 仍不如 BRRIP（+37.4%）和 DRRIP（+33.9%）。



## 修正紀錄（這輪之前）

| 問題 | 影響 | 修正 |
|---|---|---|
| gem5 對每個封包都查 tag，L2 的 CleanEvict 通知會呼叫替換策略 | Hawkeye 把它們當成存取來訓練（mcf 有 870 萬筆），mcf 比 LRU 差 8.7% | Hawkeye 忽略 CleanEvict（a02da83） |
| gem5 x86-64 `newfstatat` 用錯 stat 結構 | SE 模式下 opendir 失敗，omnetpp、gcc 無法執行 | `install_hawkeye.py` 改用 `fstatat64Func`（a02da83） |
| gem5 快取複製軟體預取 request 時沒帶 PC | omnetpp 有 28% 的 LLC 存取沒有 PC，Hawkeye 和 SHiP 把它們全算在同一個 PC 下；Hawkeye 在 omnetpp 從 −28% 改善到 −20% | 複製 PC（8886623）；只重跑 SHiP、Hawkeye（其他策略不讀 PC） |

修正軟體預取前的 SHiP、Hawkeye 結果保留在 EC2 的 `out/*/{SHiP,Hawkeye}_v2nopfpc/`。
