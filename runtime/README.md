# `runtime/` —— 引擎（换模型/换任务都不必改）

> 判定规则（落点归属）：**「换模型或换任务时，这个文件会不会必须改？」—— 会 ⇒ 任务目录；不会 ⇒ `runtime/`。**
> 第二条：文件里「可变的那部分」能剥干净吗？能 ⇒ 剥到 `run.env` / 配置里，**壳留 `runtime/`**；不能 ⇒ **整个搬任务目录**。
> 两条总纲：**执行器可泛化 ⇒ 进工程**；**配方不可泛化 ⇒ 进 YAML ＋ skill**。


## 0.2 「本工程要写的产物目录」与「冻结的轮次目录」是两件事

两类目录在跑前的 fail 方向**相反**，混为一谈就会把一类真错误伪装成正常：

| 目录 | 是谁的 | 跑前行为 | 落点 |
|---|---|---|---|
| `artifacts.root` | **本工程要写的产物根**（训练/转换/评测**产出**都落在它下面） | 不存在 ⇒ **创建**（`lp_prepare_artifacts_root`；`--dry-run` 只预告不落盘） | `config/tasks/<任务名>.yaml` 的 `artifacts.root`（`default` ⇒ `<paths.experiments>/<任务名>`） |
| `<轮次>` 目录 | **冻结件**（`design.md`／`criterion.yaml`／`round.env` 是人放进去的） | 不存在 ⇒ **拒绝**；本工程**从不自己建** | `runtime/_common.sh` 的 `lp_resolve_round_dir` |

判据：把该建的建成「该拒的」⇒ 真跑在起作业前就退出 `2`，人却以为是输入没就位；
把该拒的建成「该建的」⇒ 空目录被悄悄造出来、跑到中途才失败，或者更糟：跑完却没有产物。
正负对照（`bash -c 'source runtime/_common.sh; lp_selftest'` `[11]`，40/40 里的一部分）：
产物根缺失 ⇒ 真跑 `rc=0` **且目录真的建出来了**；`--dry-run` ⇒ `rc=0` 且**目录仍不在**。


**九件的行为契约**：

