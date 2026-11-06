---
name: report-and-conclusion
description: 当 experimenter 要写本轮报告与结论档案时加载——讲清 report.md 的判定段怎么写（对照跑前冻结的 criterion.yaml）、结论怎么写进 records/conclusions/（append-only，失败也入库）、records/best/ 什么时候更新、以及「数字只许引用 metrics.json、判定权在人冻结的判据」这条纪律。数字只抽不判；结论只给 outcome ＋ 一句话理由 ＋ 证据指针。
version: 1.0.0
applies_to: [experimenter]
---

# 报告与结论（`report-and-conclusion`）

## 0. 什么时候用 / 什么时候不用

- **用**：三段跑完、证据落盘后，写 `<轮次>/report.md`、入库 `records/conclusions/`、必要时更新 `records/best/`。
- **不用**：抽数（`runtime/metrics.py` 的职责）；改判据（跑后一字不改）；写知识条目（architect 的 `knowledge-curation`）。
- **两条核心纪律**：
  1. **判断是你的，数字不是**：报告里每个数字只能**引用** `<轮次>/metrics.json`，不许重算、不许四舍五入。
  2. **判定按跑前冻结的判据给**：`outcome` 对照的是 `<轮次>/criterion.yaml` 的 `success`／`falsification`，不许事后改判据。

## 1. 开工前要读的文件（路径 + 字段名）

| 读什么 | 取哪些字段 | 为什么 |
|---|---|---|
| `<轮次>/metrics.json`（只读） | 所有指标值（数字的唯一落点） | 报告里每个数字都从这引用 |
| `<轮次>/criterion.yaml`（只读，跑前冻结） | `success.{baseline_ref,require}`、`falsification`、`budget.*`、`eval_protocol.*` | 判定的唯一依据 |
| `<轮次>/artifacts.json` | 产物路径清单 | 报告里的产物指针 |
| `<轮次>/evidence/**`（只读） | 退出码、轨迹、评测原始输出 | 判定段的事实依据 |
| `<轮次>/test.md`、`<轮次>/changes.md` | 候选配置与机制生效验证 | 报告的执行记录段 |
| `records/conclusions/*.yaml` | 既有结论与序号 | 决定 `C-<序号>` 与是否追加 |
| `records/best/*.yaml` | 当前最优与该指标口径 | 判要不要更新最优 |

## 2. 步骤（每步带判据）

1. **写执行记录段**：**跑了几段就写几段**（命令、退出码、耗时、产物路径；基线轮可能只有 convert／eval 两段）；跑过的候选与结果（表）。
   *判据*：每条记录都能指向 `evidence/` 里的证据；没有「大概」。
2. **写判定段（`outcome`）**：逐条对照冻结判据——`success.require` **每一条都单独对一次**（它是列表，一条一个指标），
   再判 `falsification` 是否命中。
   *判据*：**逐项结论 ＋ 一条汇总**：`outcome ∈ {adopt, reject, inconclusive}`。
   - 逐项：每个 `<数据集>/<尺子>` 写「基线值 → 本轮值 → 差值 → 是否满足」；
   - 汇总：**全部满足 ⇒ `adopt`**；**任一不满足 ⇒ `reject`**；**某项缺数（没测到／数据集失败） ⇒ `inconclusive` 并点名缺哪项**。
   一句话理由写明对应哪条 `require`；证据指针指向 `metrics.json` 的字段名与 `evidence/` 的文件。
   轮与轮的精度差异用 `metrics.json` 里已经算好的 Δ（它覆盖**全部**指标，不需要你手算，也不需要判据里再列一遍）。
   `strength_target` 从 `design.md` 的受控块照抄即可（自由文本或 `null`）：**没有档位、没有机器判据**，判定不因它加减分。
   - **停止轮次（`metrics.json → early_stop.kind == "converged"`）**：判定照常给，但必须写
     「停在第 N 步、未跑满 `max_steps`」，且**训练侧 loss（last/best/min_loss）不得与跑满轮次
     直接比**；下游评测数可比（那是"各自停止点上的模型质量"）。要判**方案优劣** ⇒ 两轮同预算。
     `stop_conditions.*` 的阈值**不参与判定**：它们只回答"跑起来怎么保护"。
3. **结论入库（append-only）**：写 `records/conclusions/C-<序号>.yaml`；**失败也要入库**（否则下一轮会重试同一个坑）；
   每个数字带 `numbers_ref` 指向 `metrics.json`；同时在 `records/ledger.jsonl` 追加一条（唯一的 append-only 账本；
   `records/index.jsonl` 已删——**索引是按需从 `conclusions/` 现算的派生视图**，不是第二个真相）。
   *判据*：序号不重复（append-only）；`numbers_ref` 真实存在；失败结论里有「哪个阈值、第几步、什么数值」。
