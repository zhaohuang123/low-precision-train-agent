# `experiments/` —— 任务目录（写一次、每轮复用）

> 本目录是 `paths.experiments` 的**默认值**（工程级配置 `config/project.yaml` 的 `paths.experiments`），
> 里面的每个 `<任务名>/` 是**任务目录**；任务目录的**产物根**由任务配置的 `artifacts.root` 决定，
> 其默认值是 `<paths.experiments>/<任务名>`（**默认值、可配置**）。两者**默认重合、但允许分开**：
> 把 `artifacts.root` 指到 `/data/...` 时，任务级脚本留在工程内、轮次与证据落到大容量盘。

## 1. 一个任务目录里有什么（写一次、每轮复用）

```text
experiments/<任务名>/
├── README.md        # 本任务怎么跑（三段依赖、坑、验收命令）——任务知识跟着任务走
├── run.env          # 三段真正要跑的命令与环境变量（**任务级唯一一份**）
├── train.sh  convert.sh  eval.sh      # 三段入口：只拼 argv ＋ 调 runtime/ 引擎
├── commands/        # 型号几何写死的命令、本任务的闸门
├── drivers/         # 评测侧驱动（拼 lm_eval argv 并执行）
├── sets/<集合名>.txt # 评测集合清单（一行一名；`# count: N` 是规模声明）
└── rounds/<轮次>/    # ★ 轮次目录：**输入与档案同处一地**（位置由 artifacts.root 决定）
```

**轮次目录**（`<artifacts.root>/rounds/<轮次>/`）放的是：`design.md`／`criterion.yaml`／`round.env`／`hooks/`（输入）
＋ `scheme_resolved.json`／`changes.md`／`test.md`／`report.md`／`metrics.json`／`artifacts.json`／`patches/`／`evidence/`（档案）。
一轮的输入与档案**必须同处一地** —— 拆两处就会落出两份真相。

## 2. 硬规则

- **规则 A：每轮不再各写一份脚本。** `train.sh`／`convert.sh`／`eval.sh`／`run.env` **只在任务目录存在一份**；
  轮次目录里出现同名脚本 ⇒ `devtools/check_round_layout.py` 直接报错退出 `2`。

- **规则 B：轮次要改脚本，只允许「加覆盖 / 加钩子」。** ① 覆盖变量：`<轮次>/round.env`（只改变量值、追加 argv 片段，
  不许重定义整条命令、不许删任务级变量）；② 加钩子：`<轮次>/hooks/{pre_train,post_train,pre_eval,post_eval}.sh`（存在即执行，
  只允许「做事 ＋ 往 `evidence/` 落文件」）。**禁止**在轮次目录放三段脚本副本。

- **规则 D：补丁跨轮复用 ⇒ 引用，不复制。** 补丁先落在**出生那一轮**的 `<轮次>/patches/`；后面几轮还要用，
  `changes.md` 里写同一个 `ref: ../R-000X/patches/<文件>`（或绝对路径）＋ 挂载时 `--patch` 指那份，
  **不许再拷一份到本轮**。改补丁 ⇒ 新建一份（`0002-…`），旧的原地不动，于是"哪一轮用的哪一版"始终可查。
  **探针/观测/工具这类每轮都要挂的**（基线也得挂 ⇒ 手段类）不在这里找：直接引用
  `knowledge/frameworks/patches/<特性>/…` 那份（判据与做法见那里的 README）。

## 3. 与 `records/` 的分工（别混）

| | `experiments/<任务名>/`（任务目录，含全部轮次） | `records/`（跨轮档案） |
|---|---|---|
| 保留策略 | **可整体归档、可删除**（可重建；换模型/换任务 ＝ 新开一个任务目录） | **append-only、跨轮也跨任务**的耐久档案 |
| 体积量级 | GB 级（ckpt、日志、`evidence/`） | KB 级（`conclusions/*.yaml`、`best/*.yaml`、两个 `jsonl`） |
| 版本控制 | 体积大 ⇒ **必须 `.gitignore`** | 体积小 ⇒ **可以进 git** |

## 4. 当前状态（P4c 起，P4d 完成真命令接线）


★ 上面第 1 节里的两处与实物的差异，以**实物**为准：
`sets/<集合名>.txt`（文件名 ＝ 判据 `eval_protocol.datasets[]` 里某个 `name` 的值）；
`commands/` 里既有**本任务的闸门**（每轮门／口径门），也有**命令形状脚本**
（P4d 起：三段真 argv 的拼装入口）。

> **不用手工一件件拷**：`bash scripts/init_task_dir.sh <任务名>` 会把本节的骨架一次建好
> （三段入口、`run.env`、`commands/`、驱动、`sets/README.md`；已存在的文件不动），
> 结尾点名还差哪三样。

