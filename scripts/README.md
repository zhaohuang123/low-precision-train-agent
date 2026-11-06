# `scripts/` —— **开跑入口** ＋ 对工程**外部**的操作（装/卸 Agent 与 skill、建评测环境）

> 边界：本目录有两类东西，别混：
> ① **开跑入口**（0.18.0 起）：`preflight.sh`／`start_experiment.sh` —— 由**主 Agent**在开跑时调用，
>    四个角色跑一轮时**不会**调它们；`<轮次>/` 目录**只有** `start_experiment.sh` 会建。
> ② **对工程外部**的操作：装/卸 Agent 与 skill、建评测环境、取模型与代码 —— 四个角色跑一轮时不调用。
> 文件清单（与文档一致，共十二个）：`README.md`、`preflight.sh`、`start_experiment.sh`、
> `detect_heads.sh`、`init_task_dir.sh`、`convert_weights.sh`、`fetch_model.sh`、`fetch_code.sh`、
> `install_agents.sh`、`uninstall_agents.sh`、`install_skills.sh`、`install_env.sh`。
>
> §0 讲第 ① 类；§1–§4 讲第 ② 类。

## 0. 开跑入口（0.18.0 起；**主 Agent 用**，人也可以手跑）

```bash
bash scripts/convert_weights.sh --task <任务名>          # 训练起点 HF→mcore（0.18.9，幂等：在就跳过）
bash scripts/init_task_dir.sh <任务名>                  # 建任务目录骨架（0.18.8，幂等，只补缺失件）
bash scripts/detect_heads.sh <LLM 检出> <核心层检出>   # 打印可粘贴的四行 repo/head（0.18.7）
bash scripts/preflight.sh <任务名> [--skip-cards]      # 只查，不写任何东西；退出 0/2
bash scripts/start_experiment.sh <任务名> [轮次]        # 查 → 钉 state → 建 <轮次>/ → 打印下一步派谁
```

`preflight.sh` **不做判断逻辑**，只把四件已有的校验器串成一个退出码：

| # | 查什么 | 谁在判 | 不过的典型原因 |
|---|---|---|---|
| ① | 任务配置合法 | `runtime/config.py validate` | 字段拼错／占位值没换 |
| ② | 两个框架仓都在**钉点**上 | `git -C <repo> rev-parse HEAD` vs 任务配置的 `framework_head`／`core_head` | 检出换过分支、钉点抄短了 |
| ③ | 卡现在能用 | `runtime/resources.py check` | 别的作业正占着（**可靠来源**发现冲突才拦） |
| ④ | 评测环境齐 | `scripts/install_env.sh --dry-run` 的**退出码**（0=已就绪／3=需安装／4=需修） | venv 没建／版本与配置不一致。★ 0.18.12 前这里只看"命令跑完没"⇒ 永远 ✓（配置指向不存在的 venv 也报"已就绪"） |

`convert_weights.sh` 只做**一个方向**（HF → mcore，训练起点）且**幂等**：目标目录已是可用的 mcore
检查点就直接跳过并打印它是"转换产物"还是"训练产物"。它读任务配置（`model.source.path`、
`model.start.*`、`train.framework_repo`）——**部署事实的唯一落点在配置**，任务目录里零绝对路径。
转完自己验三条（`iter=1`／`pt` 非空／体积比 0.90–1.10）。流程与坑见 `skills/weights-convert`。

`init_task_dir.sh` 建 `experiments/<任务名>/` 的骨架：三段入口、`run.env`、`commands/`（含两个闸门）、
评测驱动、`sets/README.md` 与任务 README。**它只搬引擎件，不填任务事实** —— `train_argv.txt` 的几何、
`sets/` 的题单、`run.env` 的三条 `LP_*_CMD` 都要人/developer 填（填错不报错，会静默跑错），
脚本结尾把这三样点名打出来。已存在的文件**一律不动**（幂等，只补缺失件）。

`detect_heads.sh` 只报事实：两个仓的**全 40 位 head**、分支、领先 `origin/master` 几个提交，
并在工作区有未提交改动时**喊一声** —— 因为 `preflight.sh` 第 ② 项只比 `HEAD`，脏树照样会 ✓，
但那时的"钉点"是半句真话（代码与提交号不一致）。

