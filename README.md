# 低精度训练Agent（`low-precision-train-agent`／短名 `lpta`）

> **一句话**：把低精度训练实验的**机制**与具体的**模型/任务配方**彻底解耦。
> 机制（执行器、定卡、抽数、配置校验、状态、约定层、挂/还原、每轮必跑的门）进本工程，换模型/换任务不改；
> 配方（模型名、任务名、数据集、评测口径、量化方案）只进 `config/` 与任务目录／轮次目录。

- 中文名：低精度训练Agent ｜ 英文名：`low-precision-train-agent` ｜ 短名：`lpta`
- 落点：本工程根目录（目录名＝英文名）
- 版本起点：`VERSION` = `0.1.0`；配置版本 `cfg-<任务配置内容哈希前 8 位>`
- 流水线：`architect → developer → tester → experimenter`，末尾 `experimenter → architect` **反馈环**

> **当前状态：P0 骨架 → P10（交付完成）＋ P4d（零卡缺口收尾）**。顶层结构与逐文件骨架已建，机制件按 P 步逐步补齐
> （P1–P10 的交付见 `AGENTS.md` §6 与 `ReleaseNotes.md` 版本段）；仍未实现的按 P 步留 `TODO(P<n>)` 占位
> （可全局搜索 `grep -rn "TODO(P" .`）——
> **P4c 补齐后 `runtime/` 九件全部实现**（`executor.py`／`resources.py`／`_common.sh` 于 P4c 落盘），
> **P4d 把三笔记账一并收口**：`config.py` 的 `resolve-scheme`（`TODO(P1)`）、字典读取器搬进 `config.py`
> （`TODO(P4d)`）、旧 `scaffold/README.md` 246 行坑清单逐条搬运（`TODO(P4e)`），并把任务目录的三段命令
> 从桩换成**真命令形状**（`commands/*_cmd.sh` ＋ `drivers/lm_eval_driver.py`）。

---

## 0. 装起来（拿到 `lpta-<版本>.tar.gz` 之后）

本仓库是**工程本体**；安装材料在出厂包的 `deploy/` 里（源在 `devtools/release/`，打包时生成，仓库内没有这个目录）。

```bash
tar xzf lpta-<版本>.tar.gz && cd lpta-<版本>

# ① 升级前先看差异（新装可跳过）：只报差异，不写任何东西
bash deploy/install.sh /path/to/工程 --status

# ② 装 / 升级（目标已有安装 ⇒ 自动按升级走，不用加参数）
bash deploy/install.sh /path/to/工程 --with-agents

# ③ 装完自证
bash deploy/verify_install.sh /path/to/工程

# ④ 填工程级配置（state 目录可选先建；开跑入口每次都会自动建）
$EDITOR config/project.yaml
cd /path/to/工程 && python3 runtime/state.py init   # 可选：只为先看 state/STATUS.md

# ⑤ skill 必须单独装 —— install.sh 不管 skill
bash scripts/install_skills.sh --target "${DSH_HOME:-$HOME/.dsh}/skills" --dry-run
bash scripts/install_skills.sh --target "${DSH_HOME:-$HOME/.dsh}/skills"
```

`--with-agents` 把四个角色导出成 DSH subagent，装完**重启 dsh 再开会话**；不想用 subagent 可以去掉，
改用 `scripts/install_agents.sh` 单独装。skill 装完在 `~/.dsh/skills/<skill>/`，卸载用 `--uninstall`。

| 要什么 | 看哪里 |
|---|---|
| 前置条件（缺一个都装不起来） | `deploy/PREREQUISITES.md` §1 |
| 四个角色要不要装成 DSH subagent | `deploy/PREREQUISITES.md` §2.1 |
| 装完验"调用是否正常" | `deploy/SMOKE_TEST.md` §2（整段提示词） |
| 升级 / 卸载 / 看状态 | `deploy/PREREQUISITES.md` §4 |
| 从旧版本升上来 | `deploy/UPGRADE.md` |
| 包里明确没有的（也不用自己补） | `deploy/PREREQUISITES.md` §5 |

装好之后，回到 §1 填配置。

---

## 1. 上手：填两份配置，然后一条命令开跑

