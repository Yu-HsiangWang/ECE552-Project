# 期末前補齊的驗證與分析（2026-11-17）

- **目的**：完成 status report 的 next steps（i）–（iv），並補跑 20 輪微基準：
  - （i）Hawkeye 的預測器計數、RRPV、victim 逐筆比對（承諾 11/22 前）。
  - （ii）Mockingjay 在相同存取串流上與參考模型比對。
  - （iii）估計 Mockingjay 不能 bypass 在 SPEC 上的代價。
  - （iv）找出 Hawkeye 在 omnetpp 上資料行的損失原因。
- **腳本**：`gem5/scripts/run_final.sh`，在新開的 EC2 上一次跑完（約 3 小時）。完成的工作會跳過，所以可以重跑。
  - 6 輪微基準加 debug trace：Hawkeye、HawkeyeI、Mockingjay（MockingjayI 不加 trace）。
  - SPEC 從頭跑 3000 萬條指令（不 fast-forward）加 trace：gcc、omnetpp。
  - SPEC 照正式設定（fast-forward 10 億、暖身 5000 萬、量測 2 億），從 fast-forward 結束開始記 LLC trace：
    - Mockingjay：2 MB 六個測項，mcf 的 1 MB 與 4 MB，xalancbmk 的 4 MB。
    - Hawkeye：omnetpp 2 MB。
  - 20 輪微基準，九種策略。
- **分析工具**：
  - `tools/run_checks.sh`：跑所有逐筆比對。
  - `tools/spec_trace.py`：SPEC trace 的離線分析。
  - `tools/collect_micro.py`：整理微基準。
  - 分析的原始輸出放在 `results/07_logs/`。trace 檔太大（每個 4 MB 到 341 MB），不進 git。
- **gem5 的改動只有 log**：
  - Hawkeye 多記 set／way、計數器值、寫回、CleanEvict、invalidate 與 victim。
  - Mockingjay 多記 CleanEvict。
  - `hk_se.py` 新增 `--trace-after-ff`，fast-forward 結束才開 debug flag。
  - 用新 binary 重跑的 Hawkeye 微基準，miss 數與 IPC 和 10-30 完全相同（fit 17,343、thrash 165,951、mix 796,465 次 miss）。新跑的 Mockingjay SPEC run 也和 Endong 的結果逐格相同（第 2 節）。

## 結論摘要

1. **兩個策略的 gem5 實作都和參考模型逐筆一致**：
   - Hawkeye 比對了五串存取的 OPTgen 標籤、計數器、預測、RRPV 與 victim，0 不一致，而且故意改錯的模型會被抓出來。
   - Mockingjay 在 SPEC 上也 0 不一致。
2. **20 輪微基準**：
   - thrash 上 BRRIP（40.6%）與 Hawkeye（41.0%）最好，Mockingjay 是 44.5%。
   - mix 上 Hawkeye 最好（88.7%），Mockingjay 是 91.2%。
   - Mockingjay 學得比較慢，跑越多輪越接近 Hawkeye。
3. **不能 bypass 的代價不大**：
   - 只有 mcf 4 MB 明顯：真正 bypass 的話，miss 再少 4.7%，相對 LRU 的 miss 減少從 19.2% 變成約 23.0%。
   - 其他測項在 ±2% 以內，策略間的排名不變。
4. **xalancbmk 4 MB 的損失來自 Mockingjay 的預測範圍**：
   - Mockingjay 比 LRU 多出的 miss 中，87% 的行距離上次使用已超過 128 次同 set 存取。這超出 Mockingjay 能預測的範圍（8 × 16 路）。
   - 超出範圍後，這些行的 ETR 都停在 −15，Mockingjay 分不出哪一行比較久沒用。LRU 依時間先後淘汰，而 4 MB 幾乎放得下整個工作集，所以 LRU 較好。