`start_experiment.sh` 做四件事：跑 preflight → `runtime/state.py init`（钉 `config_version`）→
**建 `<artifacts.root>/rounds/<轮次>/` 并从 `templates/` 复制 `design.md`／`criterion.yaml` 空壳** →
打印 `stage` 与"下一步派谁"。

- **它不派 agent**：派谁、怎么派是模型的判断（`AGENTS.md` §4.1）。塞进脚本就等于又写一个引擎。
- **轮次目录只有它会建**：其余代码从不自建 ⇒ 跳过开跑就一步都走不了（构造上的，不靠自觉）。
- 轮次目录**已存在且非空** ⇒ 退出 `2`（轮次一经冻结不再改；要重开用 `--force` 或换轮次号）。

## 1. Agent 怎么装、怎么卸（七条规矩，都可机械判）

| # | 规矩 | 本目录怎么实现 |
|---|---|---|
| ① | **安装 = 扁平导出，不是复制整个目录** | `install_agents.sh` 把 `agents/<角色>/AGENT.md` 导出成 `<目标目录>/<角色>.md`，并把工程专属的 `skills:` 键**转成注释**（本机注册表对未知键静默忽略） |
| ② | **安装必须留 manifest** | 每个被写出的文件在 `<目标目录>/.lpta-install.json` 记一条（路径 ＋ sha256 ＋ 来源），**连同 skill 落点**；manifest 是卸载的**唯一依据** |
| ③ | **卸载只删 manifest 里列出、且 sha256 未变的文件** | `uninstall_agents.sh`：任一文件被改过 ⇒ **报错退出 `2`**，且不删任何东西；manifest 里没有的一律不碰 |
| ④ | **两边都先支持 `--dry-run`** | 两边都有；install 连跑两次结果一致（幂等，manifest **不写时间戳**以保证逐字节一致） |
| ⑤ | **说清生效时机** | 新写出的文件**可立即按名调用**（派发时从磁盘重读），但工具名册是**装载时静态构建**的，要出现在名册里需**重启 dsh**；目标目录里**非本工程装的文件一律不碰**。⇒ 推荐顺序：**先装、后开会话**（会话在安装之后启动，名册里就带上这四个角色，连重启都不用） |
| ⑥ | ★ **导出件写盘之前必须过注册表 frontmatter 校验** | 注册表的解析是**严格**的：`name`／`deep`（非负整数；空值也算错）／`thinking`（`off/low/medium/high/max`，**大小写敏感**）／`background`（严格 `true`/`false`）／`maxRounds`（正整数）任一不合规 ⇒ 它把**整份文件丢弃**（名册里没有）或派发时抛错 —— 那是**静默失败**：文件明明躺在目录里，「装成功」却根本没注册上。故 `install_agents.sh` 照 `@aiwayds/dsh-subagent-registry` 的 `parseAgentMarkdown` **逐条复算**（规则出处 `lib/agents-dir.js`），不合规 ⇒ **拒绝安装退出 `2`** 并指名文件＋字段。★ 另有一条注册表**自己不查但一定会炸**：`frontmatter.name` 必须**等于文件名**（名册与 `nameList` 用的是 `name`，而派发 `loadAgent` 找的是 `<name>.md`）⇒ 否则名册里会有一个**永远调不通**的名字 |
| ⑦ | ★ **本工程装过、但被本地改过的文件 ⇒ 拒绝覆盖** | 目标文件在 manifest 里、但磁盘 sha256 与 manifest 记的不符 ⇒ **退出 `2`** 并列出（与 `uninstall_agents.sh` 的「改过就拒删」同一条纪律，不静默抹掉手调过的 persona）；确认要覆盖就显式加 `--force` |

