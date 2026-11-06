# 升级指引：从 `≤ 0.18.17` 升到 `0.18.31`

> 这份文件只在**升级**时有意义。全新安装可以跳过，直接看 `PREREQUISITES.md` 与 `SMOKE_TEST.md`。
>
> 一句话：**引擎侧由安装器换，任务侧要你手工同步**；另外 0.18.18／0.18.26 有两处**会拦住升级**的契约变化，
> 它们不在任何一次 CR 里，但和 CR 的改动一起躺在这一段版本区间里。

## 1. 会拦住你的五件事（不处理就跑不起来）

| # | 项 | 症状 |
|---|---|---|
| 1 | 任务配置缺 `train.qat_probe` / `train.checkpoint`（0.18.26 起 schema **必填**） | `python3 runtime/config.py validate <配置>` ⇒ **rc=2** |
| 2 | `commands/train_argv.txt` 占位符 **11 → 14**（新增 `${save_interval}` `${finetune_flag}` `${load_state_flags}`） | **不报错**，但 ckpt 分段存／续跑／finetune 开关**静默不生效**（最难发现的一种） |
| 3 | `commands/_stage_args.sh` 是**新文件**（0.18.29），三份 `*_cmd.sh` 都 `source` 它 | 只换三份脚本不拷它 ⇒ `_stage_args.sh: No such file or directory` |
| 4 | `stop_conditions.{loss.jump_factor, loss.rel_to_best, loss.min_points, wall_clock_hours, max_steps}` 现在**真的从任务配置读**（0.18.18）；`wall_clock_hours: 0` **不再**等于"无限" | 缺／`0`／写反 ⇒ **退出 2**（以前静默以 `<轮次>/criterion.yaml` 为准） |
| 5 | `runtime/`、`skills/`、`templates/`、`docs/` 等 **managed 文件被本地改过** | 安装器**一个字节都不写**、退出 2（先报后停）。要么先合并，要么 `--force-managed`（覆盖前自动存 `.bak`） |

## 2. 安装器替你做什么、不做什么

| 类别 | 文件 | 升级时 |
|---|---|---|
| **managed（覆盖）** | `runtime/` `templates/` `skills/` `agents/` `docs/` `scripts/` `config/task.schema.json` `knowledge/{README,models,frameworks}/**` `requests/**` `experiments/README.md` | 覆盖；被改过则整包拒写 |
| **seeded（永不覆盖）** | `config/project.yaml`、`knowledge/INDEX.md`、`records/conclusions/_EXAMPLE.yaml` | 只在缺失时创建；比新包旧时只提示 `STALE_SEEDED` |
| **安装工具（不装进目标根）** | 包里的 `deploy/`（`install.sh`／`verify_install.sh`／本文档等） | 只在解包目录里用；目标根里**不会**出现 `deploy/` |
| **不随包（安装器不碰）** | `experiments/<任务名>/**`、`config/tasks/<任务名>.yaml`、`knowledge/{techniques,external}/**`（以及你自己放的 patch）、`records/{conclusions,best}/**` | **全部要手工同步**（见 §3、§4） |

## 3. 任务目录要同步的（顺序照这个来）

```bash
# 0) 只备份「你要手改的那几个文件」——不要 cp -r 整个 experiments/（rounds/evidence 可能几 GB，且本版不碰它）
cd experiments/<任务名>
mkdir -p /tmp/task-bak && cp -r commands run.env train.sh convert.sh eval.sh /tmp/task-bak/
#    工程在 git 里的话，`git commit` 就是更好的备份（能逐行看 diff，不只是回退）

# 1) 看差异：包里的 templates/ 是权威参照
diff -ru experiments/<任务名>/commands templates/commands
diff -u  experiments/<任务名>/run.env  templates/run.env
```