5. **omnetpp 上 LRU 已經接近 OPT，所以所有策略都只能輸**：
   - 量測區的 miss 幾乎都是第一次碰到的行。
   - Hawkeye 多出的資料 miss 有 86% 來自被誤判為 averse、OPT 會保留的行。這些 miss 中有 55% 的 PC 從沒存取過取樣 set，計數器無法被訓練。
   - Mockingjay 多出的 miss 有 90% 來自被預測「不會再用」（ETR 15）的行。這些行大多在 16 次同 set 存取內就被再用。

## 1. Hawkeye 逐筆比對（next step i）

`tools/hawkeye_ref.py replay` 只從 gem5 log 取事件順序：demand 存取、L2 寫回、CleanEvict、invalidate，以及 gem5 選的 way。
其餘都由 Python 模型自己算，再逐筆跟 gem5 比對：

- 每個取樣 set 的 OPTgen 標籤。
- 預測器計數器的值，以及 friendly／averse 預測。
- 存取後該行的 RRPV，包含插入 friendly 行時其他行的老化。
- 每次的 victim：
  - 先選 invalid 的行，再選第一個 RRPV = 7 的行。
  - 都沒有就選 RRPV 最大的最後一路，並在取樣 set 反向訓練。
- 寫回命中與寫回插入（RRPV 7、PC 0）。如果 gem5 命中一個模型裡沒有的行，也會被抓出來。

| 存取串流 | OPTgen 標籤 | demand 存取 | victim（averse / invalid / 最舊的 friendly） | 寫回插入 | 不一致 |
|---|---|---|---|---|---|
| 微基準 fit，6 輪 | 3,074 | 115,691 | 0 / 17,343 / 0 | 0 | **0** |
| 微基準 thrash，6 輪 | 9,218 | 345,069 | 245,677 / 32,768 / 9,195 | 121,689 | **0** |
| 微基準 mix，6 輪 | 1,853 | 902,156 | 1,501,501 / 32,768 / 12,246 | 750,050 | **0** |
| gcc，從頭 3000 萬條 | 1,333 | 99,081 | 9,447 / 32,768 / 23,844 | 2,586 | **0** |
| omnetpp，從頭 3000 萬條 | 430 | 40,268 | 0 / 25,678 / 59 | 0 | **0** |

- HawkeyeI（指令行一律 friendly）在 fit、thrash、mix、gcc 上也全部 0 不一致（`replay --inst-friendly`）。
- **這個比對抓得到錯誤**：在 thrash 上故意改模型兩處，都會被抓出來。
  - friendly 行同分時改選第一路：101 個 victim 不一致。
  - 拿掉反向訓練：32,760 個計數器不一致、34,717 個 RRPV 不一致。
- omnetpp 從頭跑的 3000 萬條還在初始化，LLC 沒有滿，只有 59 次真正從有效的行中選 victim，所以這一筆主要驗證的是預測與 RRPV。victim 選擇的驗證主要靠 thrash、mix、gcc。

## 2. Mockingjay 的比對與重現（next step ii）

- **與參考模型逐筆比對**：Endong 已在三個微基準上做到 0 不一致。這次再加兩個 SPEC 測項，從頭跑 3000 萬條：
  - gcc：比對 62,707 個 victim，0 不一致。
  - omnetpp：比對 25,737 個 victim，0 不一致。
- **模型自己選 victim 也完全一致**：上面的 `check` 照 gem5 選的 way 更新模型。另外讓模型只吃同一串事件、自己決定 victim，結果在 gcc、omnetpp 上每一次存取的命中與否都和 gem5 相同（miss 數 62,699、25,737）。
- **Endong 的數字可以在另一台 EC2 重現**：
  - 微基準：6 輪與 20 輪的 LRU、Mockingjay、MockingjayI，miss 數與 IPC 都和 Endong 的相同（例如 6 輪 thrash 201,159、mix 870,759 次 miss）。
  - SPEC（本次開 trace 的 run）：mcf 2 MB 與 4 MB、omnetpp、xalancbmk、xz、deepsjeng 的 miss 數和 IPC 都和 Endong 的 CSV 逐格相同，表示開 trace 不會改變模擬結果。

