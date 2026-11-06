# templates/commands/ —— **无型号**的命令骨架（照抄改）

> 归属：任务目录的命令形状（`AGENTS.md` §2 第 6 条）。**配方不是引擎**：型号几何写死的命令、本任务自己的闸门、
> 评测侧驱动**都不许**进 `runtime/`，也不许把带型号的文件名直接搬过来。
> 这里只放**去掉型号后**的命令形状：`<占位符>` 照抄时逐个替换。

## 0. 当前状态（P4c 起）

三份骨架已落盘（P0 时本目录只有本说明文件）。**它们是可以 `bash -n` / `py_compile` 通过的可用骨架**，
不是空文件；但每一份都要求在照抄时替换掉占位处，**没替换就当场拒绝或明确"什么都没查"**。

| 骨架（无型号） | 用途 | 谁用 | 什么时候用 |
|---|---|---|---|
| `gate.sh` | 闸门骨架：把真正的检查调起来，再把退出码翻成一句人话 | tester、experimenter | 花算力之前 |
| `switch_consistency.py` | 开关一致性：判据侧口径 ↔ 任务配置侧取值逐项比对 | tester、experimenter | 评测之前 |
| `report.py` | 把 `<轮次>/metrics.json` 的**可引用字段路径**打出来（报告里引用路径，不手抄数字） | tester、experimenter | 写报告之前 |
| `train_cmd.sh` | **训练命令骨架**：读 `train_argv.txt` → 替换 14 个占位符 → `cd <框架检出> && bash -c`；`--print` 只打印不执行 | developer | 写训练侧时 |
| `convert_cmd.sh` | **转换命令骨架**：训练产物 → 评测可加载的权重 | developer | 写转换侧时 |
| `eval_cmd.sh` | **评测命令骨架**：调 `<任务目录>/drivers/lm_eval_driver.py` | developer | 写评测侧时 |
| `_taskcfg.sh` | 三段共用的小工具：从任务配置取点号字段、取本进程可见卡 | developer | 三段都要 `source` 它 |
| `train_argv.txt` 的 `${save_interval}` / `${finetune_flag}` / `${load_state_flags}` | 0.18.26 新增的三个占位符：存盘间隔来自 `train.checkpoint.save_interval_steps`；后两个是**续跑开关**（`--resume` 时为空值，见下） |
| `train_argv.txt` | 训练 argv 的**占位模板**（14 个占位符；0.18.9 起多了 `${model_start}`／`${data_path}`） | developer | 照抄改成本任务的 flag 表 |
| `../drivers/lm_eval_driver.py` | **评测驱动骨架**：`--print` 拼 argv／真跑并落 `results.json` | developer | 评测侧 |
| `README.md` | 本目录的索引与「哪条命令什么时候用」 | 人 | — |

**实例在哪**：0.18.8 起这两份**随包发**（`validate_design.sh`、`eval_protocol_gate.sh`）——
它们是引擎件，与任何 `<任务目录>/commands/` 下的同名文件**逐字相同**，`scripts/init_task_dir.sh` 直接拷。
★ 目录里另有两份**更粗的骨架**：`gate.sh`（通用闸门骨架）与 `switch_consistency.py`（探针式，71 行）——
它们只是"照抄再改"的起点，**不是**可用实例；特别是 `eval_protocol_gate.sh` 里那套
"全局 protocol ⊕ 逐集覆盖、覆盖写 null = 显式清空、双向缺一即错、退出 6"的逻辑，骨架里没有。

**命令形状脚本的骨架（0.18.0 起）**：三段拼装入口（`train_cmd.sh`／`convert_cmd.sh`／`eval_cmd.sh`
＋ 共用的 `_taskcfg.sh`）＋ argv 模板 `train_argv.txt` ＋ 驱动 `../drivers/lm_eval_driver.py`
**在本目录有骨架**，照抄到 `<任务目录>/commands/`（驱动到 `<任务目录>/drivers/`）后把 `<...>` 换成真值。

> **为什么 0.17.0 说"不再另立骨架"、0.18.0 又加回来了**：0.17.0 的理由是"骨架与实例各写一套就会翻车"——
> 那针对的是**同一任务**有两份实现。而新工程要从零起（出厂包里没有任务目录实例），
> `developer` 第一轮面对的是 981 行没有参照的脚本 ⇒ **第一轮大概率失败**。
> 现在的口径：**骨架随包发**（无型号、带占位），**实例仍只在任务目录**（一个任务一份，不外发）。

## 1. 退出码（**照抄时最容易被搞坏的一处**）

| 码 | 什么时候用它 | 含义 |
|---|---|---|
| `0` | 检查通过 | 可以往下走 |
| `2` | 约定/用法错（参数缺、文件读不了、闸门自己坏了） | **拒绝开跑** |
| `6` | 口径不全/冲突、驱动不可用 | **评测侧无效** —— 这一轮的分数**根本不该被引用** |
| `5` | （仅训练侧）早停/发散/NaN/墙钟超时 | 训练侧无效 |

