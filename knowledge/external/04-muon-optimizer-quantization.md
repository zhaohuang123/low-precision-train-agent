# 先验 04｜优化器与低精度训练（MuonQ：方向保真）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：MuonQ、Muon-Aware QAT、Directional Fidelity Optimization、Gradient
> Orthogonalization、μ-law Companding Quantization、optimizer state quantization、
> Muon low-bit training

## 1. 它到底说了什么（来源：arXiv:2605.11396，COLM 2026）

- 原始 URL：<https://arxiv.org/abs/2605.11396>｜项目页 <https://yupengsu.github.io/MuonQ/>
  ｜代码 <https://github.com/YupengSu/MuonQ>
- 摘要（原文摘录）：

  > "The Muon optimizer … achieving remarkable computational savings through gradient
  > orthogonalization. However, Muon's optimizer state is more sensitive to quantization errors:
  > because the orthogonalization discards the magnitudes of singular values and retains only
  > directional information, even small quantization errors in singular vector directions are
  > amplified in the update. … First, we apply a pre-quantization normalization so that each step
  > introduces quantization errors of the same magnitude … Second, we introduce a structural
  > decomposition that separately quantizes the dominant singular components via power iteration,
  > ensuring that quantization errors perturb only singular value magnitudes rather than rotating
  > singular vector directions. Third, we adopt μ-law companding quantization to allocate higher
  > resolution to densely packed momentum values … enable stable 4-bit quantization of Muon's
  > optimizer states."

- 关键结论：
  1. **度量要跟着优化器走**：Muon 只用动量的方向（`polar(M)` 里幅度被丢掉），所以量化误差
     里"沿 M 方向"的部分无害，只有**正交分量**有害。判据应是**方向保真度（cosine similarity,
     CS）**，不是相对误差（RE）。项目页给的对照：某层动量 4-bit 量化 CS=0.994 但 RE=0.110；
     经过 polar 步后 CS 掉到 0.674。
  2. 三处修补对应三个误差入口：**归一化**（每步误差同量级，不让误差攒出一个方向）→
     **分解**（top-k 奇异方向单独量化，误差只动幅度不动方向）→ **μ-law 压扩**（把 15 个格点
     花在稠密的近零区，而不是被离群点拉走；μ=255）。
  3. 结果（项目页/论文）：LLaMA-1.1B 优化器状态 4.50→0.62 GB（7.28×），PPL 23.18（朴素
     4-bit）→ 12.67（MuonQ4），8-bit 12.42、全精度 11.47；闭合约 90% 的差距。代价：步时
     +10.7%（因为多了 power iteration）。
  4. 与 GRASP（部分状态留 8-bit）比：MuonQ 更省内存（7.28× vs 6.02×），PPL 高 0.34。

## 2. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| MuonQ、Muon low-bit training | 标题/摘要 | ✅ 找到 |
| Directional Fidelity Optimization | 摘要首句 | ✅ 找到 |
| Gradient Orthogonalization | 摘要（Muon 的 polar 步） | ✅ 找到 |
| μ-law Companding Quantization | 摘要第三点（μ-law companding） | ✅ 找到 |
| optimizer state quantization | 全文主题 | ✅ 找到 |
| Muon-Aware QAT | —— | ⚠️ **本文不是 QAT**（量化的是优化器状态，权重仍全精度）；把"按优化器几何设计量化"这条当先验可以，但别写成"Muon-aware QAT 已有论文" |

## 3. 落到本工程的动作

- 先确认框架用的是 AdamW 还是 Muon。**若是 AdamW**：MuonQ 的三条不能照搬（Adam 的误差度量是
  逐元素相对误差），但"归一化后再量化"与"μ-law 分配格点"两条可以移植到优化器状态/梯度压缩。
- 若是 Muon：先量 CS 再谈精度——用 RE 评价 Muon 量化会得出错误结论（这是本文最硬的先验）。
- 优化器状态量化的收益要按"省下的显存是否换来更大 batch/更长序列"折算，不能只报显存倍数。

## 4. 怎么验（证伪条件）

- 成立：4-bit 优化器状态相对 8-bit，同预算下 loss 差 < 噪声，且步时开销 < 12%。
- 不成立：CS 高但 loss 变差 ⇒ "方向保真度"这个代理指标在本任务上不成立（记录，别再用它当判据）。
