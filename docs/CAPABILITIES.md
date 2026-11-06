# 能力图谱

本文件列出工程当前**已实现并可交付**的能力：由哪些角色与技能提供、在任务配置里怎么声明、有哪些明确不支持的情形。
表内每项都能在括号中的文件里查到出处。

---

## 1. 四个子代理：职责、挂载技能与产出

| 角色 | 挂载技能（按加载顺序） | 职责 | 产出 | 不负责 |
|---|---|---|---|---|
| `architect` | `scheme-design` → `local-knowledge` → `knowledge-curation` | 把任务目标拆成 3–6 个可实验方案（含至少一个组合方案），并给出冻结前验收标准 | `design.md`（含 `intent_ref` 与外部来源小节）、`criterion.yaml`、知识条目 | 不改代码、不跑实验、不做判定 |
| `developer` | `model-and-code-fetch` → `code-change` → `train-recipe` → `local-knowledge` | 判断训练框架能否表达方案；能则给最小改动，不能则指名缺哪个分支 | `changes.md`、`patches/` | 不调参、不跑训练 |
| `tester` | `model-and-code-fetch` → `weights-convert` → `autotune` → `run-observation` → `train-recipe` | 冒烟（分钟级）→ 粗扫 → 收窄 → 复验，给出可复现的落地配置 | `test.md`、`round.env` | 不做结论判定、不改补丁 |
| `experimenter` | `model-and-code-fetch` → `weights-convert` → `run-observation` → `train-recipe` → `eval-lm-eval` → `report-and-conclusion` | 执行训练 → 权重转换 → 评测 → 指标抽取 → 报告 → 结论入库 → 框架还原 | `report.md`、`metrics.json`、`conclusions/*.yaml`、`evidence/` | 不手改数字、不改判据 |

角色定义：`agents/<角色>/AGENT.md`；挂载关系：`AGENTS.md` §5。

---

## 2. 十二项技能：支持什么

| 技能 | 使用角色 | 支持的能力 | 不覆盖的情形 |
|---|---|---|---|
| `scheme-design` | architect | 方案组设计（3–6 个，含组合方案）；架构类型与显存分项预算；外部来源两条入口（归档检索、按配置关键字检索）；判据与证伪条件写法 | 不审代码、不预测结果 |
| `local-knowledge` | 全部 | 知识库四类检索（`knowledge/INDEX.md` 检索顺序）；可信度分级；冲突裁决（本地实测优先） | 不新建知识条目 |
| `knowledge-curation` | architect | 一轮结束后写回知识库（adopt 与 reject 都写）；身份规则（同 `axis` ＋ 同 `technique` 只记一条）；更新 `INDEX.md` | 不判断实验结论本身 |
| `code-change` | developer | 训练框架侧最小改动；补丁与改动清单一对一；表达不了时交 `CODE_FAILED` 并指名缺失分支 | 不静默降级、不调参 |
| `train-recipe` | developer / tester / experimenter | 配置字段到命令参数的映射（步数、并行、序列长度、量化开关等）；`--dry-run` 与 `run.env` 逐字相等 | 不定义新旋钮 |
| `autotune` | tester | 5 步级冒烟五项判据；粗扫 → 收窄 → 复验；用"同配置重跑两次的聚合差"区分信号与噪声 | 不做最终结论 |
| `run-observation` | tester / experimenter | 读执行退出码与在线/离线观察；区分训练侧无效、评测侧无效与工程失败 | 不解释精度高低的业务原因 |
| `eval-lm-eval` | tester / experimenter | `lm_eval` 接入与评测执行；多数据集；口径对齐（`num_fewshot`／`max_gen_toks`／`batch_size`／`prompt_type`） | 不支持 `lm_eval` 之外的评测引擎 |
| `report-and-conclusion` | experimenter | 报告判定段；结论档案（append-only）；数字只引用 `metrics.json`，不手改、不四舍五入 | 不改判据 |
| `weights-convert` | tester / experimenter | HF 与 mcore 权重互转；转换后注意力头数的一致性判据 | 不训练 |
| `model-and-code-fetch` | 全部 | 下载模型权重与代码仓；把检出切到指定分支或提交（钉点） | 不改框架检出内容 |
| `bootstrap-eval-env` | 主 Agent | 构建评测用 Python 环境、钉版本、回读自证、幂等 | 不构建训练环境 |

技能定义：`skills/<技能>/SKILL.md`。

---

## 3. 任务配置（`config/tasks/<任务名>.yaml`）能声明什么

