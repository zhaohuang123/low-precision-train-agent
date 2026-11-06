---
name: train-recipe
description: 当 developer / tester / experimenter 要把配置字段变成一次可复现的训练时加载——讲清「脚本管约定、run.env 管命令」的分工、三段入口怎么写（第一行解析 LP_ROOT、由 runtime/_common.sh 校验引擎存在）、run.env 与 round.env 的写法、退出码 0/1/2/5/6 怎么处置。不用于判定，也不用于评测口径对齐。
version: 1.0.0
applies_to: [developer, tester, experimenter]
---

# 训练配方与三段入口（`train-recipe`）

## 0. 什么时候用 / 什么时候不用

- **用**：写任务级三段入口与命令；按配方起一次训练；处置退出码。
- **不用**：判框架能否表达方案（`code-change`）；评测侧驱动与口径（`eval-lm-eval`）；判定与结论（`report-and-conclusion`）。
- **一句话分工**：**脚本管约定，`run.env` 管命令**。命令不是引擎，它必须能一轮一轮复用、也必须能逐字对账。

## 0.1 开跑前核一次：任务实例 ↔ 模板（**一条命令，人读差异**）

任务目录里的三段入口是引擎件的**副本**，`commands/*_cmd.sh` 是从模板**抄出来的实例**。模板会随升级/修缺陷
变化，实例**不会自动跟着变** —— `init_task_dir.sh` 的 `put()` 是"已存在就跳过"，`config.py validate` 也不查
这件事。于是会出现最坏的一种：配置里加了字段、`validate` 也过了，但**没有任何人读它**，训练静默少采样。

所以每轮开跑前跑一次下面两条，把差异**读一遍**（不要求为空，只要求每处差异你都说得出理由）：

```bash
T=<任务目录>

# ① 三段入口：**代码**应当逐字相同（`-I '^#'` 忽略注释：任务目录常有自己的身份注释）
for f in train convert eval; do diff -q -I '^[[:space:]]*#' "$T/$f.sh" "templates/task/$f.sh"; done
bash scripts/init_task_dir.sh <任务名> --refresh-scripts     # 有差异时收掉

# ② 命令脚本：argv 因任务而异是**正常的**，只看"接线"有没有抄到
diff -u templates/commands/train_cmd.sh "$T/commands/train_cmd.sh" \
  | grep -E '^[-+].*(QAT_QSNR_EVERY|\$\{save_interval\}|\$\{finetune_flag\}|\$\{load_state_flags\}|LP_EV)'
#    有输出 ⇒ 模板新增/改过的接线本实例没有 ⇒ 那个配置字段本轮**没人消费**
#    正确动作：把那几行**手工抄进实例**（argv 是任务特有几何，别拿模板整份覆盖）
```

**判据**：① 代码有差异 ⇒ `--refresh-scripts` 后应一致（只剩注释差异）；② 出现"配置里有值、实例里没接线"⇒
要么手工抄那几行，要么把配置里那个字段删掉 —— **`schema` 里 required 的字段必须有消费者**，
`validate` 只保证"填了合法"，保证不了"有人读"。

## 1. 开工前要读的文件（路径 + 字段名）

| 读什么 | 取哪些字段 | 为什么 |
|---|---|---|
| `config/tasks/<任务名>.yaml`（只读） | `train.{framework_repo,framework_head,core_repo,core_head}`、`model.{name,source}`、`artifacts.root` | 场景与钉点 |
| `<任务目录>/commands/train_argv.txt`（只读） | 训练 argv 模板（14 个占位符） | 命令形状（0.18.0 起在任务目录，不在任务配置里） |
| 任务配置 `stop_conditions.*`（只读） | `loss.{jump_factor,rel_to_best,min_points}`（在线早停）＋ `wall_clock_hours`（墙钟闸）＋ `max_steps`（驱动 `--train-iters`） | **唯一落点**（0.18.18 起）：引擎直接读；写进判据不生效 |
| `<轮次>/criterion.yaml`（只读） | `success.*`／`falsification`／`budget.*`／`eval_protocol.*` | 判定与口径，跑前冻结 |
| `<轮次>/scheme_resolved.json`（只读） | 展开后的实际取值＋来源 | 复现读它，不读块 |
| `<轮次>/round.env`（只读） | 变量覆盖、`LP_TRAIN_EXTRA_ARGS` / `LP_CONVERT_EXTRA_ARGS` / `LP_EVAL_EXTRA_ARGS`（一段一个槽） | 本轮差异只允许这样表达 |
| `runtime/_common.sh`、`runtime/executor.py` | 退出码表、共用前导契约 | 你的入口要 source 它、要调它 |

