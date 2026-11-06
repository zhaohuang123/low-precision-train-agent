# 配置契约（CONFIG）—— 字段落在哪、路径怎么解析、谁校验

> 给谁看：人。讲**配置契约与路径优先级**：什么字段写在哪、缺失时怎么办、由谁机械校验。
> **格式与字段的唯一来源**：`config/task.schema.json`（机器契约）、
> `knowledge/README.md`（知识条目格式）。本文件只描述契约与优先级，**不另写一份默认值表**。

## 1. 配置根与路径解析（fail-closed）

- **配置根** ＝ `config/project.yaml` 所在的那个工程根。任务级入口第一行解析出 `LP_ROOT`，
  **解析不出来就退出 `2`** —— 不许猜、不许按当前工作目录反推。
- `runtime/*.py` 的配置根解析顺序：`--root` → 环境变量 `LP_ROOT` → 本文件上一级。**指错不回退**：
  那棵树里没有 `config/project.yaml` 或 `VERSION` ⇒ 退出 `2`。
- **相对路径一律相对配置根**，不相对当前工作目录、不相对脚本所在目录。

### 1.1 `paths.*` 与 `artifacts.root` 的优先级（从高到低）

| 层级 | 落点 | 是什么 | 默认值 |
|---|---|---|---|
| ① 任务级 | `config/tasks/<任务名>.yaml` 的显式字段（含 `artifacts.root`） | 覆盖下面两层 | —— |
| ② 工程级 | `config/project.yaml` 的 `paths.*` | 给所有任务提供路径默认值；**不含模型名/任务名** | `tasks: config/tasks`／`experiments: experiments`／`records: records`／`state: state`／`knowledge: knowledge` |
| ③ 内建默认 | `runtime/config.py` | 缺失时的最后兜底，并在加载日志打印一行「用了内建默认」 | 同左列 |

`artifacts.root` 的默认值是 `<paths.experiments>/<任务名>`（**默认值、可配置**）；
**轮次目录** ＝ `<artifacts.root>/rounds/<轮次>/`，位置**只由 `artifacts.root` 决定**。
任务目录与产物根**默认重合、允许分开**：把 `artifacts.root` 指到工程外的大容量盘时，
任务级脚本仍留在工程内、轮次与证据落到那块盘。

### 1.2 一轮的输入与档案必须同处一地

`design.md`／`criterion.yaml`／`round.env`（输入）与 `changes.md`／`test.md`／`report.md`／
`metrics.json`／`artifacts.json`／`evidence/`（档案）**必须在同一个轮次目录** —— 拆两处就会落出两份真相。
跨轮的东西只剩四类，全部留在 `<paths.records>/`：`conclusions/`（append-only）、`best/`（可覆盖）、
`ledger.jsonl`（**唯一**的 append-only 账本；结论索引是派生视图，不落盘）。轮次里的东西一律不在 `records/` 下，
`records/` 下也**不再出现任何 `<轮次>` 目录**（由 `devtools/check_round_layout.py` 查）。

## 2. 四类配置分栏（写在哪，不由「好不好找」决定）

| 类 | 内容 | 落点 | 可变性 |
|---|---|---|---|
| ① 任务配置 | 模型名／来源／精度、评测任务类型与数据集、产物根、监控指标、外部知识来源与关键字、循环开关、框架仓库 | `config/tasks/<任务名>.yaml`（**一份**） | 角色跑实验时**只读**；内容变只变 `config_version` |
| ② 方案自变量 | 本轮选了什么、要不要改代码 | `<轮次>/design.md` 的受控 YAML 块 `variables:`（**只能从字典取值**） | architect 写；跑前冻结 |
| ③ 实现手段 | 落地形态、框架原生开关、patch 引用与实物 | `<轮次>/design.md` 的 `implementation:` ＋ `<轮次>/patches/` | developer 写；纯配置时允许为空 |
| ④ 判据与终止 | 成功条件、证伪条件、终止阈值、预算、评测口径 | `<轮次>/criterion.yaml`（独立文件、**跑前冻结、跑后一字不改**） | architect 写、人冻结 |

## 3. `config/project.yaml`（工程级，不含模型名/任务名）

| 作用域 | 字段 | 语义 |
|---|---|---|
| 版本标记 | `schema: 1` | **保留字段，当前没有读者**（不校验、不参与任何判断）；改它不会改变行为 |
| 路径 | `paths.{tasks,experiments,records,state,knowledge}` | 见 §1.1；相对配置根 |
| 诉求 | `paths.requests` | 使用者→建设者的诉求目录（默认 `requests`）；**不进流水线**，格式见 `requests/README.md` |
| 定卡 | `devices.{usable,reserved,require_explicit}` | 定卡**策略**；真正「卡号从哪来」的唯一实现是 `runtime/resources.py`（策略／实测／决策＋来源） |
| 数据根 | `data.{root,runs}` | 权重/数据集/运行产物的盘位（★ 0.18.0 删掉了 `dataset`／`models`：无任何代码读者；具体落点永远在任务配置） |
| 资产获取 | `fetch.{hf_endpoint,hf_mirror,min_free_gb}` | 模型/代码下载的**环境事实**（端点、镜像、下载前要求的最小空闲 GB）；只给 `scripts/fetch_model.sh`／`scripts/fetch_code.sh` 读。**不放**「下哪个模型/哪个仓」——那是任务配置的事 |

`require_explicit: true` ⇒ 不许隐式选卡，必须由 `runtime/resources.py` 给出「策略/实测/决策＋来源」。

## 4. `config/tasks/<任务名>.yaml` 与它的机器契约

