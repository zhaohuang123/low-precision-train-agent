# 先验 07｜蒸馏与推理模型专用 QAT（ReQAT：TAQ ＋ SEM ＋ Q-FIT）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：QAD、quantization-aware distillation、KL distillation for QAT、ReQAT、
> Trace-Aligned QAT、Q-FIT、low-entropy token、W4A4KV4 reasoning

## 1. 它到底说了什么（来源：arXiv:2606.15682，ICML 2026）

- 原始 URL：<https://arxiv.org/abs/2606.15682>｜项目页 <https://aiha-lab.github.io/ReQAT/>
  ｜代码 <https://github.com/aiha-lab/ReQAT>
- 摘要（原文摘录）：

  > "Microscaled FP4 formats enable efficient FP4 deployment; however, fully quantizing weights,
  > activations, and KV caches (W4A4KV4) causes severe reasoning degradation that existing PTQ and
  > QAT fail to recover. We identify that FP4 failures concentrate on **low-entropy tokens**—precise
  > symbolic commitments such as digits and operators—where quantization noise inflates sampling
  > errors that cascade through reasoning traces. … three components: (i) Trace-Aligned QAT (TAQ),
  > which revisits identical reasoning traces to focus updates on critical low-entropy decisions;
  > (ii) Selective Entropy Minimization (SEM), which reinforces confidence at low-entropy
  > positions; and (iii) Q-FIT, a quantization-friendly initialization that jointly calibrates
  > RoPE-consistent KV cache transformations to stabilize QAT."

- 关键结论：
  1. **失败定位**：W4A4KV4 下推理掉分集中在**低熵 token**（数字、运算符）。量化很少翻转 top-1，
     而是把非 top-1 的**尾部概率质量抬高**，让"很确定的符号承诺"变得容易被采样错，错一个数字
     就整条推理链崩掉。
  2. **TAQ**：第二段 QAT 复用第一段 BF16 微调的**同一批推理轨迹**，把更新压到低熵决策上
     （对照：不同轨迹 ⇒ 增益消失，约 5% vs ≤1%）。
  3. **SEM**：在低熵位置加"熵最小化"辅助损失，用**软权重**（按 minibatch 熵的百分位）而不是硬
     阈值掩码；硬掩码会过度锐化边界 token（软权重多 +1.7~2.0 分）。
  4. **Q-FIT**：只调 KV 侧——**pre-RoPE 的逐通道缩放**（折进投影权重，零推理开销）＋
     **post-RoPE 的逐通道平移**，两者用"BF16 与 KV4 注意力输出距离最小"来校准。
  5. 数字：R1-Qwen-14B，NVFP4 W4A4KV4，AIME-120 65.94% vs BF16 全参微调 65.46%（+0.48）；
     吞吐 3.9×（DGX Spark）/3.1×（B200）。总训练预算不变（350M tokens 档位内）。

## 2. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| ReQAT、Trace-Aligned QAT、Q-FIT、low-entropy token、W4A4KV4 reasoning | 摘要 | ✅ 找到（Q-FIT 是本文的初始化组件） |
| quantization-aware distillation、KL distillation for QAT | —— | ⚠️ 本文**不是**蒸馏（没有教师-学生 KL）：它靠**数据轨迹对齐 ＋ 熵正则**。若你要的是蒸馏，另有 LLM-QAT（arXiv:2305.17888，"data-free distillation"），本次**未逐字核对**，引用前回原文 |
| QAD | —— | ❌ 本次未找到出处（不要把 "QAD" 当已发表方法名） |

## 3. 落到本工程的动作

- 评测侧：若任务是推理类（GSM8K/AIME 之类），**按 token 熵分桶看掉分**，别只看总分。分桶能直接
  指出"是符号位错还是表达错"。
- 训练侧：两段式的第二段**复用第一段的样本**（本工程天然满足：同一批数据），并加低熵位置的
  熵正则（软权重）。
- KV 量化（若要做 KV4）：先做 Q-FIT 式校准（缩放＋平移），别只上 scale。

## 4. 怎么验（证伪条件）

- 成立：同预算下 W4A4KV4 的推理分数 ≥ BF16 微调 − 0.5 分，且低熵桶掉分显著小于高熵桶。
- 不成立：总分持平但低熵桶明显掉 ⇒ 说明"低熵假设"在本任务不成立（记录，改判据）。
