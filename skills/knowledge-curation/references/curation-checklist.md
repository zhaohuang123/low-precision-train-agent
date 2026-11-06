# `knowledge-curation` 深化材料：价值判定 / 四类实例 / 自查清单

> 本文件是 `skills/knowledge-curation/SKILL.md` 的**渐进披露层**：正文只留入口一句话，长内容在这里。
> 本工程内的权威落点：`knowledge/README.md`（**格式唯一来源**）。
> 纪律：本文件**不复制格式**，只给「值得写吗 / 写哪类 / 怎么自查」；字段以 `knowledge/README.md` 为准。

## 1. 值不值得记：一个问题 + 一份不记清单

**一个问题**：**下一轮的人拿这条能少走哪一步？** —— 说不出来就别写。

**不记**（「不记什么」）：环境故障｜口径没跑全的轮次｜纯配置改动｜一次性的实验垃圾。

**要记**：能改变下一轮动作的事实 —— 某组自变量成立／不成立、某条轴在本预算下不可分辨、某类结构框架表达不了。

## 2. 四类分流实例（判据 ＋ 反例）

| 类 | 记什么 | 准入/判据 | 反例（别放这里） |
|---|---|---|---|
| `knowledge/techniques/` | 本轮实验的**技术方案**：一组自变量 ＋ 本地实测结果 | 评估跑完、结论入库，且值得下一轮参考 | 环境故障、口径没跑全 |
| `knowledge/models/` | 模型结构（`arch.*`／`memory.*`／`quant_notes.*`） | 数值必须**现场读模型配置**；过期就改，**不许留两版** | 抄来的数值、两版并存 |
| `knowledge/frameworks/` | ① 跨多轮复用、**已证明稳定**的公共 patch；② 带 `file:line` 的扫描理解笔记 | patch 可复用；笔记必须有 `file:line` | **单轮私有 patch**（它留 `<轮次>/patches/`） |
| `knowledge/external/` | **外部来源**（外面怎么做、通常怎么失败；**未在本工程验证**） | 准入：URL ＋ 抓取日期 ＋ 摘要 ＋ 怎么验；**可作候选来源、永不进判定**；验证过的写 `techniques/` | 任何判定、任何数字路径 |

**判据**：**一个事实只有一个落点** —— 同一内容不在 yaml 与 md 各写一份、不在两处各维护一份。

## 3. 多轮验证同一方案：只记一条

在既有条目的 `evidence.rounds` 里**追加**轮次，`result` 取最新一次为准；**不要**每轮建新文件。
**判据**：`grep -l '<方案关键词>' knowledge/techniques/` 只命中一条。
`TODO(P3)`：多轮累计到什么程度才能写「已成立」需要一份可机械核对的规则；现只有定性口径「累计到足够轮次、结论才稳时」
（§13.3 ①），**没有给条数** ⇒ 本 skill 不发明阈值，一律以「有 `records/conclusions/` 对应结论 ＋ `numbers_ref` 存在」为下限。

## 4. 成功与失败都记

失败条目 `status: rejected` ＋ `why_failed`：**一句话、可机械核对** —— 哪个阈值、第几步、什么数值。
**判据**：失败条目要能让下一轮的人直接判「这条不用再试」；写「效果不好」不算。

## 5. 数字只引不抄

条目里写 `numbers_ref` 指到 `<artifacts.root>/rounds/<轮次>/metrics.json`；`patch_ref` 指向本轮 patch 与/或公共 patch。
**判据**：条目里**没有裸数字**；`numbers_ref` 路径真实存在。

追加优先：能追加就不覆盖；确实要覆盖（如 `status`），覆盖前后都要能在 `records/ledger.jsonl` 里查到。

## 6. 四类的必填字段（形状；权威版本在 `knowledge/README.md`）

- `techniques/`：`schema`／`id`／`title`／`axis`／`status`／`technique`／`hypothesis`／
  `evidence.{rounds,conclusions,result,numbers_ref}`／`patch_ref`／`notes`（失败时 `status: rejected` ＋ `why_failed`）。
- `models/`：`one_liner`／`arch.*`（每值带 `source`）／`weights.local_path`／`quant_notes.*`／`memory.{per_card_blocks,anchors}`／`notes`。
- `frameworks/`：公共 patch 直接是 `.patch` 文件；扫描笔记是 `.md` 且**必须带 `file:line`**。
- `external/`：`.md`，一节一来源，首段写明 URL／抓取日期／摘要／**怎么验**／`永不进判定`（骨架见 `knowledge/external/_README.md`）。

**字段校验靠自查**：出厂包里没有 `devtools/`，没有脚本可跑 —— 本清单就是判据；逐项对完再写 `INDEX.md`。
「字段齐不齐」**先按本清单人工逐项核、再跑 lint 复核** —— 人工核是复核，不是替代。

## 7. 写完自查清单

- [ ] 新条目落在四类之一，且与既有条目**不重复**（同一方案只追加轮次，不新建）
- [ ] 必填字段齐（按 `knowledge/README.md`）、`numbers_ref` 真实存在、无裸数字
- [ ] 成功/失败都记；失败带 `why_failed`（哪个阈值、第几步、什么数值）
- [ ] 追加优先；覆盖有据（`records/ledger.jsonl` 可查）
- [ ] 入口对齐：`knowledge/INDEX.md` 的「已登记条目」列已更新
- [ ] 身份唯一：`axis` ＋ `technique` 相同的条目只有一个文件（自己核；出厂包不含校验脚本，所以这一项就是判据）

## 8. 写回动作的前置（P6 之后）

- **格式已定稿（P6，2026-10-24）**：`knowledge/README.md` 是四类格式的唯一来源，
  **角色可以按它新建/追加知识条目** —— 没有「格式未定稿不许落盘」这条禁令了
  （那是 P6 之前的占位规定，已随 `knowledge/README.md` 定稿失效）。仍受准入约束：没到准入就不建、没有内容就不建空文件。
- **lint 已实现（P8，2026-10-24）**：写回后的机械校验现在**跑得了**（见 §6）；人工逐项核 §6 清单是复核。
