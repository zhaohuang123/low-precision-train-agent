# 先验 08｜混合精度与敏感层回退

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：mixed-precision QAT、layer sensitivity analysis、MSE-based fallback、W8A8
> fallback、outlier-aware fallback、per-layer bit allocation、Fisher information sensitivity

## 1. 三条**已核对**的证据

### A. 注意力是第一个该回退的地方（arXiv:2607.24953）
- 原始 URL：<https://arxiv.org/abs/2607.24953>
- 摘要原文："… To handle the sensitivity of attention mechanisms, we adopt MXFP8 quantization
  for query and key projections, yielding a practical mixed-precision design."
- 含义：**Q/K 投影退 MXFP8，其余 FP4**。这不是调优，是让 FP4 训练能稳定的前提之一。

### B. 离群回退（arXiv:2605.20402）
- 原始 URL：<https://arxiv.org/abs/2605.20402>
- 摘要原文："… 'deadzone truncation' from zeroing small values … Outlier Fallback recovers
  deadzone entries, but also partially reduces scale bias induced error …"
- 含义：**按"离群值"回退**（把落进死区的元素单独保留/高精度处理）能救回被清零的信息，且顺带
  减轻 scale 偏差 —— 一个动作治两个症状。这正是 "outlier-aware fallback" 的实证形态。

### C. 旋转之后可能**不需要**回退（QuaRot，arXiv:2404.00456）
- 原始 URL：<https://arxiv.org/abs/2404.00456>
- 摘要原文："The result is a quantized model where all matrix multiplications are performed in
  4 bits, without any channels identified for retention in higher precision."
- 含义：先用旋转把离群值消掉，就不必再维护"保留通道"这套混合精度逻辑。**回退与旋转是两条替代
  路线，不是叠加越多越好**（与 09 一起读）。

## 2. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| mixed-precision QAT | A（Q/K 用 MXFP8）、B（离群回退） | ✅ 找到（两篇都有混合精度设计） |
| outlier-aware fallback | B 的 Outlier Fallback | ✅ 找到 |
| W8A8 fallback | —— | ⚠️ 概念同类（退到更高位宽），但"W8A8 fallback"这次**没找到出处** |
| layer sensitivity analysis | —— | ❌ 未找到可靠出处（本次检索质量差，宁可空着） |
| MSE-based fallback | —— | ❌ 未找到（B 用的是"恢复死区条目"，不是 MSE 判据） |
| per-layer bit allocation | —— | ❌ 未找到（A 是**按模块类型**给精度，不是自动分配） |
| Fisher information sensitivity | —— | ❌ 未找到（Fisher 用于量化敏感度是老思路，但本次没核到可引的原文） |

## 3. 落到本工程的动作

- 回退**不要按论文里的层名照抄**（模型结构不同）。本工程已有 `qat-qsnr-probe`，可以用它给每层
  出 QSNR，按 QSNR 排序决定回退 top-k 层到 MXFP8 —— 这是"可测的敏感度"，比"论文说 Q/K 敏感"
  更站得住。
- 回退的代价必须一起报：混合精度会让 GEMM 形状不齐、吞吐下降；如果换不来精度，就不该上。

## 4. 怎么验（证伪条件）

- 成立：按 QSNR 回退 top-k 层到 MXFP8，同预算下 loss 改善 > 噪声，且吞吐损失 < 10%。
- 不成立：全 4-bit ＋ 旋转（09）已经持平，回退层只是多花吞吐 ⇒ 记录"本任务不需要回退"。
