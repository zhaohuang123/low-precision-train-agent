# `knowledge/INDEX.md` —— 知识库入口（先读这里，再读四类）

> 用法：`architect` 出方案前、`developer` 判框架支持性前、`experimenter` 写结论前，**先读本文件**找落点，
> 再按 `knowledge/README.md` 的写作指导取用。**格式的唯一来源是 `knowledge/README.md`**，本文件只做索引。
> **P6 已登记（2026-10-24）**：下表「已登记条目」是逐条清单；`techniques/` 现在**本来就是空的**
> （准入要求「评估跑完、结论入库」，本工程还没跑过实验 —— 见 `knowledge/README.md` 开头与 §1）；
> `external/` 是**外部来源**（0.19.2 校正口径）：未验证、**可作候选来源**，但必须写清出处、摘要与
> **怎么验**，且永不进判定。验证有效的技术方案归 `techniques/`。见 `knowledge/README.md` §4。
> 不是还没建。`models/` 三份是 P6 从旧工程按 §12.2 映射搬来的；`frameworks/` 现有**两条特性**：
> `qat-qsnr-probe`（0.18.4）与 `mxfp4-mask-fix`（0.18.10），共 **5 个文件**（3 个 `.patch` ＋ 2 篇笔记）。

## 0. 四类落点一览

| 落点 | 放什么 | 可信度 | 已登记条目 |
|---|---|---|---|
| `techniques/` | 可复用的技术方案（自变量 ＋ 实测结果；成功与失败都记） | 中—高（有本地实测） | **0 条** —— 准入＝「评估跑完、结论入库」（`README.md` §1）；尚无满足者 |
| `models/` | 模型结构（`<模型名>.yaml`，一个模型一个文件） | 高（数值须来自现场读模型配置） | **3 份**：`Qwen3-4B.yaml`（✅ 架构数值已现场核实）／`DeepSeek-V4-Flash.yaml`（⚠️ 部分待确认）／`Qwen3.5-35B-A3B.yaml`（⚠️ 部分待确认） |
| `frameworks/` | ① `patches/` 公共 patch（已证明稳定）；② `<框架>-<主题>.md` 扫描理解（带 `file:line`） | 高（须带 `file:line`） | **5 件**（3 patch ＋ 2 笔记）—— 特性① `qat-qsnr-probe`：`patches/qat-qsnr-probe/core/…/qsnr_probe.patch`（探针本体）＋`patches/qat-qsnr-probe/llm/…/qat_quant_engine.patch`（LLM 层接线）＋笔记 `MindSpeed-qat-qsnr-probe.md`（上游两树 `git apply --check` 通过、自检 32/32）；特性② `mxfp4-mask-fix`：`patches/mxfp4-mask-fix/core/…/w4a16_fake_quantization.patch`（MXFP4 内核「≤ −127 硬清零」→ `QAT_MASK_FIX`）＋笔记 `MindSpeed-mxfp4-mask-fix.md`（上游 `origin/master` 通过、§3 三条行为判据全过） |
| `external/` | **外部来源**：外面怎么做、通常怎么失败。可作**候选来源**，**永不进判定** | 低（未验证；引用要回原文） | **10 条** —— 01 缩放规则（转置不变/免截断）｜02 宏块缩放（MBS）｜03 残差量化（RaBiT）｜04 优化器（MuonQ）｜05 QAT 调度（两段式/OCS）｜06 参数高效 QAT（L4Q）｜07 推理模型 QAT（ReQAT）｜08 混合精度回退｜09 离群值抑制（旋转）｜10 校准初始化。**按这些词 grep 就能落到对应一篇** |

> 两档 ⚠️ 的模型档**本机没有对应 `config.json`**：`arch` 里拿不准的值一律 `null`，并写清去哪读 ——
> 这是刻意的（编一个数会得到"看起来对的错结论"）；状态字段照搬旧档原文，不许被下游升级成「已现场核实」。
> 另一条与工程强相关：`Qwen3-4B.yaml` 是 **dense**，旧工程 MoE 场景的结论（专家层不被 `w4a4-mxfp4` 覆盖）**不适用**。

## 1. 跨轮档案（不在本目录，但与取证强相关）

| 落点 | 放什么 | 可变性 |
|---|---|---|
| `records/conclusions/` | 结论档案（`C-<序号>.yaml`；**append-only**，失败也入库） | 只允许追加 |
| `records/best/` | 最优（`<任务名>__<指标>.yaml`） | 可覆盖（须有新判定或新证据） |
| `records/ledger.jsonl` | **唯一**的 append-only 账本（结论索引由 `records/conclusions/` 现算，不落盘） | 只允许追加 |
| `records/ledger.jsonl` | 变更账本（配置/知识/patch 的每次覆盖都能查到） | 只允许追加 |

## 2. 检索顺序（推荐）

1. `records/best/` → 现在的最好结果与口径是什么。
2. `knowledge/techniques/` → 同样或相近的自变量组做过没有（含 `rejected` 的坑）。
3. `knowledge/models/<模型名>.yaml` → 结构事实与显存预算算式。
4. `knowledge/frameworks/` → 框架能力与关键 `file:line`（判「能不能表达」）。
5. `records/conclusions/` → 逐轮结论与失败原因。
6. `knowledge/external/` → **找方向／出候选**（可作候选来源）；两条入口：按上面那行的主题词 grep 归档，或按本轮 intent 的 `external.keywords` 用 `web_search` 搜（命中不落盘，只在 `design.md` §2.2 留痕）；**判据不许来自这里**。

## 3. 纪律回指（不要在本文件复述，去源头读）

- 四类怎么写、准入是什么 → `knowledge/README.md`。
- 何时写、写哪类、怎么自查 → `skills/knowledge-curation/SKILL.md`。
- 怎么取证、可信度怎么分级 → `skills/local-knowledge/SKILL.md`。
- 框架改动的两条铁律（检出永不提交、patch 跑完还原） → `AGENTS.md` §2 第 1 条与 `runtime/framework_patch.sh`。