**不许**用 `0` 表示"没查但放行"。骨架阶段确实什么都没查时，要让它**可见**（`gate.sh` 里
`GATE_CMD="true"` 那一行就是这句话），而不是让一条空闸门冒充通过。

## 2. 三条纪律

1. **去型号**：骨架里不出现模型名/任务名/数据集名/配方串；一律 `<占位符>`
   （`devtools/check_decoupling.py` 会查 `runtime/`、`agents/`、`skills/`、`templates/`）。
2. **一个事实只有一个落点**：命令形状在这里，**逐字命令**在 `<任务目录>/run.env`；
   判据/口径在 `<轮次>/criterion.yaml` 与 `config/tasks/<任务名>.yaml`。闸门**只调起检查**，
   不许把判据在闸门里再写一份。
3. **只做人/流水线触发的检查**：本目录是任务级对账工具，不是每轮门
   （每轮门只有 `runtime/validate_round.py` 一个）。

## 轮次追加片段的边界（0.18.29）

`<轮次>/round.env` 的 `LP_*_EXTRA_ARGS` 是**追加到该段生效命令末尾**的片段，一个段一个槽。
三段模板**共用** `_stage_args.sh` 解析（唯一一份实现、唯一一份"不许改"清单）：

| 位置 | 含义 |
|---|---|
| `--print`／`--dry-run` | 只打印拼装结果，不执行（**位置任意**） |
| `--run` | 忽略（"真跑"是默认） |
| `--` | 其后全部当片段（片段自己带 `-` 开头也不怕） |
| 其余 | 原样转交，落在命令末尾；`--print` 里会单独打一行便于对账 |

**一律拒（rc=2，并指名该改哪个键）**：值有唯一落点的那些 flag。三段的清单在
`_stage_args.sh` 的 `_lp_stage_owner()` 一处 —— 例如 `train` 的 `--save-interval`（→ 任务配置）、
`--seq-length`（→ `run.env` 的 `LP_SEQ_LEN`）；`convert` 的 `--save-dir`；`eval` 的 `--tasks`／
`--num_fewshot`（口径，跑前冻结）。
**放行**：不改变口径也不改变落点的临时开关（`--log-interval`、`--no-load-optim` 之类）。

为什么不许用片段改"有落点的值"：同一个事实两处写，改一处就静默不同步 —— 这正是本工程反复
在躲的那类问题。要改就去改那个落点。

> 回归网：`bash devtools/check_templates.sh`（`run_all.sh` 的一步）。它只用 `--print` 拼命令，
> **不占卡**，但能证明"片段接得住／该拒的拒／卡扣在正确位置"。

## 训练形状的四个旋钮（在 `<任务目录>/run.env`，**不在**任务配置里）

`train_cmd.sh` 读这四个变量（`run.env` 里以 `${VAR:-默认}` 形式给默认值，改值就改那一行）：

| 变量 | 决定 | 骨架默认 | 注意 |
|---|---|---|---|
| `LP_SEQ_LEN` | `--seq-length` | `8192` | 显存大头；与 `--micro-batch-size` 联动 |
| `LP_MICRO_BS` | `--micro-batch-size` | `1` | 单卡步内批 |
| `LP_GLOBAL_BS` | `--global-batch-size` | `64` | 必须能被 `micro_bs × cards` 整除 |
| `LP_QAT_SCHEME` | `--qat-scheme`（量化方案） | 取任务配置 `model.precision` | 任务配置给了就以它为准，别两边写 |

> 为什么不在任务配置里：这四个是**命令形状**（怎么落地），与 `train_argv.txt` 同层；
> 任务配置只放身份/目标/预算（见 `docs/CONFIG.md` §2 的四类分栏）。
> `LP_MASTER_PORT` 同理（骨架 6040／任务实例可能不同），撞端口时改 `run.env` 那一行。

## 续跑（0.18.26）

```bash
bash <任务目录>/train.sh --round R-0003 --resume latest     # = <轮次>/ckpt（框架读 tracker 定迭代数）
bash <任务目录>/train.sh --round R-0003 --resume <ckpt 目录>
```

- 只对 **train** 段有意义；`convert.sh`/`eval.sh` 给 `--resume` ⇒ 退出 2。
- 目录里必须有 `latest_checkpointed_iteration.txt` 或 `iter_*`，否则退出 2（**不许拿基座权重目录当续跑点**）。
- `train_cmd.sh` 据此改 argv 三处：`--load <ckpt>`、去掉 `--finetune`、去掉
  `--no-load-optim/--no-load-rng` ⇒ 框架恢复迭代数＋优化器＋RNG。
- 续跑那一轮必须在 `report.md` 写「从 `<ckpt>` 续跑，起始步 = N」（出处 `evidence/train.exec.json` 的 `resume_from`）。