**模型名／任务名／数据集名／精度只在 `config/tasks/<任务名>.yaml` 出现**（其他任何目录出现即由
`devtools/check_decoupling.py` 机械判失败）。模板是 `config/tasks/_TEMPLATE.yaml`——**要照抄就看它**，
每个字段都带注释；本节逐字段讲"为什么有它、写错会怎样"。

**最小可跑的一份**（下面各节是对其中每一块的展开）：

```yaml
schema: 1
task_id: "<任务名>"                    # 与文件名 <任务名>.yaml 一致
model:
  name: "<模型名>"
  precision: "w4a4"
  source: {url: "https://...", path: "/data/models/<模型名>"}
  start:  {format: mcore, path: "/data/models/<模型名>-mcore"}
train:
  data_path: "/data/datasets/<语料>"
  framework_repo: "<框架检出的绝对路径>"
  framework_head: "<40 位提交号>"
  core_repo: "<核心层检出的绝对路径>"
  core_head: "<40 位提交号>"
  monitor_metrics: [loss, quant_error]
  qat_probe: {every_n_steps: 10}
  checkpoint: {save_interval_steps: 50, keep_last: 2}
eval:
  engine: lm_eval
  task_type: generation
  lm_eval: {package: lm-eval, version: "0.4.13", python: "<评测 venv>/bin/python", driver: "<任务目录>/drivers/lm_eval_driver.py"}
  protocol: {num_fewshot: 5, max_gen_toks: 512, batch_size: 4, prompt_type: "<模板名>"}
  datasets: [{name: "<数据集>", path: "/data/datasets/<数据集>"}]
artifacts: {root: default}             # 展开为 <paths.experiments>/<任务名>
stop_conditions:
  max_steps: 300
  quant_error_max: 0.05
  wall_clock_hours: 6
  loss: {jump_factor: 4.0, rel_to_best: 2.5, min_points: 10}
knowledge:
  external: {sources: ["https://arxiv.org/abs/<id>"], keywords: ["<检索词>"]}
intents: ["<一句话目标 ＋ 可验收边界>"]
loop: {max_rounds: 3, no_progress_rounds: 2}
```

校验：`python3 runtime/config.py validate config/tasks/<任务名>.yaml`（不通过逐条打印字段路径，退出 `2`）。
上面示例里的 `<…>` 是**占位值**，校验器会跳过路径存在性；换成真路径后再跑一次必须通过 —— **本文档这份示例实测 rc=0**。

契约文件 `config/task.schema.json`（**唯一执行者**是 `runtime/config.py`）：

- 顶层 `required`：`schema`／`task_id`／`model`／`train`／`eval`／`artifacts`／`knowledge`／`loop`；
- 嵌套必填：`model.{name,precision,source}`、`train.{framework_repo,monitor_metrics}`、
  `eval.{engine,task_type,datasets}`（每集只要 `name`）、`artifacts.root`；
- `objective`（可选）：一句话目标，**纯说明字段，没有任何读者**（不参与校验、不参与判定）；
- 可选但决定"能不能复现"的：`train.framework_head`／`train.core_repo`／`train.core_head`（**两仓钉点**；
  形状**不在**这里校验 —— `git` 是权威，见 `scripts/preflight.sh`）、`eval.protocol`（全局默认，
  `datasets[].protocol` 逐键覆盖、写 `null` 表示显式清空）；
- `train.{framework_url,core_url}`：两仓**远端 URL**（可选），只给「从零下载 / 切换分支」用（`scripts/fetch_code.sh`）；
  为空 ⇒ 回退该检出的 `git remote get-url origin`。它们**不是钉点** —— 切换后必须同步改 `framework_head`／`core_head`，否则 `preflight.sh` 拒绝开跑。
- `additionalProperties: false` 逐层打开（**拼错的键会报「多余字段」**）。
  **代价明写**：以后要加一个新字段，必须**先**登记进 `config/task.schema.json`，否则合法配置也会被拒 ——
  这是契约文件的本意（字段集只有一个落点）。
- `runtime/config.py` 只实现 draft-07 的**已声明子集**；schema 里出现它没实现的**校验用**关键字 ⇒ 退出 `2`
  （fail-closed，不许静默跳过一条校验）。

`runtime/config.py` 另外执行三条 schema 表达不了的**语义规则**（都打印字段路径）：

1. **占位值规则**：值里出现 `<...>`、为空串、或是 `default` ⇒ 视为占位，**跳过存在性检查**
   （所以模板里 `/data/models/<model-name>` 这类带前缀占位不会误杀）。
2. **路径类字段存在性**（只对具体值判；相对路径相对配置根）：`train.framework_repo`（必须是目录）、
   `model.source.path`、`eval.datasets[].path`。**没判**的：`eval.lm_eval.python`（venv 可能尚未创建）、
   `eval.lm_eval.driver`（驱动住任务目录，其存在性由三段入口的跑前准备查）、`artifacts.root`（由跑前准备创建）。
3. `task_id` 是**路径名**：不许含 `/`、空白，不许是 `.`／`..`（它决定 `<paths.experiments>/<任务名>`）。

用法与退出码：

```bash
python3 runtime/config.py [--root <配置根>] <任务配置.yaml>            # 与下行等价
python3 runtime/config.py [--root <配置根>] validate <任务配置.yaml>
python3 runtime/config.py [--root <配置根>] resolve-scheme <任务配置.yaml> [--out <文件>]
#   0 通过（validate 打印一行 OK；resolve-scheme 逐行打印「字段 = 实际值 ← 来源」）
#   2 不通过（逐条打印字段路径）／用法错／根解析不出／schema 用了没实现的关键字
```