| # | 文件 | 一句话含义 | 为什么必须／不放这行不行 | 旧 `scaffold/` 对应 | 本工程 P 步 |
|---|---|---|---|---|---|
| 1 | `executor.py` | 起进程 ＋ 逐行落日志（行缓冲／独立线程排空）＋ 按**观察**在线早停 ＋ 杀整个进程组 ＋ 墙钟超时；**阈值不进执行器** | 四个机制与模型/任务无关，是全工程唯一一份；放任务目录 ⇒ N 份分岔 | `scaffold/run_job.py`（946 行，改名并重写落点） | **已完成（P4c）**：四机制各一条自检 ＋ 命令行验 |
| 2 | `resources.py` | 起作业前扫占用（`/proc` 命令行、`ss` 端口）＋ 定卡三层（策略／实测／决策 ＋ **打来源**）；录制回放 | 写死的卡号会腐烂，它是「卡号从哪来」的唯一实现 | `scaffold/resources.py`（1545 行）；其「建议命令」表搬去任务目录 | **已完成（P4c）**：`cards`／`check`／`pick`／`capture`／`--selftest` |
| 2b | `charts.py` | **只画图不判定**（0.18.26）：读 `evidence/` 出 `charts/{loss,qsnr,timing}.svg` ＋ `loss-sparkline.txt`，供 `report.md` 引用；纯标准库（目标机没有 matplotlib）。它不写 `metrics.json`、不改任何数字 |
| 3 | `metrics.py` | **只抽数不判定**：读 `evidence/` 写 `<轮次>/metrics.json`（loss 轨迹正则**全工程唯一一份**） | 数字的唯一落点；放任务目录 ⇒ 每个任务一套正则，数字立刻不可比 | `scaffold/metrics.py`（3188 行）；写死的模型锚点与目录命名**改读配置** | **已完成（P4）** |
| 4 | `config.py` | 读 `config/task.schema.json` 校验 `config/tasks/<任务名>.yaml`；不通过打印字段路径并退出 `2`；另提供 `resolve-scheme`（展开 `default` 与省略项） | 校验逻辑只此一份（两套校验必然静默分岔） | 本工程新增 | **已完成（P9）**：`validate`（`resolve-scheme` 仍 `TODO(P1)`） |
| 5 | `state.py` | 写 `state/{current.json,rounds.jsonl,STATUS.md}`；`init`／`advance`／`close` | 状态只有一个写者，两个写者＝状态不可信 | 本工程新增 | **已完成（P7）** |
| 6 | `_common.sh` | 三段入口的**共用前导**（被 `source`）：解析参数、算落盘位置、读 `run.env`／`round.env`、设备守卫、校验 `$LP_ROOT/runtime/executor.py` 存在 | 它是「约定层」的唯一一份；放任务目录 ⇒ 每个任务抄一份路径解析 | `scaffold/_common.sh`（727 行） | **已完成（P4c）**：`lp_setup`／`lp_build_stop_args`／`lp_guard_devices`／`lp_hooks`／`lp_run_stage`／`lp_selftest` |
| 7 | `framework_patch.sh` | 挂 patch → 跑 → **还原 → 机械校验**（采 `framework_head/status` 前后快照，diff 有差异即失败） | 「还原是流程里的一个正式步骤，不是记得清理」；不做成脚本就是记性活 | 由旧工程的手工步骤固化而来 | **已完成（P5）** |
| 8 | `README.md` | 本文件：引擎的说明与「已知坑」 | 引擎的使用说明要在引擎旁边 | `scaffold/README.md`（246 行） | 本文件已建 |
| 9 | `validate_round.py` | **每轮必跑的门**：读 `<轮次>/design.md`，跑方案块格式规则 ＋ `requires_code⇒patch` 自洽（0.18.0 起无字典）；不过 ⇒ 在**花卡之前**拒绝开跑（退出 `2`），显式错误行进 `<轮次>/test.md`／`report.md` | 只放 `devtools/` 就只有开发期有人跑 —— 用户与 agent 每轮都不触发它，铁律会退化成文档里的一句话 | 本工程新增（旧工程靠手工核对） | **已完成（P4）** |

**落点判据**（不问「它是不是工具」，只问「谁、在什么时候跑它」）：

| 类别 | 触发者 | 该住哪 |
|---|---|---|
| 开发期自检 | **人**改工程时才跑（`validate_design.py`／`check_round_layout.py`／`check_decoupling.py`／`run_all.sh`）；`devtools/` 共**九件**（`README.md` ＋ 八个工具）——「10 件」是文档侧的回填口径，见 `docs/MIGRATION.md` §6 | `devtools/` |
| **每轮必跑的门** | **每轮**都过，由流水线在**方案冻结、花卡之前**调用（`validate_round.py`）；不过 ⇒ 拒绝开跑 | **`runtime/`** ＋ 流水线 |
| 只读契约／配置数据 | 不执行、被读被校验、角色不许改（`task.schema.json`／`project.yaml`／`tasks/<任务名>.yaml`） | `config/` |
| 经验 | **每轮实验后由角色增补**（`techniques/`／`models/`／`frameworks/`／`external/`） | `knowledge/` |

## 1. 任务脚本怎么找到引擎（fail-closed，不许猜根）

任务级 `train.sh` 第一行：

```bash
LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
```

随后由 `runtime/_common.sh` **校验** `$LP_ROOT/runtime/executor.py` 存在；不存在就退出 `2`。
**解析不出配置根就退出 `2`** —— 不许猜、不许按当前工作目录反推（旧工程踩过「靠当前目录反推根、错了不报错，
反而把产物正常写进错的树」的坑）。相对路径一律相对配置根，不相对当前工作目录、不相对脚本所在目录。

## 2. 退出码表（**约定层唯一一份**，`runtime/_common.sh` 实现）

