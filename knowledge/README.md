# `knowledge/` —— 可继承的经验（四类的**唯一**写作指导）

> **先说边界**：这里放的是**实验学到了什么**（可继承经验、模型档、框架理解），
> **不是**契约（契约在 `config/`，只读）、**不是**工具（工具在 `devtools/`／`runtime/`）、**不是**跨轮档案（档案在 `records/`）。
> **一个事实只有一个落点**：同一内容不许在 YAML 与 Markdown、或在两个目录各写一份。
> **本文件是四类格式的唯一来源；P6 已定稿（2026-10-24）**：四类的完整格式、必填字段与样例都在这里，别处只指向它。
> 实际条目登记在 `INDEX.md` —— 现况：`models/` 三份模型档已落盘；`external/` 有 **10 篇外部来源**（未验证、可作候选，见 §4）；`techniques/` 尚无满足准入的条目
> （`techniques/` 的准入要求「评估跑完、结论入库」，本工程还没跑过实验）；`frameworks/` 暂无公共 patch 与扫描笔记。

## 0. 四条通用规则

1. **一个事实只有一个落点**：同一内容不许在 yaml 与 md 里各写一份。
2. **数字只引不抄**：条目里的数字写 `numbers_ref` 指到 `<artifacts.root>/rounds/<轮次>/metrics.json`；不许出现裸数字。
3. **写不出判据就别写**：说不清「什么结果算它成立／不成立」的，还不是知识。
4. **append 优先**：能追加就不覆盖；确实要覆盖（如 `status`），覆盖前后都要能在 `records/ledger.jsonl` 里查到。

## 1. `techniques/` —— 每轮评估后的经验沉淀

| 项 | 规定 |
|---|---|
| 记什么 | 一个**可复用的技术方案**：一组自变量 ＋ 它在本工程实测的结果 |
| 何时记 | **不是每轮都要记**。只有「评估跑完、结论入库」且该方案值得下一轮参考时才记 |
| 多轮验证同一方案 | **只记一条**：在该条 `evidence.rounds` 里追加轮次，`result` 取最新一次为准；**不要**每轮建新文件 |
| **身份规则（判「是不是同一条」）** | `axis` 相同 **且** `technique` 键值集合完全相同 ⇒ **同一条**（与 `id`／文件名／标题／轮次**无关**）。命中既有条 ⇒ 改它：`rounds`／`conclusions` 追加，`result`／`status` 取最新，`numbers_ref` 换成最新一轮，`patch_ref` 合并去重 |
| 什么时候算新方案 | `technique` 的任何取值变了（4-bit → 3-bit、per-channel → per-block）或换了 `axis` ⇒ **新方案、新建一条**；别把两条不同方案揉进一个文件的 `rounds` |
| 身份字段与翻转 | `id`／`axis`／`technique` 写下不改（笔误更正要在 `notes` 记一行）；`status` 从 adopted 翻到 rejected（或反向）时 `notes` 必须写「哪一轮、为什么翻」—— 否则等于静默改判 |
| 写回前怎么核（模型自查，无脚本） | `grep -l '^axis:' knowledge/techniques/*.yaml` 找候选，再比 `technique:` 块：同 `axis` ＋ 同键值 ⇒ 改它，否则新建 |
| 成功与失败 | **都记**。失败条目 `status: rejected` 并写 `why_failed`（一句话、可机械核对：哪个阈值、第几步、什么数值） |
| 格式 | 默认 `.yaml`（机器要读：自变量、证据、轮次、结论指针）。**yaml 不够就写 md**：要讲机制/适用边界/多次试错经过时用 `.md`，开头放一个 fenced `yaml` 块装机器字段，正文写叙述；**一个技术方案仍然只有一个文件** |
| 不记什么 | 环境故障、口径没跑全的轮次、纯配置改动、一次性的实验垃圾 |

**必填字段**（缺一项这条就不合格；写回时自己逐条对，没有脚本兜底）：`schema`／`id`／`title`／`axis`／`status`／
`technique`／`hypothesis`／`evidence.{rounds,conclusions,result,numbers_ref}`／`patch_ref`／`notes`。
失败条目 `status: rejected` 时必须另写 `why_failed`（一句话、可机械核对：哪个阈值、第几步、什么数值）。