**P4d 起 `resolve-scheme` 已实现**（`TODO(P1)` 收口）：展开任务配置里可省略／写成 `default` 的**路径类**字段
（`artifacts.root`、`paths.*`）并逐行打印实际值＋来源；`--out <文件>` 另落一份 JSON —— 它就是
`<轮次>/scheme_resolved.json` 的生产者（父目录必须已存在，本文件**不建目录**）。

**已随字典删除而作废**：§10 规则 5 的另一半 —— `design.md` 受控块里 `variables.<名>.value: default` ⇒ 按字典
`default` 展开 —— 0.18.0 删掉了旋钮字典，"字典默认值"这个落点不存在了。给 `resolve-scheme` 一个 `.md` 仍**明确拒绝**（`2`）。
另外 `artifacts.root` 的**跑前创建**两个子命令都不做（它们是只读的）。
★ 一处**契约自相矛盾**（只报告、未改 schema）：`config/task.schema.json` 既把 `artifacts` 列进顶层 `required`，
又在其 `description` 里写「缺失或写成 `default` ⇒ 展开为 `<paths.experiments>/<任务名>`」。
按 P1 验收实现的结果是**两个入口行为不同**：裸 `validate` 缺 `artifacts` ⇒ `2`；`resolve-scheme` 缺 `artifacts` ⇒ 展开并 `0`。
★ YAML **解析原语只有一份**（P4d 起住 `runtime/config.py`，`validate_round.py` 改为 `from config import ...`）；0.18.0 起不再有"旋钮字典"这个被解析对象。

### 4.1 `eval.protocol` 与逐集覆盖（评测口径）

评测口径只在两处写：**任务配置定默认**（本节），`<轮次>/criterion.yaml` 的 `eval_protocol` **定本轮**；
两者必须逐项一致——判据侧与任务侧各写一份口径，迟早对不上。

| 键 | 含义 | 不写会怎样 |
|---|---|---|
| `num_fewshot` | 少样本示例数 | 不传 ⇒ 走 `lm_eval` 默认；跨轮比较时口径可能悄悄漂 |
| `max_gen_toks` | 生成任务的最大生成长度 | generation 用它；multiple_choice 用不上（走日志似然口径） |
| `batch_size` | 评测批大小 | 只影响显存与耗时，不影响指标 |
| `prompt_type` | 提示模板名 | 模板不同 ⇒ 分数不可比 |

**覆盖规则**：`eval.datasets[].protocol` **逐键覆盖**全局 `eval.protocol`；覆盖写 `null` = **显式清空继承**
（该集回到 `lm_eval` 默认，而不是沿用全局）。`datasets[].task_type` 同理覆盖全局 `eval.task_type`。

```yaml
eval:
  engine: lm_eval
  task_type: generation                 # generation | multiple_choice（单集可覆盖）
  protocol:                             # 全局默认口径
    num_fewshot: 5
    max_gen_toks: 512
    batch_size: 4
    prompt_type: "<模板名>"
  datasets:
    - name: "<数据集A>"                 # 名字进 lm_eval --tasks，也是 metrics 复合键前缀（不许含 /）
      path: "/data/dataset/<A>"
    - name: "<数据集B>"
      path: "/data/dataset/<B>"
      task_type: multiple_choice        # 单集覆盖任务类型
      protocol: {max_gen_toks: null, num_fewshot: 0}   # 逐键覆盖；null = 显式清空
```

生效值由 `templates/commands/eval_cmd.sh` **一次算完**并写成 `--protocols-json` 交给驱动；驱动只吃
`--tasks/--dataset/--protocols-json`，**不自己读配置**（读第二份就会各算一次）。

### 4.2 `model.start.*` 与 `train.data_path` —— 部署事实的唯一落点

```yaml
model:
  source: {path: "/data/.../Qwen3-4B"}        # 从哪来（原始 HF 权重，记出处）
  start:                                       # 这一轮 `--load` 吃哪份
    format: "mcore"                            # hf | mcore
    path: "/data/.../ckpt/qwen3_4b_base_mcore"
    convert: {model_type_hf: "qwen3", tp: 1, pp: 1}   # 仅「目标不存在、需要转一次」时用
train:
  data_path: "/data/dataset/..."               # 训练语料
```

为什么单独开一节：**这两处是「换机器就得改」的东西**。它们一旦写进任务目录（`run.env`、`commands/train_argv.txt`），
任务目录就不再可迁移 —— 而任务目录里的三段入口与命令脚本本该**逐字相同**地出现在任何部署里。

- **`source` 与 `start` 是两个事实**，别合并：`source` 回答「这个实验从哪个原始权重来」（复现出处，永远指 HF）；
  `start` 回答「这一轮加载哪份」（可以是转换产物，也可以是上一轮训练产物）。
- **`format` 必须显式写**：守卫据此判断该查什么文件（`mcore` ⇒ `latest_checkpointed_iteration.txt`；`hf` ⇒ `config.json`），
  不许靠猜目录里有啥。
- **`start.path` 不参与存在性校验**（`config.py` 的 `PATH_FIELDS` 只有三个路径 ＋ `eval.datasets[].path`）——
  因为它可能**还不存在**，那正是要转换的理由。真正拦住的是训练命令拼装时的守卫（退出 `2`）。
- **`convert.*` 只在需要转换时读**：`model_type_hf` 必填（写错型号会转出「看着正常」的错误权重），`tp`/`pp` 默认 1。
  幂等规则：**目标已存在且像 mcore 检查点 ⇒ 一律跳过**（`scripts/convert_weights.sh`，流程见 `skills/weights-convert`）。
- 部署侧自检：任务目录里**不该出现任何绝对路径** →
  `grep -rn "/data/" experiments/<任务>/ --include="*.sh" --include="*.txt" --include="run.env"` 应只命中注释。