## 3. 20 輪微基準

所有策略都跑了 6 輪與 20 輪，數字在 `results/07_micro.csv`。fit 在所有策略下都相同（6 輪 15.0%、20 輪 5.0%，只有強制 miss）。

LLC miss 率（%）與 IPC：

| 策略 | thrash 6 輪 | thrash 20 輪 | mix 6 輪 | mix 20 輪 |
|---|---|---|---|---|
| LRU | 100 / 0.822 | 100 / 0.541 | 100 / 1.135 | 100 / 1.129 |
| SRRIP | 100 / 0.816 | 100 / 0.538 | 100 / 1.135 | 100 / 1.129 |
| BRRIP | **46.8 / 1.116** | **40.6** / 0.912 | 96.4 / 1.182 | 95.4 / 1.178 |
| DRRIP | 61.7 / 1.039 | 56.1 / 0.811 | 99.1 / 1.144 | 98.8 / 1.140 |
| SHiP | 90.0 / 0.899 | 80.0 / 0.654 | 100 / 1.136 | 100 / 1.130 |
| Hawkeye | 48.1 / 1.104 | 41.0 / **0.914** | **88.3 / 1.211** | **88.7 / 1.204** |
| HawkeyeI | 48.1 / 1.104 | 41.0 / 0.914 | 88.3 / 1.211 | 88.7 / 1.204 |
| Mockingjay | 58.3 / 1.047 | 44.5 / 0.885 | 96.5 / 1.180 | 91.2 / 1.196 |
| MockingjayI | 58.3 / 1.047 | 44.5 / 0.885 | 96.5 / 1.180 | 91.2 / 1.196 |
| OPT（模型，不含寫回） | 42.9 | 36.5 | 87.3 | 88.4 |

- **checksum 全部相同**：6 輪 fit 9682944、thrash 29048832、mix 47431680；20 輪 fit 34570240、thrash 103710720、mix 160399360。
- **Hawkeye 在 mix 上最好**：
  - 20 輪 88.7%，只比 OPT 高 0.3 點。
  - Hawkeye 一開始就分得出重用陣列和只用一次的串流。Mockingjay 也分得出，但要跑較多輪才學會。
- **thrash 上 BRRIP 和 Hawkeye 差不多**：
  - 20 輪 40.6% 對 41.0%，IPC 0.912 對 0.914。
  - 循環存取正好是 BRRIP 的設計目標。
- **Mockingjay 學得比較慢，但會追上來**：
  - 和 Hawkeye 的差距，thrash 從 10.2 點縮到 3.4 點，mix 從 8.2 點縮到 2.5 點。
- **I 版本與原版相同**：微基準幾乎沒有指令行進到 LLC，所以 HawkeyeI＝Hawkeye、MockingjayI＝Mockingjay。
- **thrash 20 輪時 LRU 的 IPC（0.541）比 6 輪（0.822）低**：
  - 輪數越多，全部 miss 的掃描占總時間的比例越高，初始化所占的比例越低。
  - 各策略之間的比較不受影響。

## 4. Mockingjay 不能 bypass 的代價（next step iii）

**方法**：

- 把 gem5 Mockingjay run 的 LLC 事件（demand、L2 寫回、CleanEvict）依序重播給參考模型，分別用「真正 bypass」（論文的設計）和「不 bypass」（我們的 gem5 版）兩種模式，只數量測區的 demand miss。
- 兩種模式都從 fast-forward 結束時的冷快取開始，所以彼此可以直接比較（第 7 節說明它和 gem5 的差距）。
- 估計 gem5 真正 bypass 時的 miss：把 gem5 的 Mockingjay miss 數乘上模型的「bypass ／ 不 bypass」比例。
- LLC 的 demand 串流幾乎不受策略影響（存取數相差 < 0.3%），所以可以用同一串存取比較不同策略。