```yaml
schema: 1
id: <示例技术方案名>
title: "<一句话：这条技术做了什么>"
axis: "<受控轴名>"
status: adopted
technique: {<自变量字段一>: "<值>", <自变量字段二>: "<值>"}
hypothesis: <为什么觉得它有效；带机制解释，不写"应该能提升">
evidence:
  rounds: [R-0003, R-0005]          # 多轮验证同一技术方案：只记这一条，轮次在这里追加
  conclusions: [C-0007]
  result: adopt
  numbers_ref: <artifacts.root>/rounds/R-0005/metrics.json
patch_ref: [<artifacts.root>/rounds/R-0005/patches/0001-<简述>.patch,   # 本轮私有 patch（一次性）
            knowledge/frameworks/patches/<公共简述>.patch]              # 或跨轮复用的公共 patch
notes: 适用边界与注意事项。失败时把 status 改成 rejected 并写 why_failed：一句话说清"哪个阈值、第几步、什么数值"。
```

> 上面这条是**格式样例**，不是某轮真实条目 —— 本工程尚无满足准入的 `techniques/` 条目。
> `patch_ref` 的两个落点的区别见 §3；`numbers_ref` 是数字纪律的锚（§0 规则 2）。

## 2. `models/` —— 模型结构

| 项 | 规定 |
|---|---|
| 格式 | **`.yaml`**（结构是机器要读的：architect 要算显存预算、判架构类型） |
| 落点 | `knowledge/models/<模型名>.yaml`，**一个模型一个文件** |
| 记什么 | 架构类型、层数与维度、attention 类型、MoE 专家数与共享专家、显存分项、典型并行、量化注意点 |
| 准入 | 数值必须来自**现场读模型配置**（真打开过 `config.json` 之类）；过期就改，**不许留两版** |
| 一句话 | 叙述放 `notes` 字段，不另开 md |

**键结构（P6 定稿）** —— 顶部 6 个键 ＋ `arch`／`weights`／`quant_notes`／`memory`／`notes` 五段：

```yaml
schema: 1                       # 必填
id: "<模型名>"                   # 必填；与文件名 <模型名>.yaml 一致
archived: "<归档日期>"           # 照搬旧档
status: "<状态原文>"             # 照搬旧档，**不许升级**（纪律 ②）
one_liner: <一句话>

arch:                           # 每个值都写成 {value, source}
  type:            {value: <dense|MoE|…>, source: <出处>}
  experts:         {value: null, source: <非 MoE 写 null＋理由>}       # MoE 写 {routed, top_k, shared}
  layers:          {value: <int|null>, source: <出处>}
  hidden:          {value: <int|null>, source: <出处>}
  ffn:             {value: <int|null>, source: <出处>}
  attention:       {value: <GQA|MHA|MQA|混合…>, source: <出处>}
  num_heads:       {value: <int|null>, source: <出处>}
  num_kv_heads:    {value: <int|null>, source: <出处>}
  head_dim:        {value: <int|null>, source: <出处>}
  qk_layernorm:    {value: <bool|null>, source: <出处>}
  norm:            {value: <RMSNorm|null>, source: <出处>}
  eps:             {value: <float|null>, source: <出处>}
  rope_theta:      {value: <float|null>, source: <出处>}
  max_position:    {value: <int|null>, source: <出处>}
  vocab_size:      {value: <int|null>, source: <出处>}
  tied_embeddings: {value: <bool|null>, source: <出处>}
  dtype:           {value: <bfloat16|null>, source: <出处>}
  params:          {value: <int|null>, source: <出处>}   # 需要时加 estimate: <估算值＋可信度>
weights: {local_path: {value: <路径|null>, source: <出处>}}
quant_notes:
  moe_experts_covered: <一句话>
  scope_source: <一句话＋file:line>
  quantized_linears: {value: <int|null>, source: <出处>}
  risks: <一句话或多行>
memory:
  per_card_blocks: {config: <锚点配置>, symbols: <符号表>, blocks: [{block, formula, per_card|key_point}], source: <出处>}   # 保留算式
  anchors: [{config: <…>, observed: <…>, source: <…>}]          # 实测锚点（并行度、序列长度、微批逐项写明）
  notes_parallel: <可选：并行可行域与判据式>
notes: <多行字符串：叙述、适用边界、更正记录、未确认清单、来源>
```