| 文件 | 要做什么 | 为什么 |
|---|---|---|
| `commands/_stage_args.sh` | **新增**，直接拷 | 三份命令脚本都 `source` 它（0.18.29） |
| `commands/train_cmd.sh` | 换 | 0.18.28 显示一致／片段槽、0.18.29 片段槽、0.18.30 `extra_pythonpath`、0.18.31 探针落点 |
| `commands/convert_cmd.sh` | 换 | 0.18.29：缺 `config.json` ⇒ 退 2；`--hf-cfg-dir` 默认值 |
| `commands/eval_cmd.sh` | 换 | 0.18.28／0.18.29 的片段与显示一致 |
| `commands/train_argv.txt` | 换 | 占位符 11 → 14（否则 §1 第 2 条） |
| `run.env` | 合并 | 三个片段槽语义。★ 若你以前把 convert 的片段写进 `LP_TRAIN_EXTRA_ARGS`，**要挪到** `LP_CONVERT_EXTRA_ARGS`（0.18.29 前 convert 吃的是训练那个槽） |
| `train.sh` / `convert.sh` / `eval.sh` | **整份覆盖**：`bash scripts/init_task_dir.sh <任务名> --refresh-scripts` （只这三份；`run.env`／`commands`／`sets` 不动） | 0.18.26 的 `--resume`／ckpt 参数、0.18.29 的转换段、**0.18.38 的 `eval.sh` 训练观察门**（读 `stop_kind`，否则平台早停的轮次评不了） |

**注意**：`templates/commands/*_cmd.sh` 是**通用模板**（里面有 `<任务名>` 这类占位），
你目录里的是**任务专用实例**。方向别搞反：参照模板改你的实例，不要拿模板盖上去。

## 4. 任务配置要补的字段

```yaml
train:
  monitor_metrics: [loss, quant_error]     # 含 quant_error ⇒ 起训练自动打开 QSNR 探针
  qat_probe:
    every_n_steps: 10                      # 0.18.26 起必填；缺 ⇒ 开探针时退 2
  checkpoint:
    save_interval_steps: 50                # 0.18.26 起必填
    keep_last: 2
  # extra_pythonpath: ["/path/to/Megatron-LM"]   # 可选；只注入 train/convert，eval 不注入（有意）

stop_conditions:                           # 0.18.18 起这五个真的被读
  max_steps: 300
  wall_clock_hours: 6                      # <= 0 现在退 2（老模板里的 0 会静默无限等）
  loss: { jump_factor: 4.0, rel_to_best: 2.5, min_points: 5 }
  # plateau: { window_steps: 20, min_gain_pct: 1.0, patience: 2, min_steps: 60 }   # 可选
```

## 5. 行为变了（不用改东西，但结论会变）

| 版本 | 变化 | 要注意 |
|---|---|---|
| 0.18.18 | 早停／墙钟阈值只认任务配置 | 以前"判据写 4.0、配置写 999"的轮次，**生效值会变** |
| 0.18.26 | **平台期早停 ⇒ converged ⇒ rc 0**（合法结论） | 编排按"非 0 才是坏"判是对的；若有脚本按 `rc==5` 识别早停，要改 |
| 0.18.26 | `last_iter < max_steps` 成为常见结果 | 判据按"跑满 `max_steps`"判完成的，要看 `converged`／`steps_observed` |
| 0.18.29 | 转换缺 `config.json` ⇒ 退 2 | 以前"转换成功"的轮次现在会失败（这是修缺陷） |
| 0.18.29 | 已完成轮数**现算**（不再归 1） | 之前被算错的轮数会纠正 |
| 0.18.30 | `extra_pythonpath` 只注入 train／convert，**eval 不注入**（有意） | 以前靠 `run.env` `export PYTHONPATH` 的，改成字段后 eval 侧会少一条路径 |
| 0.18.31 | 探针落点跟随 `LP_EV` | 不设 `LP_EV` 时行为不变；**冒烟要开始带** `LP_EV=<轮次>/evidence/smoke` |

## 6. 升级顺序

