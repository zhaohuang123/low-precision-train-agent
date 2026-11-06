# AGENTS.md — 仓库级约定（给 agent 的 README）

> 本文件是**给 agent 的约定**，不是给人看的教程（人读 `README.md`）。
> 约定：**取离被改文件最近的那一份 `AGENTS.md`**；本工程当前只有根这一份。

## ★ 身份：先判你是「建设者」还是「使用者」

同一套文件，两种身份**能改的东西完全不同**。不先判这个，后面每一条都会用错。

|  | **建设者**（开发本工程的机制） | **使用者**（在本工程里跑实验） |
|---|---|---|
| 谁 | 改机制、扩能力的人 | 跑 `architect → developer → tester → experimenter` 的人（**含最外层主 Agent**） |
| 可写 | 脚手架 ＋ 运行数据 | **只有运行数据** |
| 禁碰 | —— | **脚手架**（见下） |

**脚手架（＝引擎与契约；使用者禁碰）**：`runtime/`、`agents/`、`skills/`、`templates/`、`scripts/`、
`config/task.schema.json`、`docs/`、`AGENTS.md`、`README.md`、`VERSION`、`ReleaseNotes.md`。

**运行数据（使用者可写）**：它的任务配置 `config/tasks/<任务名>.yaml`；任务目录 `experiments/<任务名>/**`
（`run.env`、`commands/*_cmd.sh`、`drivers/**`、`sets/**` —— **三段脚本与评测驱动按本任务特异化写**）；本轮目录
`<轮次>/**`；`records/{conclusions,best}/**`；`knowledge/` 的四类条目与 `INDEX.md`；部署值 `config/project.yaml`
（装完**必须先填**，见 `docs/CONFIG.md` §3）。★ `state/` 是例外：**只经 `runtime/state.py` 写**
（状态只有一个写者）。

**出厂包（release）只含引擎与契约，不含 `devtools/` 与 `tests/`** —— 那两件是**开发侧质检工具**（唯一入口
`bash devtools/run_all.sh`），**使用者那边本来就不该有**。所以使用者看不到它们，也**不许自己补一份**。


**使用者诉求超出可写范围时，不许就地改**：停下来，把诉求写成一个文件放进 `paths.requests` 目录
（默认 `requests/`；格式与纪律见 `requests/README.md`，骨架 `requests/_TEMPLATE.yaml`），
**诉求本体只在那一个文件里**；`<轮次>/change_request.md` 只留一行指针（诉求 ID ＋ 本轮卡点），
再按角色发对应 token（`ARCHITECT_FAILED`／`CODE_FAILED`／`TEST_BLOCKED`），交给建设者。
**就地改脚手架 ＝ 本轮无效。**

> 本节说的是「**谁有权改**」（身份语义）；§1 表里的「只读」说的是「**冻结后不许改**」（轮次语义）。
> 两者不矛盾：任务配置在**定义任务时**由使用者写，一旦本轮冻结就不再动它。

## 0. 你先读什么（顺序）

1. **上一节「身份」** —— 先判你是建设者还是使用者；判错的方向是**改坏引擎而没人发现**。
2. `README.md` —— 本工程是什么、从哪跑第一轮。
3. 本文件 —— 去哪找配置、不许改什么、怎么自检、交接 token。
4. `agents/<你的角色>/AGENT.md` —— 你的五段职责（①加载哪些 skill ②拿到什么 ③怎么做 ④交出去什么 ⑤不做什么）。
5. `skills/**/SKILL.md` —— 只有 `AGENT.md` 第①段列出的那些，按写的顺序加载。
6. `config/task.schema.json` ＋ `config/tasks/<任务名>.yaml` —— 你要用的**契约与场景**（只读）；
   旋钮有没有、叫什么、取值域多大，**去框架检出里读**（0.18.0 起没有旋钮字典）。

## 1. 配置在哪、谁是唯一落点

| 你要的东西 | 唯一落点 | 你能做什么 |
|---|---|---|
| 模型名、模型来源、目标精度 | `config/tasks/<任务名>.yaml` 的 `model.*` | **只读**；跑实验时不许改 |
| 多轮实验的**起点/想法** | `config/tasks/<任务名>.yaml` 的 `intents[]` | **唯一可追加**：只许往末尾加，不改写既有条目（不参与 `config_version` ⇒ 不会打断进行中的一轮） |
| 评测数据集与口径 | `config/tasks/<任务名>.yaml` 的 `eval.*` | **只读** |
| 产物根 `artifacts.root` | `config/tasks/<任务名>.yaml` | **只读**；轮次目录 = `<artifacts.root>/rounds/<轮次>/` |
| 工程级路径与定卡策略 | `config/project.yaml` | **只读** |
| 框架里有哪些旋钮、取值域、要不要改代码 | **框架代码本身**（只读）；每个旋钮在方案正文写清生效的 `file:line` | 只读；要向框架加旋钮 ⇒ 写成 `implementation.patch` |
| 任务配置的机器校验契约 | `config/task.schema.json` | **只读** |
| 本轮选了什么 | `<轮次>/design.md` 的受控 YAML 块 `variables:` | architect 写；键名与取值**由它读框架判定**（无白名单） |
| 本轮怎么落地 | `<轮次>/design.md` 的 `implementation:` ＋ `<轮次>/patches/` | developer 写 |
| 怎么算通过、何时停 | `<轮次>/criterion.yaml` | architect 写、人冻结；**跑后一字不改** |
| 跑起来怎么保护（早停/墙钟阈值） | `config/tasks/<任务名>.yaml` 的 `stop_conditions.*` | **只读**（0.18.18 起判据里没有这块）；architect 与 experimenter 都**不许**改 —— 要变就是新轮次 |
| 数字 | `<轮次>/metrics.json`（`runtime/metrics.py` 抽出） | **只读**；报告里每个数字只能**引用**它 |