```bash
# ① 工程级配置（装完填一次）：数据盘、卡、路径
$EDITOR config/project.yaml

# ② 任务级配置（每个任务一份）：模型、评测、两仓钉点、产物根
cp config/tasks/_TEMPLATE.yaml config/tasks/<任务名>.yaml && $EDITOR config/tasks/<任务名>.yaml
python3 runtime/config.py validate config/tasks/<任务名>.yaml    # 不过 ⇒ 逐条打印字段路径

# ③ 开跑（preflight → 钉 state → 建 <轮次>/ → 打印"下一步派谁"）
bash scripts/start_experiment.sh <任务名>
```

**人只在两处必须出现**：① 填配置；② `architect` 写完判据后**点头冻结**。其余全由主 Agent 派四个角色推进
（§1.3 是操作视角，`AGENTS.md` §4.1 是编排视角，`docs/PIPELINE.md` 是机制视角）。

### 1.1 填 `config/project.yaml`（工程级；装完填一次，之后基本不动）

| 字段 | 填什么 | 填错会怎样 |
|---|---|---|
| `data.root` | **数据盘根**（如 `/data`）。唯一被 `runtime/_common.sh` 取用、export 成 `LP_DATA_ROOT` | 三段脚本拿不到数据根 ⇒ 起训练前退出 2 |
| `data.runs` | 三段产物的**默认落点**（`<data.runs>/<任务名>`；`run.env` 的 `LP_WORK_DIR` 可覆盖它），**须是真实可写的大盘** | 指到小盘 ⇒ 训练中途写爆；指到不存在的盘 ⇒ `state.py init` 打一行警告（不改 rc），起作业时才失败 |
| `devices.usable` | 本机**允许**用的卡，如 `"0-7"` | 定卡定不出来 ⇒ `preflight` 第③项 ✗ |
| `devices.reserved` | **排除**的卡，如 `"0-3"`（别人/系统占的） | 与 `usable` 冲突时定卡拒绝 |
| `devices.require_explicit` | `true`：不许隐式选卡，卡号只能由 `runtime/resources.py` 给出 | 设 `false` 会让"抢低号卡"那类事故重新变得可能 |
| `paths.*` | 六个目录（默认 `config/tasks`／`experiments`／`records`／`state`／`knowledge`／`requests`） | 改它等于改所有下游路径；一般别动 |

> **卡号优先级**（高 → 低）：环境变量 `LP_CARDS` ＞ 已导出的 `ASCEND_RT_VISIBLE_DEVICES` ＞ `devices.*` 策略 ＋
> 实测占用。任务配置里**没有**卡数上限字段（0.18.0 删了 `round.budget_cards`：它从来没有读取者）。

### 1.2 填 `config/tasks/<任务名>.yaml`（每个任务一份）

复制模板后逐块填。机器契约：`config/task.schema.json`（唯一执行者是 `runtime/config.py`）；
人读版字段说明：`docs/CONFIG.md` §4。

> **不在本文件里的两个旋钮区**：① 训练形状（`LP_SEQ_LEN`／`LP_MICRO_BS`／`LP_GLOBAL_BS`／`LP_QAT_SCHEME`／
> `LP_MASTER_PORT`）写在 `<任务目录>/run.env`；② 命令形状写在 `<任务目录>/commands/train_argv.txt`。
> 两者都是「怎么落地」，与身份/目标/预算分开 —— 见 `templates/commands/README.md`。