```bash
T="${DSH_HOME:-$HOME/.dsh}/agents"                        # 目标 agent 目录（本机注册表的默认值）
bash scripts/install_agents.sh   --target "$T" --dry-run   # 先看要写什么；不落盘（⑥ 同样跑）
bash scripts/install_agents.sh   --target "$T"             # 装；再跑一次结果一致（幂等）
bash scripts/install_agents.sh   --target "$T" --force     # 显式覆盖被本地改过的角色文件（⑦）
python3 -c "import json;print(len(json.load(open('$T/.lpta-install.json'))['files']))"   # 装了 4 个
bash scripts/uninstall_agents.sh --target "$T"             # 卸；之后目标目录回到安装前
```

## 2. skill 怎么装

```bash
S="${DSH_HOME:-$HOME/.dsh}/skills"
bash scripts/install_skills.sh --target "$S" --dry-run
bash scripts/install_skills.sh --target "$S"                 # 装（一个 skill 一棵树：SKILL.md ＋ references/**）
bash scripts/install_skills.sh --target "$S" --force         # 显式覆盖被本地改过的 skill 文件
bash scripts/install_skills.sh --target "$S" --uninstall     # 卸（同一份 manifest、同一套规矩）
```

**装的是「一棵树」，不是一个文件**：`<目标目录>/<skill>/SKILL.md` **以及该 skill 目录下的全部文件**（现在的实际
内容是 `SKILL.md` ＋ `references/*.md`）。★ 只拷 `SKILL.md` 是**断链安装** —— 九份 `SKILL.md` **全部**以内联相对
路径引用 `references/…`，而 skill 的相对路径按**该 skill 自己的目录**解析（`skill-filesystem` 的
`resourceBase = locator.directory`），少拷一个 `references/` 就是死链。卸载时按 manifest 逐文件删，再把**已空**的
skill 目录（含 `references/`）由深到浅清掉。

**写盘之前先校验 `SKILL.md` frontmatter**（同上规矩 ⑥ 的同类理由，但规则来自另一份实现）：`skill-filesystem` 的
`parseSkillFile` 在「没有 frontmatter／frontmatter 不是合法 YAML／不是映射／缺 `name` 或 `description`／`name` 不是
小写 kebab-case／invocation 键非法」时**只打一条 `logger.warn` 就丢弃整个 skill** —— 文件装上了、会话里却没有它。
故 `install_skills.sh` 用 PyYAML 照该实现逐条复算（规则出处 `@deepseek-ai/dsh-skill-filesystem/lib/index.js` ＋
`@deepseek-ai/dsh-skill/lib/index.js` 的 `SKILL_NAME`），不合规 ⇒ 拒绝安装退出 `2` 并指名文件＋字段；另要求
`frontmatter.name` **等于 skill 目录名**（工程侧一律按目录名指认 skill）。

**文档说明（不是自创结构，是清单缺项的处置）**：文档的 `scripts/` 文件清单里**没有** `uninstall_skills.sh`，
所以 skill 的卸载能力**并入 `install_skills.sh` 的 `--uninstall` 模式**（同一份 manifest），没有新增文件。
若上游要求拆成独立文件，属 P10 的清单变更，需先改文档再改代码。

## 3. 评测环境

`install_env.sh`（**P10 已实现**）—— 建评测用的 venv 并**钉** `lm_eval` 版本：

```bash
bash scripts/install_env.sh --task <任务名|任务配置路径> --dry-run   # 先看要建/装什么；不落盘
  #   ↑ 退出码：0 = 已就绪／3 = 需要安装／4 = 需修（缺 torch 等，跑一次也装不好）／2 = 契约不过
  #   0.18.13 起 dry-run 自己就判"能不能跑"（真跑一次 import）；preflight ④ 只读这个码
bash scripts/install_env.sh --task <任务名|任务配置路径>             # 建 venv ＋ 装；再跑一次 = 跳过（幂等）
```

- **字段的唯一落点**是任务配置：`eval.engine`（须为 `lm_eval`）＋ `eval.lm_eval.{package,version,python}`；
  动手前先经 `python3 runtime/config.py <任务配置>` 校验，不过即退出 `2`。
- **venv 落点由配置推出来**：`eval.lm_eval.python` 必须是 `<venv 根>/bin/python` 形状（推不出就退出 `2`）；
  不另设第二个落点。