```text
0  成功
1  未分类的运行期失败（三段内部命令失败且未归类）
2  约定/契约/门不过（fail-closed：配置校验不过、门不过、根解析不出、目标已被人改过…）
5  训练侧无效：由任务配置阈值触发的训练侧主动终止 —— 发散早停/NaN，以及**墙钟超时**
   （任务配置 `stop_conditions.wall_clock_hours` 到点 ⇒ 杀整个进程组）
   ⇒ experimenter 报 EXPERIMENT_INVALID，本轮不产生精度结论
  ★ 0.18.26 起**平台早停不归 5**：`stop_conditions.plateau.*` 命中 ⇒ 留痕
    `stop_kind=converged`、退出 **0**（合法收工；结论有效，但属"停止轮次"，比较口径见
    `templates/report.md` §2）。依据：`metrics.STOP_KINDS` 早就把 `converged` 列为
    "主动停：合法结果"，只是一直没接上。
    ★ 0.19.0 起**held-out racing 归 5**：`stop_conditions.holdout.*` 命中 ⇒ 留痕
      `stop_kind=holdout`、退出 **5**（"没希望赢历史最好" ⇒ 这一轮不产生精度结论，
      与发散早停同处置）。三种 stop_kind 的分工：`invalid` = 测的不是方案；
      `holdout` = 落后参照轮、把卡让出来；`converged` = 不用再花算力、结论有效。
      优先级 `invalid > holdout > converged`（`make_gate` 里显式排序，不许互相顶替）。
6  评测侧无效（口径不全、驱动异常、结果不可比）⇒ 该轮不产生精度结论
```

★ **`evidence/<段>.exec.json` 的 `exit_code` 就是本段的判定码**（与进程退出码逐字一致，
0.18.38 起由 `executor.stage_exit_code()` 单点决定）。早停/超时时被杀的**子进程**（torchrun）
自己那个非零码另存在 `child_exit_code` —— 它是事实，不是判定；拿它当"训练失败"会把
`converged` 整轮误杀（这就是 R-0006 那次事故的入口）。

### 2.0 ckpt 保留与续跑（0.18.26）

| 能力 | 谁做 | 落点 |
|---|---|---|
| 每 N 步存一份 | 框架（`--save-interval`） | `templates/commands/train_argv.txt` 的 `${save_interval}` ← 任务配置 `train.checkpoint.save_interval_steps` |
| 只留最近 K 份 | **`executor.py`**（框架没有保留开关） | `--ckpt-dir/--ckpt-keep-last/--retention-log`，由 `_common.sh` 从任务配置传入 |
| 从 ckpt 续跑 | `--resume latest|目录` → 改 argv 形状 | `_common.sh` 解析校验 → `train_cmd.sh` 去掉 `--finetune`/`--no-load-*`、`--load` 指向 ckpt |

刈草的六条安全规则写在 `runtime/executor.py` 的 `prune_checkpoints()` 文件头（只删 `iter_*`、
永不删最新、`keep_last<1` 不删、mtime<120 s 不删、删失败不中断、每次留痕到
`evidence/ckpt-retention.log`）。

### 2.1 相对旧工程是**有意变更**（P4 二选一后统一）

旧工程三段脚本头部记的是 `0/1/2/5/6`，其中 `5 = 在线早停触发`、**`6 = 超过墙钟上限`**
（旧 `scaffold/train.sh:16-21`；`_common.sh` 里同义），旧工程**没有**「评测侧无效」这一码。

| 旧工程 | 本工程 | 为什么换 |
|---|---|---|
| `5` = 在线早停触发 | `5` = **训练侧无效**（发散/早停/NaN **＋ 墙钟超时**） | 早停与墙钟超时在机制上是同一类：**判据阈值触发 ⇒ 杀整个进程组 ⇒ 训练没跑完 ⇒ 本轮无精度结论**。按「**哪一段无效**」切，比按「是不是超时」切更贴近下一步动作 |
| `6` = 超过墙钟上限 | `6` = **评测侧无效** | 评测口径不全／驱动异常／结果不可比**必须有自己的码**：下一步动作（重跑评测、对齐口径）与「训练侧无效」（换机制重跑）完全不同；旧表下这三类只能含糊成 `1`，而 `1` 的定义正是「还没归类」 |
| （旧表无此码） | `6` = 评测侧无效 | 见上一行 |