| 块 | 必填 | 怎么填（要点） |
|---|---|---|
| `task_id` | ✓ | 任务名，同时当目录名：不许含 `/`、空白，不许是 `.`／`..` |
| `model.{name,precision}` | ✓ | 模型名、目标精度（如 `w4a4`） |
| `model.source.{url,path}` | ✓ | `url` 与 `path` **至少一个**；`path` 写具体值时必须**真实存在**（配置门会查） |
| `train.framework_repo` | ✓ | 训练框架检出的**绝对路径**（必须是目录） |
| `train.framework_head` | 强烈建议 | 起点提交号。**形状不校验** —— 由 `preflight.sh` 用 `git rev-parse` 比对（git 是权威） |
| `train.core_repo` / `train.core_head` | 视框架 | 第二个仓（`import mindspeed` 真正解析到的那层）。单仓框架可整对省略 |
| `train.{framework,core}_url` | 否 | 远端 URL，只给 `scripts/fetch_code.sh` 用（留空则回退该检出目录的 `git remote`）；**钉点仍是 `*_head`** |
| `train.monitor_metrics` | ✓ | 监控指标清单（写给人/报告看；**抽取口径**由 `runtime/metrics.py` 唯一决定，不在这里配正则） |
| `train.qat_probe.every_n_steps` | ✓ | 量化误差探针的**采样频率**（模板 `10`）。写 `50` ⇒ 300 步只有 6 个点，`metrics.json` 只能记「不能判趋势」；`10` ⇒ 30 个点。采样频率的唯一落点，`train_cmd.sh` 读它 export `QAT_QSNR_EVERY` |
| `train.checkpoint.{save_interval_steps,keep_last}` | ✓ | 每 N 步存一份、只留最近 K 份（模板 `50` / `2`）。框架**没有**保留开关 ⇒ 删旧 `iter_*` 由 `executor.py` 在训练进程旁做（留痕 `<轮次>/evidence/ckpt-retention.log`）。磁盘账：4B 级全量状态 ≈55 GB/份 |
| `eval.engine` | ✓ | 本工程统一 `lm_eval` |
| `eval.lm_eval.{package,version,python}` | 建议 | **钉版本**；`python` 必须是 `<venv 根>/bin/python` 形状，版本与 venv 不一致 ⇒ `install_env.sh` 拒绝静默换 |
| `eval.task_type` | ✓ | `generation` / `multiple_choice`（可被单集覆盖） |
| `eval.datasets[]` | ✓ | 每集一项；`name` = lm-eval 任务名 = `metrics.json` 复合键**前缀**（不许含 `/`）；`path` 要给**文件**、不是目录 |
| `eval.protocol` | 建议 | 全局口径（`num_fewshot`／`max_gen_toks`／`batch_size`／`prompt_type`）；单集用 `datasets[].protocol` **逐键覆盖** |
| `artifacts.root` | ✓ | 写 `default` ⇒ 展开为 `<paths.experiments>/<任务名>`；写绝对路径 ⇒ 轮次目录落在那里 |
| `stop_conditions.*` | 建议 | 运行期保险丝与预算（**唯一落点在本文件**，不再抄进判据）：`max_steps` 真驱动 `--train-iters`；`quant_error_max` 换算成 QSNR 地板并用探针看门狗停跑；`wall_clock_hours` 到点杀进程组（退出 5）；`loss.{jump_factor,rel_to_best,min_points}` 在线发散早停；`plateau.*` 见下一行 |
| `stop_conditions.plateau` | 否 | **平台早停**（0.18.26 起）：`window_steps`／`min_gain_pct`／`patience`／`min_steps` **四件齐全才生效**，整块不写＝关闭。命中 ⇒ `stop_kind=converged`、**退出 0**（合法收工，属「停止轮次」：训练侧 loss 不得与跑满轮次直比）。标定与算法见 `docs/CONFIG.md` §4.0.1 |
| `knowledge.external` | 否 | 外部知识检索的来源与关键字（architect 取证用；`external/` 可作候选来源） |
| `model.start.{format,path}` | ✓（运行时） | 训练 `--load` 吃哪份权重：`source` 是「从哪来」、`start` 是「这一轮吃哪份」。`path` 可以先填一个**还不存在**的目录（转换见 `scripts/convert_weights.sh`，幂等） |
| `model.start.convert.{model_type_hf,tp,pp}` | mcore 按需 | 仅当 `format: mcore` 且 `path` **还不存在**时，从 `model.source.path`（HF）转过去：`model_type_hf` 必填（如 `qwen3`，不许猜），`tp`/`pp` 默认 1。**目标已存在 ⇒ 一律跳过**（幂等） |
| `train.data_path` | ✓（运行时） | 训练语料路径。与 `model.start.path` 同理：**部署事实只放配置**，任务目录里零绝对路径 |
| `intents[]` | 建议 | **多轮实验的起点**：人往里 append 想法（一条一行，或 `{text,external,loop}` 对象 = 一次尝试），architect 每轮挑一条做并在 `design.md` 里写明。**append-only**；不参与 `config_version` ⇒ 中断中追加不需要重钉 state |
| `loop.{max_rounds,no_progress_rounds}` | ✓ | **声明式**多轮边界（总量上限／缺省；单次尝试的预算写进 `intents[].loop`；这条线最多连开几轮／连续几轮无进展即建议停）。**引擎没有自动开关**：满额后由主 Agent 给 `LOOP_STOP`，见 §1.3 第 6 步 |
| `objective` | 否 | 一句人话目标（architect 读它出方案） |

**三个常见坑**（都会当场退出 2，不会静默）：

