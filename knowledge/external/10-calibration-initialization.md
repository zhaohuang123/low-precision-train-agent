# 先验 10｜校准与初始化（PTQ 式校准 → QAT；Q-FIT / 保功能初始化）

> 状态：**外部来源（未在本工程验证）** —— 可作**候选来源**（启发方案），但**永不进判定**：
> 不进 `criterion.yaml`、不进结论、不进 `records/best`。**本地验证有效的结论归 `techniques/`**。
> 抓取日期：2026-11-04

> 你给的关键词：calibration initialization for QAT、PTQ-initialized QAT、GPTQ initialization、
> scale initialization、quantization-friendly initialization

## 1. 来源 A：Q-FIT（ReQAT 的初始化组件，arXiv:2606.15682，ICML 2026）

- 原始 URL：<https://arxiv.org/abs/2606.15682>
- 摘要原文："… (iii) Q-FIT, a quantization-friendly initialization that jointly calibrates
  RoPE-consistent KV cache transformations to stabilize QAT."
- 正文细节（项目页，未逐字核对）：pre-RoPE 的逐通道缩放 `s` 折进投影权重（零推理开销）＋
  post-RoPE 的逐通道平移 `m`；两者通过**最小化 BF16 与 KV4 注意力输出的距离**来选；不同层会
  自动偏向 scaling 或 shifting。
- 含义：**"先在 BF16 下把量化参数校准好，再开 QAT"** 是稳定 W4A4KV4 的关键一步；校准的目标函数
  是"输出距离"，不是"权重近似误差"。

## 2. 来源 B：RaBiT 的保功能初始化（arXiv:2602.05367）

- 原始 URL：<https://arxiv.org/abs/2602.05367>
- 摘要原文："This process is stabilized by a robust initialization that prioritizes functional
  preservation over mere weight approximation."
- 含义：残差多项分解的路径初始化若只做"权重近似"，各路径会耦合塌掉；要按"**功能**保持一致"
  （即输出/激活分布一致）来初始化。这与来源 A 的"输出距离"是同一个思想。

## 3. 关键词对账

| 你给的关键词 | 对应位置 | 状态 |
|---|---|---|
| quantization-friendly initialization | 来源 A 摘要（Q-FIT） | ✅ 找到 |
| calibration initialization for QAT | 来源 A（校准后进 QAT 第二段） | ✅ 找到 |
| scale initialization | 来源 A 的 `s`（缩放）与 `m`（平移） | ✅ 找到 |
| PTQ-initialized QAT | —— | ⚠️ 概念成立（先用 PTQ 式校准得到初值再 QAT），但本次**没找到以此命名的原文**；引用时写清"这是概念，不是论文名" |
| GPTQ initialization | —— | ❌ 未找到"用 GPTQ 初始化 QAT"的原始出处。GPTQ 本身是 PTQ 方法（Frantar et al., arXiv:2210.17323，本次未逐字核对） |

## 4. 落到本工程的动作

- QAT 开跑前加一步**校准**：对每层用 BF16 与量化后的输出做距离最小化，得到 scale/shift 初值；
  把校准前后的"前 100 步 loss 抖动"记进 `evidence/`。
- 校准数据必须**与训练数据同分布**（本工程用验证集的一小批即可，别用评测集）。

## 5. 怎么验（证伪条件）

- 成立：校准后 QAT 前 100 步 loss 抖动（首 10 步与 100 步的极差）明显小于不校准，且最终精度不降。
- 不成立：抖动无差别 ⇒ 校准对本任务无收益（记录；不要再把"先校准"当默认步骤）。