### 4.3 `train.qat_probe.*` 与 `train.checkpoint.*`（0.18.26，**必填**）

```yaml
train:
  qat_probe:
    every_n_steps: 10        # 探针采样频率（>=1）；10 ⇒ 300 步 30 个点
  checkpoint:
    save_interval_steps: 50  # 每多少步存一份（>=1）
    keep_last: 2             # 只留最近几份（>=1）
```

| 键 | 谁读 | 生效方式 |
|---|---|---|
| `qat_probe.every_n_steps` | `commands/train_cmd.sh` | export `QAT_QSNR_EVERY`（探针采样步） |
| `checkpoint.save_interval_steps` | `train_cmd.sh` | 拼进 `--save-interval`（argv 占位符 `${save_interval}`） |
| `checkpoint.keep_last` | `runtime/_common.sh` → `runtime/executor.py` | 训练期间每 60 s 删旧 `iter_*`，只留最近 N 份 |

**磁盘账**（先 `du -sh <ckpt>/iter_0000100` **量一份**再定额，别照抄估算）：
只有 bf16 权重 ≈ **8.5 GB/份**（Qwen3-4B 量级）；权重 ＋ fp32 主权重 ＋ Adam 两阶矩（全量状态）
≈ **55 GB/份**。峰值 = 份数 × 单份大小（`50` 步 / `keep_last: 2` 在全量状态下 ≈110 GB，
只存权重时 ≈17 GB —— 差 6 倍，按哪个估决定了你敢留几份）。
★ **`keep_last` 别为省盘压太小**：执行器的刈草只留最近 N 份，判据若点名早期 `ckpt/iter_*`
（如 `iter_0000100`），压到 2 就把它删了 —— `validate_round.py` 会算"结束时还剩哪些"给你看。
单份保存耗时实测 **12.9 s**（300 步 6 次 ≈ 78 s，墙钟 <1%）。框架**没有**保留开关，
所以"删旧份"只能在进程外做；六条安全规则见 `runtime/executor.py` 的 `prune_checkpoints()`。

**续跑**：`<任务目录>/train.sh --round R-000N --resume latest`（或给具体 ckpt 目录）。
它把 argv 改成"接着跑"的形状：`--load <ckpt>`、去掉 `--finetune`、去掉 `--no-load-optim/--no-load-rng`
⇒ 框架从 ckpt 恢复迭代数与优化器/RNG。**`--resume` 只对 train 段有意义**，参数不合法 ⇒ 退出 2。

### 4.4 `train.extra_pythonpath[]` —— 训练侧"另一半代码"的唯一落点（0.18.30）

```yaml
train:
  extra_pythonpath: ["/path/to/Megatron-LM"]     # 绝对路径；顺序＝sys.path 顺序
```

存在理由：训练侧要 import 的代码并不都在 `train.framework_repo` 里（例如与 MindSpeed-LLM 配对的
Megatron-LM 检出）。没有这个字段时，唯一可行的写法是 `run.env` 里 `export PYTHONPATH=...`，
而那等于**同一个事实两处落点**（配置里没有、命令里却有），换机器就静默变。

**四条规矩**（实现只有一处：`templates/commands/_taskcfg.sh::taskcfg_extra_pythonpath`）：

| 规矩 | 为什么 |
|---|---|
| 只认**绝对路径**（相对 ⇒ 退出 `2`） | 相对哪个 cwd 不确定：executor 起独立 bash 进程，cwd 随段而变 |
| 目录**必须存在**（否则退出 `2`） | 打错一个字就静默 import 到别的版本，比现在退 2 贵得多 |
| 顺序＝`sys.path` 顺序（左＝优先） | 重名模块靠它定优先级，不能靠"碰运气" |
| 缺省／空列表 ⇒ **完全不设** `PYTHONPATH` | 空值等于把当前目录塞进 `sys.path` ⇒ 变成"悄悄能 import 到别的目录" |

拼出来的形式是 `PYTHONPATH=<本字段>:$PYTHONPATH` —— **原有的值接在后面、不覆盖**：
算子/驱动栈（例如 CANN 的 site-packages）常靠环境里的 `PYTHONPATH` 才找得到，覆盖它会把
训练直接弄坏。

**为什么 `eval` 段不注入**（这一条最容易被误改成"三段都注入"）：

1. 评测的口径只依赖 `eval.lm_eval.*` 与驱动，驱动 `drivers/lm_eval_driver.py` 只用**标准库**，
   再把 lm-eval 当命令 `subprocess` 起 —— 它不需要训练侧那一半代码；
2. 注入它会让"评测环境"多一个隐式输入：同一份 HF 产物在不同 `PYTHONPATH` 下可能给出不同数字，
   而 `criterion.yaml` 是跑前冻结的 —— 数字的来源必须能在一处说清；
3. 反过来，评测**真的**需要额外模块时，那是 `eval.lm_eval.python` 那个 venv 的事（`install_env.sh`），
   不是 `sys.path` 里塞目录。

> `templates/commands/convert_cmd.sh` 也注入（它复用同一份检出做权重转换，需要同一套模块）；
> 它同样**不是**评测口径的一部分。

### 4.5 `intents[]` —— 多轮实验的起点（append-only，一次尝试 = 一条）

一条 intent 有两种合法形状（`config/task.schema.json` 用 `oneOf` **严格约束**：对象缺 `text` 或带多余键 ⇒ 校验退出 `2`）：

