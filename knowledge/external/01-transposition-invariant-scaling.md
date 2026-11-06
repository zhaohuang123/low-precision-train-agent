# 先验 01｜免截断缩放与缩放规则改进（Transposition-Invariant / Truncation-Free）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：Truncation-Free Scaling、2D Square Block Quantization、Transposition-Invariant
> Block Quantization、Scale Inconsistency under Transposition、Ceil_X、ceil-based shared
> exponent、overflow-aware scaling（OAS）

## 1. 它到底说了什么（来源：arXiv:2607.24953，2026-07）

- 原始 URL：<https://arxiv.org/abs/2607.24953>
- 标题：Stable FP4 Training via Transposition-Invariant Block Quantization（v1，2026-07-27）
- 摘要（原文摘录）：

  > "We identify a fundamental source of this instability in existing microscaling approaches:
  > scale inconsistency induced by tensor transposition. In conventional 1D block quantization,
  > forward and backward passes assign different scaling factors to the same values after
  > transposition, leading to biased and unstable gradient updates. To address this issue, we
  > propose a low-precision training framework based on 2D block FP4 quantization, which enforces
  > transposition-invariant scaling and preserves consistency between forward and backward
  > computations. We further combine this with truncation-free scaling and stochastic rounding to
  > control quantization error and maintain unbiased gradients. To handle the sensitivity of
  > attention mechanisms, we adopt MXFP8 quantization for query and key projections …"

- 关键结论（中文）：
  1. **同一个数在前向与反向拿到不同 scale**，是 1D 分块量化在转置下的结构性缺陷；这不是
     "精度不够"，是"前后向不一致"，会让梯度产生系统性偏差。
  2. 修法是**按 2D 方块划分**（转置后仍是同一组元素），保证 `q(X)^T` 与 `q(X^T)` 一致。
  3. 再叠 **truncation-free scaling**（scaling 不含截断，误差可控）与 **stochastic rounding**
     （去偏）。
  4. Q/K 投影对精度敏感 ⇒ 这两处退到 MXFP8，其余 FP4：**混合精度是稳定性的组成部分**，不是
     可选的优化。
  5. 实验规模：dense ≤7B ＋ 30B MoE，≤100B tokens；PPL/下游掉点 < 1.3%。

## 2. 关键词对账（**没找到的不要引用**）

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| Transposition-Invariant Block Quantization | 论文标题/摘要 | ✅ 找到 |
| 2D Square Block Quantization | 摘要 "2D block FP4 quantization" | ✅ 找到（原文写 2D block） |
| Scale Inconsistency under Transposition | 摘要首句 | ✅ 找到 |
| Truncation-Free Scaling | 摘要 "truncation-free scaling" | ✅ 找到（未展开定义，需读正文） |
| ceil-based shared exponent | 见 02 的 arXiv:2605.20402：`δ_b = ⌈log2 s*⌉ − log2 s*`（E8M0 向上取整的 scale 误差） | ⚠️ 概念找到，但**不是本文**；两处要分开引 |
| Ceil_X | —— | ❌ **未找到出处**（不要引用） |
| overflow-aware scaling（OAS） | —— | ❌ **未找到出处**（不要引用） |

## 3. 落到本工程（lpta）的动作

- 先查框架：现在的缩放粒度是 **per-tensor / per-channel 还是 per-block**？若是 1D 分块，
  再做 `X` 与 `X^T` 的量化误差一致性小实验（构造同一矩阵，前向量化与转置量化各一次，比
  `q(X)^T` 与 `q(X^T)` 的差异）。
- 若差异显著 ⇒ 候选方案写成"2D 方块量化"，并把 Q/K 退 MXFP8 作为**稳定性前提**一起报，
  不许只报"我们也是 FP4"。

## 4. 怎么验（本工程的证伪条件）

- 成立：同一轮里 `q(X)^T` 与 `q(X^T)` 的逐元素相对误差 < 1e-3，且前 100 步梯度范数无系统性
  偏移（与 BF16 对照，斜率差在噪声内）。
- 不成立：转置一致性做到了、但 loss 轨迹与 1D 分块的差异落在种子噪声内 ⇒ 这条先验对本任务
  **不成立**（结论入库，别下一轮再试同一个）。

## 5. 未解决的问题

- "truncation-free scaling" 的具体算法（是否指 scale 取 2 的幂时的截断问题）摘要没讲清，
  要用就得读 PDF §3；本文件不替它编定义。
