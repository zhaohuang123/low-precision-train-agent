# `report-and-conclusion` 深化材料：判定段实例 / 判定段的三条硬边界 / 结论档案字段

> 本文件是 `skills/report-and-conclusion/SKILL.md` 的**渐进披露层**：正文只留入口一句话，长内容在这里。
> 本工程内的权威落点：`templates/criterion.yaml`／`records/conclusions/_EXAMPLE.yaml`／`templates/report.md`
> 纪律：**判断是你的，数字不是** —— 数字只引用 `<轮次>/metrics.json`，判定只对照跑前冻结的 `criterion.yaml`。

## 1. 结论档案字段清单（以 `records/conclusions/_EXAMPLE.yaml` 为准）

| 段 | 字段 | 说明 |
|---|---|---|
| 身份 | `schema`／`id`／`round`／`task_id`／`scheme_id` | `id` 形如 `C-<序号>`；append-only，序号不重复 |
| 判据指针 | `criterion_ref` | `<轮次>/criterion.yaml#id=<判据 id>` |
| 数字 | `metric.{name,value,baseline,delta}` ＋ `numbers_ref` | **只引用**；`numbers_ref` 指向 `<轮次>/metrics.json` |
| 判定依据 | `success_check.{require,satisfied}`／`falsification_hit`／`why_failed` | `require` 抄冻结判据原文；口径没跑全 ⇒ `satisfied: null` ＋ 理由 |
| 产物指针 | `artifacts.{round_dir,report,evidence}` | 引用路径，不搬内容 |
| 框架 | `framework.{repo,head,restored}` | 还原校验结果必须为 `true` |
| 收尾 | `best_updated`／`created_at`／`notes` | `best_updated` 记是否更新了 `records/best/<任务名>__<指标>.yaml` |

**判据**：每个数字都能在 `numbers_ref` 指名的那份 `metrics.json` 里找到对应字段；失败结论里必须有
「哪个阈值、第几步、什么数值」（`why_failed`，`outcome: reject` 时必填）。

> **已定稿（P9）**：结论档案的字段集**就是本表列出的这些** —— 锚点是 `records/conclusions/_EXAMPLE.yaml`；
> 第一条真实档案按它落盘。要加字段先改样例（格式的唯一锚点），再改档案；**不许**在档案里自创新字段。

## 2. 判定段怎么写（逐条对账，不写形容词）

```markdown
## 2. 判定段（对照跑前冻结的 <轮次>/criterion.yaml）
- outcome: adopt | reject | inconclusive
- 一句话理由：<对着哪条冻结条件（字段名）、为什么>
- 证据指针：`metrics.json` 的 `<字段>` ＋ `<轮次>/evidence/<文件>`
- 对账 1：`success.require` = "<原文>"  vs  `metrics.json` 的 `<字段>` = <值>  ⇒ 满足 / 不满足
- 对账 2：`falsification` = "<原文>"  ⇒ 命中 / 未命中
- strength_target（从 `design.md` 照抄，自由文本或 null）：<原文>
- 污染检查：口径是否逐项一致 / 训练是否发散 / 转换是否真生效
```

**判据**：结论只给 **`outcome` ＋ 一句话理由 ＋ 证据指针**；对账时每条都写明**对应判据字段名**与
**`metrics.json` 字段名**。只有「提升明显／略有下降」这类形容词 = 不合格（「明显」没有定义，下一轮无法复用）。

## 3. 判定段：三条硬边界（**没有"质量档位"这回事**）

★ 本工程**不设档位**：结论 = `outcome` ＋ 一句话理由 ＋ 证据指针。`strength_target` 只是方案作者写的一句
**自由文本**（也可写 `null`），**没有机器判据、不参与判定**（曾经那套 `L1|L2|L3` 枚举已按"减法"删掉：
枚举会把一句话变成一道必须过的机器闸，而它本来只是一句话）。三条硬边界照旧：

1. **判定只对照跑前冻结的 `criterion.yaml`**：`success.require` 是否满足、`falsification` 是否命中 ——
   不新增字段、不事后改判据（要改 ⇒ 新写一份并用 `supersedes:` 指向旧份）。
2. **判不了 ≠ 判了但落在波动内**：前者先补齐证据（`inconclusive`），后者也要把"波动"的事实与证据指针写明；
   两者在报告里分开说。
3. **沉没成本不是证据**：绝不因为「这轮花了很多卡」就把 `inconclusive` 写成 `adopt`；
   把 `inconclusive` 写成「趋势向好」是最坏的一种失败。

**已闭合（P4 ＋ P4c）**：抽数器 `runtime/metrics.py` 已落地（P4）；判据口径一致性检查在 P4c 由
任务目录的闸门承担 —— `commands/eval_protocol_gate.sh`（判据 `eval_protocol.*` ↔ 任务配置 `eval.*` 逐项比对，
不一致 ⇒ 退出 `6`，**不出数字**）。`runtime/metrics.py` **只抽数、不判定**，不替方案增设字段。

## 4. 三种去向与硬边界