| 測項 | LLC | bypass 版的 miss 中被 bypass 的比例 | 模型：不 bypass | 模型：真正 bypass | bypass 少掉的 miss | gem5 Mockingjay 相對 LRU | 估計 bypass 版相對 LRU |
|---|---|---|---|---|---|---|---|
| mcf | 1 MB | 68% | 5,886,047 | 5,813,456 | 1.23% | +8.3% | +9.4% |
| mcf | 2 MB | 82% | 4,592,064 | 4,550,645 | 0.90% | +11.6% | +12.4% |
| mcf | 4 MB | 99% | 3,603,143 | 3,435,354 | **4.66%** | +19.2% | **+23.0%** |
| omnetpp | 2 MB | 3% | 142,233 | 143,732 | −1.05% | −9.2% | −10.3% |
| xalancbmk | 2 MB | 39% | 73,619 | 72,188 | 1.94% | +28.7% | +30.1% |
| xalancbmk | 4 MB | 9% | 33,521 | 33,376 | 0.43% | −30.0% | 無法估計（見第 5 節） |
| gcc | 2 MB | 13% | 110,752 | 110,796 | −0.04% | −1.7% | −1.8% |
| xz | 2 MB | 1% | 70,075 | 70,067 | 0.01% | +2.4% | +2.4% |
| deepsjeng | 2 MB | 0% | 52,186 | 52,185 | 0.00% | −0.7% | −0.7% |

（「相對 LRU」是 miss 減少的比例，正值代表比 LRU 少。）

- **代價只有在 mcf 4 MB 明顯**。真正 bypass 能再少 4.7% 的 miss，相對 LRU 的 miss 減少從 19.2% 變成約 23.0%。其他測項都在 ±2% 以內。
- **為什麼 mcf 有 68–99% 的填入會被 bypass，代價卻這麼小**：
  - 不 bypass 時，這些行以最大的 |ETR| 插入，成為下一個 victim。
  - 下一個要被 bypass 的行進來時，淘汰的通常就是它。推測它們大多輪流占用同一路，很少擠掉有用的行，代價大約像少了一路。
  - mcf 4 MB 的 bypass 比例最高（99%），所以受影響最大。
- **omnetpp 真正 bypass 反而多 1%**：被預測不會再用、但其實會再用的行，bypass 後連一次命中的機會都沒有。
- **對期末報告的意義**：
  - gem5 版最多低估 Mockingjay 約 4 個百分點的 miss 減少（mcf 4 MB）。
  - 排名不變：mcf 上 Mockingjay 本來就最好；xalancbmk 2 MB 估計 +30.1%，仍不如 BRRIP 的 +37.4%。
  - 06 推測「代價可能比微基準估的大」。實際上除了 mcf 4 MB（3.8 點），其餘都在 1.4 點以內，和微基準估的 1.2 點相近。

## 5. xalancbmk 4 MB 為什麼輸 LRU

gem5 的 Mockingjay 有 39,848 次 miss，LRU 只有 30,663 次（多 30%）。離線模型重現不出這個差距：

- trace 裡只出現 68,180 個不同的行，和 4 MB LLC 的 65,536 行差不多。
- 冷啟動的模型到量測結束時還有約三分之一的 set 沒填滿。量測區的 33,521 次 miss 中有 33,037 次是第一次碰到的行，所以模型的 Mockingjay、LRU、OPT 幾乎一樣。

所以這裡改用 gem5 自己記下的 victim 分析：對每一次「gem5 Mockingjay miss、LRU 命中」的存取，查 gem5 當初淘汰這一行時的 ETR。

| | 4 MB | 2 MB（對照） |
|---|---|---|
| Mockingjay miss、LRU 命中的次數 | 6,833 | 10,964 |
| 淘汰時已過期（ETR < 0） | 82.7%（幾乎都是 −15） | 37.2% |
| 淘汰時預測不會再用（ETR 15） | 17.0% | 36.1% |
| 距上次使用 ≥ 128 次同 set 存取 | **87.1%** | 42.6% |