**越界的失败方式是静默的**：把「怎么实现」写进 ②、把阈值写进 ②、把模型名写进 `runtime/`，都会让下一轮复现不出来或让门形同虚设。

## 2. 不许做的事（硬禁令）

1. **不改框架检出**：**任务配置 `train.framework_repo` 指向的那个检出**任何改动都不许提交；改动只经 `<轮次>/patches/`
   挂载、**跑完还原**，还原校验（前后 `rev-parse HEAD` ＋ `status --porcelain` diff）有差异 ⇒ **本轮失败**。
2. **不改只读契约**：`config/task.schema.json`。
3. **不改判据**：`<轮次>/criterion.yaml` 跑后一字不改；要改 ⇒ 新写一份并用 `supersedes:` 指向旧份。
4. **不改数字**：`<轮次>/metrics.json` 谁都不许手改、不许四舍五入；报告里每个数字都必须能在它里面找到对应字段。
5. **不改产物**：`<轮次>/evidence/**`、`patches/framework_*.{before,after}` 只读。
6. **不在轮次目录放三段脚本副本**：`train.sh`／`convert.sh`／`eval.sh` 只在任务目录存在**一份**；轮次要改就只允许「改 `round.env` 变量／追加 argv 片段」或「加 `hooks/{pre_train,post_train,pre_eval,post_eval}.sh`」，覆盖内容**必须落在轮次目录**。
7. **不许静默降级**：框架表达不了方案 ⇒ 当场报 `CODE_FAILED` 并指名缺哪个分支；选了 `requires_code: true` 却给不出 patch ⇒ 该方案**不可执行**（花卡之前由门拒绝开跑）。
8. **不许原样重跑**：`EXPERIMENT_INVALID` 后必须说清「重跑要改什么」，否则不许重跑。
9. **一个事实只有一个落点**：同一内容不许在 YAML 与 Markdown／两处文档里各写一份。


## 3. 自检怎么跑（谁在什么时候跑）

| 工具 | 谁跑／什么时候 | 不过会怎样 |
|---|---|---|
| `runtime/validate_round.py <轮次>/design.md` | **每轮**：流水线在**方案冻结、花卡之前**调用 | 退出 `2` ⇒ **拒绝开跑**；显式错误行进 `<轮次>/test.md`／`report.md`；用户在对话里只看到一句人话 |

**每轮必跑的门只有 `runtime/validate_round.py` 一个**；其余都是开发期／CI 的自检。


## 4. 交接 token（全大写；**一个 token 只有一个生产者**）

```text
architect    ─ ARCHITECT_READY ─▶ developer      交接物 <轮次>/{design.md,criterion.yaml}
architect    ─ ARCHITECT_FAILED ─▶ abort         卡点说明（需求在当前硬件/框架下不可满足，须指名卡点）
developer    ─ CODE_READY ─▶ tester              交接物 <轮次>/changes.md ＋ patches/
developer    ─ CODE_FAILED ─▶ architect          卡点说明 ＋ 缺哪个分支（不许填假参数静默降级）
tester       ─ TEST_READY ─▶ experimenter        交接物 <轮次>/test.md、<轮次>/round.env
tester       ─ TEST_BLOCKED ─▶ developer         报错原文 ＋ 复现命令（代码缺陷不能靠调参绕过）
experimenter ─ EXPERIMENT_DONE ─▶ architect       交接物 report.md（含判定）＋ metrics.json ＋ conclusions/C-<序号>.yaml ＋ evidence/ ＋ 框架还原校验记录
experimenter ─ EXPERIMENT_INVALID ─▶ experimenter 失败证据 ＋ 触发阈值与步数；必须说清重跑要改什么
architect    ─ NEXT_ROUND ─▶ developer           新一轮 <轮次>/{design.md,criterion.yaml}（人/上层编排决定接着开，且未达 max_rounds）
architect    ─ LOOP_STOP ─▶ done                 知识增补记录 ＋ 停止理由（人决定不开／达 max_rounds／连续无进展）
```