## 2. 步骤（每步带判据）

1. **三段只写一份**：`<任务目录>/{train.sh,convert.sh,eval.sh}` ＋ `<任务目录>/run.env`，**所有轮次共用**；轮次目录里**不许**出现同名脚本副本。
   *判据*：`ls <轮次>/ | grep -E '^(train|convert|eval)\.sh$'` 为空（`devtools/check_round_layout.py` 会机械查）。
2. **入口第一行解析配置根**：`LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"`；随后 `source "$LP_ROOT/runtime/_common.sh"`。
   *判据*：`$LP_ROOT/runtime/executor.py` 不存在时**退出 `2`**；解析不出根也退出 `2`（**fail-closed，不许猜根**）。
3. **命令写进 `run.env`**：真正的 argv 与环境变量只在 `run.env` 一份；`--dry-run` 时打印的命令必须与 `run.env` **逐字相等**。
   *判据*：`bash <任务目录>/train.sh --dry-run --round R-0001` 退出 `0` 且 `grep -F` 比对通过。
4. **轮次差异只允许两种**：① 改 `round.env` 的变量值／追加 argv 片段；② 加 `hooks/{pre_train,post_train,pre_eval,post_eval}.sh`（存在即执行，前后各一次）。
   *判据*：没有重定义整条命令、没有删除任务级变量；钩子只往 `evidence/` 落文件，不改 `criterion.yaml`／`metrics.json`／`report.md`。
4.1 **一个轮次目录只放一次正式跑**：同一轮次要重跑（崩了修完再跑），**先把 `evidence/` 归档**（挪出 `evidence/`，不要留在原地），再起。
   *为什么*：证据文件按**名字**读（`train.log`／`train.exec.json`／`eval_clamp_qsnr.json`…），
   旧文件留在原地、新的一遍又没写出来，抽数就会把上一遍的数当成本轮 —— 这种错**看起来完全正常**。
   *判据*：起正式跑之前，`evidence/` 里没有上一遍留下的同名产物。冒烟不走这条（冒烟一律落
   `LP_EV=<轮次>/evidence/smoke`，见 `autotune` skill）。
