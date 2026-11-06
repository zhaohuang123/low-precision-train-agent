# 先验 02｜宏块／多级缩放（Macro Block Scaling, MBS）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：Macro Block Scaling、MBS、dual-scale block quantization、E0M8 correction
> factor、microscaling FP4、multi-level scaling、block-wise scaling

## 1. 来源 A：arXiv:2605.20402（2026-05，v3 2026-06）

- 原始 URL：<https://arxiv.org/abs/2605.20402>
- 标题：Decomposing MXFP4 quantization error for LLM reinforcement learning: reducible bias,
  recoverable deadzone, and an irreducible floor
- 摘要（原文摘录）：

  > "We prove an exact three-way decomposition of quantization error … decomposes the MXFP4
  > quantization error into three additive components: 'scale bias' from power-of-two rounding,
  > 'deadzone truncation' from zeroing small values, and 'grid noise' from rounding to the
  > nearest 4-bit grid. Each component dominates a distinct RL failure mode: scale bias
  > accumulates multiplicatively through the backward pass, affecting gradient accuracy;
  > deadzone truncation degrades rollout quality; and grid noise raises the policy's entropy.
  > We combine corrections that are RL failure mode-targeted but not component-exclusive:
  > Macro-block scaling to reduce scale bias, Outlier Fallback recovers deadzone entries …,
  > and Adaptive Quantization Noise (AQN) for controlling the policy entropy."

- 关键结论：
  1. MXFP4 的误差可以**精确拆成三项**：2 的幂取整造成的 scale 偏差、小值被清零、4-bit 网格
     舍入噪声。三项各自主导一种失败模式 ⇒ **治哪一项要看失败表征，不要一把抓**。
  2. **Macro-block scaling（MBS）= 把多个小块的 scale 合并到更大一级的块上再表达**（属"多级
     缩放"），用来压低 2 的幂取整的 scale 偏差。
  3. 论文正文用 `E8M0 → E8M8` 说明"MBS 改变了 scale 精度、网格误差完全不变"——即 **scale 位宽与
     网格位宽是两件事**。这是一个可以直接照搬的判据：改了 scale 精度，就只该动 scale 那一项。

## 2. 来源 B：arXiv:2610.32229（2026-10，ALTO 配方）

- 原始 URL：<https://arxiv.org/abs/2610.32229>
- 摘要（原文摘录）：

  > "We also report negative end-to-end results from differential gradient estimation, outlier
  > clipping, and macro-block scaling, despite each showing operator-level SNR gains."

- **这条比"有效"更有用**：MBS 在**算子级 SNR** 上确实有增益，但在 20B MoE、MXFP4 的端到端训练里
  **没换来更好的收敛**。ALTO 最终靠的是 RHT ＋ stochastic rounding ＋ 去振荡（de-oscillation），
  把 FP4 相对 BF16 的收敛开销从 +20.0% 压到 +5.0%。

## 3. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| Macro Block Scaling / MBS | 2605.20402 摘要；2610.32229 摘要（负结果） | ✅ 找到（两边说法**相反**，都要记） |
| dual-scale block quantization | 等于 MBS 的"块内 scale ＋ 块级 scale" | ✅ 概念对应（原文用 MBS 一词） |
| multi-level scaling、block-wise scaling | 同上 | ✅ 概念对应 |
| microscaling FP4 | MXFP4（两篇都用） | ✅ 找到 |
| E0M8 correction factor | 见 2605.20402 的 `E8M0 → E8M8` | ⚠️ **原文是 E8M8**，不是 E0M8；术语按原文写 |

## 4. 落到本工程的动作

- 若要做 MBS：判据必须落在 **loss/精度**，不许拿 operator-level SNR 当成功证据（ALTO 明确证伪
  这条推理）。先在单层做 SNR 复现，再跑端到端；两者不一致时以端到端为准。
- 做"scale 位宽"实验时，固定网格位宽（否则两项误差混在一起，无法归因）。

## 5. 怎么验（证伪条件）

- 成立：同一预算下，MBS 相对 1D 分块的 validation loss 改善 > 种子噪声（建议 2 个种子）。
- 不成立：SNR 上升但 loss 无改善 ⇒ 记录"算子级 SNR 不作为判据"（与 ALTO 一致）。
