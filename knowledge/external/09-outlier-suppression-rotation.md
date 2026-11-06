# 先验 09｜离群值抑制（旋转、随机 Hadamard、随机舍入）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：rotation-based outlier suppression、QuaRot、Iterative Smooth、Hadamard
> transform、random Hadamard、stochastic rounding、outlier injection、SpinOut、block rotation

## 1. 它到底说了什么（来源：QuaRot，arXiv:2404.00456）

- 原始 URL：<https://arxiv.org/abs/2404.00456>｜代码 <https://github.com/spcl/QuaRot>
- 摘要（原文摘录）：

  > "We introduce QuaRot, a new Quantization scheme based on Rotations, which is able to quantize
  > LLMs end-to-end, including all weights, activations, and KV cache in 4 bits. QuaRot rotates
  > LLMs in a way that removes outliers from the hidden state without changing the output, making
  > quantization easier. This computational invariance is applied to the hidden state (residual)
  > of the LLM, as well as to the activations of the feed-forward components, aspects of the
  > attention mechanism, and to the KV cache. … Our 4-bit quantized LLaMa2-70B model has losses of
  > at most 0.47 WikiText-2 perplexity and retains 99% of the zero-shot performance. We also show
  > that QuaRot can provide lossless 6 and 8 bit LLaMa2 models without any calibration data …"

- 关键结论：
  1. **旋转是"不改输出"的等价变换**（computational invariance），把离群值摊到所有通道上再量化。
  2. 覆盖范围要**全套**：残差流、FFN 激活、注意力的若干投影、KV cache。只转一处收益有限。
  3. 旋转做干净之后，**不需要保留高精度通道**（见 08-C），量化的工程复杂度下降。
  4. 校准数据可以不要（6/8-bit 无损），4-bit 才需要。

## 2. 来源 B：ALTO 配方的三个部件（arXiv:2610.32229）

- 原始 URL：<https://arxiv.org/abs/2610.32229>
- 摘要原文："The recipe combines established techniques … (hybrid 1D/2D block quantization,
  randomized Hadamard transforms, and stochastic rounding) with a simplified weight
  de-oscillation scheme …"；并明确："We also report negative end-to-end results from …
  outlier clipping … despite each showing operator-level SNR gains."
- 含义：**RHT（随机 Hadamard）＋ SR（随机舍入）是 MXFP4 训练的实测有效部件**；而
  **outlier clipping 在端到端上没用**（尽管算子 SNR 变好）。这条与 02-B 一起构成"别拿 SNR 当
  判据"的证据链。

## 3. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| rotation-based outlier suppression、QuaRot、block rotation | 来源 A（QuaRot 的块对角 Hadamard） | ✅ 找到 |
| Hadamard transform、random Hadamard | 来源 B（RHT） | ✅ 找到 |
| stochastic rounding | 来源 B（SR）；01 的 2607.24953 也用 | ✅ 找到 |
| outlier injection、SpinOut | SpinOut: Enhanced Rotation-Based Quantization for LLM by Outlier Injection（IEEE Access 2026, DOI 10.1109/ACCESS.2026.3664084） | ✅ 出处找到；**摘要未逐字核对**，引用前回原文 |
| Iterative Smooth | —— | ❌ 未找到（SmoothQuant 系列本次未核对，别把 "Iterative Smooth" 当已发表名称） |

## 4. 落到本工程的动作

- 优先级：**先旋转（RHT）＋ 随机舍入**，再考虑回退（08）与 clipping；ALTO 的负结果说明 clipping
  是最后才试的。
- 旋转要落到框架能表达的位置：本工程要先确认 MindSpeed-LLM 里残差流/FFN 的等价变换能否挂公共
  补丁（`knowledge/frameworks/patches/`），否则"方案成立但跑不了"。

## 5. 怎么验（证伪条件）

- 成立：开 RHT+SR 相对不开，同预算 loss 改善 > 噪声，且算子级 SNR 也改善（两者同向才可信）。
- 不成立：SNR 改善而 loss 不变（复现 02-B/09-B 的负结果）⇒ 记录"本任务上 SNR 不是判据"。