1. 写成 `eval.dataset:`（单数）⇒ 报「多余字段」。0.17.0 起是 `eval.datasets[]`。
2. `datasets[].path` 指到**目录** ⇒ 配置门只查存在性会放行，但评测驱动的 `is_file()` 会失败。请给文件。
3. 钉点抄短（`223eda00` 而非 40 位）⇒ `preflight.sh` 报「检出在 …，配置钉的是 …」。

**`quant_error_max` 现在真生效（0.18.14 起）**：写在**任务配置**的 `stop_conditions.quant_error_max`
（相对误差，`0.05` = 5%），`commands/train_cmd.sh` 换算成 QSNR 地板 `−20·log10(ε)` 注入
`QAT_QSNR_FLOOR_DB`，探针看门狗在训练中途低于地板即停跑（`EXPERIMENT_INVALID`）。
`runtime/metrics.py` 照旧把探针产物读成 `metrics.json` 的 `quant_error` 段（`status ∈ measured /
unmeasured / probe_invalid`，段里没有 pass/fail）——「没测」与「达标」分得开。

探针怎么开：任务配置 `train.monitor_metrics` 里写了 `quant_error`（模板默认就有）⇒ 起训练时自动
export `QAT_QSNR_PROBE=1`、`QAT_QSNR_EVERY`（取自 `train.qat_probe.every_n_steps`，模板 10）、`QAT_QSNR_OUT=<轮次>/evidence`、
`QAT_QSNR_LABELS={"round":…,"task":…}`。**声明即开关**，不另设旋钮；`LP_QSNR_PROBE=0` 可显式关。
缺这些时探针不装，`quant_error.status` 就是 `unmeasured`（不是「达标」）。
`LP_QSNR_WATCHDOG=0` 只观测不 kill（默认开；`QAT_QSNR_{DROP,FLOOR}_DB` 可换护栏阈值）。

QSNR 与阈值的换算（唯一关系）：`ε = 10^(-QSNR/20)` ⇒ **26.02 dB = 5%**、30 dB = 3.16%、
40 dB = 1%。为什么还不接成停跑闸：本工程没有自己的 QSNR 锚点，拿别人网络的 15 dB 当判据
就是拿护栏当科学结论。详见 `docs/CONFIG.md` §4.6.3。

### 1.3 开一轮：每一步谁做、你做什么

| 步 | 谁 | 产物 / 命令 | **你要做什么** |
|---|---|---|---|
| 0 | 你 ＋ 主 Agent | `bash scripts/start_experiment.sh <任务名>` | 确认 preflight 四项全 ✓ |
| 1 | `architect` | `<轮次>/{design.md,criterion.yaml}` | ★ **点头冻结判据**（"就按这个判吗"）—— 全流程只有这一处必须人 |
| 2 | 门（引擎） | `runtime/validate_round.py <design.md>` | 无。不过 ⇒ architect 重写，**不花卡** |
| 3 | `developer` | `<轮次>/{changes.md,patches/}` | 无。框架表达不了 ⇒ `CODE_FAILED` 指名缺哪个分支 |
| 4 | `tester` | `<轮次>/{test.md,round.env}` | 无。冒烟先行；测试暴露代码缺陷 ⇒ 回 `developer` |
| 5 | `experimenter` | 三段执行 → `metrics.json`／`evidence/`／`report.md`／`conclusions/C-*.yaml` | 无。命中早停 ⇒ `EXPERIMENT_INVALID`（必须说清重跑要改什么） |
| 6 | `architect` | `NEXT_ROUND` 或 `LOOP_STOP` | 决定"接着开 / 停"。`loop.max_rounds` 是**声明式边界**：满了就该给 `LOOP_STOP`，但**引擎不替你停**（0.11.0 删掉了自动探测开关） |

**现在到哪了**：`cat state/STATUS.md`（人读）；机器读 `state/current.json` 的 `stage` 与 `next_action`。
**主 Agent 怎么推**：`AGENTS.md` §4.1（读 `stage` → 派角色 → 收 token → `advance`）。
**为什么轮次目录只有 `start_experiment.sh` 会建**：跳过开跑就一步都走不了 —— 是构造上的，不靠自觉。

### 1.4 常见失败对照

