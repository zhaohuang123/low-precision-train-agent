---
name: knowledge-curation
description: 当 architect 拿到 EXPERIMENT_DONE 反馈、要把这一轮的经验写回 knowledge/ 时加载——讲清什么时候该写、写哪一类（techniques/models/frameworks/external）、同一技术方案多轮验证怎么只记一条、失败条目怎么写、写完怎么自查。不复制 knowledge/README.md 的格式，只指向它。
version: 1.0.0
applies_to: [architect]
---

# 知识写回（`knowledge-curation`）

## 0. 什么时候用 / 什么时候不用

- **用**：收到 `EXPERIMENT_DONE` 后，判「这轮有没有记录价值」并写回；或推翻/更正旧条目。
- **不用**：出方案（`scheme-design`）；检索取证（`local-knowledge`）。
- **格式的唯一来源是 `knowledge/README.md`** —— 本 skill 只讲「什么时候写、写哪类、怎么自查」，**不复制格式**。

## 1. 开工前要读的文件（路径 + 字段名）

| 读什么 | 取哪些字段 | 为什么 |
|---|---|---|
| `<轮次>/report.md` | 判定段 `outcome`、结论指针 | 决定「值不值得记」 |
| `records/conclusions/*.yaml`（append-only） | `outcome`、`numbers_ref` | 结论是知识的证据来源 |
| `records/best/*.yaml` | 当前最优 | 写 `techniques` 时要与最优对齐 |
| 既有 `knowledge/techniques/*.yaml` | `technique`、`axis`、`evidence.rounds`、`status` | 判「这是新条目还是追加轮次」 |
| `knowledge/README.md` | 四类的必填字段与写作指导 | **格式唯一来源** |
| `knowledge/INDEX.md` | 落点索引 | 写完要更新入口 |

## 2. 步骤（每步带判据）

1. **判有没有记录价值**（含多轮累计价值）。
   *判据*：能说出「下一轮的人拿这条能少走哪一步」；说不出来就别写（环境故障、口径没跑全的轮次、纯配置改动、一次性垃圾**都不记**）。
2. **分流到四类中的一类**：
   - `knowledge/techniques/` = 本轮实验的**技术方案**（自变量 ＋ 结果 ＋ 指向 `metrics.json`）；
   - `knowledge/models/` = 模型结构变化（数值须来自现场读模型配置；过期就改，不许留两版）；
   - `knowledge/frameworks/` = ① 跨多轮复用、已证明稳定的**公共 patch**；② 带 `file:line` 的**扫描理解笔记**（单轮私有改动**不放这里**）；
   - `knowledge/external/` = **外部来源**（外面怎么做、通常怎么失败；**没在本工程验证**）。准入：URL ＋ 抓取日期 ＋
     摘要 ＋ 怎么验；**可作候选来源，永不进判定**。本地验证有效的技术方案写进 `techniques/`，**不要写这里**。
   *判据*：**一个事实只有一个落点**；同一内容不在 yaml 与 md 各写一份。
3. **同一技术方案多轮验证：只记一条（改既有条，不新建文件）**。
   **身份判定（不看文件名、不看标题、不看轮次）**：`axis` 相同 **且** `technique` 键值集合完全相同 ⇒ **同一条**。
   找它的命令（按轴名收窄，再比对 `technique:` 块）：
   ```bash
   grep -l '^axis: "<轴名>"' knowledge/techniques/*.yaml
   grep -A6 '^technique:' knowledge/techniques/*.yaml
   ```
   **命中旧条 ⇒ 只改这一处**：`evidence.rounds` 追加本轮、`evidence.conclusions` 追加本轮结论、
   `evidence.result`／`status` 取最新一轮、`numbers_ref` 换成本轮的 `metrics.json`、`patch_ref` 合并去重。
   **判据**：`grep -l '^axis: "<轴名>"' knowledge/techniques/*.yaml` 里与本轮同 `technique` 的文件**恰好一个**。
   - **身份字段不许动**：`id`、`axis`、`technique` 一旦写下就是这条的身份（笔误更正要在 `notes` 记一行）。
     方案取值变了（例如 4-bit 改 3-bit、或换了轴名）＝ **新方案、新建一条** —— 别把两条不同方案揉进一个文件的 `rounds`。
     判据：改 `technique` 里的任何值之前先自问「这还是同一个方案吗」；不是就新开一条。
   - **翻盘要留痕**：`status` 从 `adopted` 变 `rejected`（或反过来）时，`notes` 必须写清「哪一轮、为什么翻」——
     `status` 只是个枚举，不留痕等于静默改判。判据：只看 `notes` 就能复述翻转理由。
