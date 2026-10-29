# Hawkeye 專案學習順序

這份是給剛接觸這個專案的人看的。照順序走，每一步都建立在前一步上。前三步不用碰程式。

| 步驟 | 內容 | 預估時間 |
|---|---|---|
| 1 | 快取的基本運作 | 半天 |
| 2 | 替換策略在解決什麼 | 半天 |
| 3 | 讀 Hawkeye 論文 | 1–2 天 |
| 4 | gem5 怎麼用 | 1–2 天 |
| 5 | 自己跑一次 | 半天 |

---

## 第 1 步：快取的基本運作

**讀什麼**：H&P（Computer Architecture: A Quantitative Approach, 6th ed.）附錄 B 的前半，以及 Ch.2 講快取的部分。

**要搞懂的事**：
- 一個位址怎麼切成 tag、index、offset。
- set 和 way 是什麼：同一個 index 的資料只能放進同一個 set，set 裡有幾個位置就是幾 way。
- hit 和 miss；set 滿了又 miss 時，為什麼要踢掉一行。
- 為什麼 LLC（最後一層快取）的 miss 特別貴：下一站就是 DRAM，要等上百個 cycle。

**自我檢查**：2 MB、16-way、每行 64 B 的快取有幾個 set？

<details><summary>答案</summary>

總行數 = 2 MB / 64 B = 32768 行；set 數 = 32768 / 16 = **2048 個 set**。
所以 index 要 11 bit，offset 要 6 bit。
</details>

---

## 第 2 步：替換策略在解決什麼

**核心問題**：set 滿了，要踢掉哪一行？踢錯了，等一下又要用到它，就多一次 miss。

**手算這個例子**：一個 set 只有 3 個位置，程式反覆存取 `A B C D A B C D A B C D …`

- **LRU**（踢掉最久沒用的）：每次被踢掉的，剛好就是下一個要用的那行，結果**全部 miss**。
- **Belady OPT**（踢掉未來最晚才會再用到的）：每輪可以留住一部分，**有一部分會 hit**。

自己在紙上畫出每一步 set 裡的內容，比較兩者的 hit 次數。

**這個例子就是整個專案的動機**：
- LRU 在「反覆存取比快取大的資料」這種模式下很糟（thrashing）。
- OPT 是理論上最好的策略，但它要知道未來，硬體做不出來。
- Hawkeye 的想法：雖然看不到未來，但可以回頭算「過去如果用 OPT 會怎麼做」，再拿這個去學習。

**延伸（可選）**：讀 RRIP 論文（Jaleel et al., ISCA 2010）的前三節。Hawkeye 的替換規則建立在 RRIP 的 RRPV 計數器上，先懂 RRIP 會比較好讀 Hawkeye。

---

## 第 3 步：讀 Hawkeye 論文

**論文**：A. Jain and C. Lin, "Back to the Future: Leveraging Belady's Algorithm for Improved Cache Replacement," ISCA 2016。
PDF：https://www.cs.utexas.edu/~lin/papers/isca16.pdf

不用從頭讀到尾，照這個順序：

1. **Abstract、Introduction**：在解決什麼問題。
2. **Section 3.1 OPTgen**，配合 Fig. 5 和 Fig. 6：
   - 這是整篇最核心、也最難的部分。
   - **拿紙筆把 Fig. 6 的例子自己算一遍**，算到每一步 occupancy vector 的值都對得上為止。
   - 關鍵概念：usage interval（一行從上次被用到下次被用之間的時間），以及 occupancy vector（每個時間點 OPT 在這個 set 裡放了幾行）。
3. **Section 3.2**：為什麼只在 64 個取樣 set 上跑 OPTgen，以及 Sampled Cache 在存什麼。
4. **Section 3.3 Predictor**：怎麼用 load 指令的位址（PC）學「這條指令帶進來的資料值不值得留」。
5. **Section 3.4 和 Table 1**：怎麼用預測結果決定每行的 RRIP 值，以及踢哪一行。
6. 多核心和評估的部分先跳過，之後做實驗時再回來看。

**讀完應該能回答**：
- OPTgen 怎麼判斷某次存取在 OPT 下會不會 hit？
- 預測器的計數器什麼時候加、什麼時候減？
- cache-friendly 和 cache-averse 的行，RRIP 值分別設成多少？
- 沒有 RRIP = 7 的行時，Hawkeye 踢哪一行？為什麼還要反向訓練？

---

## 第 4 步：gem5 怎麼用

1. **官方教學 Learning gem5 的 Part I**（https://www.gem5.org/documentation/learning_gem5/introduction/）：
   怎麼用 Python 腳本組出一台模擬機器（CPU、快取、記憶體怎麼接起來）。
2. **讀我們的設定檔** [`gem5/configs/hk_se.py`](../gem5/configs/hk_se.py)：
   讀完 Part I 應該看得懂每一段在接什麼。LLC 的替換策略由 `--rp` 決定。
3. **讀 gem5 原始碼** `src/mem/cache/replacement_policies/` 裡的三個檔案：
   - `lru_rp.cc`：最簡單的範例，先看懂介面（`touch`、`reset`、`getVictim`、`invalidate`）。
   - `brrip_rp.cc`：RRIP 的實作。
   - `ship_rp.cc`：有用到 PC，**Hawkeye 寫出來會最像它**。

---

## 第 5 步：自己跑一次

在 EC2 上（連線方式問 Vito）：

```sh
cd ~/hawkeye
# hello world，換不同的 --rp 看看
~/gem5/build/X86/gem5.opt -d /tmp/try configs/hk_se.py \
    --cmd=$HOME/gem5/tests/test-progs/hello/bin/x86/linux/hello --rp=LRU

# SPEC mcf：暖身 1000 萬條指令，量 5000 萬條
bash scripts/run_spec.sh 605.mcf_s DRRIP 10000000 50000000
```

打開輸出資料夾裡的 `stats.txt`，找這幾個數字：

| 統計名稱 | 意思 |
|---|---|
| `simInsts` | 跑了幾條指令 |
| `system.cpu.ipc` | 每個 cycle 完成幾條指令，越高越快 |
| `system.llc.overallMisses::total` | LLC miss 次數 |
| `system.llc.overallMissRate::total` | LLC miss 率 |

**LLC MPKI** = miss 次數 ÷ 指令數 × 1000，就是 proposal 裡要比的主要指標。

---

## 學完之後

- 對照 proposal（[`Proposal/ECE552_Hawkeye_Proposal.tex`](../Proposal/ECE552_Hawkeye_Proposal.tex)）和實作計畫（[`hawkeye_plan.md`](../hawkeye_plan.md)），看自己負責哪一塊。
- 分工：Vito 負責 Hawkeye 的設計與 gem5 實作（OPTgen、Sampled Cache、預測器、替換策略）、Python OPT 參考模型、驗證計畫，以及結果分析與敏感度分析；Endong 寫微基準、跑單元測試並對照 log；Xiaotian 跑基準和 SPEC 模擬、整理統計與畫圖。