```yaml
intents:
  # 形状 A：一句话。没有专门检索计划，用任务级 knowledge.external 与 loop
  - "先把 W4A4 训练链路跑通：相对 fp16 基线掉分 ≤ 3 分（首轮只验可行性）"

  # 形状 B：一个对象 = 一次完整的尝试（检索计划 ＋ 轮次预算）
  - text: "试 2D 方块量化 + MXFP8 Q/K，压住 W4A4 不稳定"
    external:                       # 这次尝试怎么取线索
      keywords: ["transposition-invariant block quantization", "mxfp8 qk projection"]
      sources: ["https://arxiv.org/abs/2607.24953"]   # 必读 URL，architect 用 web_fetch 逐条读
    loop: {max_rounds: 3, no_progress_rounds: 2}      # 这次尝试最多几轮、连续几轮无进展就停
```

- **谁写**：人（或主 Agent 代笔）。**只许往末尾追加**，不改写既有条目 —— 已做过的实验不能被
  事后改写。要换词／换目标 ⇒ 追加一条新的（这就是"一次尝试"的边界）。
- **谁读**：`architect`。它每轮挑**一条**，并在本轮 `<轮次>/design.md` 顶部写
  `- intent_ref: <序号>「原文首句」`（一行、正文、可 grep）。**预算计数只认这一行**（派生，见下）。
- **取值优先级**（两条入口之一，另一条是 `knowledge/external/` 归档）：
  `intent.external.keywords` → 任务级 `knowledge.external.keywords` → 都没有 ⇒ 不检索并在
  `design.md` §2.2 写「未配置」。`loop` 同理：intent 里省掉的键回落任务级同名键。
- **轮次怎么数**：`state` **不记** intent 维度，按 `design.md` 的 `intent_ref` 派生：
  `grep -rl 'intent_ref: *<N>' <artifacts.root>/rounds/*/design.md | wc -l`。漏写那一行 ⇒
  该轮不归属任何一次尝试（表现为预算用不完）——这是唯一的软肋，`agents/architect/AGENT.md` 把它列为必写项。
- **任务级 `loop` = 总上限**（对所有 intent 合计）＋缺省值。两级都还有余量才开下一轮。
- **为什么不参与 `config_version`**：它是想法区，不是本轮输入。参与的话，人开跑中途追加一条想法
  就会让状态与配置"不一致"，而重钉 state（`state.py init`）会把 `stage` 重置回 `architect`
  —— 追加一条想法毁掉进行中的一轮。指纹只认**实验输入**：模型／精度／评测口径／钉点。
  **注意**：`intent.external` 因此可以每轮不同而不动指纹 —— 这是它放在 `intents` 里、而不是放在
  任务级 `knowledge.external` 的唯一理由。
- 不写实现（怎么改、改哪个 patch）—— 那是 `design.md`／`changes.md` 的事。

### 4.6 `stop_conditions` 子字段逐条含义

本块**五个键全部真生效**，读者都在引擎里（0.18.18 起；此前 `loss.*` 与 `wall_clock_hours` 的读者
在判据那条线上，于是人填的这一份没人读 —— 能力只剩纸面）：

| 键 | 谁读 | 生效方式 |
|---|---|---|
| `max_steps` | `commands/train_cmd.sh` | 拼进 `--train-iters` —— **决定训练多少步** |
| `quant_error_max` | `train_cmd.sh`（0.18.14 起） | 换算成 QSNR 地板 `−20·log10(ε)` → `QAT_QSNR_FLOOR_DB`，探针看门狗据此中途停跑（见 §4.1.1） |
| `loss.jump_factor` | `runtime/_common.sh` → `runtime/executor.py` | 相邻步 loss 比值超它 ⇒ **在线早停并杀训练** |
| `loss.rel_to_best` | 同上 | 末步/最好步超它 ⇒ 在线早停 |
| `loss.min_points` | 同上 | 离线观察至少几个点才下结论 |
| `wall_clock_hours` | 同上 | 单轮墙钟上限，到点杀整个进程组、退出 `5`；**必须 > 0** |
| `plateau.*`（0.18.26，可选） | 同上 | **平台早停**：loss 不再明显下降就收工，留痕 `stop_kind=converged`、退出 **0**（合法结论，不是作废）。整块不写 ⇒ 关闭 |
| `holdout.*`（0.19.0，可选） | `runtime/_common.sh` → `executor.py` | **held-out racing**：验证 loss 相对 `records/best` 那一轮落后超阈且不收窄 ⇒ 停、留痕 `stop_kind: holdout`、退出 `5`（这一轮不作结论）。参照轮**不是配置项**，从 best 档案的 `round:` 现算 |

★ 这几项是**运行期保险丝与预算**，不是"算不算成"：唯一落点是本文件，**不再抄进判据**
  （判据只管 `success.require`／`falsification`／`eval_protocol`／`budget`）。旧轮次的
  `criterion.yaml` 里还有一份 `stop_conditions`，那是归档，引擎不读。
★ 取值守卫（缺一项／写反就退出 `2`，不猜默认值）：`jump_factor > 1`、`rel_to_best > 1`、
  `min_points >= 1`、`wall_clock_hours > 0`。`wall_clock_hours: 0` **不等于**"没有上限"，
  它是错值 —— 0.18.18 之前执行器会把它当成"没给"，静默无限等一张卡。
★ `no_progress_rounds` **不在**这里：它在 `loop` 下（0.18.5 删掉了 `stop_conditions` 里那条重复且
  **无任何读者**的键 —— 连 `_common.sh` 的 `LP_STOP_KEYS` 里都没有它）。

#### 4.6.1 held-out racing（`stop_conditions.holdout.*`，0.19.0，可选）

**要解决的问题是"训练效率"**：一轮跑到一半就能看出它没希望赢历史最好，就该把卡让出来，
而不是烧满 300 步再判。判据是**相对位置**，不是曲线形状：