5. **退出码按表处置**：`0` 成功（**含平台早停**）；`1` 运行期失败；`2` 约定/门不过（**不许重试**）；`5` 训练侧无效（发散/非有限值/**墙钟超时** ⇒ `EXPERIMENT_INVALID`；**不含平台早停**）；`6` 评测侧无效（口径不全 ⇒ 本轮不产生精度结论）。
   *判据*：每类都有对应的下一步动作，不把 5/6 含糊成 1。

## 3. 模板与命令（可直接复制）

```bash
# <任务目录>/train.sh（convert.sh / eval.sh 同构）
#!/usr/bin/env bash
set -euo pipefail
LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # 解析不出根就退出 2，不许猜
source "$LP_ROOT/runtime/_common.sh"                            # 校验 $LP_ROOT/runtime/executor.py 存在 + 读 run.env/round.env

# 真正跑什么命令：只在 run.env 一份
python3 "$LP_ROOT/runtime/executor.py" --round "$LP_ROUND" --stage train
```

```bash
# <任务目录>/run.env（片段）—— 命令与环境变量逐字可对账
# ${max_steps} 由 commands/train_cmd.sh 从**任务配置** stop_conditions.max_steps 取
# （判据里那份同名字段只用于对账，不驱动本参数）。
LP_TRAIN_CMD=(torchrun --nproc_per_node="${cards}" --master_port="${port}" <入口脚本> \
  --load "${model_path}" --train-iters "${max_steps}" --seq-length "${seq_len}" \
  --micro-batch-size "${micro_bs}" --global-batch-size "${global_bs}" --save "${out_dir}")
LP_TRAIN_EXTRA_ARGS=()          # 轮次追加片段（round.env 可追加，不可重定义命令）
```

## 4. gotchas（症状 → 正确动作）

1. **按当前工作目录反推配置根** → 症状：根错了不报错，产物正常写进错的树。正确动作：入口第一行从 `BASH_SOURCE` 解析，`_common.sh` 校验引擎存在。
2. **阈值写进脚本/执行器** → 症状：改了配置但早停没变。正确动作：阈值只写在任务配置 `stop_conditions.*`，由引擎传给执行器。
3. **每轮各写一份脚本** → 症状：公共脚本的修复不传导到旧轮次。正确动作：只留任务目录一份，轮次用 `round.env`/`hooks` 覆盖。
4. **相对路径相对脚本目录** → 症状：换个调用位置就跑偏。正确动作：一律相对**配置根** `LP_ROOT`。
5. **把评测口径常量写进训练脚本** → 症状：训练侧与评测侧口径不一致。正确动作：口径只在 `config/tasks/<任务名>.yaml` 与 `<轮次>/criterion.yaml`，逐项对账。

## 5. 校验回路（自查「我真的做对了」）

- `--dry-run` 打印的命令与 `run.env` 逐字相等；`LP_ROOT` 指向不存在的树 ⇒ 退出 `2`。
- 轮次目录没有三段脚本副本；`round.env` 没有重定义命令。
- 退出码 5/6 的处置已写进 `test.md`/`report.md` 的对应段落。
- 命令里没有出现模型名/数据集名的硬编码（它们来自配置）。

## 6. 参考

- 本工程：`AGENTS.md` §2 第 6 条（轮次只放差异）、`runtime/_common.sh` 的根解析（fail-closed 找引擎）。
- `skills/eval-lm-eval/SKILL.md`（评测侧口径与驱动）、`skills/run-observation/SKILL.md`（读观察）。
- `references/three-stage-and-exit-codes.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①三段入口的形状（写一次、每轮复用）＋ fail-closed 解析配置根 ＋ 轮次差异只允许两种（`round.env` 覆盖/追加 ＋ `hooks/*.sh`）
  ②退出码表与逐类处置 ③**已定名的** `run.env` 键（`LP_ROOT`／`LP_ROUND`／`LP_TRAIN_EXTRA_ARGS`／`LP_CONVERT_EXTRA_ARGS`／`LP_EVAL_EXTRA_ARGS`／`LP_EVAL_PYTHON`）
  ④`--dry-run` 逐字对账与 `LP_ROOT` 负对照 ⑤不许写进脚本的三样（阈值、口径常量、卡号）。
- **已闭合（P4c）**：完整的 `run.env` 键清单已落盘 —— 字段表唯一落点是 `templates/run.env` 顶部
  （实例：`<任务目录>/run.env`；读它的实现只有 `runtime/_common.sh`）。本文件**不复制**键清单（一个事实一个落点），
  只登记与三段处置直接相关的那几个键；两处不一致时以 `templates/run.env` 为准。
- **已定案（P4）**：退出码表的新旧冲突**已二选一** —— `5`＝训练侧无效（发散/NaN **＋ 墙钟超时**；0.18.26 起平台早停 `converged` 归 `0`）、
  `6`＝评测侧无效（旧表没有这一码）；对照表与理由在 `runtime/README.md` §2.1（本文件不复述旧工程路径与行号）。
