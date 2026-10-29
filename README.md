# ECE552 課程專案：重現 Hawkeye 快取替換策略（10-29 定題）

- 課程規定原文：`local/ECE552_Project.md`（不進 git）
- 截止：2026-12-03（proposal 需重交、status report、presentation、final report 4–8 頁）
- 2026-10-29：老師表示 SPU 稀疏注意力電路不算架構專案，要 microarchitecture 類題目。
  舊的 SPU proposal、PPT、方塊圖已全部刪除，ISCAS 論文本身不受影響。
- 可以只重現一篇論文或一個架構，不必創新。
- **10-29 定題：Hawkeye（Jain & Lin, ISCA 2016），在 gem5 實作。** 往年課程專案有「DRRIP and BRRIP Caching」（見課程規定原文），proposal 要交代差別；RRIP 當基準。
- 以下候選清單保留作紀錄。

## CEI 現任 PhD 的架構論文（2025–2026，cei.pratt.duke.edu/publications）

| 論文 | 第一作者 | 類型 | 模擬方式 |
|---|---|---|---|
| Ecco, ISCA 2025（LLM 資料的熵感知快取壓縮） | Feng Cheng | GPU 記憶體階層（L1–L2–HBM 之間的壓縮/解壓縮器） | 改 Accel-Sim / GPGPU-Sim 4.0；RTL 用 DC 28nm；未見程式碼釋出 |
| Prosperity, HPCA 2025（SNN product sparsity） | Chiyue Wei | 加速器 | 自寫 cycle-accurate 模擬器，GitHub dubcyfor3/Prosperity（MIT） |
| Phi, ISCA 2025（SNN 階層稀疏） | Chiyue Wei | 加速器 | 自寫模擬器 |
| Transitive Array, ISCA 2025（GEMM 結果重用） | Cong Guo | 加速器 | 自寫模擬器；未見程式碼 |
| Focus, HPCA 2026（VLM） | Chiyue Wei | 加速器 | — |
| EVA, ISCA 2026（LLM decoding 向量量化） | Bowen Duan | 加速器 | — |
| FractalCloud, HPCA 2026；FlashFPS, DAC 2026（點雲） | Yuzhe Fu | 加速器 | — |
| NP-CAM, HPCA 2026（DNA 分類，NoC 分割 CAM） | Benjamin Morris | 加速器 + NoC | — |

結論：只有 Ecco 是在改處理器（GPU）的記憶體階層，最接近 microarchitecture；其餘都是 domain-specific 加速器。

## 候選方向（討論中）

1. Ecco 照原樣縮小重現：Accel-Sim 上在 L2–HBM 路徑加壓縮（要問老師能不能不用 gem5）。
2. Ecco 的想法搬到 CPU：在 gem5 現有的壓縮快取框架（src/mem/cache/compressors，已有 BDI、FPC、C-Pack 等）
   加一個 Ecco 式壓縮器，跑 CPU 上的 LLM decode，跟內建壓縮器比；壓縮/解壓縮器另寫小 RTL 做 PPA。
3. 不用 CEI：經典 microarchitecture 論文（預取器、替換策略、分支預測），挑 gem5 沒內建的。

## 不限 CEI 的候選（10-29 查 gem5 stable 原始碼確認未內建）

- gem5 已內建替換策略：LRU/FIFO/LFU/MRU/Random/BIP/BRRIP/Dueling/SecondChance/SHiP/TreePLRU/WeightedLRU（無 Hawkeye、Mockingjay）
- gem5 已內建預取器：Stride/Tagged/AMPM/DCPT/IMP/ISB/Multi/PIF/SBOOE/SPP/SPPv2/SlimAMPM/STeMS/BOP（無 Berti、Bingo、Pythia）

1. Hawkeye 快取替換（Jain & Lin, ISCA 2016）：Belady OPT 模擬（OPTgen）+ PC 預測器；基準用 gem5 內建 LRU/BRRIP/SHiP；
   CRC2 有 ChampSim 參考碼可對照。硬體小（預測表、取樣集的 occupancy vector），好做 Verilog PPA。可延伸 Mockingjay（HPCA 2022）。
2. Berti L1D 預取器（Navarro-Torres et al., MICRO 2022）：每條指令的 local delta；基準用 gem5 內建 Stride/BOP/SPP；有 ChampSim 參考碼。
3. BLISS 記憶體排程（Subramanian et al., ICCD 2014）：在 gem5 MemCtrl 的 FR-FCFS 旁加黑名單，多核心公平性。

## 環境

- 課程 AWS instance：gem5 v23.0.0.1（X86 已編），SPEC CPU2017 與課程腳本 `spec_scripts`（10 個 speed 測項可跑）。
- 連線方式與私鑰在 `local/`（不進 git）。
- 課程的 `gem5_se.py` 是 MinorCPU＋兩層快取（L2 256KB），Hawkeye 需要 O3CPU＋三層（2MB LLC）設定。

## 學習資料

- `Learning/01_learning_order.md`：剛接手的人從這裡開始，照五個步驟學。
- `Learning/02_hawkeye_paper_vs_crc2.md`：論文和作者 CRC2 程式碼的差異，以及我們照哪個做。

## Proposal

- `Proposal/ECE552_Hawkeye_Proposal.tex`（IEEEtran，照老師 98 分範例 Cyclone proposal 的章節），正文 2 頁＋參考文獻第 3 頁。

## gem5 設定與腳本（`gem5/`）

- `gem5/configs/hk_se.py`：O3CPU＋三層快取（L1 32KB 4-way、L2 256KB 8-way、LLC 2MB 16-way，照 Hawkeye 原文 Table 2），
  `--rp` 選 LLC 替換策略（LRU、Random、SRRIP、BRRIP、DRRIP、SHiP）。
  `--fast-forward` 先用 atomic CPU 跑過初始化（快取照樣被存取），再切到 O3CPU；`--warmup`／`--measure` 指令數（暖身後清零統計）。
  DRRIP 的 set dueling 參數依 LLC 大小自動計算（每個策略 32 個 dueling set）。
- `gem5/scripts/run_spec.sh <bench> <policy> [fast_forward] [warmup] [measure]`：在 EC2 上跑一個 SPEC2017 測項，輸出到 `~/hawkeye/out/<bench>/<policy>[_$TAG]/`。
- 10-29 實測：mcf 在 O3CPU 上約每秒 25 萬條指令，6000 萬條約 5 分鐘，記憶體約 115 MB（可同時跑 7 組）。只暖身 1000 萬條時 LLC miss 率 97.6%，還在初始化階段，所以要 fast-forward。
- EC2 上的路徑：`~/hawkeye/configs`、`~/hawkeye/scripts`（從這裡 scp 上去）。

## Hawkeye 實作（`gem5/src/mem/cache/replacement_policies/hawkeye_rp.*`）

- `gem5/install_hawkeye.py <gem5 目錄>`：把 Hawkeye 複製進 gem5、註冊 `HawkeyeRP` 與 debug flag `Hawkeye`，之後 `scons build/X86/gem5.opt`。
- 設定檔 `--rp=Hawkeye` 會自動依 LLC 大小設定 set 數、OPTgen 長度（8×ways）與容量（ways − 2）。