- **原因是這些行的重用距離超出 Mockingjay 能預測的範圍**：
  - Mockingjay 只追蹤 8 × 16 = 128 次同 set 存取以內的重用距離（INF_RD 127），ETR 也只到 ±15（每格 8 次存取）。
  - 4 MB 幾乎放得下整個工作集，所以 LRU 連間隔很長的重用都留得住。Mockingjay 多出的 miss 正是這些長間隔的重用，87% 超出了 128 次同 set 存取。
  - 2 MB 時 LRU 自己也留不住這麼長的重用，所以它們不算 Mockingjay 的損失。2 MB 時 Mockingjay 多出的 miss 只有 43% 超出 128。
  - （11-18 更正：先前寫「4 MB 時每個 set 的存取較少，所以重用距離變遠」，方向寫反了。每個 set 的存取變少，同樣的重用在 set 存取次數上其實變近。）
  - 超出之後，這些行的 ETR 都停在 −15，和真正不會再用的行分不出來。
  - |ETR| 相同時，Mockingjay 依 way 的位置挑 victim，不是挑最久沒用的。
- **LRU 為什麼好**：工作集只比容量多一點，LRU 依時間先後淘汰，幾乎所有會再用的行都留得住。
- 這驗證了 06 的推測（快取夠大時，很多行超過預測時間後仍會被用到），並指出具體的界線：重用距離超過 8 × ways 次 set 存取。
- **影響很小**：MPKI 從 0.15 升到 0.20，IPC 少 0.5%。

## 6. omnetpp 的損失（next step iv）

### 先看上限：LRU 已經接近 OPT

- 在 Mockingjay run 的存取串流上，從同樣的冷快取開始，模型的 LRU 有 137,441 次 miss，OPT 有 136,233 次，只差 0.9%。gem5 自己跑 LRU 是 137,403 次。
- 量測區的 demand 存取中，有 136,232 次是 fast-forward 之後第一次碰到的行。也就是說，omnetpp 這一段的 miss 幾乎都是新的行，替換策略幾乎沒有改善空間，任何策略都只能輸。
- 這解釋了為什麼 06 裡所有策略（包括 SHiP）在 omnetpp 都輸 LRU。
- **其他測項的改善空間**（同一串存取上 OPT 相對 LRU 的 miss 減少）：
  - 有空間：mcf 27–29%，xalancbmk 2 MB 55%。
  - 幾乎沒有：gcc 2.8%、xz 4.8%、deepsjeng 0.2%。
- **量測區看起來還在建網路**：LLC 存取最多的是 `memcpy`，其次是 `malloc`、NED 樹的走訪（`NEDElement::getFirstChildWithTag`）和 `PatternMatcher`。omnetpp 跳過 10 億條指令後，看起來還沒進入事件模擬的主迴圈。期末報告要寫明這一點。

### Hawkeye

gem5 的 Hawkeye 有 165,440 次 miss，比 LRU 多 20.4%。用 trace 逐筆找出「Hawkeye miss、LRU 命中」的存取：

| | 資料 | 指令 |
|---|---|---|
| Hawkeye miss、LRU 命中 | 17,899 | 10,525 |
| （反過來：LRU miss、Hawkeye 命中） | 316 | 123 |
| 上次存取時預測 averse，但 OPT 會保留 | 15,374（85.9%） | 10,521（100%） |
| 　其中 PC 從沒存取過取樣 set | 8,405 | 9,989 |
| 由寫回插入（RRPV 7），之後沒被用過就被淘汰 | 2,505（14.0%） | 3 |
| 距上次使用 ≤ 16 次同 set 存取 | 85.8% | 92.8% |