| 配置块 | 可声明的项 | 开启的能力 |
|---|---|---|
| `model.name` / `model.precision` / `model.source` | 模型名、目标精度（如 `w4a4`）、权重来源与出处 | 场景定义；精度档位切换 |
| `model.start.{format,path}` | 本轮训练加载的起点（`hf` / `mcore`，绝对路径） | 从转换产物或上一轮产物续训 |
| `train.framework_repo` / `framework_url` / `framework_head` | 训练框架检出与提交钉点 | 代码可追溯、跑完可还原 |
| `train.core_repo` / `core_url` / `core_head` | 核心层检出与提交钉点 | 同上 |
| `train.data_path` / `extra_pythonpath` | 训练数据、附加 Python 路径 | 训练可执行 |
| `train.qat_probe.every_n_steps` | 量化误差探针采样频率 | 训练中的 QSNR 监测 |
| `train.checkpoint.{save_interval_steps,keep_last}` | 分段保存与保留份数 | 中断可续、磁盘可控 |
| `eval.engine` | 评测引擎（当前仅 `lm_eval`） | 评测执行 |
| `eval.task_type` | `generation` / `multiple_choice` | 两类评测任务 |
| `eval.datasets[]` | 数据集名、本地路径或 URL、可选的逐集 `protocol` 覆盖 | 多数据集评测 |
| `eval.protocol` | `num_fewshot`／`max_gen_toks`／`batch_size`／`prompt_type` | 评测口径固定，跨轮可比 |
| `stop_conditions.max_steps` | 训练步数 | 预算控制 |
| `stop_conditions.quant_error_max` | 相对量化误差上限（换算为 QSNR 地板） | 量化质量保险丝 |
| `stop_conditions.wall_clock_hours` | 单轮墙钟上限（必须 > 0） | 时间保险丝 |
| `stop_conditions.loss.{jump_factor,rel_to_best,min_points}` | 在线早停阈值 | 跑飞即杀 |
| `stop_conditions.plateau.*` | 平台早停参数 | 收敛即收工 |
| `stop_conditions.holdout.*` | held-out racing 参数 | 相对历史最好一轮的早停 |
| `artifacts.root` | 产物根目录 | 训练/评测产物落盘位置 |
| `knowledge.external.{sources,keywords}` | 任务级默认检索来源与关键字 | 外部来源检索 |
| `intents[]` | 一句话字符串，或对象 `{text, external{keywords,sources}, loop{max_rounds,no_progress_rounds}}` | 多轮实验目标；单次尝试的检索计划与轮次预算 |
| `loop.{max_rounds,no_progress_rounds}` | 轮数与连续无进展的总量上限 | 声明式停止边界 |

契约：`config/task.schema.json`；唯一执行者 `runtime/config.py`（不通过则逐条打印字段路径并退出 `2`）。

---

## 4. 引擎能力（`runtime/`）

| 能力 | 实现 | 触发方式 |
|---|---|---|
| 训练/转换/评测进程启动与逐行日志 | `executor.py`、`runtime/_common.sh` | 三段入口脚本 |
| 在线早停：loss 跳变、相对最好、QSNR 地板、墙钟、平台期、held-out racing | `executor.py` | 读 `stop_conditions.*` |
| 分段保存检查点与旧目录清理 | `executor.py` | 读 `train.checkpoint.*` |
| 设备占用扫描与定卡 | `resources.py` | 起作业前 |
| 指标抽取（写 `metrics.json`） | `metrics.py` | 每轮结束 |
| 图表生成（loss / QSNR / timing） | `charts.py` | 每轮结束 |
| 配置校验 | `config.py` | 开跑前与任意时刻 |
| 状态机与交接校验（`init`／`advance`／`close`） | `state.py` | 编排器调用 |
| 方案校验门（`requires_code` 必须带补丁等） | `validate_round.py` | 方案冻结、花卡之前 |
| 框架补丁挂载 / 还原 / 前后快照对账 | `framework_patch.sh` | `apply` / `restore` / `verify` / `roundtrip` |

---

## 5. 入口与运维能力（`scripts/`）

| 能力 | 实现 |
|---|---|
| 一条命令开始一轮（预检 → 写状态并钉配置指纹 → 建轮次目录 → 打印下一步） | `start_experiment.sh` |
| 开跑前预检（配置、两个代码钉点、可用卡、评测环境） | `preflight.sh` |
| 安装 / 卸载四个子代理（manifest 与漂移检测） | `install_agents.sh`、`uninstall_agents.sh` |
| 安装 / 卸载技能 | `install_skills.sh` |
| 构建评测环境 | `install_env.sh` |
| 获取代码仓、模型权重 | `fetch_code.sh`、`fetch_model.sh` |
| 探测注意力头数、权重转换 | `detect_heads.sh`、`convert_weights.sh` |
| 初始化任务目录 | `init_task_dir.sh` |

---

## 6. 知识与档案能力

| 能力 | 落点 | 说明 |
|---|---|---|
| 本地验证有效的技术方案 | `knowledge/techniques/` | 必须带 `numbers_ref` 指向 `metrics.json` |
| 模型结构事实 | `knowledge/models/` | 层数、头数、显存锚点 |
| 框架行为事实与公共补丁 | `knowledge/frameworks/` | 带 `file:line`；补丁须 `git apply --check` 通过 |
| 外部来源（只作候选） | `knowledge/external/` | 须有 URL、抓取日期、摘要、"怎么验"；永不进判定 |
| 跨轮结论档案 | `records/conclusions/` | append-only |
| 当前最优结果 | `records/best/` | 每格一份，可覆盖 |
| 追加式账本 | `records/ledger.jsonl` | 只追加 |
| 编排状态 | `state/current.json`、`rounds.jsonl`、`STATUS.md` | 唯一写入方 `runtime/state.py` |

---

## 7. 明确不支持的情形

| 情形 | 原因与现状 |
|---|---|
| 引擎自动连开下一轮 | 刻意没有。`loop.*` 是声明式边界，判定与交接由人/编排完成（`docs/PIPELINE.md`） |
| 外部来源作为判据或变量取值理由 | 不支持。外部来源只到候选为止（`knowledge/README.md` §4） |
| 框架表达不了时静默降级 | 不支持。必须交 `CODE_FAILED` 并指名缺失分支（`AGENTS.md` §2） |
| 实验无效后原样重跑 | 不支持。必须说明重跑要改什么（`AGENTS.md` §2） |
| `lm_eval` 之外的评测引擎 | 不支持。`eval.engine` 枚举当前只有 `lm_eval` |
| `generation` / `multiple_choice` 之外的任务类型 | 不支持。`eval.task_type` 枚举当前只有这两类 |
| 跨机调度 | 不支持。定卡范围限于本机 `devices.usable` / `devices.reserved` |
| 训练框架以外的框架适配 | 当前实现面向 MindSpeed-LLM / Megatron-LM 侧改动（`skills/code-change/`） |