```
gap(s) = val_本轮(s) / val_best(s) − 1        # 正 = 落后
停：s ≥ min_step ∧ 最近 patience 个点 gap 都 > max_gap_pct ∧ gap 没有收窄
```

| 键 | 含义 | 守卫 |
|---|---|---|
| `min_step` | 跳过 warmup：不足这么多步不判（低精度方案常"慢热"） | `>= 1` |
| `max_gap_pct` | 允许落后 best 的比例（`0.05` = 5%） | `>= 0` |
| `patience` | 连续几个验证点都超阈才停（抗噪） | `>= 1` |

**三条硬规则**（缺一条就不判 —— 宁可不判也不猜）：

1. **参照轮由 `records/best/<任务名>__<指标>.yaml` 的 `round:` 现算**，不在任务配置里点名。
   理由：best 那一轮天然"跑完 ＋ 通过判定 ＋ 证据齐全"，不用再从 `design.md` 认身份。
   找不到 / 有多份 / 那一轮没有验证曲线 ⇒ **本轮不判**（止损仍在），`metrics.json` 的
   `holdout.baseline.reason` 会写明是哪一种。
2. **只比两边都评过的 step**，**不插值**。验证点必须落在同一批 step 上才可比。
3. **"没有收窄"是必须条件**：低精度方案常见"慢热后追平"，只看落后幅度会误杀。

**前提：训练 argv 里必须有验证集。** 这是**任务事实**，唯一落点是
`<任务目录>/commands/train_argv.txt`：

```
--split 98,2,0          # 第二段 = 验证比例（或改用 --valid-data-path <独立验证集前缀>）
--eval-iters 10         # > 0 才会打验证行；0 = 不评验证集
--eval-interval 10      # 每多少步评一次 —— 跨轮必须一致，否则两边点对不上
```

执行器**开跑前**核对这三项（没验证集 / `--eval-iters 0` ⇒ 退出 `2`）：配了 racing 却不打
验证行等于"配了不用"，比"没配"更该炸。默认模板是 `100,0,0` ＋ `--eval-iters 0`，即
**不开验证集**（历史轮次都是这样，所以它们的验证曲线补不出来）。

**写法**：`holdout` 用**块风格**（`metrics.py` 的 YAML 读取器只认块风格；`holdout: {…}` 这种
流式写法两侧会不一致）。为此**实际生效值以 `evidence/train.exec.json` 的
`holdout.thresholds` 为准** —— 离线判据优先读它（`thresholds_source` 会写明来源），
任务配置只是退路，两侧不会各算一次。

**留痕**：`metrics.json` 的 `holdout` 段记 `baseline.{record,round,metrics,fingerprint,reason}`、
`valid.{points,curve,...}`、`racing.{fired,reason,points,...}`。参照换了会写进 `note` ——
**看得见，不阻止**。`is_verdict` 恒 `False`：停是事实，"这轮算不算数"归 `criterion.yaml`。

#### 4.6.2 平台早停（`stop_conditions.plateau.*`，0.18.26）

| 键 | 含义 | 取值守卫 |
|---|---|---|
| `window_steps` | 窗口宽度：取最近 W 点中位数 vs 再前 W 点中位数 | `>= 2` |
| `min_gain_pct` | 改善阈值（百分数，`2.0` = 2%）：改善小于它记一次"平台" | `> 0` |
| `patience` | 连续命中几次才停（抗噪） | `>= 1` |
| `min_steps` | 最低步数，不足不谈平台 | `>= 1` |

**为什么比中位数而不是单点**：实测（`/mnt/share/train.log`，300 步 × 54.2 s/步）平台期
20 步窗的相对标准差中位 **3.8%**，单步比较必然被骗。

**实测标定**（同一条日志，末 10 点中位基准 1.0864）：

| 参数 | 停在第几步 | 省墙钟 | 停下时末 10 点中位 |
|---|---|---|---|
| W=30 / X=2.0% / patience=2 / min_steps=40 | **84** | **72%（≈3.2 h）** | 1.0965（+0.9%） |
| W=20 / X=1.0% / patience=2 | 69 | 77% | 1.1356（+4.5%） |

W 越窄、X 越贴噪声，越容易抢跑 —— 模板默认给的是上面第一组。

**语义**：命中 ⇒ executor 杀掉训练进程、marker 写 `stop_kind: converged`、**退出 0**。
这一轮的结论**有效**（`EXPERIMENT_DONE`，不是 `EXPERIMENT_INVALID`），但它是**停止轮次**：
训练侧 loss／步数类量**不得**与跑满轮次直接比；下游评测可以比（那是"各自停止点上的模型质量"）。

#### 4.6.3 量化误差（QSNR）：门槛在任务配置、护栏在探针

探针在框架侧（核心层实现 + LLM 层接线，由 `QAT_QSNR_PROBE=1` 打开），采样步由
**任务配置 `train.qat_probe.every_n_steps`**（模板默认 10）决定 —— `train_cmd.sh` 读它并
export 成 `QAT_QSNR_EVERY`（0.18.26 起；此前只有环境变量默认 50 ⇒ 300 步只有 6 个点，
`metrics.json` 只能记「不能判趋势」）。产物落 `<轮次>/evidence/eval_clamp_qsnr.json`（rank0），每次采样再打一行
`[qat-qsnr] step=<k> aggregate_db=<v> (weight=… activation=…)`。

- **谁打开**：`commands/train_cmd.sh` —— 任务配置 `train.monitor_metrics` 含 `quant_error`
  **或** `stop_conditions.quant_error_max` 非空，就 export `QAT_QSNR_PROBE` / `QAT_QSNR_EVERY` /
  `QAT_QSNR_OUT` / `QAT_QSNR_LABELS`（**声明即开关**；`LP_QSNR_PROBE=0` 显式关，
  `LP_QSNR_WATCHDOG=0` 只观测不 kill）。