4. **按需更新最优**：只有**新判定或新证据**才覆盖 `records/best/<任务名>__<指标>.yaml`。
   *判据*：覆盖前后都能在 `records/ledger.jsonl` 里查到你；不同口径的指标**不许**互相覆盖。
5. **收口状态**：`python3 runtime/state.py close --conclusion C-<序号> --outcome <...>`（`state/rounds.jsonl` 本轮**恰好追加一行**）。
   *判据*：`state/rounds.jsonl` 的 `metric.*` 与 `metrics.json` 一致（引用，不重算）。
6. **交接**：`EXPERIMENT_DONE`（含框架还原校验记录）；无效轮次 `EXPERIMENT_INVALID`。

## 3. 模板与命令（可直接复制）

```markdown
<!-- <轮次>/report.md 骨架 -->
## 1. 执行记录
| 段 | 命令来源 | 退出码 | 耗时 | 产物 |
|---|---|---|---|---|
## 2. 判定段（对照跑前冻结的 criterion.yaml）
- outcome: adopt | reject | inconclusive
- 一句话理由：<对着哪条冻结条件>
- 证据指针：<metrics.json 字段> ＋ <evidence/ 文件>
- 逐条对账：success.require（判据字段）vs `<metrics.json 字段>` = `<值>`
- falsification 是否命中：<…>
- strength_target（从 design.md 照抄，自由文本或 null；不参与判定）：<…>
## 3. 数字（全部引自 <轮次>/metrics.json）
## 4. 结论指针：records/conclusions/C-<序号>.yaml（账本 records/ledger.jsonl 追加一条）
## 5. 框架还原校验记录：<before/after diff 结果>
```

```bash
python3 runtime/state.py close --conclusion C-<序号> --outcome adopt   # 收口本轮
```

## 4. gotchas（症状 → 正确动作）

1. **手抄/四舍五入数字** → 症状：报告与 `metrics.json` 不一致、不可追溯。正确动作：只引用字段，原样写值。
2. **事后改判据让它「通过」** → 症状：判定不可信。正确动作：判据跑后一字不改；要改 ⇒ 新写一份并用 `supersedes:` 指向旧份。
3. **失败不入库** → 症状：下一轮重试同一个坑。正确动作：失败也写结论，含阈值/步数/数值。
4. **不同口径的最优互相覆盖** → 症状：历史最优被抹掉。正确动作：`best/` 按 `<任务名>__<指标>` 分文件，口径不同的分开放。
5. **把外部知识写进判定** → 症状：判定被污染。正确动作：外部知识永不进判定。
6. **状态与报告两处各写一份结论** → 症状：状态不可信。正确动作：状态只由 `runtime/state.py` 写，报告只引用。

## 5. 校验回路（自查「我真的做对了」）

- 报告里每个数字都能在 `metrics.json` 找到对应字段；无重算、无四舍五入。
- `outcome` 与冻结判据逐条对得上；结论只有 `outcome` ＋ 一句话理由 ＋ 证据指针（无档位、无额外机器判据）。
- 结论 append-only、`numbers_ref` 存在、失败条目也入库。
- `state/rounds.jsonl` 只多一行；框架还原校验 diff 为空。

## 6. 参考

- 本工程：`templates/report.md`、`records/conclusions/_EXAMPLE.yaml`、`runtime/state.py`（状态接口）。
- `skills/run-observation/SKILL.md`（读观察）、`skills/knowledge-curation/SKILL.md`（architect 侧的知识写回）。
- `references/verdict-and-fields.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①结论档案字段清单（以 `records/conclusions/_EXAMPLE.yaml` 为准，逐段列出）②判定段实例（`outcome` ＋ 一句话理由 ＋
  证据指针，每条都写判据字段名 ＋ `metrics.json` 字段名）③判定段的三条硬边界 ④`records/best/` 更新条件 ⑤收口与留痕。
- 缺口纪律（**不许自创**）：本工程**没有**"质量档位"这回事 —— 结论只给 `outcome` ＋ 一句话理由 ＋ 证据指针。
  `strength_target` 只是一句自由文本（或 `null`），**不定义任何机器判据、不参与判定**；
  判定时若需要"够不够强"这类事实，就在报告里**逐条写明事实与证据指针**，不新增字段、不新增档位。
