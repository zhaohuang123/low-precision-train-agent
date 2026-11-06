# 目录划分与职责

本工程的目录按"配置、模板、引擎、角色、知识、产物与档案、开发工具、文档"划分。下表给出每个目录的内容、
关键文件、写入方，以及是否随出厂包发布。

| 目录 | 内容 | 关键文件 | 写入方 | 出厂包 |
|---|---|---|---|---|
| `config/` | 工程级与任务级配置，以及任务配置的 JSON Schema 校验契约 | `project.yaml`、`task.schema.json`、`tasks/<任务名>.yaml` | 使用者（安装时、新建任务时） | 是 |
| `templates/` | 每一轮实验的文档模板与训练、转换、评测入口模板 | `design.md`、`criterion.yaml`、`run.env`、`task/{train,convert,eval}.sh`、`commands/` | 建设者 | 是 |
| `runtime/` | 引擎实现：进程启动与日志采集、在线早停、指标抽取、图表生成、设备与资源分配、配置校验、状态写入、方案校验 | `executor.py`、`metrics.py`、`charts.py`、`resources.py`、`config.py`、`state.py`、`validate_round.py`、`framework_patch.sh`、`_common.sh` | 建设者 | 是 |
| `agents/` | 四个子代理的角色定义与技能挂载表 | `architect/`、`developer/`、`tester/`、`experimenter/` 下的 `AGENT.md` | 建设者 | 是 |
| `skills/` | 各角色执行任务所需的方法、判据与检查清单 | 12 份 `SKILL.md` 及各自的 `references/` | 建设者 | 是 |
| `knowledge/` | 跨轮次复用的知识条目：技术方案、模型结构事实、框架行为与公共补丁、外部来源 | `INDEX.md`、`README.md`、`techniques/`、`models/`、`frameworks/`、`external/` | 各角色（按写回规则） | 是 |
| `experiments/` | 任务目录与轮次目录：每轮的方案、补丁、原始证据、指标数据与报告 | `<任务名>/rounds/<轮次>/` 下的全部文件 | `scripts/start_experiment.sh` 创建，各角色填写 | 是（空目录） |
| `records/` | 跨轮次档案：结论、当前最优结果、追加式流水账 | `conclusions/`、`best/`、`ledger.jsonl` | 各角色（只追加） | 是 |
| `state/` | 当前阶段、下一步动作与轮次记录，供编排器读取 | `current.json`、`rounds.jsonl`、`STATUS.md` | 仅 `runtime/state.py` | 是 |
| `scripts/` | 实验启动入口，以及安装与卸载代理和技能、构建评测环境、获取代码与权重等工程外部操作 | `start_experiment.sh`、`preflight.sh`、`install_*.sh`、`fetch_*.sh` | 建设者 | 是 |
| `requests/` | 使用者向建设者提交的需求（框架缺失的能力、不可执行的规则），不参与流水线 | `_TEMPLATE.yaml` | 使用者 | 是 |
| `devtools/` | 开发期自检工具与发布打包器，仅在修改工程时运行 | `run_all.sh`、8 个检查器、`make_release.py`、`release/` | 建设者 | 否 |
| `tests/` | 自检工具的正向与负向对照用例 | `positive_controls.sh`、`negative_controls.sh`、`pin_negative.sh` | 建设者 | 否 |
| `docs/` | 面向读者的设计文档 | `ARCHITECTURE.md`、`PIPELINE.md`、`CONFIG.md`、`DESIGN.md`、`MAP.md`、`CAPABILITIES.md` | 建设者 | 是（仅上述 6 篇） |
| `deploy/` | 出厂包中的安装与验收脚本；由 `devtools/release/` 在打包时生成，仓库内无此目录 | `install.sh`、`verify_install.sh`、`PREREQUISITES.md`、`SMOKE_TEST.md`、`UPGRADE.md` | 打包器 | 是（仅包内） |

**归属规则**

1. 配置值只出现在 `config/`。代码、模板与提示词中不得内联具体模型名、任务名、路径或阈值，由 `devtools/check_decoupling.py` 检查。
2. 跨轮可复用的结论写入 `knowledge/`；单轮产物留在 `experiments/`；跨轮汇总写入 `records/`；编排状态只写入 `state/`（唯一写入方为 `runtime/state.py`）。
3. 实验执行时会调用的代码属于 `runtime/`；仅在开发期调用的工具属于 `devtools/`，不随出厂包发布。

出厂包包含上表"出厂包"列为"是"的目录（`docs/` 只带白名单内的 6 篇）。`devtools/` 与 `tests/` 不发布，因此出厂文档中不引用这两个目录下的文件。
