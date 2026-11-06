# 架构（ARCHITECTURE）—— `low-precision-train-agent` 的模块关系与调用图

> 给谁看：人。讲**机制怎么设计的**：模块边界、谁调用谁、一个事实落在哪。
> 边界：本文件**只写本工程本体的机制**；不写「实验学到了什么」（那在 `knowledge/`）、
> 不写操作步骤（那在 `scripts/README.md` 与 `README.md`）、不复述配置字段全集（那在 `docs/CONFIG.md`）。
> 改了机制才改本文件，并与 `VERSION` 同步（§15.2）。

## 0. 一句话

把低精度训练实验的**机制**与具体的**模型/任务配方**解耦：机制进本工程（换模型、换任务不必改），
配方只进 `config/` 与任务目录／轮次目录。

## 1. 分层：每层一个用途

| 落点 | 一句话用途 | 谁读它 | 改动时机 |
|---|---|---|---|
| `agents/<角色>/AGENT.md` × 4 | 四个角色的五段职责与 `skills:` 挂载表 | 派发器／人 | 角色职责变了才改 |
| `skills/<名字>/SKILL.md` × 9 | 过程性知识（设计法、改码、扫参、配方、评测、观察、取证、知识写回、报告） | Agent 按 `AGENT.md` 第①段加载 | 过程性知识变了才改 |
| `runtime/`（9 件） | 引擎：配置校验、状态、抽数、挂/还原、每轮必跑的门；**换模型/换任务不必改** | 任务目录脚本、流水线、CI | 机制变了（升 `VERSION`） |
| `config/` | 模型名／任务名／阈值／路径的**唯一落点**；配置契约（`task.schema.json`；0.18.0 起**没有**变量字典） | 角色（只读）、`runtime/config.py`、门 | 契约变了（升 `VERSION`）；任务配置内容变了只变 `config_version` |
| `knowledge/` | 可继承的经验：`techniques/`／`models/`／`frameworks/`／`external/` | 角色（取证） | **每轮实验后**增补 |
| `templates/` | 每轮照抄的骨架，防止自创格式 | 角色 | 骨架变了（升 `VERSION`） |
| `experiments/<任务名>/` | 任务目录：三段入口与命令（写一次、每轮复用）＋ `rounds/<轮次>/`（输入与档案） | 任务目录脚本、角色 | 新增任务时建 |
| `records/` | **跨轮**档案：`conclusions/`（append-only）、`best/`、`ledger.jsonl`（**唯一**账本；索引派生） | 编排、人、角色取证 | 每轮结束追加 |
| `state/` | 「现在在哪、下一步派谁、产物在哪」（唯一写者是 `runtime/state.py`） | 上层编排（机器）、人 | 每次交接／收口 |
| `docs/` | 给人读的机制说明（本目录） | 人 | 机制升级时（与 `VERSION` 同步） |
| `scripts/` | **开跑入口**（`preflight.sh`／`start_experiment.sh`）＋ 对工程**外部**的操作：装卸 Agent 与 skill、建评测环境 | 人／主 Agent | 安装方式变了才改 |
| `devtools/` | **开发期**（人触发）自检：禁用词、解耦、方案块、轮次布局、状态、知识、agents | 人／CI | 加了新卡口才改 |
| `tests/` | `devtools/run_all.sh` 的正/负对照（证明「检查真的能失败」） | 人／CI | 加了新卡口才改 |

**四个角色跑一轮时不调用 `scripts/` 与 `devtools/`**；但**开跑**要过 `scripts/start_experiment.sh`
（0.18.0 起它是 `<轮次>/` 目录的唯一创建者）—— 那是编排层的事，不是角色的事。

## 2. 落点判据：什么进 `runtime/`，什么进任务目录

判定规则：

1. 「换模型或换任务时，这个文件会不会必须改？」——**会 ⇒ 任务目录；不会 ⇒ `runtime/`**。
2. 文件里「可变的那部分」能剥干净吗？能 ⇒ 剥到 `run.env`／配置里，**壳留 `runtime/`**；不能 ⇒ 整个搬任务目录。

两条总纲：**执行器可泛化 ⇒ 进工程；配方不可泛化 ⇒ 进 YAML ＋ skill**。

同一套判据也决定「工具住哪」：

