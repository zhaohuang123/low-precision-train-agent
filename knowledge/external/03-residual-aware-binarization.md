# 先验 03｜残差量化／误差补偿（Residual-Aware Binarization, RaBiT）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：Residual Quantization、Residual-Aware Binarization、RaBiT、Multi-term Additive
> Decomposition、Residual Refinement Quantization、R2Q、W/A residual quantization、residual
> compensation

## 1. 它到底说了什么（来源：arXiv:2602.05367，ICML 2026）

- 原始 URL：<https://arxiv.org/abs/2602.05367>
- 标题：RaBiT: Residual-Aware Binarization Training for Accurate and Efficient LLMs
- 摘要（原文摘录）：

  > "Residual binarization enables hardware-friendly, matmul-free inference by stacking binary
  > (±1) layers, but is plagued by pathological feature co-adaptation. We identify a key failure
  > mode, which we term inter-path adaptation: during quantization-aware training (QAT), parallel
  > residual binary paths learn redundant features, degrading the error-compensation structure and
  > limiting the expressive capacity of the model. While prior work relies on heuristic workarounds
  > (e.g., path freezing) … we propose RaBiT … Its core mechanism sequentially derives each binary
  > path from a single shared full-precision weight, which ensures that every path corrects the
  > error of the preceding one. This process is stabilized by a robust initialization that
  > prioritizes functional preservation over mere weight approximation."

- 关键结论：
  1. **残差量化 = 多项加性分解**：`W ≈ B1 + B2 + … + BN`（每 Ci 是 ±1 的二值矩阵）。项数越多
     表达力越强，但代价是"各路径容易学到冗余特征"。
  2. 失败模式有名字：**inter-path adaptation**（路径间耦合）——各路径不再做"补偿前一项的误差"，
     而是互相抄袭，误差补偿结构塌掉。以前的补丁（冻结路径）只是限制解空间。
  3. RaBiT 的修法是**从同一个共享全精度权重顺序导出各路径**，让第 k 条路径的职责在结构上就是
     "纠正第 k−1 条的残差"；再配一个"保功能优先于保权重"的初始化。
  4. 结果：2-bit 前沿（比肩 VQ），RTX 4090 上 4.49× 推理加速。三星开源
     <https://github.com/SamsungLabs/RaBiT>。

## 2. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| Residual-Aware Binarization / RaBiT | 论文标题 | ✅ 找到 |
| Residual Quantization、Multi-term Additive Decomposition | "stacking binary layers"、N-path 残差分解 | ✅ 概念找到（原文未用 "multi-term additive decomposition" 字样） |
| residual compensation | 摘要 "error-compensation structure" | ✅ 找到 |
| Residual Refinement Quantization / R2Q | —— | ❌ **未找到出处**（不要引用） |
| W/A residual quantization | —— | ❌ 未找到（本文只做权重侧二值叠加） |

## 3. 落到本工程的动作

- 对 W4A4 的"误差大"层，候选方案可以是**两项残差**：`W ≈ Q1(W) + Q2(W − Q1(W))`。代价必须
  一起报：权重带宽/访存 ×2、量化参数 ×2。
- 若采用多项残差，**必须防 inter-path 冗余**：要么顺序导出（每个后续项只拟合前项残差），
  要么显式加"路径正交"的正则；否则多花一倍的带宽换不到精度。

## 4. 怎么验（证伪条件）

- 成立：同预算下残差两项相对单项，validation loss 改善 > 种子噪声，且推理/训练吞吐损失在
  可接受范围（先定阈值再跑）。
- 不成立：精度改善落在噪声内（说明这一层不是误差主因），或各路径余弦相似度过高（冗余 ⇒
  inter-path adaptation 复现）。
