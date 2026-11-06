---
name: local-knowledge
description: 当任何角色需要从本工程知识库取证时加载——讲清 knowledge/ 四类内容各自的可信度与用途、INDEX.md 怎么用、records/conclusions 与 records/best 怎么查，以及 knowledge/external/ 为什么永不进判定。写方案前、判框架支持性前、写结论前都该先过一遍。
version: 1.0.0
applies_to: [architect, developer, tester, experimenter]
---

# 本地知识库取证（`local-knowledge`）

## 0. 什么时候用 / 什么时候不用

- **用**：写方案前（找方向）、判框架支持性前（查 `file:line`）、写结论前（对照历史）。
- **不用**：写回知识（那是 `knowledge-curation`）；把外部知识当判定依据（**永远不行**）。
- **一句话**：**知识是「经验」，不是「事实契约」**；契约在 `config/`（只读）。

## 1. 四类内容各自的可信度与用途

| 落点 | 是什么 | 可信度 | 你怎么用它 |
|---|---|---|---|
| `knowledge/techniques/*.yaml`（不够写就 `.md`） | 一个**可复用的技术方案**：一组自变量 ＋ 本工程实测结果（`status`／`evidence.rounds`／`result`／`why_failed`／`numbers_ref`） | 中—高（有本地实测；多轮验证更稳） | 出方案时先查：别重试已 `rejected` 的坑；`adopted` 的可作为候选基础 |
| `knowledge/models/<模型名>.yaml` | 模型结构（`arch.*`／`memory.*`／`quant_notes.*`） | 高（数值须来自现场读模型配置） | 判架构类型、算显存预算；数值过期就改，**不许留两版** |
| `knowledge/frameworks/` | ① `patches/*.patch`：**跨多轮复用、已证明稳定**的公共 patch；② `<框架>-<主题>.md`：能力、限制、关键 `file:line`、「改哪里能达成什么」 | 高（须带 `file:line`） | 判框架能否表达方案时的第一手扫描结论 |
| `knowledge/external/*.md` | **外部来源**：外面怎么做、通常怎么失败（**未在本工程验证**）。准入：URL ＋ 抓取日期 ＋ 摘要 ＋ 怎么验 ＋ `永不进判定`。**作候选来源**，不作依据 | 低（未验证） |；**另一条入口**：本轮 intent 的 `external.keywords` 用 `web_search` 搜、`sources` 用 `web_fetch` 读（命中不落盘，只在 `design.md` §2.2 留痕） |

## 2. 步骤（每步带判据）

1. **先读入口**：`knowledge/INDEX.md` 找落点，再读 `knowledge/README.md` 的四类写作指导。
   *判据*：你知道要查的四类各在哪，不靠 `find` 乱翻。
2. **按「一个事实只有一个落点」查**：先查 `techniques/`（有没有做过同样的自变量组）、再查 `records/conclusions/`（结论档案）与 `records/best/`（当前最优）。
   *判据*：能说出「这个方向上一轮的结果是什么、为什么失败」；查不到也要写明「未命中」。
3. **交叉核对数字**：知识条目里的数字必须写 `numbers_ref` 指到 `<artifacts.root>/rounds/<轮次>/metrics.json`。
   *判据*：条目里没有**裸数字**；有裸数字的条目**不可作为依据**（可提请修正）。
4. **区分可信度并写下取证结论**：`knowledge/`（经验）与 `records/`（本工程结论）支持推断；`knowledge/external/` 只能提示方向。
   *判据*：写方案/写结论时，**能逐条指出每条依据来自哪一类**；引用外部线索处注明「未验证」。
5. **不改只读项**：`config/task.schema.json` 是契约，不是知识；旋钮的真相在框架代码里，知识库只记经验。
   *判据*：你没有改动契约、也没有把契约内容抄进知识条目。

## 3. 检索命令（可直接复制）

```bash
# ① 入口与四类写作指导
sed -n '1,80p' knowledge/INDEX.md; sed -n '1,120p' knowledge/README.md
# ② 同类技术方案（按轴名/关键词）
grep -rln "axis:" knowledge/techniques/ | xargs grep -ln "<关键词>"
# ③ 历史结论与最优
ls records/conclusions/ records/best/ 2>/dev/null
grep -rn "outcome" records/conclusions/*.yaml 2>/dev/null | head
# ④ 框架能力（带 file:line）
grep -rn "<能力关键词>" knowledge/frameworks/*.md
```

## 4. gotchas（症状 → 正确动作）

1. **拿 `knowledge/external/` 当依据** → 症状：判据说不清怎么算成立。正确动作：外部来源**可以**产生候选，但判据只用本地实测与冻结判据（它永不进判定）。
2. **引用裸数字** → 症状：改了产物后知识条目变假。正确动作：只写 `numbers_ref`，数字留在 `metrics.json`。
3. **同一技术方案每轮建一个新文件** → 症状：同一件事多处各写一份。正确动作：只记一条，轮次追加进 `evidence.rounds`。
4. **只记成功、不记失败** → 症状：下一轮重试同一个坑。正确动作：失败条目 `status: rejected` ＋ `why_failed`（哪个阈值、第几步、什么数值）。
5. **查了知识库但没写「未命中」** → 症状：别人以为你查过。正确动作：写明查了哪几类、命中什么、未命中什么。

## 5. 校验回路（自查「我真的做对了」）

- 每条依据都能指出落点类别与文件路径。
- 引用数字处都带 `numbers_ref`；没有裸数字。
- 没有把 `knowledge/` 的内容当成契约，也没有改动 `config/` 契约。
- `knowledge/external/` 没有进入任何判据/数字路径。

## 6. 参考

- `knowledge/README.md`（格式的唯一来源）、`knowledge/INDEX.md`。
- `skills/knowledge-curation/SKILL.md`（写回）、`skills/scheme-design/SKILL.md`（用知识出方案）。
- `references/retrieval-playbook.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①检索顺序（`records/best` → `techniques` → `models` → `frameworks` → `conclusions` → `external`）
  ②冲突裁决（实测 > 文档；框架代码 > 经验）③可信度分级细则（每类「能支撑什么／不能支撑什么」）
  ④按轴/关键词/模型/能力的检索命令 ⑤`knowledge/external/` 永不进判定的两条理由与「一条链」用法 ⑥五条禁令。
  - **现状（0.19.2）**：`knowledge/models/` **三份**模型档已登记（格式见 `knowledge/README.md`，
    逐条见 `knowledge/INDEX.md`）；`knowledge/external/` 有 **10 篇外部来源**（未验证、可作候选）；
    `techniques/` 仍为 **0 条** —— 不是「还没建」，是**准入不满足**（要求「评估跑完、结论入库」）。
    ⇒ 按类判命中：`models/` 与 `external/` 可命中（`external/` 只作候选来源），`techniques/` **必然「未命中」**；
    取证结论里要写明「该类尚无满足准入的条目」，再转去 `records/` 与 `config/` 取事实。