> 一句话：**码按「哪一段无效」切，不按「哪种失败形式」切** —— `5`＝训练侧、`6`＝评测侧、`1`＝还没归类。
> **阈值不进执行器**：早停阈值与墙钟上限都来自**任务配置** `config/tasks/<任务名>.yaml` 的
> `stop_conditions.*`（0.18.18 起的唯一落点），由 `_common.sh` 读出后原样传入。
> 这张表**就是**退出码表相对旧工程的唯一对账记录（旧工程那一处是 `scaffold/train.sh:16-21`）。

## 3. 已知坑（**只搬结论**，不搬旧工程的数据本体）

`TODO(P4e)`（**已收口**，见 §3.1）：旧 `scaffold/README.md`（246 行）里的坑清单已**逐条**过完，
搬运结论在下表；P4c 当时只搬了与本次实现直接相关的几条，本步把其余条目补齐并逐条注明出处。

## 3.1 旧 `scaffold/README.md`（246 行）逐条搬运 —— `TODO(P4e)` 收口

> **只搬结论**：不搬旧工程的数据本体、不搬它的目录布局与代号、不照抄它的具体名与路径。
> **列义**：`搬` ＝ 结论已写进本工程并有落点；`不搬` ＝ 原样留在旧工程，理由写在表里。

