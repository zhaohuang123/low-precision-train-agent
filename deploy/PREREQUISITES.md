# PREREQUISITES.md —— 装 lpta 之前，目标容器得有什么

> 第 1 节是「装」的前提，第 2 节是「跑实验」的前提。

## 1. 硬前提（缺一个都装不起来）

| # | 要求 | 为什么 | 怎么自查 |
|---|---|---|---|
| 1 | Linux ＋ `bash` ≥ 4 | 三段入口与 `runtime/_common.sh` 是 bash（用数组、`set -u`） | `bash --version` |
| 2 | `python3` ≥ 3.8 | 引擎六件是 Python | `python3 -c 'import sys;print(sys.version)'` |
| 3 | **`PyYAML`** | ★ **唯一的第三方依赖**：`config/*.yaml`（任务配置、`project.yaml`）与 `state/` 全靠 `import yaml` 读；**缺即 fail-closed**（`resources.py` 会直接报「需要 PyYAML 才能读 config/project.yaml」），**没有回退** | `python3 -c 'import yaml;print(yaml.__version__)'`（实测本机 **6.0.3**）；缺就 `pip install pyyaml` |
| 4 | `sha256sum`（GNU coreutils） | 安装器靠它判「这个文件有没有被改过」 | `sha256sum --version` |
| 5 | `git` | 只用来 `git init` 目标目录（让 `AGENTS.md` 从任意子目录都能被找到）；**不替你做任何提交** | `git --version` |
| 6 | 目标目录**已存在**且**可写** | 安装器不替人建工程根 | `mkdir -p <目标> && test -w <目标>` |

`deploy/verify_install.sh` 会**先查 2 与 3**，缺了当场报出来 —— 不用等它跑到一半才发现。

## 2. 跑实验才需要（装完之后）

| 需要 | 落点（**唯一**） |
|---|---|
| 训练框架检出 | 任务配置 `train.framework_repo`（只读；改动只经 `<轮次>/patches/` 挂载、**跑完还原**） |
| 卡与定卡策略 | 任务配置 `device.*` ＋ `config/project.yaml` 的定卡段 |
| 数据根 | 任务配置 `data.root`（默认 `/data`） |
| 评测解释器 | 任务配置 `eval.lm_eval.python`；`scripts/install_env.sh` 可建 venv |

### 2.1 四个角色要不要装成 DSH subagent

出厂包里**有** `agents/{architect,developer,tester,experimenter}/AGENT.md`，也有 `scripts/install_agents.sh`，
但 `deploy/install.sh` **默认不会**把它们装成 DSH 的 subagent —— 那是往**另一个盘**写
（`${DSH_HOME:-$HOME/.dsh}/agents`），不是往你的工程目录写。两种用法都合法，**选错了症状很隐蔽**：

| 用法 | 你要做什么 | 不做的症状 |
|---|---|---|
| **A** 一个主 Agent 依次扮四个角色（自己读 `agents/<角色>/AGENT.md`，按 `AGENTS.md` §5 挂 skill） | **什么都不用做** —— 工程文件齐了就够（默认就是这个模式） | —— |
| **B** 真用 `use_agent architect` 之类**派子代理** | 装的时候加 `--with-agents`，装完**重启 dsh** | `use_agent architect` 报 **unknown agent**，而 `agents/*/AGENT.md` **明明都在** ⇒ 你会以为「角色没起作用」，其实只是没注册 |

```bash
bash deploy/install.sh <目标> --with-agents --dry-run    # 先看要写什么（不落盘）
bash deploy/install.sh <目标> --with-agents              # 装（默认写 ${DSH_HOME:-$HOME/.dsh}/agents）
bash deploy/install.sh <目标> --agents-dir /别处/agents   # 装到别人指定的目录
bash deploy/install.sh --uninstall-agents                # 只卸 subagent，不动工程（也不需要给目标目录）
```

三条要注意的：

1. **装完必须重启 dsh** —— 要出现在 `use_agent` 的**工具名册**里；名册是**装载时静态构建**的。
   改**已有**角色文件不用重启（派发时从磁盘重读）。所以推荐**先装、后开会话**。
2. **它对宿主只做加法，且先查后写**：装之前会在**本工程一个字节都没写**的状态下先跑一遍预检；
   目标目录里有**非本工程装的同名角色**、或本工程装过的被你**手改过** ⇒ 报出来并退出 2。
   处置：① 手工合并/移走冲突文件；② 换 `--agents-dir` 另指一处；③ 只想先把工程装上就**先不带 `--with-agents`**；
   ④ 确认要覆盖那些手改 ⇒ 单独跑 `bash scripts/install_agents.sh --target <目录> --force`。
3. **`--uninstall` 不会顺手删宿主里的角色** —— agent 文件可能是别人手调过的 persona，不由项目安装器替你决定。要删显式 `--uninstall-agents`。

## 3. 装（五步）

