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

## 修正紀錄（這輪之前）

| 問題 | 影響 | 修正 |
|---|---|---|
| gem5 對每個封包都查 tag，L2 的 CleanEvict 通知會呼叫替換策略 | Hawkeye 把它們當成存取來訓練（mcf 有 870 萬筆），mcf 比 LRU 差 8.7% | Hawkeye 忽略 CleanEvict（a02da83） |
| gem5 x86-64 `newfstatat` 用錯 stat 結構 | SE 模式下 opendir 失敗，omnetpp、gcc 無法執行 | `install_hawkeye.py` 改用 `fstatat64Func`（a02da83） |
| gem5 快取複製軟體預取 request 時沒帶 PC | omnetpp 有 28% 的 LLC 存取沒有 PC，Hawkeye 和 SHiP 把它們全算在同一個 PC 下；Hawkeye 在 omnetpp 從 −28% 改善到 −20% | 複製 PC（8886623）；只重跑 SHiP、Hawkeye（其他策略不讀 PC） |

修正軟體預取前的 SHiP、Hawkeye 結果保留在 EC2 的 `out/*/{SHiP,Hawkeye}_v2nopfpc/`。