- **主要原因：有些 PC 永遠訓練不到**：
  - Hawkeye 只在 64 個取樣 set（占 2048 個 set 的 3%）上訓練。只碰少數幾行的 PC，可能完全不落在取樣 set 上，它的計數器就不會變。
  - 例如 `PatternMatcher::matches` 在 trace 中只碰 24 行，每行約 130 次，沒有一行在取樣 set 上。
    - 它的計數器在整個 trace 裡一直是 3（門檻 16），所以每次都被判為 averse。
    - OPT 會保留它 99% 的存取。
  - `strcmp`、`__dynamic_cast`、`cNEDNetworkBuilder::doAddConnection`、`NEDElement::getFirstChild` 情況相同：計數器停在 11–15，每次都判 averse，OPT 都保留 98–99%。
  - 這些計數器的值，可能來自共用同一個計數器的其他 PC（量測區有 3,905 個 PC，只用到 1,759 個計數器），或來自更早的程式階段。
  - 這類 PC 占資料損失的 55%、指令損失的 95%。
- **其餘的資料損失**：主要來自 `memcpy`、`malloc` 這類很多地方共用的程式。
  - 同一個 PC 的行，有的會再用、有的不會。OPT 保留 35–86%，Hawkeye 判 friendly 45–98%，常在該保留時判成 averse。
- **另外 14% 是寫回插入的行**：
  - LLC 淘汰了一個 L2 還持有的髒行，L2 之後寫回時，Hawkeye 以 RRPV 7 插入，很快又被淘汰。
  - LRU 把寫回插入放在最近使用的位置，所以留得住。
- **HawkeyeI 修好了指令的部分**：2 MB 指令 miss 從 11,113 降到 577，LRU 是 662。
  - 剩下的資料損失（152,788 對 LRU 136,741）就是上面兩個原因：訓練不到的 PC，以及寫回插入。

### Mockingjay

| | 2 MB |
|---|---|
| Mockingjay miss、LRU 命中 | 12,770 |
| 淘汰時預測不會再用（ETR 15） | 90.4% |
| 由寫回插入（ETR −15），之後沒被用過就被淘汰 | 7.7% |
| 距上次使用 ≤ 16 次同 set 存取（不含寫回插入） | 82.4% |

- 和 Hawkeye 的情況類似：RDP 對這些行的簽名預測「不會再用」，但它們大多在 16 次同 set 存取內就被再用。
- Mockingjay 也只在取樣 set 上訓練。推測原因和 Hawkeye 相同：有些簽名訓練不到，或同一個簽名混合了不同的重用行為。

## 7. 離線重播的限制

- **trace 從 fast-forward 結束才開始**：模型的快取和預測器是空的，gem5 的已經用前 10 億條指令訓練過。
- **從頭開始時兩者完全一致**：
  - gcc、omnetpp 從頭跑 3000 萬條時，模型每一次存取都和 gem5 相同。
  - 所以 fast-forward run 上的差距只來自起始狀態，不是模型或串流的問題。
- **fast-forward run 上，模型不 bypass 的 miss 和 gem5 的差距**：
  - mcf 三種大小、xalancbmk 2 MB、deepsjeng 在 0.3% 以內。
  - gcc −1.3%、xz +2.8%、omnetpp −5.2%。
  - xalancbmk 4 MB −15.9%（快取沒填滿，見第 5 節）。
  - omnetpp 的差距在 2 億條指令中一直存在，沒有縮小。推測是因為 gem5 的 RDP 在前 10 億條指令學到的值和模型從頭學的不同，而只在取樣 set 上訓練的簽名，很久都不會被更新。
- **模型的 LRU 和 gem5 的 LRU 很接近**：
  - 把 Mockingjay run 的串流餵給模型的 LRU，和 gem5 自己跑 LRU 的 miss 相差 −3.4% 到 +0.3%（不含 xalancbmk 4 MB）。
  - 這表示換策略後 LLC 看到的串流確實差不多。
- **所以第 4 節只在模型內比較**（兩種模式起點相同），再按比例換算回 gem5。第 5、6 節的原因分析則直接用 gem5 自己記下的預測與 victim。
