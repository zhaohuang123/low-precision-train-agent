# `scheme-design` 深化材料：架构判定 / 显存预算 / 候选组拆解

> 本文件是 `skills/scheme-design/SKILL.md` 的**渐进披露层**：正文只留入口一句话，长内容在这里。
> 纪律：`skills/` 里不许出现模型名/任务名/阈值/具体路径；本文件一律用 `<模型名>`／`<任务名>`／`<轮次>` 占位，
> 取值/默认值**不复述**（唯一落点是框架代码本身，0.18.0 起没有旋钮字典）。

## 1. 架构类型判定清单（先判架构，再谈量化）

架构决定「哪些层能压、压了会不会塌」；跳过这一步的方案会**不可解释地翻车**。

| 类型 | 怎么判 | 对量化的含义 |
|---|---|---|
| dense | 无 router/experts，每层一个 MLP | 全层均匀受力，量化误差直接进主通路 |
| MoE | 有 `num_experts`／router／moe 层 | 专家层可单独压（`*-moe-only` 一类），dense 主干可留高精度 |
| MLA | attention 有 `q_lora_rank`／`kv_lora_rank`，无独立 `k_proj`／`v_proj` | 压 KV 压缩矩阵比压普通投影更敏感，第一轮先别动 |
| GQA | `num_key_value_heads < num_attention_heads` | KV 侧通道少，per-channel scale 统计量小，容易不稳 |

**判据**：判完必须落到字段，不是形容词 —— 写清你读的是哪一份材料、哪个字段（现场读模型配置，如 `config.json`）。
字段落点是 `knowledge/models/<模型名>.yaml` 的 `arch.*`（键结构见 `knowledge/README.md` §2）；档案里没有该模型 ⇒
先去现场读模型配置，读完把结论补回 `knowledge/models/`。

## 2. 显存五块预算：算式模板（不写数字的显存分析等于没做）

| 块 | 口径 | 备注 |
|---|---|---|
| 权重 | `P × bytes/param / TP` | 各精度下的 bytes/param 与 scale/zero-point 开销要现场取证 |
| 梯度 | `P_trainable × bytes / TP` | QAT 冻结的部分不算 |
| 优化器状态 | 按**实际 optimizer** 算（Adam 类通常是最大头） | 最常被漏算 |
| 激活 | `b × s × h × layers` 量级，按 recompute 开关折算 | 与 `seq_len` 强相关，长序列必须单列 |
| 通信缓冲 | allreduce/allgather/ring 的桶大小 × 并发数 | 与 TP/PP/DP 配置耦合 |

**判据式写法**（每条都这么写，而不是给一句"应该能跑"）：
- 若 `权重 + 梯度 + 优化器状态` 已超过单卡显存 × 0.8 ⇒ 先降 TP／加卡／上 offload，**因为激活还没算进去**，直接开训必然 OOM。
- 若激活预算超了 ⇒ 先开 activation recompute，**不要直接砍 `seq_len`** —— 砍 `seq_len` 会同时改评测口径，历史结论全部不可比。

**落点**：算式与锚点配置（并行度、序列长度、微批）进 `knowledge/models/<模型名>.yaml` 的 `memory.{per_card_blocks,anchors}`；
`design.md` **正文**写预算结论与排序理由。算不出的项标 `unknown` 并写清缺哪份材料。

## 3. 候选组怎么拆（3–6 个，含至少一个组合方案）

1. **数量**：一轮 3–6 个候选，**至少一个组合方案**（同时动 ≥2 个自变量维度）。
2. **可区分**：候选之间必须在**自变量维度**上可区分；每个候选要能一句话说清「它与其它候选的差别是哪一行」。
3. **组合的理由要写出来**：因子之间互补／互斥／一个补偿另一个的误差；并写清「**如果它成了，下一步怎么拆开归因**」。
   这一段写在 `design.md` **正文** —— 受控块里不许出现依据/假设（受控块纪律：依据归正文）。
4. **同一轮所有候选共享同一份 `criterion.yaml`**：口径一致，聚合差值才可比。
5. **明确禁止**：单因子严格推导、逐题配对（一轮只动一个因子）。这是本工程刻意放弃的方法论，
   代价用「一组候选 ＋ 组合方案」补回来。

**为什么禁止单因子**：一轮只动一个因子会把一批候选全挤进同一个成本档，档内排序是**噪声排序**而不是知识；
人真正想试的方案会排到很后面。

## 4. 多源取证：至少触碰 3 个源

| 源 | 拿什么 | 可信度 |
|---|---|---|
| `knowledge/techniques/*.yaml` | 同/相近自变量组做过没有（含 `status: rejected` 的坑） | 中—高（有本地实测） |
| `knowledge/models/<模型名>.yaml` | 架构与显存算式 | 高（数值须现场读过） |
| `knowledge/frameworks/*.md` | 框架能力、限制、关键 `file:line`（判「能不能表达」） | 高（须带 `file:line`） |
| `records/conclusions/*.yaml` | 已判过的 `outcome`（失败结论一样值钱） | 高（实测） |
| `records/best/*.yaml` | 当前最优与该指标口径 | 高（一格一个） |
| `knowledge/external/*.md`＋intent 的 `external.keywords`（`web_search`） | 只用来找方向 | **低：永不进判定** |

**判据**：
- 两条来源冲突时（例如 `frameworks/*.md` 说支持、`conclusions/` 里有同方案 `outcome: reject`）⇒ **以 `conclusions/` 为准**（实测 > 文档，文档会漂）。
  - 某技术只出现在 `knowledge/external/` ⇒ **可以作候选**，但方案里必须标注「**外源未验证**」，并写出本地要跑的**最小证伪实验**；
    不许把它当已知有效的因子直接交给 experimenter 烧卡。

## 5. 落点复核（写完自分流）

| 内容 | 落点 | 不许去哪 |
|---|---|---|
| 选了什么（自变量） | `design.md` 块内 `variables:`（键名/取值由 architect 读框架判定，正文写依据） | 不许自造旋钮名 |
| 怎么落地 | `design.md` 块内 `implementation:` ＋ `<轮次>/patches/` | 不许写进 `variables:` |
| 依据、假设、排序理由 | `design.md` **正文** | 不许进受控块 |
| 成功/证伪条件、评测口径 | `<轮次>/criterion.yaml`（跑前冻结） | 不许进 `design.md` 块 |
| 早停阈值、墙钟上限 | 任务配置 `stop_conditions.*`（**不在判据里**） | 不许进 `design.md` 块，也不许抄进判据 |

## 6. 本 skill 已点名的缺口（不许自创，故留 TODO）

1. **已定稿（P6，2026-10-24）**：`knowledge/models/<模型名>.yaml` 的 `arch.*`／`memory.*` 键结构已随
   `knowledge/README.md` §2 定稿（键清单见该节，实例见 `knowledge/models/*.yaml` 三份）。本文件的
   「架构判定清单」现在**按这些键名当契约引用**；**数值**仍须现场核实并带 `source`（`null` 保持 `null`）。
2. `TODO(P3)`：显存五块的**系数表**（各 dtype 的 bytes/param、优化器状态数、激活项折算）在**本工程里没有落点** ——
   方案只给「五块」与「保留算式与锚点配置」。因此本 skill **不写死系数**：一律要求现场取证并带 `source`；
   模型档（P6 已定稿）可作 `arch`／`memory` 的取值落点，但系数仍须逐次带出处。