| # | 旧出处（行号） | 结论（只搬结论） | 本工程落点 |
|---|---|---|---|
| 1 | `scaffold/README.md:6-11` | 三段是 `训练 → 转换 → 评测 → 抽数`；执行器是独立一层（持有进程／逐行落日志／按观察在线早停／杀进程组），三段脚本不自己管进程。 | `runtime/executor.py`；`docs/PIPELINE.md` |
| 2 | `scaffold/README.md:13-21` | 旧退出码表是 `0/1/2/5/6`，其中 `6`＝超时、**没有**「评测侧无效」这一码。 | **搬（有意变更）**：`runtime/README.md` §2／§2.1（按「哪一段无效」切：`5`＝训练侧、`6`＝评测侧） |
| 3 | `scaffold/README.md:18` | 抽数器「数还没齐」用**独立码**表示，**不是判定**。 | `runtime/metrics.py`（`2`＝数没齐；本工程退出码表只有 `0/1/2/5/6`） |
| 4 | `scaffold/README.md:20` | 资源冲突用**独立码**表示，也不是判定；探测不了**不许**降级。 | `runtime/resources.py`（`check` 的 `2`＝冲突/BLOCK；探测不了**不**降级成「全都空闲」） |
| 5 | `scaffold/README.md:27` | 命令形状与「逐字命令」分家：形状放任务目录的命令目录，逐字命令接进 `run.env`；命令对入口是**不透明字符串**。 | `<任务目录>/commands/` ＋ `<任务目录>/run.env` |
| 6 | `scaffold/README.md:28` | 评测侧驱动必须能自证「下发的开关/驱动认不认」，否则「没启用」与「启用了没生效」在日志里长得一样。 | `<任务目录>/drivers/`；`skills/eval-lm-eval/references/lm-eval-driver-contract.md` |
| 7 | `scaffold/README.md:29` | 0 卡离线探针**先把线程数压到 32**（默认 256 线程在本机会假死）。 | **不搬**：本工程暂无对应的 0 卡探针实现（`probe/` 未迁移）；将来真要建，照此行结论办 |
| 8 | `scaffold/README.md:31-34` | 卡号不写死：策略／发现／决策三层，并**打印来源**；优先级＝显式给 > 已导出的可见集 > 自动探测；保留卡**永不入选**（自动选卡与显式点名都一样）；探测不了**不**降级成「全都空闲」；先看现场再定卡。 | `runtime/resources.py`（`cards`／`check`／`pick`） |
| 9 | `scaffold/README.md:41-47` | 数字文件是**机械产物**：任何角色、任何情况不许手改；抽数器只做加法与取极值，**不产出** PASS/FAIL、不算置信区间、不贴档位。 | `runtime/metrics.py`；`AGENTS.md` §2.5 |
| 10 | `scaffold/README.md:49-53` | 判定**不在**抽数器那一环：判定者读数字（只引用不重算），对照**跑前冻结**的判据给结论。 | `skills/report-and-conclusion/` |
| 11 | `scaffold/README.md:55-67` | 不许有「指定结论」的开关（`--force-pass` 一族）；把它们列出来是为了让「我们想过并且拒绝了」留在代码里。 | `runtime/metrics.py` 的禁用开关表 ＋ 形状自测 |
| 12 | `scaffold/README.md:73-83` | 成功条件与证伪条件必须在**跑之前**填好 —— 跑完再定标准，标准就会往结果靠。 | `templates/criterion.yaml`；`AGENTS.md` §2.4 |
| 13 | `scaffold/README.md:85-94` | 每一步都可以先 `--dry-run` 看清楚它要做什么，**不动任何文件**。 | 三段入口的 `--dry-run`（门都不跑 ⇒ 不写 `test.md`） |
| 14 | `scaffold/README.md:96-104` | 抽数器的自证只能靠 `--selftest`；必须覆盖「**假失败回归**」（跳变倍数很大但全是有限值 ⇒ 不许报失败）与「输出里不出现判定字段」。 | `runtime/metrics.py --selftest` |
| 15 | `scaffold/README.md:106-111` | 旧的机械判定器与它的产物**在本工程不存在**（数字由抽数器出、判定由判定者给）；见到让人读那个产物的文档 ⇒ 那是旧文档。 | `runtime/metrics.py`（恒带 `is_verdict: false`） |
| 16 | `scaffold/README.md:115-121` | 命令配置是 **shell 语法**（会被 source）：值里有空格要用引号；**命令**与「产物落哪／失败怎么留痕」的**约定**必须分家（混在一起改，早晚把稳定那段改坏）。 | `templates/run.env`；`runtime/_common.sh` |
| 17 | `scaffold/README.md:141-143` | 命令里能引用哪些变量（工程根／轮次／轮次目录／证据目录／阶段／数据根）—— 它们是**预置**的，不是命令自己派人去找。 | `runtime/_common.sh` 的 `lp_setup`／`_common.sh` 头部契约 |
| 18 | `scaffold/README.md:145-155` | 起 `torchrun` **必须显式声明可见设备**：不声明时框架会默认抢低号卡（真实事故）；守卫要在命令看起来要起 `torchrun` 而变量没设时**直接拦下**，不许绕过。 | `runtime/_common.sh` 的 `lp_guard_devices` |
| 19 | `scaffold/README.md:157-159` | 缺 `run.env` 或缺必需字段 ⇒ 打印可照抄的模板并退出 `2`；**绝不替人猜一条命令** —— 猜出来的命令跑出一个「看着正常」的实验，比直接失败糟得多。 | 三段入口 ＋ `<任务目录>/run.env`（命令唯一落点） |
| 20 | `scaffold/README.md:165-184` | 抽 loss 的机制：从训练日志抽行写 loss 文件；**不覆盖**已有的结构化 loss 文件；认得出若干（框架风格为主）写法；一个点都抽不到时**不判「训练无效」**，只说「数还没齐」。 | `runtime/executor.py` ＋ `runtime/metrics.py` |
| 21 | `scaffold/README.md:186-204` | 评测结果形状：只留一个总分也能抽数（抽数器要的是能做减法的聚合值）；但**强烈建议连逐样本一起留**（否则答不出「差值来自哪一类题」）；抽数器把两侧指标名／样本数／来源文件都记下。 | `runtime/metrics.py`；`skills/eval-lm-eval/` |
| 22 | `scaffold/README.md:210-224` | 抽数四条最易记错：① Δ 就是**两个聚合值相减**；② 参考侧**可选**，缺了记 `null` 是**正常情况、不是错误**，两侧指标名不同仍相减但要在 `notes` 里写明；③ 训练观察**两道阈值不许合并**（合并只有两条坏路：要么在线永不触发，要么把离线门槛拉到在线那个值）；④ 输出里**不许出现判定字段**。 | `runtime/metrics.py`（**只抽数不判定**；抽取规则是这一条的唯一落点） |
| 23 | `scaffold/README.md:228-237` | 诚实清单：目录本身**不含**任何框架真实调用（命令从配置读）；「全量评测」只是脚本读一个 flag 得来的，**没有任何东西能检测是不是真跑了全量**（例如驱动侧的 `--limit` 截断）。 | `runtime/README.md` §2；`skills/eval-lm-eval/` |
| 24 | `scaffold/README.md:238-242` | 抽数器**不能给自己算哈希**（自指）；结论里引用的数字指纹由判定者用**机械命令**算，是留证不是判断。 | `skills/report-and-conclusion/references/verdict-and-fields.md` |
| 25 | `scaffold/README.md:243-245` | 执行器判定「训练结束」靠的是「日志连续 N 个周期没有新点」的**启发式**，不是精确信号 —— 别把它当结论。 | `runtime/executor.py`（结束判定与在线早停是两件事） |
| 26 | `scaffold/README.md:245-246` | 转换段的**产物存在性检查只在声明了产物路径时生效**；不声明就只记一句「未声明」（转换是「命令成功但产物不对」的高发段）。 | **搬（结论登记，实现归 `TODO(P4f)`）**：本工程三段入口还没有「转换产物路径」字段与存在性检查 |