| 去向 | 条件 | 必须落盘 |
|---|---|---|
| `EXPERIMENT_DONE` ＋ `outcome: adopt` | 达到冻结的成功条件 | 结论档案 ＋ 更新 `best/`（若有新判定/新证据） |
| `EXPERIMENT_DONE` ＋ `outcome: reject` | 不达标，或数字好看但被污染（口径不一致、训练发散） | 结论档案（**失败也入库**） |
| `EXPERIMENT_INVALID` | 训练侧无效（`5`）或评测侧无效（`6`）；无效轮次**不产生精度结论** | 失败证据 ＋ 触发阈值与步数 ＋ **重跑要改什么** |

- **停止轮次**（`early_stop.kind == "converged"`）**不是** `EXPERIMENT_INVALID`：它按正常三去向判，
  只是报告要写「停在第 N 步」并把训练侧 loss 的跨轮比较剔掉（依据：`templates/report.md` §2、执行器退 `0`）。
- 达标但**证据撑不住**「本轮结论成立」⇒ **不是 adopt**，按 `inconclusive` 交，并写明缺哪一条事实、缺多少证据。
- **判不了**（证据不齐）与**判了但落在波动内**是两件事，报告里分开说；前者先补齐证据。
- **绝不因为「这轮花了很多卡」就把 `inconclusive` 写成 `adopt`**（沉没成本不是证据）；
  把 `inconclusive` 写成「趋势向好」是最坏的一种失败。

## 5. `records/best/` 什么时候更新

只有**新判定或新证据**才覆盖 `records/best/<任务名>__<指标>.yaml`；**不同口径的指标不许互相覆盖**
（口径不同的分文件放）。`inconclusive` 永远不更新 `best/`（波动内的最好成绩不是最好，是运气）。
覆盖前后都要能在 `records/ledger.jsonl` 里查到。

### 5.1 文件里**必须有的字段**（0.19.0 起有机器读者）

这份 yaml 不再只是档案：`runtime/metrics.py` 与 `runtime/executor.py` 会读它来决定
**本轮验证集的参照是谁**（held-out racing）。最小字段集（多写不限，少的这几项必须齐）：

```yaml
cell: <任务名>                 # 与文件名前缀一致，撞号时用于消歧
metric: <指标名>               # 与文件名后缀一致
value: <数字>                  # 该指标在那一轮的值（引用 metrics.json，不重算）
round: R-0007                  # ★ 参照轮次 id —— **racing 就靠这一个字段**
numbers_ref: records/rounds/<任务名>/R-0007/metrics.json   # 数字出处
updated_at: 2026-01-01T00:00:00+08:00
```

- **`round:` 缺失或不是 `R-\d{3,}` 形态 ⇒ racing 不判**（记 `holdout.baseline.reason`，不报错）。
- **同一个任务有多份 best 档案 ⇒ 不判**：不同指标的档案口径不同，合成一个参照就是拿两把
  尺子当一把。要参照就用"当前唯一那把尺子"的档案。
- 那一轮**必须在 `metrics.json` 里带验证曲线**（`holdout.valid.curve`，或至少
  `evidence/valid.txt`）。历史轮次大多 `--split 100,0,0` ⇒ 没有验证点 ⇒ 照不到，也就不能当参照。

## 6. 收口与留痕

```bash
python3 runtime/state.py close --conclusion C-<序号> --outcome <adopt|reject|inconclusive>
```

**判据**：`state/rounds.jsonl` 本轮**恰好追加一行**，其中 `metric.*` 与 `metrics.json` **一致（引用，不重算）**；
`state/` 只由 `runtime/state.py` 写（两个写者＝状态不可信）。

## 7. 缺口

- **没有"档位机器判据"这个缺口了**（按"减法"消掉）：本工程不设档位 —— 结论只给 `outcome` ＋ 一句话理由 ＋
  证据指针；`strength_target` 是自由文本（或 `null`），没有机器判据、不参与判定。
- 结论档案字段集：**已定稿（P9）**，见 §1（锚点 `records/conclusions/_EXAMPLE.yaml`）。
- 工具落地现况：`runtime/metrics.py` **已实现（P4）**、`runtime/state.py` **已实现（P7）**（`init`／`advance`／`close`）。
  因此本文件提到的抽数与收口命令现在**跑得了**；`devtools/lint_knowledge.py` 也已实现（P8，退出 `0` 才算过），
  本工程 `devtools/` 八件里**没有**占位工具了。
  `runtime/` 其余件（`executor.py`／`resources.py`／`_common.sh` ＋ 任务目录）**P4c 已落地**；
  **P4d 已把 `TODO(P4d)`（字典读取器搬家）／`TODO(P4e)`（`scaffold/README.md` 坑清单逐条搬运）收口**，
  并把任务目录三段命令接成**真命令形状**（`commands/*_cmd.sh` ＋ `drivers/lm_eval_driver.py`）——
  ★ 但那些真命令**本工程从未执行过**（验证只用 `--dry-run`／`--print`／`bash -n`／拼装结果比对）。