| 现象 | 先看哪里 | 处置 |
|---|---|---|
| `preflight` 报「配置不过」 | 它跟着打印的字段路径 | 改任务配置（契约是 `config/task.schema.json`） |
| `preflight` 报「检出在 X，配置钉的是 Y」 | `git -C <repo> log -1 --oneline` | 把 `*_head` 补成 40 位，或把检出切回钉点 |
| `preflight` 报卡 `[BLOCK] NPU_BUSY` | `npu-smi info` | 等别的作业跑完；`--skip-cards` 只跳过这一项（**不建议**在有作业时开跑） |
| `start_experiment` 报「轮次目录已存在且非空」 | `ls <轮次>/` | 换轮次号；确要重开用 `--force` |
| 门退出 `2` | `<轮次>/test.md` 的显式错误行 | architect 重写方案（不花卡） |
| `stage` 长时间不动 | `state/current.json` 的 `next_action` | 主 Agent 没派活，或子代理交回 token 后没 `advance` |
| 数字对不上 | `<轮次>/metrics.json` | 不许手改；查 `runtime/metrics.py` 的抽取规则 |

**轮次目录**：`<artifacts.root>/rounds/<轮次>/`，其中 `artifacts.root` 的默认值是
`<paths.experiments>/<任务名>`（默认即 `experiments/<任务名>`，**默认值、可配置**）。
一轮的**输入**（`design.md`／`criterion.yaml`／`round.env`）与**档案**（`changes.md`／`test.md`／`report.md`／
`metrics.json`／`evidence/`）**必须同处这一个目录** —— 拆两处就会落出两份真相。

---

## 2. 顶层结构（每一层一个用途）

| 落点 | 一句话用途 | 现状 |
|---|---|---|
| `agents/` | 四个 Agent 的角色定义与 `skills:` 挂载表 | 四份 `AGENT.md` 已建 |
| `skills/` | 过程性知识：怎么设计、怎么改码、怎么扫参、怎么写训练/评测/报告 | **十二份** `SKILL.md` 正文已落盘（P3 九份 ＋ 后续补齐）；正文里仍留的 `TODO(P3)` 是**已点名的缺口**，不是没写正文 |
| `runtime/` | 引擎：起进程、落日志、在线早停、抽数、定卡、加载配置、写状态、挂/还原、**每轮必跑的门** | **九件全部实现**：`metrics.py`／`validate_round.py`（P4）、`framework_patch.sh`（P5）、`state.py`（P7）、`config.py` 的 `validate`（P9）、`executor.py`／`resources.py`／`_common.sh`（P4c）；只剩 `config.py` 的 `resolve-scheme`（`TODO(P1)`）与 `config.py`／`runtime/README.md` 里照实留的两笔记账 |
| `config/` | 模型名/任务名/产物根的**唯一落点**；配置契约（`task.schema.json`） | 三件：`task.schema.json`／`project.yaml`／`tasks/`（`_TEMPLATE.yaml` 是任务配置模板；**0.18.0 删掉了变量字典**） |
| `knowledge/` | 可继承的经验：techniques（**本地验证有效**）／models／frameworks（公共 patch ＋ 理解笔记）／external（**外部来源**：可作候选、未验证） | `models/` 三份与 `external/` **10 篇外部来源**已登记；`techniques/` 仍 0 条（准入＝评估跑完、结论入库） |
| `templates/` | 每轮照抄的骨架，防止自创格式 | 七个顶层模板（`design.md`／`criterion.yaml`／`run.env`／`changes.md`／`test.md`／`report.md`／`state-entry.json`）＋ `commands/`（`train/convert/eval_cmd.sh`、`_taskcfg.sh`、`train_argv.txt` 等骨架）＋ `drivers/lm_eval_driver.py`（0.18.0 起） |
| `experiments/` | 任务目录（脚本与清单，写一次）＋ `<任务目录>/rounds/<轮次>/`（输入与档案） | 形状与逐件说明见 `experiments/README.md`；`run.env` 模板见 `templates/run.env` —— **任务目录由使用者按自己的任务写** |
| `records/` | **跨轮**档案：`conclusions/`（append-only）、`best/`（可覆盖）、`ledger.jsonl`（**唯一**的 append-only 账本；结论**索引是派生视图**，由 `conclusions/` 现算、不落盘） | **P9 起有真实行**：`conclusions/C-0001.yaml`（演练轮 `inconclusive`）＋ `ledger.jsonl` 追加；字段集由 `_EXAMPLE.yaml` 定稿 |
| `state/` | 上层编排读的「现在在哪、下一步派谁、产物在哪」 | **已完成（P7）**：三件由 `runtime/state.py`（唯一写者）的 `init`／`advance`／`close` 写；`rounds.jsonl` append-only |
| `docs/` | 工程本体的设计文档（人读）：**文件与目录地图**、能力图谱、全景介绍、模块关系、状态机、配置契约 | `DESIGN.md`（**先读这一份**：原则/架构/角色/开跑/结果/知识六段全景）＋ `ARCHITECTURE.md`／`PIPELINE.md`／`CONFIG.md`／`MIGRATION.md` ＋ `docs/decisions/D-0001`／`D-0002`；不放旧工程文档副本 |
| `requests/` | **使用者→建设者的诉求**：框架层面缺什么、哪条规则跑不通。**不进流水线**（不发 token、不设门） | 格式见 `requests/README.md`，位置由 `config/project.yaml` 的 `paths.requests` 定 |
| `scripts/` | **开跑入口** ＋ 对工程**外部**的操作：装/卸 Agent 与 skill、建评测环境 | `preflight.sh`／`start_experiment.sh`／`install_agents.sh`／`uninstall_agents.sh`／`install_skills.sh` 已按 §3.5 四条规矩实现；`install_env.sh` **P10 由占位变为实现**（建评测 venv、钉版本、回读自证、拒绝静默换版本、幂等） |
| `devtools/` | **开发期（人触发）自检**，不为每轮实验服务 | **已完成（P8）**：九件全部实现（`README.md` ＋ 八个工具；「10 件」是文档侧回填口径，见 `docs/MIGRATION.md` §6），唯一入口 `bash devtools/run_all.sh`（逐项打印名字与 rc） |
| `tests/` | 正/负对照，验证脚本真能抓错 | `positive_controls.sh`（**16 条**）＋`negative_controls.sh`（**12 条**）＋`pin_negative.sh`（4 条，0.17.0 起） |