| 类别 | 触发者 | 该住哪 |
|---|---|---|
| 开发期自检 | **人**改工程时才跑 | `devtools/`（＋ `tests/` 对照） |
| **每轮必跑的门** | **每轮**都过，方案冻结、花卡**之前** | `runtime/`（`validate_round.py`）＋ 流水线 |
| 只读契约／配置数据 | 不执行、被读被校验、角色不许改 | `config/` |
| 经验 | 每轮实验后由角色增补 | `knowledge/` |

## 3. 调用图（谁调用谁、谁的产物给谁）

```text
上层编排 / 人
  │  ① 写 config/tasks/<任务名>.yaml（模型名/任务名的唯一落点）
  │  ② python3 runtime/config.py [--root <配置根>] <任务配置>      ← 字段级校验，不过退出 2
  │  ③ python3 runtime/state.py init --task <任务名> --round <轮次>   ← 写 state/ 三件
  ▼
architect ──► <轮次>/{design.md,criterion.yaml}
  │            │
  │            └─► python3 runtime/validate_round.py <轮次>/design.md   ★ 每轮必跑的门
  │                 读 design.md 的受控 YAML 块（无旋钮字典）；不过 ⇒ 退出 2、拒绝开跑，
  │                 错误行进 <轮次>/test.md／<轮次>/report.md
  │                 （开发期同规则入口：devtools/validate_design.py）
  ▼ ARCHITECT_READY
developer ──► <轮次>/{changes.md,patches/**}
  │            框架检出改动只经 patch 挂载 → runtime/framework_patch.sh apply
  ▼ CODE_READY
tester ──► <轮次>/{test.md,round.env}
  │        冒烟与扫参；命令只来自 <任务目录>/run.env（＋ round.env 覆盖）
  ▼ TEST_READY
experimenter
  │  三段执行：<任务目录>/{train.sh,convert.sh,eval.sh}
  │            └─ source runtime/_common.sh（约定层：解析参数、算落盘位置、读 run.env/round.env、
  │               设备守卫、校验 $LP_ROOT/runtime/executor.py 存在）→ runtime/executor.py（起进程/早停/杀组/超时）
  │  抽数：python3 runtime/metrics.py …  → <轮次>/{metrics.json,artifacts.json}   ★ 只抽数不判定
  │  收口：python3 runtime/state.py close --conclusion C-<序号> --outcome <adopt|reject|inconclusive>
  │        → state/rounds.jsonl 追加一行；结论归档 records/conclusions/C-<序号>.yaml、账本追加 records/ledger.jsonl
  │  还原：runtime/framework_patch.sh restore → verify（前后快照 diff，有差异 ⇒ 本轮失败）
  ▼ EXPERIMENT_DONE
architect（反馈环：沉淀经验 → 决定是否开新一轮）
  ├─ NEXT_ROUND ──► developer（新一轮 <轮次>/{design.md,criterion.yaml}）
  └─ LOOP_STOP  ──► done（知识增补记录 ＋ 停止理由）
```

开发期与工程外部两条旁路：

```text
bash devtools/run_all.sh ──► 12 个开发期步骤（逐项打印名字与 rc；任一项非 0 ⇒ 整体非 0；**不随包**）
                              # `devtools/` 顶层 12 件：README ＋ 8 个检查器 ＋ run_all.sh ＋ 打包器 ＋ 禁用词表
bash tests/{positive,negative}_controls.sh ──► 由 run_all.sh 调起（正/负对照）

bash scripts/install_agents.sh    --target <目标目录> [--dry-run]   ──► 扁平导出 4 个角色文件 ＋ manifest
bash scripts/uninstall_agents.sh  --target <目标目录> [--dry-run]   ──► 按 manifest 卸载（改过的拒删 ⇒ 2）
bash scripts/install_skills.sh    --target <目标目录> [--install|--uninstall] [--dry-run]
bash scripts/install_env.sh       --task <任务名|路径> [--dry-run]  ──► 建评测 venv 并钉版本（回读自证）
```

## 4. 唯一落点（一个事实只有一个落点）

