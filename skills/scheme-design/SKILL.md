---
name: scheme-design
description: 当 architect 拿到低精度训练需求、要产出「一组」可实验方案时加载——讲清怎么判架构与显存、一次产出 3-6 个（含至少一个组合方案）带自变量与依据的候选、怎么把自变量写进 design.md 的受控 YAML 块。不用于审代码或跑实验；单因子严格推导与逐题配对在这里是明确禁止的做法。
version: 1.0.0
applies_to: [architect]
---

# 方案设计（`scheme-design`）

## 0. 什么时候用 / 什么时候不用

- **用**：收到任务需求，要**从零或换方向**产出一组候选方案（流水线入口）。
- **不用**：执行层面的问题（改代码 → `code-change`；跑不动 → `run-observation`；扫参 → `autotune`）；审代码；写结论。
- **明确禁止**：单因子严格推导、逐题配对（一轮只动一个因子）。要找的是**一组**候选（含组合方案），不是一条推导链。

## 1. 开工前要读的文件（路径 + 字段名）

| 读什么 | 取哪些字段 | 为什么 |
|---|---|---|
| `config/tasks/<任务名>.yaml` | `model.{name,precision,source}`、`train.{framework_repo,monitor_metrics}`、`eval.{task_type,datasets,protocol}`、`artifacts.root`、`knowledge.external.{sources,keywords}`、`loop.*` | 定场景（①）；你不知道模型名/任务名写在哪，就不可能设计对 |
| **框架代码**（只读） | 旋钮名、取值域、生效点（`file:line`） | 自变量**只能从框架里读出来**（0.18.0 起没有字典）；每个旋钮在正文写清依据 |
| `knowledge/INDEX.md` → `knowledge/models/<模型名>.yaml` | `arch.*`、`memory.*`、`quant_notes.*` | 判架构类型与算显存预算 |
| `knowledge/techniques/*.yaml`、`records/conclusions/*.yaml`、`records/best/*.yaml` | `technique`、`evidence.result`、`status`、`numbers_ref` | 别重试已知的坑；沿用已成立的技术方案 |
| `knowledge/frameworks/*.md` | 能力、限制、关键 `file:line` | 判「这个自变量框架能不能表达」 |
| `knowledge/external/*.md` ＋ 本轮 intent 的 `external` | 已知做法、**已知失败模式**（按 `INDEX.md` 那行的主题词 grep）；intent 里给了关键字就用 `web_search` 搜、`sources` 用 `web_fetch` 读 | **候选来源**：出候选时先看外面有没有人做过、通常怎么失败；两者都只到候选为止（`design.md` §2 留痕） |
| 上一轮 `<轮次>/report.md`（若有） | 判定段 `outcome` ＋ 结论指针 | 反馈环的输入 |

## 2. 步骤（每步带判据）

1. **判架构与显存预算**：先按模型档定架构类型（dense/MoE/MLA/GQA），再算五块显存分项。
   *判据*：每块显存有算式与锚点配置（并行度、序列长度、微批），不是一句「应该能跑」；算不出的项标 `unknown` 并写清缺哪份材料。
2. **定候选组**：3–6 个候选，**至少一个组合方案**（两个及以上自变量叠加）；每个候选在 `design.md` 里一块受控 YAML。
   *判据*：候选之间在**自变量维度**上可区分；每个候选都能说清「它与其它候选的差别是哪一行」。
3. **写受控块**：块内只放 `schema`/`id`/`axis`/`question_ref`/`rank`/`strength_target`/`supersedes`/`variables`/`implementation`。
   `variables.<名>` 必须同时有 `value` 与 `requires_code`；`implementation` 按 `requires_code` 决定 `{mode: framework_native}` 或给 `patch`。
   *判据*：`python3 runtime/validate_round.py <轮次>/design.md` 退出 `0`（每轮必跑的门）；开发期自检用 `devtools/validate_design.py`（**同一份规则**）。
4. **写依据与排序**：依据、假设、排序理由写在 `design.md` **正文**（块外）；块里**不许**出现依据/假设/阈值/判据（规则 6）。
   *判据*：正文的排序理由与块里的 `rank` 一一对应。
5. **写判据并冻结**：`<轮次>/criterion.yaml`（`success.*`／`falsification`／`budget.*`／`eval_protocol.*`）。
   **`stop_conditions.*` 不写进判据**：0.18.18 起唯一落点是任务配置，早停阈值与墙钟由引擎直接读。
   *判据*：`eval_protocol.*` 与任务配置 `eval.protocol.*` **逐项一致**；跑前冻结，跑后一字不改。

