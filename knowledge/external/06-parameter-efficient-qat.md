# 先验 06｜参数高效 QAT（PE-QAT / L4Q：QAT 与 LoRA 合流）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：PE-QAT、L4Q、LoRA + fake quantization、parameter-efficient QAT、learned
> smoothing and clipping

## 1. 它到底说了什么（来源：L4Q，ACL 2025；arXiv:2402.04902 v6）

- 原始 URL：<https://arxiv.org/abs/2402.04902>｜ACL：<https://aclanthology.org/2025.acl-long.99/>
- 摘要（原文摘录）：

  > "Previous quantization-aware PEFT methods typically apply post-training quantization (PTQ) to
  > pre-trained LLMs, followed by PEFT to recover accuracy loss. Meanwhile, this approach has
  > limitations in recovering the accuracy loss. In this paper, we propose L4Q, a method that
  > integrates Quantization-Aware Training (QAT) with LoRA. By employing a memory-optimized layer
  > design, L4Q significantly reduces QAT's memory overhead, making its training cost comparable to
  > LoRA, while preserving the advantage of QAT in producing fully quantized LLMs with high
  > accuracy. Our experiments demonstrate that this combined approach to quantization and
  > fine-tuning achieves superior accuracy compared to decoupled fine-tuning schemes, particularly
  > in 4-bit and 3-bit quantization …"

- 关键结论：
  1. **"先 PTQ 再 PEFT" 与 "QAT ＋ LoRA 一起做" 不是同一件事**：前者在 4/3-bit 上明显吃亏，
     L4Q 的对照实验就是这么比的。
  2. 省显存靠**层设计**（不是少训参数）：把 QAT 需要的全精度副本/梯度压下去，使训练代价接近
     LoRA。
  3. 产出是**全量化模型**（不像 LoRA 那样推理还要合并回全精度）。

## 2. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| L4Q、LoRA + fake quantization、parameter-efficient QAT | 标题/摘要 | ✅ 找到 |
| PE-QAT | 通用叫法，L4Q 属这一类 | ⚠️ 本次未检索到代号就叫 "PE-QAT" 的原始论文（作为类别名用可以，别当引文） |
| learned smoothing and clipping | —— | ⚠️ LSQ 系列用可学习 step size（≈ 可学习 clipping），但本次**未逐字核对**；引用前回原文 |

## 3. 落到本工程的动作

- 显存不够时的**第一顺位**候选：只训 LoRA ＋ 量化参数（等价于 L4Q 思路），而不是缩小模型。
- 判据要写清"省的是**训练**显存还是**推理**显存"——L4Q 的卖点是两者都省，但方式不同。

## 4. 怎么验（证伪条件）

- 成立：同卡同预算下，L4Q 式训练能跑到目标步数（不 OOM），且精度不低于全参 QAT 的 −0.5 分。
- 不成立：不 OOM 但精度掉出噪声范围（说明只训 LoRA 的表达力不够），或省下的显存没换来更大
  batch（收益不落地）。