| 事实 | 唯一落点 | 被谁读 |
|---|---|---|
| 模型名／任务名／数据集名／精度 | `config/tasks/<任务名>.yaml` | 角色（只读）、任务目录脚本 |
| 框架里有哪些旋钮、要不要改代码 | **框架代码本身**（0.18.0 起无字典；方案正文里写清 `file:line`） | `runtime/validate_round.py`（只查 `requires_code⇒patch` 自洽） |
| 字段集契约 | `config/task.schema.json` | `runtime/config.py`（唯一执行者） |
| 本轮选了什么（自变量） | `<轮次>/design.md` 的受控 YAML 块 `variables:` | 门、`scheme_resolved.json` |
| 怎么落地（patch 与理由） | `<轮次>/design.md` 的 `implementation:` ＋ `<轮次>/patches/` | `runtime/framework_patch.sh` |
| 成功/证伪/终止阈值、口径 | `<轮次>/criterion.yaml`（跑前冻结、跑后一字不改） | 门、`state.py close`、执行器调用方 |
| 命令（真正跑什么） | `<任务目录>/run.env`（＋ `<轮次>/round.env` 覆盖） | 三段入口脚本 |
| 数字 | `<轮次>/metrics.json`（由 `runtime/metrics.py` 抽出） | 报告、`state.py close`、知识条目 |
| 状态 | `state/`（唯一写者 `runtime/state.py`） | 上层编排、人 |
| 退出码含义 | `runtime/README.md` §2（实现落点 `runtime/_common.sh`） | 三段脚本、角色 |

越界的失败方式是**静默的**：把「怎么实现」写进设计、把阈值写进配置、把模型名写进 `runtime/`，
都会让下一轮复现不出来或让门形同虚设 —— 所以 `devtools/check_decoupling.py` 把这类越界做成机械卡口。

## 5. fail-closed 与退出码

- **解析不出配置根就退出 `2`**，不许猜、不许按当前工作目录反推；相对路径一律相对配置根。
- 未实现的件**调用即退出 `2`**，不许静默通过（九件的行为契约写在各文件头 docstring 里）。
- 退出码表 `0/1/2/5/6` 的**唯一落点**是 `runtime/README.md` §2：`5` ＝ 训练侧无效（含墙钟超时）、
  `6` ＝ 评测侧无效；对旧工程是**有意变更**，对账记录在同一节（§2.1）。

## 6. 现状：九个引擎件与未完成项（照实点名，不夸张）

| `runtime/` 件 | 状态 | 未完成项的唯一落点 |
|---|---|---|
| `metrics.py` | **已实现**（P4；`--selftest` 110/110） | — |
| `validate_round.py` | **已实现**（P4；`--selftest` 40/40） | — |
| `framework_patch.sh` | **已实现**（P5；`apply`／`restore`／`verify`／`roundtrip`） | — |
| `state.py` | **已实现**（P7；`init`／`advance`／`close`） | — |
| `config.py` | **已实现**（`validate` P9；`resolve-scheme` ＋ 字典读取器 **P4d**） | `design.md` 自变量展开 ⇒ `TODO(P4f)`；`artifacts.root` 跑前创建 ⇒ **已实现（P4f 补件）**，落在 `_common.sh` 的跑前准备（本文件只读，不认识「跑」） |
| `executor.py` | **已实现（P4c）**：四机制 ＋ `--selftest` 37/37 ＋ 5 组独立子进程验证 | `runtime/executor.py` 文件头 |
| `resources.py` | **已实现（P4c）**：占用扫描／定卡三层（打来源）／录制回放；`--selftest` 61/61 | `runtime/resources.py` 文件头 |
| `_common.sh` | **已实现（P4c ＋ P4f 补件）**：三段入口共用前导（`lp_setup` 等）＋ 产物根跑前创建（`lp_prepare_artifacts_root`）；`lp_selftest` 40/40 | `runtime/_common.sh` 文件头；§0.2 |
| `README.md` | 已建（引擎说明与退出码表） | — |


## 7. 与旧工程的关系

- 框架检出（任务配置 `train.framework_repo` 指向的路径）**永不提交改动**；改动只经轮次 patch 挂载、跑完还原。
- 搬运映射、带了什么／没带什么见 `docs/MIGRATION.md`（**建设者文档，不随出厂包**）。

## 8. 已知坑（只搬结论，不搬旧工程的数据本体）

1. **判据写了证伪条件，代码就必须真读它** —— 写了却不读 ＝ 假冻结。
2. **写死的卡号会腐烂** —— 卡号一律由 `runtime/resources.py` 给出「策略／实测／决策＋来源」。
3. **一个事实只有一个落点** —— 见 §4。
4. **数字只由抽取器算** —— 报告里每个数字只能引用 `metrics.json`，不许重算、不许四舍五入。
5. **没启用 ≠ 搜了没搜到** —— 「补丁没挂上」与「开关没生效」在日志里长得一样，要靠机制生效验证命令区分。
6. **框架检出的干净是流程的一部分** —— 跑完不还原，下一轮就与上一轮互相污染。