- **误差上限只写一处**：任务配置 `stop_conditions.quant_error_max`（相对误差，`0.05` = 5%）。
  `train_cmd.sh` 用 `floor = −20·log10(ε)` 换算后注入 `QAT_QSNR_FLOOR_DB`；
  判据文件里**不再有**这个字段（两处各写一份只会分叉）。
- **环境变量契约**（全部属于探针，框架侧不认识任何"轮次/任务"词汇）：`QAT_QSNR_PROBE=1|2` 开关、
  `QAT_QSNR_EVERY` 采样间隔、`QAT_QSNR_OUT` 落点、`QAT_QSNR_LABELS` 身份标签（JSON，原样透传）、
  `QAT_QSNR_WATCHDOG=0` 关护栏、`QAT_QSNR_{DROP,FLOOR}_DB` 护栏阈值、`QAT_QSNR_KERNEL`
  假量化内核（`<module>:<attr>`，默认 w4a16）。
- **谁读**：`runtime/metrics.py` 的 `load_qsnr()` ⇒ `metrics.json.quant_error`
  （`status` / `series` / `min_db` / `last_db` / `min_rel_err` / `last_rel_err` /
  `watchdog_tripped`）。**只登记数**。
- **三态必须分开**：`measured`（有采样点）/ `unmeasured`（没开探针）/ `probe_invalid`
  （探针自证装配失败，训练继续但序列不可用）。把「没测」写成「达标」是这类指标最贵的事故。
- **换算**：`ε = 10^(-QSNR/20)`。`quant_error_max: 0.05` ⇔ QSNR ≥ 26.02 dB。
- **两条规则、一硬一软**：`absolute_floor`（`aggregate_db < 地板`）由 `quant_error_max` 决定；
  `relative_drop`（相对第 10 步掉超过 3 dB）是**固定工程护栏**，没有 YAML 旋钮 ——
  它不是判据，不给它开口子。两处都只在训练进程内 kill 该 run（`EXPERIMENT_INVALID`，不许原样重跑）。

### 4.7 已评估、**决定不做**的校验（留档，避免重复提案）

| 提案 | 为什么不做 |
|---|---|
| `train.framework_head` 加 `pattern: ^[0-9a-f]{40}$` | 唯一消费者是 `git worktree add`，非法 ref 由 **git 自己响亮报错**；正则管不住真失败（格式合法但不存在的 sha 照样炸），还须为 `_TEMPLATE.yaml` 开豁免洞 |
| 占位词表补「中文散文占位」（`你请手动补充`／`待补`…） | 开放式词表永远补不全；且 `_is_placeholder` 的现有调用者**全是「跳过检查」语义**，加词只会让校验**更宽松** |
| `runtime/state.py init` 也校验 head 形状 | 与第 1 行是**同一个事实**；两处各写一份必然漂移，且 `init` 故意不跑 git |

另一条真缺口**已修**（与上面三条无关，0.17.0）：`runtime/framework_patch.sh` 的 `--head` 原先只在**创建工作树**时生效，
工作树已存在时被**完全忽略**；现在 `do_roundtrip` 会先把两边的 ref 解析成完整 sha 再比对，
不一致 ⇒ 退出 `2` 并打印「工作树在哪个 sha / 要求哪个 sha」。边界：它管的是「工作树 == 调用方给的 `--head`」，
**不管**「`--head` 是否等于任务配置的 `train.framework_head`」（脚本不读任务配置，那属调用方传参）。

## 5. 评测环境：`eval.lm_eval.*` 与 `scripts/install_env.sh`

评测字段的唯一落点是任务配置的 `eval.engine`（本工程统一 `lm_eval`）与
`eval.lm_eval.{package,version,python,driver}`：

```bash
bash scripts/install_env.sh --task <任务名|任务配置路径> --dry-run   # 打印将建/装什么，不落盘
bash scripts/install_env.sh --task <任务名|任务配置路径>             # 建 venv ＋ 钉版本 ＋ 回读自证
```

- venv 落点**由配置推出来**：`eval.lm_eval.python` 必须是 `<venv 根>/bin/python` 形状；不另设第二个落点。
- **建法固定为继承**（0.18.13）：`python3 -m venv --system-site-packages <venv 根>`，venv 里只装
  `lm_eval`，torch / torch_npu / transformers 从**主环境**继承。理由两条：
  ① 评测必须用**与训练同一个** Ascend 栈，否则分数差异里会混进运行时差异；
  ② `lm-eval` 的 torch/transformers 在它的 `hf` extra 里，裸装不拉，而 `lm_eval --model hf`
  在 `lm_eval/models/huggingface.py:10` 就 `import torch` ⇒ 隔离建的 venv 会"装上了但跑不了"。
  **不要自己 `python3 -m venv` 建评测环境**，只用这个脚本。
- 动手前先经 `runtime/config.py` 校验任务配置，不过即退出 `2`；装完**回读**
  `importlib.metadata.version()` 必须与 `eval.lm_eval.version` 逐字相同，否则退出 `2`；
  **拒绝静默换版本**（版本不一致 ⇒ 退出 `2`，人工确认后重建）。
- **验收判"能不能跑"，不判"dist-info 在不在"**：回读版本后再用目标解释器跑一次
  `import torch, transformers, lm_eval, torch_npu`；失败或 `torch.npu.is_available()` 为假 ⇒ 退出 `2`
  （指名缺哪个、给修法）。**不自动 `pip install torch`** —— 那会用 PyPI 的 CPU torch 悄悄换掉 Ascend 栈。
