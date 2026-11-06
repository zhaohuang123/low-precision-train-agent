# 先验 05｜QAT 训练调度（两段式：Block-AP → E2E-QP；离群通道分裂）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：delayed fake quantization、fake_quant_after_n_steps、progressive QAT、
> Bit-by-Bit、block-wise precision reduction、outlier channel splitting、compute-optimal QAT、
> cooldown-QAT fusion、QAT budget allocation

## 1. 来源 A：EfficientQAT（ACL 2025，2025.acl-long.498）

- 原始 URL：<https://aclanthology.org/2025.acl-long.498/>
- 摘要（原文摘录）：

  > "… we propose Efficient Quantization-Aware Training (EfficientQAT), a more feasible QAT
  > algorithm. EfficientQAT involves two consecutive phases: Block-wise training of all
  > parameters (Block-AP) and end-to-end training of quantization parameters (E2E-QP). To the
  > best of our knowledge, Block-AP is the first method to enable direct training of all
  > parameters in a block-wise manner, reducing accuracy loss in low-bit scenarios by enhancing
  > the solution space during optimization. E2E-QP then trains only the quantization parameters
  > (step sizes) end-to-end, further improving the performance of quantized models … For
  > instance, EfficientQAT obtains a 2-bit Llama-2-70B model on a single A100-80GB GPU in 41
  > hours, with less than 3 points accuracy degradation …"

- 关键结论：
  1. **两段式预算是关键设计**：第一段 block-wise 训**全部参数**（解空间大、代价可控），第二段
     端到端只训**量化参数（step size）**（把子模块间相互作用补上）。
  2. 给出了可对照的预算锚：70B / 2-bit / 单卡 A100-80G / 41 小时 / 掉点 < 3。
  3. "预算分配"的实质是：**大部分算力给第一段，第二段只做精调**——不是全程端到端 QAT。

## 2. 来源 B：Outlier Channel Splitting（ICML 2019, PMLR v97）

- 原始 URL：<https://proceedings.mlr.press/v97/zhao19c.html>
- 一句话：把含离群值的通道**一分为二**（复制一半到新通道），使两者都落回量化范围，**不需要重训**
  或微调。可作"离群值不必动用 QAT 就能压住"的对照手段。
- 摘要本次**未逐字核对**（只核了出处与标题），引用前请回原文。

## 3. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| outlier channel splitting | 来源 B | ✅ 找到（ICML 2019） |
| QAT budget allocation、compute-optimal QAT | 来源 A 的两段式预算 | ⚠️ 概念找到；"compute-optimal QAT"这个术语**未找到出处** |
| block-wise precision reduction | 来源 A 的 Block-AP | ⚠️ **不是**"精度逐段降"，是"逐 block 训练"；不要把两件事混写 |
| delayed fake quantization / fake_quant_after_n_steps | —— | ❌ 本次未找到论文出处。工程实现里常见（很多框架有 `fake_quant_after_n_steps` 之类开关），要用就引**框架源码行号**，别引论文 |
| progressive QAT | —— | ❌ 未找到（"progressive quantization" 另有一批 PTQ 工作，别混同名） |
| Bit-by-Bit | —— | ❌ 未找到可靠出处（不要引用） |
| cooldown-QAT fusion | —— | ❌ 未找到出处 |

## 4. 落到本工程的动作

- 若 QAT 预算紧，先把方案写成**两段式**：① block-wise 训全参（可中断、可续跑，适合本工程的
  轮次化实验）；② 端到端只训 step size。两段各自的步数/墙钟要分开记进 `evidence/`。
- "延迟开启 fake quant"如果要上，把它当**实现旋钮**记录（哪个框架、哪个 flag、默认值），
  不进知识库当论文结论。

## 5. 怎么验（证伪条件）

- 成立：两段式在同墙钟预算下端到端段更短，且精度不低于"全程端到端 QAT"。
- 不成立：block-wise 段的精度提升在端到端段被抹平（说明第二段预算不够），或显存峰值超限。