```bash
tar xzf lpta-<版本>.tar.gz && cd lpta-<版本>

# ① 升级前先看差异：只报目标版本与逐文件差异，不写任何东西（新装可跳过）
bash deploy/install.sh /path/to/你的工程目录 --status

# ② 装 / 升级（目标已有安装 ⇒ 自动按升级走，不用加参数）
bash deploy/install.sh /path/to/你的工程目录 --with-agents

# ③ 装完自证：解释器与依赖、目录裁剪、入口语法、清单行数、各引擎 --selftest、状态是否初始化
bash deploy/verify_install.sh /path/to/你的工程目录

# ④ 填工程级配置；状态目录可选先建（开跑入口每次都会自动建一份）
$EDITOR config/project.yaml        # 部署值；字段见 docs/CONFIG.md §3（seeded，升级不覆盖）
cd /path/to/你的工程目录 && python3 runtime/state.py init   # 可选：只为先看到 state/STATUS.md

# ⑤ skill 必须单独装 —— install.sh 不管 skill
bash scripts/install_skills.sh --target "${DSH_HOME:-$HOME/.dsh}/skills" --dry-run
bash scripts/install_skills.sh --target "${DSH_HOME:-$HOME/.dsh}/skills"
```

**三步各管什么**（省得重复做或漏做）：

| 步骤 | 管 | 不管 |
|---|---|---|
| `install.sh` | 工程本体（managed 覆盖 / seeded 仅在缺失时创建）；加 `--with-agents` 时把四个角色导出成 DSH subagent | **不装 skill**；不动已有的 `config/project.yaml` |
| `install_skills.sh` | 12 份 skill 整棵树（`SKILL.md` ＋ `references/`）＋ 一份 manifest；`--dry-run` 先看清单，`--uninstall` 按 manifest 卸 | 不装 agent |
| `verify_install.sh` | 逐项自证（`--selftest`、`config.py validate`、清单行数、状态初始化） | 不写任何文件 |

- `--with-agents` 装完**重启 dsh 再开会话**才生效；不用 `use_agent` 的用法（一个主 Agent 扮四个角色）可以不加，改用 `scripts/install_agents.sh` 单独装。
- **升级就是重跑 ②**（目标已有安装会自动走升级）；想先看差异用 ①。
- `state.py init` **不是必做的一步**：`start_experiment.sh` 开跑前会自动跑一次（并把 `config_version` 钉住）；手动跑只为装完先看一眼 `state/STATUS.md`。它覆盖 `current.json`（把 `stage` 打回起点），**中途不要跑**。
- skill 落到 `~/.dsh/skills/<skill>/`；改坏后重装加 `--force`。

## 4. 升级 / 卸载 / 看状态

```bash
bash deploy/install.sh <目标> --status      # 只报差异，不写任何东西
bash deploy/install.sh <目标>              # 升级（就是重跑安装）
bash deploy/install.sh <目标> --uninstall   # 卸载（只删 managed；seeded 全留）
bash deploy/install.sh --uninstall-agents  # 另卸：宿主里的四个 subagent（不动工程）

# skill 与工程本体分开卸（同一份 manifest、同一套规矩）
bash scripts/install_skills.sh --target "${DSH_HOME:-$HOME/.dsh}/skills" --uninstall --dry-run
bash scripts/install_skills.sh --target "${DSH_HOME:-$HOME/.dsh}/skills" --uninstall
```

两类文件的升级语义**不同**，这是故意的：

| 类 | 内容 | 升级时 |
|---|---|---|
| **managed** | 引擎 `runtime/`、契约 `config/{task.schema.json,tasks/_TEMPLATE.yaml}`、模板 `templates/`、角色 `agents/`、技能 `skills/`、装卸 `scripts/`、文档、`README.md`、`AGENTS.md`、`VERSION`、`ReleaseNotes.md`、`.gitignore` | 覆盖。**若你改过它** ⇒ 报出**全部**冲突然后**一个字节都不写**；要覆盖得显式加 `--force-managed`（覆盖前自动存 `<文件>.bak`） |
| **seeded** | `config/project.yaml`、`knowledge/INDEX.md`、`records/conclusions/_EXAMPLE.yaml` | **只在缺失时创建**，永不覆盖 |

另外：**拒绝降级**（目标版本比包新 ⇒ 报错退出，要降级加 `--force-downgrade`）；
安装记录 `<目标>/.lpta-install.tsv` 只有 `sha256<TAB>class<TAB>路径`，**没有时间戳** ⇒ 同一份包装两次记录逐字节相同。

## 5. 明确**不在**包里（也不用自己补一份）

| 不在包里 | 为什么 |
|---|---|
| `devtools/` | 开发侧质检工具（建设者用，唯一入口 `bash devtools/run_all.sh`）。`verify_install.sh` 会**检查它不存在** |
| `tests/` | 开发侧正负对照（14 ＋ 12 条） |
| 变更全量账本、旧工程 | 与你无关；包里没有那些路径 |
| 任何**具体任务目录** | 任务目录**由你在自己的工程里写**（形状见 `experiments/README.md`，`run.env` 模板见 `templates/run.env`，三段命令怎么拼见 `templates/commands/`） |