- `--dry-run` 的退出码要能当判据（`preflight.sh` ④ 只读它）：`0` 已就绪／`3` 还需要装／
  `4` 需修（缺运行所需的包或 NPU 不可见，跑一次也装不好）／`2` 契约不过。
- 幂等：解释器在、包版本一致、**且可运行性过** ⇒ 不重装、退出 `0`（记录内容不变就不重写）。
- **安装记录**：`<venv 根>/.lpta-env-install.json`（schema 2）—— 包名/版本/解释器/任务配置＋**建法**
  （含基解释器）＋**实际生效的** `inherited_versions.{torch,torch_npu,transformers,accelerate,datasets}`
  ＋ `npu.{available,device_count}` ＋ `shadowed`（被 venv 内部装的东西遮住的包）。供轮次复现回答
  "这份环境到底用了哪个 torch / torch_npu"。
- `eval.lm_eval.driver` 住在**任务目录**（驱动施加与训练侧同一次舍入的量化补丁）；任务目录已交付（P4c），
  但 `runtime/config.py` **不判**它的存在性 —— 那是三段入口跑前准备的职责（`runtime/_common.sh`）。

## 6. 旋钮：没有字典了（0.18.0 删除 `config/variables.yaml`）

**删掉的原因**：那张 21 条 × 7 字段的表想用一个字段回答三个不同的问题 —— ①上游框架有没有这条轴？
②哪一轮实验把它提交进框架仓了？③本轮方案要不要再挂 patch？而它只能写 `framework_native: true`，
这句话**在干净框架上不成立**（`rotation` 就是这样：字典说原生，实际是 R-0006 那轮提交进 `MindSpeed` 仓的）。
一张抄来的静态表必然比事实晚，还会让门照着过期答案放行。

**现在旋钮的真相在哪**：框架代码本身。`<轮次>/design.md` 的 `variables:` 键名与取值**没有白名单**，
由 architect 读框架检出判定，并在 design.md 正文写清每个旋钮生效的 `file:line`。

**门还剩什么**：一条**不依赖任何外部知识**的自洽规则 —— `requires_code: true` ⇒ 本轮
`implementation.patch` 必须非空（选了"要改代码"就必须给出 patch 引用，且 `ref` 文件真实存在）。
写错的旋钮会在起训练时**响亮**失败（参数不认识／环境变量无人读），不静默。

**代价（明说）**：门的"不许自造旋钮"能力没有了 —— 它变成了"起训练时才炸"。这与 `framework_head`
的取舍同一标准：形状/合法性不设静态检查，让真正的权威（git、框架本身）响亮报错。

## 7. 状态接口字段（`state/current.json`，只由 `runtime/state.py` 写）

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema` | int | 状态结构版本，与 `VERSION` 独立 |
| `task_id` / `round` | str | 当前任务（来自配置）／当前轮次（形如 `<轮次>`） |
| `stage` | str | `architect`／`developer`／`tester`／`experimenter`／`done`／`abort` |
| `framework_version` | str | 读 `VERSION`（`devtools/check_state.py` 会核对一致性） |
| `config_version` | str | 任务配置内容哈希前 8 位，形如 `cfg-9f2c1a40`；尚无真实任务配置时 `cfg-00000000` |
| `artifacts.{root,round_dir,runtime_root}` | str | 产物根（来自 `artifacts.root`）／本轮归档目录／**本轮产物真实目录** `<LP_WORK_DIR>/rounds/<轮次>/`（`LP_WORK_DIR` 读任务目录的 `run.env`，没写则 `<data.runs>/<任务名>` —— 与三段脚本同源，0.18.14 起） |
| `framework_state.{head,clean}` | obj | 框架检出 `head` 与 `clean`（`clean: null` ＝ 未核验；「空输出 ≠ 干净」） |
| `last_handoff` / `last_conclusion` | str/null | 最近一次交接 token／上一步结论 id 与一行摘要 |
| `next_action` | str | 一句话：下一步派谁、要它做什么（机器读这一条） |
| `loop` | obj | `rounds_done`（`close` 自增）／`no_progress_rounds`（从任务配置抄来）。**没有自动开关**：引擎只记录，不比较、不自动停 |
| `blockers` | list | 卡点（空列表 ＝ 无） |

`state/rounds.jsonl` 的轮次行字段与 `templates/state-entry.json` 同源；`state/STATUS.md` 由 `current.json` 渲染。

## 8. 落点纪律（唯一落点规则）

模型名、任务名、阈值、路径**只许**出现在 `config/` 与任务目录／轮次目录；
`runtime/`、`agents/`、`skills/`、`templates/` 里出现即由 `devtools/check_decoupling.py` 机械判失败
（它同时查两类：具体模型名/任务名，以及把具体配方焊成机制默认值的串）。

配置校验入口一览：

| 入口 | 校验什么 | 谁在什么时候跑 |
|---|---|---|
| `runtime/config.py <任务配置>` | 任务配置的字段级契约（schema ＋ 3 条语义规则） | 人／CI；`install_env.sh` 动手前 |
| `runtime/validate_round.py <轮次>/design.md` | 方案块的格式规则与 `requires_code⇒patch` 自洽（不再读字典） | **每轮**、方案冻结花卡之前 |
| `devtools/validate_design.py` | 与每轮门**同一份规则实现** | 开发期／CI |
| `devtools/check_state.py` | `state/` 三件自洽（含 `framework_version` 与 `VERSION` 一致） | 开发期／CI |
| `devtools/run_all.sh` | 一次跑齐 **12 步**（任一项非 0 ⇒ 整体非 0）；`devtools/` 顶层共 **12 件**（`README.md` ＋ 八个工具）——「10 件」是文档侧回填口径，见 `docs/MIGRATION.md` §6 | 开发期／CI |