1. 进行中的轮次先收口（`python3 runtime/state.py close …`）或暂停 —— **别在跑的时候换引擎**
2. 备份：只备份 §3 那几个要手改的文件（或 `git commit`），**不要** `cp -r` 整个 `experiments/`
3. 新包解到临时目录（**别解进目标根**），先看计划：`bash <发布包目录>/deploy/install.sh <目标根> --dry-run`
4. 正式装：`bash <发布包目录>/deploy/install.sh <目标根>`（要用 `use_agent <角色>` 就加 `--with-agents`，装完**重启 dsh**）
5. 按 §3 同步任务目录
6. 按 §4 补任务配置字段
7. 跑 §7 的四条验证
8. 跑一次 10 步冒烟（带 `LP_EV=<轮次>/evidence/smoke`），确认 `evidence/` 根目录干净
9. 再开正式跑

> **升级时不要手工跑 `runtime/state.py init`。** 它是**开轮**用的（`scripts/start_experiment.sh` 第 3 步无条件调它），
> 语义是"给这一轮造一份新状态"：`stage` 会被重置成 `architect`、`last_handoff`/`last_conclusion` 会被清空——
> 对一条**已收口**（`stage: done`）的线照做，等于把"这条线已停"抹掉，编排器会以为该再派一次 architect，
> 而 `rounds/<轮次>/` 里已经有上一轮的产物了。
>
> **版本戳也不用人工刷**：`framework_version` 由 `init` 从 `VERSION` 写入，所以**下一轮开跑时自动就是新版本**，
> 收口时再抄进 `state/rounds.jsonl` 那一行。已经结束的线停在旧版本号是正常的（它不会再产生台账行，历史也不许改）。
> 要核对：`python3 -c "import json;print(json.load(open('state/current.json'))['framework_version'])"`（开轮后应等于 `cat VERSION`）。

## 7. 升级后必跑

> 只有**第一条**在**发布包解压目录**下跑 —— `deploy/` 是安装工具，**不随安装进目标根**（见 §2）；
> 其余都在**目标根**下跑。

```bash
# ① 引擎自证（在发布包解压目录执行！不是目标根）
bash <发布包目录>/deploy/verify_install.sh <目标根>

# ② 任务配置契约（切到目标根）
cd <目标根>
python3 runtime/config.py validate config/tasks/<任务名>.yaml      # 期望 rc=0

# ③ 三段命令拼装（不占卡；入口脚本自己解析 root/任务/轮次，不用手工给环境变量）
bash experiments/<任务名>/train.sh   --round <轮次> --dry-run
bash experiments/<任务名>/convert.sh --round <轮次> --dry-run
bash experiments/<任务名>/eval.sh    --round <轮次> --dry-run

# ④ 冒烟落点（只影响训练段；应打印「证据目录 <轮次>/evidence/smoke」）
LP_EV=<轮次>/evidence/smoke bash experiments/<任务名>/train.sh --round <轮次> --dry-run
```

**别拿 `commands/*_cmd.sh --print` 当日常入口**：那是三段入口调用的**内部拼装层**，手工跑要自己给
`LP_ROOT`／`LP_TASK_ID`／`LP_ROUND`／`LP_CARDS`（用到第三仓还要 `LP_MEGATRON_REPO`），少一个就退出 2。
要核对拼装结果，用上面 ③ 的入口脚本 `--dry-run` 即可（它打印的就是同一条命令）。

## 8. 回滚

- 保留**旧包**与 §3 的备份即可：回滚 = 重装旧包 + 恢复任务目录。
- `seeded` 文件（`config/project.yaml`、知识库索引等）升级时不会被覆盖，所以回滚也不会丢你写的内容。
- 旧轮次的 `evidence/` 与 `metrics.json` 不用动：抽数只读 `<轮次>/evidence/` 根目录，
  0.18.31 没有改抽数逻辑 ⇒ 重跑 `python3 runtime/metrics.py --round <轮次>` 的结果与升级前一致。