状态由 `runtime/state.py` 写：`advance --handoff <TOKEN>`、`close --conclusion C-<序号> --outcome <adopt|reject|inconclusive>`；
**状态只有一个写者**（两个写者＝状态不可信）。上层编排读 `state/current.json` 的 `next_action`，人读 `state/STATUS.md`。

### 4.1 编排（主 Agent 怎么把一轮推起来）

**开跑的唯一入口是一条命令**（人只说"开跑"，由主 Agent 执行）：

```bash
bash scripts/start_experiment.sh <任务名> [轮次]
```

它做四件事，**一件都不许由子代理代劳**：① 跑 `scripts/preflight.sh`（配置／两仓钉点／卡／评测环境，
不过就退出 2）② `runtime/state.py init`（钉 `config_version`）③ **建 `<轮次>/` 目录并从 `templates/`
复制 design.md／criterion.yaml 空壳** ④ 打印"下一步该派谁"。

> **轮次目录只有 `start_experiment.sh` 会建。** 引擎其余部分从不自建 —— 所以"跳过 preflight 直接开跑"
> 不是靠提示词自觉，而是**目录不存在，后面每一步都拒绝**。

**编排循环**（主 Agent 自己转，不嵌套子代理）：

| `stage` | 派谁 | 交回什么 | 然后 |
|---|---|---|---|
| `architect` | `use_agent architect` | `ARCHITECT_READY`／`ARCHITECT_FAILED`／`NEXT_ROUND`／`LOOP_STOP` | `runtime/state.py advance --handoff <TOKEN>` |
| `developer` | `use_agent developer` | `CODE_READY`／`CODE_FAILED` | 同上 |
| `tester` | `use_agent tester` | `TEST_READY`／`TEST_BLOCKED` | 同上 |
| `experimenter` | `use_agent experimenter` | `EXPERIMENT_DONE`／`EXPERIMENT_INVALID` | 同上 |

读完 `state/current.json` 的 `stage` → 派对应角色 → 等它交回 TOKEN → `advance` → 再读 `stage`，直到
`stage` 变成 `done`／`abort`。`advance` 会**fail-closed 校验**"这个 token 的生产者必须是当前 stage"，
所以编排器写不坏状态机。

**两条硬规则**：

1. **冻结判据是人的闸门**：architect 出完 `criterion.yaml` 后，主 Agent **必须问人**"就按这个判吗"
   —— 问的时候把 `bash runtime/validate_round.py <轮次目录>/design.md --root <配置根>` 的输出一起给人看：
   它会打印**本轮边界**（`plateau.min_steps` ⇒ 最早第几步能合法停、`keep_last` ⇒ 结束时还剩哪些 ckpt）。
   若本轮判据要求「跑满 `max_steps`／同预算对比／点名早期 ckpt」，而边界摘要与它矛盾 ⇒ **冻结前改配置
   或改判据**，别等花完卡再发现（CR-0011 的 30.9 卡时就是这么没的）。，
   人点头才进 developer。子代理问不到人（答案流回到主 Agent）—— 这也是**不把编排下沉成子代理**的主因。
2. **编排器就是主 Agent**：不要派一个"编排子代理"再去派四个角色。编排没有算法（读一个字段、派一个
   agent、交一个 token），多一层只增加排障路径，还会把上面那道人工闸门压扁。

## 5. 四角色 × skill 挂载表（顺序即正文里的先后）

| Agent | 挂载的 skill（顺序） | 谁写它 |
|---|---|---|
| `architect` | `scheme-design` → `local-knowledge` → `knowledge-curation` | 出方案 → 取证 → 把经验写回知识库 |
| `developer` | `model-and-code-fetch` → `code-change` → `train-recipe` → `local-knowledge` | 先取代码（切完同步钉点）→ 再判框架能否表达 → 再写训练脚本 → 全程查历史结论 |
| `tester` | `model-and-code-fetch` → `weights-convert` → `autotune` → `run-observation` → `train-recipe` | 先取资产/确认起点可用 → 冒烟再扫参 → 读退出码与观察 → 按配方起训练 |
| `experimenter` | `model-and-code-fetch` → `weights-convert` → `run-observation` → `train-recipe` → `eval-lm-eval` → `report-and-conclusion` | 先取资产/确认起点可用 → 三段执行 → 读观察 → 跑评测 → 出报告与结论 |

`skills:` 是**本工程新增的键**（本机注册表没有它、会静默忽略）：写在 `agents/<角色>/AGENT.md` 的 frontmatter 里，
`devtools/validate_agents.py` 逐条查「路径真实存在」；装进目标 agent 目录时由 `scripts/install_agents.sh` **导出为扁平
`<角色>.md`** 并把 `skills:` 转成注释（skill 挂载由工程侧履行）。