**搬运计数（逐条，可复算）**：候选 **26 条**；`搬` **25 条**（其中第 26 条只搬结论、实现记 `TODO(P4f)`）；
`不搬` **1 条**（第 7 条，理由：本工程暂无对应的 0 卡探针实现 —— 没有落点的结论搬进来只会腐烂）。
第 2 条是**有意变更**：旧表不再适用，改成「按哪一段无效切」的新表（§2.1 已逐行对账）。
**没有留空**：26 行每行都有结论与落点或明确理由。

**本工程**继续适用的七条总纲（P0 起就写在这里，与上表不重复）：

1. **判据写了证伪条件，代码就必须真读它** —— 写了却不读 = 假冻结。
2. **写死的卡号会腐烂** —— 卡号一律由 `resources.py` 给出「策略／实测／决策＋来源」，任何脚本不许再写一遍卡号。
3. **一个事实只有一个落点** —— 命令只在 `<任务目录>/run.env`，运行期阈值只在**任务配置**的
   `stop_conditions.*`，判定只在 `criterion.yaml`，数字只在 `metrics.json`；
   两处各写一份，改一处就会静默不同步。
4. **数字只由抽取器算** —— 报告里每个数字只能**引用** `metrics.json`，不许重算、不许四舍五入。
5. **没启用 ≠ 搜了没搜到**（例如 patch 没挂上、开关没生效），两者在日志里长得一样：要靠机制生效验证命令区分。
6. **框架检出的干净是流程的一部分** —— 跑完不还原，下一轮的结果就与上一轮互相污染；还原校验 diff 有差异 ⇒ 本轮失败。
7. **谁最后写谁赢** —— `run.env` 里写成 `${VAR:-默认}` 的键**被导出的环境变量压过**；
   但 `<轮次>/round.env` 是 `set -a; source` 进来的，**它压过导出的环境变量**。
   所以优先级是 `round.env` > 环境变量 > `run.env` > 内建默认 ——
   「我在命令行 `LP_XXX=... bash train.sh` 设了却不生效」多半是这条，不是 bug。


