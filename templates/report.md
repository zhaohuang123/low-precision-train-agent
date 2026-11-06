<!-- templates/report.md —— experimenter 的本轮报告骨架（照抄到 <轮次>/report.md 再改） -->
<!-- 规则：人读；**唯一**的判定落点（废除裁决角色后判定整条上移到 experimenter）。
     数字纪律：报告里**每个数字只能引用** <轮次>/metrics.json，不许重算、不许四舍五入、不许手改。 -->
# <轮次> 报告 —— <任务名> @ <框架版本> + <配置版本>

- 轮次目录：`<artifacts.root>/rounds/<轮次>/`
- 方案：`<轮次>/design.md` 的 `id=<方案名>`；判据：`<轮次>/criterion.yaml`（跑前冻结）
- 框架仓库与钉点：`<框架仓库> @ <framework_head>`

## 1. 执行记录

| 段 | 命令来源 | 退出码 | 耗时（秒） | 产物路径 |
|---|---|---|---|---|
| 训练 | `<任务目录>/train.sh` ＋ `<轮次>/round.env` | | | |
| 转换 | `<任务目录>/convert.sh` | | | |
| 评测 | `<任务目录>/eval.sh` | | | |

- **耗时口径（0.18.26）**：上表三个数字**只能**引 `metrics.json` 的
  `timing.stages.<段>.duration_s`（机器净耗时，来源 `evidence/<段>.exec.json`）；
  三段之和见 `timing.engine_total_s`。**不报角色墙钟**（architect/developer/tester 没有落点，
  也不许凭记忆填）—— 想写"人等了多久"请写在 §6，并明确标为"非引擎时间"。
- 续跑记录（若本轮是 `--resume` 起来的）：`从 <ckpt 路径> 续跑，起始步 = <N>`；出处
  `evidence/train.exec.json` 的 `resume_from`。**没续跑就写"无"**，别留空。
- ckpt 保留（0.18.26）：本轮按 `train.checkpoint.*` 存盘/刈草，删除清单见
  `evidence/ckpt-retention.log`（无删除则该文件可能不存在）。
- 候选与结果（表）：<…>
- 在线早停 / 平台停 / 墙钟超时 / 失败证据（阈值名 ＋ 步数 ＋ 数值）：<…>

## 1b. 趋势（图由 `runtime/charts.py` 生成，**不许手画**）

- loss：`evidence/charts/loss.svg`（原始 ＋ median-10 平滑；纯文本兜底 `loss-sparkline.txt`）
- 量化噪声：`evidence/charts/qsnr.svg`（若 `train.monitor_metrics` 含 `quant_error`）
- 三段耗时：`evidence/charts/timing.svg`
- 生成命令：`python3 runtime/charts.py --round <轮次>`；图里的数字**只来自 `evidence/`**，
  报告正文引用的数字仍以 `metrics.json` 为准。
- 一句话读图结论（趋势/拐点/平台大约在第几步）：<…>

## 2. 判定段（对照**跑前冻结**的 `criterion.yaml`）

> 结论只给 **`outcome` ＋ 一句话理由 ＋ 证据指针** —— 没有档位、没有额外的机器判据。

- **outcome**：`adopt` | `reject` | `inconclusive`
- **一句话理由**：<为什么是这个 outcome，对着上面哪一条冻结条件>
- **证据指针**：`<轮次>/metrics.json` 的 <字段> ＋ `<轮次>/evidence/<文件>`
- **停止轮次口径（0.18.26）**：若本轮被平台早停（`early_stop.kind=converged`），必须写
  「停在第 N 步、未跑满 `max_steps`」。**训练侧 loss（last/best/min_loss）不得与跑满轮次直接比**；
  下游评测可以比，但那说的是"各自停止点上的模型质量"，不是"同预算下的方案优劣"。
  要判方案优劣 ⇒ 两轮同预算（都跑满，或同一平台规则且步数对齐）。
- 逐条对账：

| 判据字段 | 判据要求 | metrics.json 字段 | 实测值 | 结果 |
|---|---|---|---|---|
| `success.require` | | | | |
| `falsification` | | | | |

- **强度目标**：照抄跑前冻结的 `strength_target`（自由文本或 `null`）—— 它**只是方案作者写的一句话**，
  没有档位、没有机器判据，判定不因它加减分。

## 3. 数字（全部引自 `<轮次>/metrics.json`，原样写值）

| 指标 | 值 | metrics.json 字段路径 |
|---|---|---|

## 4. 结论与指针

- 结论档案：`records/conclusions/C-<序号>.yaml`（append-only；**失败也入库**）
- 最优更新：`records/best/<任务名>__<指标>.yaml`（只在有新判定或新证据时覆盖）
- 账本：`records/ledger.jsonl`（**唯一**的 append-only 账本；结论索引由 `conclusions/` 现算，不落盘）

## 5. 框架还原校验记录

| 项 | 结果 |
|---|---|
| `framework_head.before` vs `.after` | <无差异 / 有差异> |
| `framework_status.before` vs `.after` | <无差异 / 有差异> |
| 框架工作树 `git status --porcelain` | <空 / 非空> |

> 任一有差异 ⇒ **本轮失败**（还原是流程里的一个正式步骤，不是记得清理）。

## 6. 交接

- `EXPERIMENT_DONE`（→ architect：反馈环，含知识增补与「要不要开新一轮」）
- `EXPERIMENT_INVALID`（→ 自己：失败证据 ＋ 触发阈值与步数 ＋ **重跑要改什么**；说不清不许原样重跑）