**值的写法（`{value, source}` 约定）**：`arch.*`／`weights.local_path`／`quant_notes.quantized_linears` 的每个值都带 `source`；
**值未知时 `value: null`，不许填估算值** —— 估算只能放进同层的 `estimate:` 子键并写明可信度（例：`params: {value: null, estimate: "约 291B", source: "低可信度：由 582GB 反推，需 config.json 确认"}`）。
`source` 写「哪个文件/哪条记录 ＋ 现场是否复核过」；照搬旧档而本步未复核框架检出的 `file:line` 要显式注明。

**P6 定稿时对键清单的补充（四处，规格缺口，透明登记）**：`arch` 的键清单（`type`…`params`）里
没有 MoE 专家数／共享专家的落点，但同节「记什么」明确要求记它 —— 故 `arch` 下新增 **`experts`**（三档都写）；
另外两档模型各自特有的结构事实用 **`arch.compress_ratios`**、**`arch.mtp_layers`**（DeepSeek 逐层压缩率、MTP 层数）
与 **`arch.attn_layer_interleave`**（Qwen3.5 的线性/全注意力交替间隔）承载。
这四个键之外不许再往 `arch` 里加键；要加先改本节（格式的唯一来源）。

三条纪律：① 数值必须来自现场读模型配置；② 旧档里的状态字段照搬原文，**不许升级**成「已现场核实」；
③ 更正走 `notes` **追加**，不许原地改数值。

## 3. `frameworks/` —— 只放两类东西

| 放什么 | 落点 | 判据 |
|---|---|---|
| (a) **公共的代码修改 patch** | `knowledge/frameworks/patches/<简述>.patch` | **跨多轮复用、已证明稳定** |
| (b) **对框架代码的扫描理解** | `knowledge/frameworks/<框架>-<主题>.md` | 能力、限制、关键 `file:line`、「改哪里能达成什么」 |

**单轮实验的私有改动不要放这里** —— 它在轮次归档的 `<轮次>/patches/` 里（一次性，用完即还原）。
**三处链接关系**：① `techniques/*` 的 `patch_ref:` → 指向本轮 patch 与/或公共 patch（两个都指就写成清单）；
② `frameworks/` 的理解笔记 → 指向它描述的**具体 `file:line`**（不是指向 patch）；
③ 轮次归档里的 patch → 在 `<轮次>/changes.md` 里被引用一次（改了哪些文件、怎么验的）；**不把 patch 内容抄进知识条目**。

> 一句话区别：**轮次归档里的 patch 是一次性的（跑完还原）；`knowledge/frameworks/` 里的 patch 是可复用的（已证明稳定），理解笔记是只读的扫描结论。**

## 4. `external/` —— 外部来源（**可作候选，永不进判定**）

| 项 | 规定 |
|---|---|
| 它是什么 | **外部来源**：论文、工程报告、开源配方里写的做法与踩过的坑。**没有在本工程验证过** |
| 它与 `techniques/` 的分工 | **"外面有这招"归这里，"这招在我们这儿管用"归 `techniques/`**。验证过的写进 `techniques/`（要 `numbers_ref`），没验证的写这里 |
| 准入条件（缺一不可） | ① 原始 URL ＋ 抓取日期；② 原文摘要（未逐字核对的可显式标"未逐字核对"）；③ **怎么验**（本工程的证伪条件：什么算成立、什么算不成立）；④ 文首 `永不进判定` 声明 |
| 能进方案吗 | **能，作候选来源**：先验可以触发一个候选方案。候选能否成立仍要过框架取证（`file:line`）与本地实测 |
| 不能进什么 | 不进 `criterion.yaml`、不进结论、不进 `records/best`；报告里的数字不许来自这里 |
| 关键词对账 | 每条都要有"关键词 → 对应位置 → ✅/⚠️/❌"表；**检索不到原始出处就写 ❌ 并注明不要引用** —— 编一个像论文的假出处，下一个人会照着错的出处写方案 |
| 格式 | `.md`，一节一来源；骨架见 `external/_README.md`（`_` 开头 ⇒ 不算条目） |
| 谁来写 | **人**（主 Agent 开工前整理）；四个角色只读：architect 用它出候选、其余角色只在需要找方向时读 |

## 5. 谁能写、什么时候写

- 四个角色**只读**使用（`local-knowledge`）；**写回**由 architect 在反馈环收尾时做（`knowledge-curation`）。
- 写回前先读本文件与 `INDEX.md`；写完按 §1 的必填字段与身份规则**自己逐条核一遍**（没有校验脚本，自查就是判据）。
- `config/` 的契约（`task.schema.json`）**不是知识**，任何角色都不许改。