## 3. 模板与命令（可直接复制）

````markdown
<!-- LP-SCHEME-BEGIN -->
```yaml
schema: 1
id: <方案名>                      # 同一轮内唯一
axis: <受控轴名>                  # 受控轴名；取值一律现场取证（0.18.0 起无旋钮字典）
question_ref: <本份 criterion.yaml 的 id>
rank: 1
strength_target: <一句话自由文本>   # 或 null；**不是档位枚举**，内容不参与机器判定
supersedes: null
variables:                        # 键名与取值由你读框架判定；正文里要写清各自的 file:line 依据
  <变量名>: {value: <取值>, requires_code: false}
implementation: {mode: framework_native}
```
<!-- LP-SCHEME-END -->
````

```bash
python3 runtime/validate_round.py <轮次>/design.md        # 每轮必跑的门（退出 2 ⇒ 拒绝开跑）
python3 devtools/validate_design.py <轮次>/design.md      # 开发期自检，同一份规则
```

## 4. gotchas（每条：症状 → 正确动作）

1. **把「怎么实现」写进 `variables:`** → 症状：下一轮照着错的变量复现。正确动作：实现手段进 `implementation:` 与 `<轮次>/patches/`。
2. **把阈值写进 design 块** → 症状：执行器读不到早停阈值。正确动作：阈值只写在任务配置 `stop_conditions.*`。
3. **临时发明旋钮名** → 症状：起训练时参数不认识／环境变量无人读，跑到一半才炸。正确动作：先读框架确认这条轴存在，再写进方案。
4. **`requires_code: true` 却给不出 patch** → 症状：门规则 11 报错、该方案不可执行。正确动作：要么给出 `implementation.patch[].ref`（文件必须真实存在），要么把该取值改成 `false`。
5. **一轮只动一个因子** → 症状：多轮累计仍无信号、找不到方向。正确动作：产出**一组**候选（含组合）。
6. **把未验证的外部线索当自变量** → 症状：判据说不清怎么算成立。正确动作：外部线索只进 `design.md` 正文引用小节，`knowledge/external/` 永不进判定。

## 5. 校验回路（自查「我真的做对了」）

- 块数量 1–6、标记成对不嵌套、每块恰好 1 个 ```yaml、必需键齐全、`id` 唯一。
- `variables` 每个键都能指向框架里的一处 `file:line`，且每个写出来的变量都有 `value` ＋ `requires_code`。
- 有 `requires_code: true` ⇒ `patch` 至少 1 条，且 `ref` 指向的文件真实存在。
- `criterion.yaml` 与任务配置的口径一致；两个文件的 `id`／`question_ref` 对得上。
- 最后跑一次门：`python3 runtime/validate_round.py <轮次>/design.md` 退出 `0`。

## 6. 参考

- 本工程：`templates/design.md`（受控块格式）、`docs/CONFIG.md` §6（旋钮：0.18.0 起没有字典，真相在框架代码里）。
- `skills/local-knowledge/SKILL.md`（怎么取证）、`skills/knowledge-curation/SKILL.md`（怎么把经验写回）。
- `references/scheme-playbook.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①架构类型判定清单（dense／MoE／MLA／GQA 怎么判 ＋ 对量化的含义）
  ②显存五块预算的算式模板与两条判据式写法 ③候选组拆解（3–6 个、含组合、组合理由与「成了怎么拆开归因」写正文）
  ④多源取证（至少 3 源）与冲突裁决 ⑤落点复核表。
- 未定的缺口（**不许自创，故留 TODO**）：`TODO(P3)` 显存五块的**系数表**（各 dtype 的 bytes/param、优化器状态数、
  激活折算）在**本工程里没有预设系数** —— 本 skill **不写死系数**，一律现场取证并带 `source`；
  `knowledge/models/<模型名>.yaml` 的 `arch.*`／`memory.*` 键结构**已随 P6 定稿**（`knowledge/README.md` §2，
  本工程 P6 又在 `arch` 里补了 4 个键 ⇒ **键结构可当契约引用**；但**数值**仍须逐个现场核实并带 `source`，
  `null` 就是 `null`，不许被下游升级成「已现场核实」）。