目录划分见 `docs/MAP.md`；角色、技能、配置项与能力边界见 `docs/CAPABILITIES.md`。

**两个关键区分**（放错就是静默失败）：

1. **`devtools/` ≠ 每轮门**：`devtools/` 只放**人改工程时**跑的自检；**每轮都过、由流水线在花卡之前调用**的门
   是 `runtime/validate_round.py`。门只放 `devtools/` ⇒ 用户与 agent 每轮都不触发，铁律退化成文档里的一句话。
2. **`experiments/` ≠ `records/`**：前者是**可整体归档、可删除**的任务产物（GB 级，进 `.gitignore`）；
   后者是**append-only、跨轮也跨任务**的耐久档案（KB 级，可进 git）。两者**不合并**。

---

## 3. 每轮流程（谁写什么、谁读什么）

```text
上层编排/用户 ──写──▶ config/tasks/<任务名>.yaml ──▶ 按 agents/ 派活
architect   ──▶ <轮次>/{design.md, criterion.yaml}                 [ARCHITECT_READY]
   ★ 每轮必跑的门：runtime/validate_round.py（方案冻结、花卡之前）—— 不过 ⇒ 拒绝开跑，错误行进 test.md/report.md
developer   ──▶ <轮次>/{changes.md, patches/}                      [CODE_READY / CODE_FAILED]
tester      ──▶ <轮次>/{test.md, round.env}                        [TEST_READY / TEST_BLOCKED]
experimenter──▶ <轮次>/{report.md, metrics.json, artifacts.json, evidence/}
             ＋ records/conclusions/C-<序号>.yaml                  [EXPERIMENT_DONE / EXPERIMENT_INVALID]
architect   ◀── 反馈环：report.md ＋ conclusions/ ──▶ knowledge/    [NEXT_ROUND / LOOP_STOP]
state.py    ◀── 四个 Agent 每次交接 ── state/{current.json,rounds.jsonl,STATUS.md}
```

**一个数字只有一个家**：`<轮次>/metrics.json` 是数字的唯一落点（`runtime/metrics.py` 机械算出，谁都不许手改、不许四舍五入）；
`records/` 只放工具生成的派生结论，结论里**引用**轮次目录的路径而不复制数字。

**四类旋钮别混**：① 任务配置（`config/tasks/<任务名>.yaml`，定场景）→ ② 方案自变量（`design.md` 的 `variables:` 段，定选了什么）
→ ③ 实现手段（`design.md` 的 `implementation:` 段 ＋ `<轮次>/patches/`，定怎么落地）→ ④ 判据与终止（`criterion.yaml`，定怎么算通过、何时停）。
②的键名与取值**由 architect 读框架代码判定**（没有白名单字典；正文里写清每个旋钮的 `file:line` 依据）；④**跑前冻结、跑后一字不改**。