4. **成功与失败都记**：失败条目 `status: rejected` ＋ `why_failed`（一句话、可机械核对：哪个阈值、第几步、什么数值）。
   *判据*：失败条目能被下一轮直接判「这条不用再试」。
5. **数字只引不抄**：条目里写 `numbers_ref` 指到 `<artifacts.root>/rounds/<轮次>/metrics.json`；`patch_ref` 指向本轮 patch 与/或公共 patch。
   *判据*：条目里没有裸数字；`numbers_ref` 路径真实存在。
6. **写完自查并更新入口**：`docs`/`INDEX.md` 与新条目对齐；再按 `references/curation-checklist.md` §6
   *判据*：清单逐项都是「是」；追加式写入（能追加就不覆盖），覆盖前后都能在 `records/ledger.jsonl` 里查到。

## 3. 写作骨架（字段名以 `knowledge/README.md` 为准；这里只给最小形状）

```yaml
schema: 1
id: <技术方案名>
title: "<一句话：这条技术做了什么>"
axis: "<受控轴名>"
status: adopted | rejected
technique: {<自变量字段>: "<值>"}
hypothesis: <机制解释；不写「应该能提升」>
evidence:
  rounds: [R-0001]              # 多轮验证只记一条，轮次在这里追加
  conclusions: [C-0001]
  result: adopt | reject
  numbers_ref: <artifacts.root>/rounds/R-0001/metrics.json
patch_ref: [<轮次>/patches/0001-<简述>.patch, knowledge/frameworks/patches/<公共简述>.patch]
notes: 适用边界与注意事项。失败时 status: rejected 并写 why_failed。
```

## 4. gotchas（症状 → 正确动作）

1. **每轮新建一个同类条目** → 症状：同一件事多处不一致。正确动作：只记一条，追加 `evidence.rounds`。
2. **只记成功** → 症状：下一轮重试同一个坑。正确动作：`status: rejected` ＋ `why_failed`。
3. **裸数字** → 症状：产物一变条目就假。正确动作：`numbers_ref`。
4. **把单轮私有 patch 放进 `knowledge/frameworks/patches/`** → 症状：把一次性改动当成稳定复用件。正确动作：单轮改动留 `<轮次>/patches/`；只有跨多轮复用、已证明稳定的才进知识库。
5. **把本地验证过的技术方案写进 `knowledge/external/`** → 症状：验证过的东西混进"外部来源"，下一个人分不清哪条信得过。正确动作：验证过的写 `knowledge/techniques/`（要 `numbers_ref`）；`external/` 只放**没验证**的外部来源。

## 5. 校验回路（自查「我真的做对了」）

- 新条目落在四类之一，且与既有条目**不重复**。
- 每条都有必填字段、`numbers_ref`、可机械核对的成立/不成立条件。
- 追加优先；覆盖有据（`records/ledger.jsonl` 可查）。
  - 必填字段齐、`id` 唯一、同 `axis` ＋ 同 `technique` 只有一个文件（自己核）。

## 6. 参考

- `knowledge/README.md`（**格式唯一来源**）、`knowledge/INDEX.md`。
- `skills/local-knowledge/SKILL.md`（取证）。
- `references/curation-checklist.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①价值判定（一个问题：**下一轮的人拿这条能少走哪一步**）＋「不记」四类
  ②四类分流实例与反例 ③同一方案多轮验证只记一条 ④失败条目写法（哪个阈值、第几步、什么数值）
  ⑤数字只引不抄 ⑥四类的必填字段形状（权威版本在 `knowledge/README.md`）⑦写完自查清单。
- **格式已定稿（P6，2026-10-24）**：`knowledge/README.md` 现在就是四类格式的权威版本，
  **角色可以按它新建/追加知识条目**（准入与「同一方案多轮只记一条」照 §1／§3 执行）——
  P6 之前那句「格式未定稿前不许按本文件新建知识条目」是**占位规定，已随 P6 定稿失效**，不再是禁令。
  仍要守的：没到准入就别建条目、没有内容就不建空文件。
  - **字段校验靠自查**：出厂包不含 `devtools/`，没有脚本可跑；按 `knowledge/README.md` §1 的必填字段与
    身份规则逐条对（清单 `references/curation-checklist.md`），对完再写 `INDEX.md`。
  人工逐项核（清单见 `references/curation-checklist.md` §6）是**复核**，不是替代。