- **建法固定为继承**（0.18.13）：`python3 -m venv --system-site-packages` —— venv 里只装 `lm_eval`，
  torch / torch_npu / transformers 从主环境继承。评测必须用**与训练同一个** Ascend 栈；隔离建的 venv
  只有裸包（`lm-eval` 的 torch 在 `hf` extra 里，裸装不拉），`lm_eval --model hf` 一 import 就炸
  ⇒ **不要自己 `python3 -m venv` 建评测环境**。
- **验收判"能不能跑"**（0.18.13）：回读版本后用目标解释器跑一次
  `import torch, transformers, lm_eval, torch_npu`，失败或 `torch.npu.is_available()` 为假 ⇒ 退出 `2`；
  **不自动** `pip install torch`（那会用 PyPI 的 CPU torch 换掉 Ascend 栈，评测口径随之变化而无人记录）。
- **装完回读自证**：`<python> -c "import importlib.metadata as m; print(m.version('<package>'))"` 必须与
  `eval.lm_eval.version` 逐字相同，否则退出 `2`。
- **拒绝静默换版本**：解释器在、包版本与配置不一致 ⇒ 退出 `2`（人工确认后重建 venv），不自动升降级。
- **幂等**：解释器在、包版本一致、**且可运行性过** ⇒ 不重装；记录内容不变就不重写（逐字节稳定），退出 `0`。
- **安装记录**：`<venv 根>/.lpta-env-install.json`（包名/版本/解释器/任务配置/UTC 时间），
  供 `docs/CONFIG.md` 与轮次复现引用。
- 只对工程**外部**的 venv 目录操作：不碰框架检出、不碰旧工程、不写 `git`。

### 3.1 资产获取：模型与代码（`fetch_model.sh`／`fetch_code.sh`）

**谁用**：起点权重还没下到本机，或代码仓还没克隆／不在指定分支时（skill 侧是 `model-and-code-fetch`）。

```bash
bash scripts/fetch_model.sh --task <任务名> --print      # 只看将执行的命令（含官方与镜像两个端点）
bash scripts/fetch_model.sh --task <任务名> --dry-run    # 查依赖/磁盘/现状；0=已就绪 3=需要下载 2=不过
bash scripts/fetch_model.sh --task <任务名>              # 真下：官方端点先试，失败换 fetch.hf_mirror

bash scripts/fetch_code.sh --task <任务名> --repo train --check           # 只比对 HEAD vs 钉点、工作树干净
bash scripts/fetch_code.sh --task <任务名> --repo core --clone --ref <ref> # 从零克隆再切
bash scripts/fetch_code.sh --task <任务名> --repo train --ref <ref>        # 已有检出：fetch + checkout
```

- **落点不新造**：模型 = 任务配置 `model.source.path`；代码 = `train.{framework_repo,core_repo}`；
  端点/镜像/最小空闲 ＝ 工程级 `fetch.*`（`config/project.yaml`）。
- **自证**：模型下完查「`config.json` 可解析 ＋ 权重文件非空 ＋ 文件数/总大小」；代码切完打
  `rev-parse HEAD` ＋ `status --porcelain`，任一不符 ⇒ 退出 `2`。
- **钉点**：切 ref ⇒ 钉点必变。脚本**只切换、不改配置**，切完打印「`train.framework_head`: 旧 → 新」；
  不同步改钉点就开跑 ⇒ `preflight.sh` 拒绝（这是设计如此，不是 bug）。
- **失败归属**：下载/切换失败 = **环境未就绪（退出 `2`）**，不是训练侧无效（`5`）也不是评测侧无效（`6`）。
- **纪律**：不猜模型名/分支名/仓地址（缺什么问什么）；不 `reset --hard`、不删已下内容；
  **轮次进行中不许切钉点** —— 那是诉求，写进 `requests/`（见 `requests/README.md`）。


## 4. 三条禁令

1. **不写 git**：本目录的脚本不做任何 git 写操作（挂/还原框架 patch 是 `runtime/framework_patch.sh` 的事，P5 已交付）。
3. **不碰非本工程文件**：目标目录里不是本工程装的文件一律不碰（install 拒绝覆盖、uninstall 拒绝删除）。