---

## 4. 新工程与旧工程的边界（重要）

| 项 | 约定 |
|---|---|
| 旧工程的 `records/` 数据 | **留在旧工程**，按需**只读**引用；新工程 `records/` 从空账本开始 |
| 旧工程的文档 | **不搬、也不改写后搬**（`docs/`、`records/*.md` 一类）—— 那些是旧工程的历史，搬过来就是第二份真相 |
| 训练框架检出 | 任务配置 `train.framework_repo` 指向的检出**永不提交改动**。改动一律以轮的 `patches/` 挂载（建议挂到按需切出的 `git worktree`）、**跑完即还原**，前后 `rev-parse HEAD` 与 `status --porcelain` 必须为空 |
| 本工程是否进版本控制 | 本工程是**独立的 git 仓库**（P0 已 `git init`）。**提交只由主 Agent 执行**，子代理禁一切 git 写操作；`experiments/**/rounds/` 等 GB 级轮次产物由 `.gitignore` 排除，`records/` 这类 KB 级 append-only 档案进仓 |

`docs/` **只写本工程本体的机制**：`DESIGN.md`（**全景介绍，第一次读它**：原则/架构/角色与状态机/skill/开跑/
结果维护/知识沉淀）／`ARCHITECTURE.md`（模块关系与调用图）／
`PIPELINE.md`（状态机与交接词）／`CONFIG.md`（配置契约与路径优先级）／`CAPABILITIES.md`（能力图谱：角色/技能/配置项/不支持的情形）／
`MIGRATION.md`（迁移落地记录，**建设者文档，不随包**）／
`decisions/D-<序号>-<简述>.md`（一条决策一份，append-only）。**没有内容就不建空文件**；
旧工程的文档**不搬、也不改写后搬**。

---

## 5. 只读与禁令（任何角色都不许改）

- **只读契约**：`config/task.schema.json`（要向框架加旋钮 ⇒ 写成 `implementation.patch`，不是改契约）。
- **只读产物**：`<轮次>/metrics.json`、`<轮次>/evidence/**`、`<轮次>/patches/framework_*.{before,after}`。
- **只允许追加**：`<轮次>/**`（定稿后）、`records/{conclusions,ledger.jsonl}`、`state/rounds.jsonl`（结论索引是派生的，不落盘）。
- **永不提交**：框架检出（`MindSpeed*`／`Megatron-LM`）的任何改动。
- **唯一落点**：模型名／任务名／阈值／路径**只许**出现在 `config/` 与任务目录／轮次目录；出现在 `runtime/`、`agents/`、`skills/` 里
  由 `devtools/check_decoupling.py` 判失败（P8 起可用：`python3 devtools/check_decoupling.py`）。

---

## 6. 版本三件套（缺一个，事后就复现不出那一轮）

| 文件 | 说什么 |
|---|---|
| `VERSION` | **框架版本**：机制是哪一版（单行，`wc -l` 必须为 1） |
| `ReleaseNotes.md` | 每个版本一段；**每轮实验结束必须追加一行**：框架版本 ＋ 配置版本 ＋ 框架仓库版本 |
| `config/tasks/<任务名>.yaml` | **配置版本** `config_version` = 任务配置内容哈希前 8 位 |
| `train.{framework_head,core_head}` | **框架仓库版本**：本轮起点钉在任务配置里的提交号（两仓各一个；`core_*` 可省） |

### 6.1 subagent 的推理档位：本工程不指定，走注册表默认

`agents/*/AGENT.md` 的 frontmatter **不写 `thinking`**（0.20.2 起）。原因：一旦写了档位，而这台机器的
模型 provider 没有在声明里列出该档位（`reasoningEfforts`），失败会发生在**派活那一刻**——agent 装成功了、
配置也没报错，只有派发时才炸，最容易被误判成本工程的 bug。

- 要指定档位：在 harness 侧（`~/.dsh/settings.yaml` 的 provider 声明，或注册表里那份 agent 文件）加，
  **不写进本工程目录**；换机器／换网关都要重配。
- `scripts/install_agents.sh` 与 `devtools/validate_agents.py` 仍保留"若出现则必须合法"的校验；
  `thinking` 不出现就跳过。

