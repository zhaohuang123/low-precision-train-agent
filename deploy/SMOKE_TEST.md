# SMOKE_TEST.md —— 装完之后，用这段提示词验「调用是正常的」

> **怎么用**：把本文件第 2 节那段话**整段贴进目标容器里的新会话**（用部署好的 `architect` 等角色所在的那个 harness）。
> 它只做**只读或干跑**的事，不花卡、不写你的任务目录。全过 ⇒ 引擎与角色链路都在位。

## 1. 它验什么（三层，从下往上）

| 层 | 验什么 | 谁验 |
|---|---|---|
| **引擎** | 依赖齐（`python3`／**PyYAML**）＋ 五件自检跑得起来 ＋ 契约能加载 ＋ `state/` 能初始化 | `bash deploy/verify_install.sh <目标>` |
| **契约** | 「每轮必跑的门」在**方案冻结、花卡之前**真的会拒绝一份坏方案 | 提示词第 ③ 步（喂一份故意写坏的 `design.md`，要求退出 `2`） |
| **角色** | 主 Agent 认得出自己的**身份**（使用者 ≠ 建设者）、四个角色各自的**可写边界**，以及这四个角色**有没有**装成 subagent | 提示词第 ①②④ 步 |
| **开跑** | 开跑入口在"环境不对"时**拒绝**，并且**不自己派 agent**（编排归主 Agent） | 提示词第 ⑤ 步 |

## 2. 提示词（整段贴进新会话）

```text
这是一次安装后的自证，只做只读或干跑的事：不花卡、不写任务目录、不改任何脚手架文件。

请按顺序做五件事，每件都给「命令 + 关键输出 + 结论」，最后给一张总表（项 / 结果 / 证据）。

① 身份与边界自证。读根目录的 AGENTS.md，然后回答：
   · 你是「建设者」还是「使用者」？依据是它的哪一节？
   · 「脚手架」清单里有哪几项？（列全）
   · 「运行数据」里你**可以写**的是哪几项？其中哪一项是例外、只能经哪个程序写？
   · 如果你是使用者，却需要改脚手架，正确做法是什么（照 AGENTS.md 的原话说）？

② 出厂形态自证。跑：bash deploy/verify_install.sh <你的工程目录>
   要求：逐项报 rc；并确认 `devtools/` 与 `tests/` **不存在**（它们不随包）。
   如果它报了 `config/project.yaml` 还有占位值，那是**提示**不是失败 —— 但请把还缺哪几项列出来。

③ 每轮门自证（干跑，不花卡）。在 /tmp/门自证/ 下建 design.md，内容**逐字**如下：

   # r0001 冒烟 —— 门能不能拦住坏方案

   ## 1. 候选组

   <!-- LP-SCHEME-BEGIN -->
   ```yaml
   schema: 1
   id: smoke-a
   axis: precision
   question_ref: Q-0001
   rank: 1
   strength_target: null
   supersedes: null
   variables:
     qat_scheme: {value: w4a4-mxfp4, requires_code: false}
   implementation: {mode: framework_native}
   ```
   <!-- LP-SCHEME-END -->

   然后做三次，**每次贴出真实输出与 rc**：
     (a) 正例 · 原样跑  python3 runtime/validate_round.py /tmp/门自证/design.md      → 期望 rc=0
     (b) 负例 · 把 `requires_code: false` 改成 `true`（但 `implementation` 仍只有 mode，没有 patch）
                 再跑同一命令 → 期望 rc=2，且错误行说 `requires_code=true` 但本轮没有 patch
     (c) 负例 · 把 `implementation: {mode: framework_native}` 改成 `{mode: 随便写}` 再跑
                 → 期望 rc=2，且错误行说 mode 只允许 framework_native|patch|mixed
   另外确认：负例会把错误行写进**同目录的 test.md**（这是它的约定，不是副作用）。

   ★ 这一正两反是整条链路最重要的一条：它证明「方案冻结、花卡之前」真的会被拦住。
   ★ **0.18.0 起没有旋钮字典了**：`variables:` 的键名/取值不再有白名单（写错的旋钮会在**起训练时**报错）。
     所以这里不要用"故意写错旋钮名"当负例 —— 那种写法现在是**合法通过**的，用它验门只会误判。

④ 角色与技能自证。把 agents/ 下四个角色的 AGENT.md 各读一遍，给一张表：
   角色 / 它挂载的 skill（按 AGENT.md 第①段写的顺序）/ 它**能写**的目录与文件 / 它**只读**的东西。
   再自查两条：
   · AGENTS.md §5 的挂载表与四份 AGENT.md 第①段**是否一致**？不一致就指出来。
   · **这四个角色有没有装成 DSH subagent？** 用这条只读命令判：
       ls "${DSH_HOME:-$HOME/.dsh}/agents"/{architect,developer,tester,experimenter}.md
     然后明确回答属于哪种：
       · 四个都在 ⇒ 用法 **B**（真派子代理）可用，但要**重启过 dsh** 才会进 `use_agent` 的名册；
       · 缺 ⇒ 那就是用法 **A**（你一个主 Agent 依次扮四个角色），**这是正常的，不用补装**。
     若你确实要用法 B 却没装，正确做法是
         bash deploy/install.sh <工程目录> --with-agents        # 然后重启 dsh
     —— **不要**自己手写一个 `*.md` 丢进 ${DSH_HOME}/agents。

⑤ 开跑入口自证（只读，不建目录、不花卡）。
   跑这两条，贴出 rc 与关键输出：
     · bash scripts/preflight.sh <你的任务名> --skip-cards
         → 期望 rc=0，且逐项打印「✓ 任务配置 / ✓ LLM 层仓 / ✓ 核心层仓（未配置则跳过）/ ✓ 评测环境」
         → 若某项 ✗，**原样贴出来**：这就是你要先修的东西（最常见是任务配置里的钉点与检出 HEAD 不一致）
       （`--skip-cards` 只是跳过"卡有没有被别人占"，其余三项照查）
     · bash scripts/start_experiment.sh __no_such_task__ R-1 --skip-preflight
         → 期望 rc=2（任务配置不存在／轮次号不合规时**必须拒绝**，不许猜）
   再读一遍 `scripts/start_experiment.sh` 末尾的打印，确认它**没有**自己派任何 agent
   （编排是主 Agent 的事，见 AGENTS.md §4.1）—— 这一条决定"谁能当编排器"。

做完之后不要继续往下跑任何训练或评测；把总表给我就行。
```

## 3. 通过长什么样

| 项 | 期望 |
|---|---|
| ① | 判出自己是**使用者**；脚手架与运行数据两份清单列全；`state/` 的例外说成「只经 `runtime/state.py` 写」；越界做法说成「停下来写 `<轮次>/change_request.md` 并发 `*_FAILED`／`TEST_BLOCKED`，交给建设者」 |
| ② | `verify_install.sh` **九项**里带 ❌ 的为 0（第 ⑥ 项的安装记录只对「用 `install.sh` 装过的目录」成立；直接解压出来的包这一项会是 ❌，属正常）（含依赖项：python3 ≥ 3.8 ＋ **PyYAML**）；`devtools/`、`tests/` 报「不存在（正确）」；⚠ 项不算失败 |
| ③ | (a) rc=0；(b) rc=2 且说 `requires_code=true` 但本轮没有 patch；(c) rc=2 且说 mode 只允许三选一；错误行进同目录 `test.md`（**这一条最重要**：它证明「花卡之前会被拦住」） |
| ④ | 四张行都在；`architect` 三项（`scheme-design`→`local-knowledge`→`knowledge-curation`）等与 §5 表一致；subagent 那条**判对 A/B**（没装 ⇒ 说成「用法 A，正常」，而不是「缺件」） |
| ⑤ | `preflight.sh` rc=0（或如实报出 ✗ 的项）；`start_experiment.sh __no_such_task__ R-1` rc=2；脚本**没有**自己派 agent |

## 4. 不通过怎么办（分流，别自己猜）

| 现象 | 去哪 |
|---|---|
| `verify_install.sh` 有 ❌ | 先看它尾部打出的那 12 行真实报错；引擎缺件 ⇒ 重跑 `install.sh`（升级语义） |
| ③ 的坏方案**没被拒绝** | 这是**引擎/契约缺陷**，不是配置问题：把命令与原文报给建设者，别自己改 `runtime/` |
| ④ 的挂载表与四份 AGENT.md 不一致 | 同上：报给建设者（`AGENTS.md` §5 是唯一来源，四份 AGENT.md 第①段应向它对齐） |
| ④ 把「角色没装成 subagent」当成**缺件**来报 | 那是**用法 A 的正常状态**（`install.sh` 的默认）；只有你要 `use_agent` 真派子代理时才需要 `--with-agents`。**别为此自己往 `${DSH_HOME}/agents` 手写文件** —— 要走 `install.sh --with-agents`，见 `PREREQUISITES.md` §2.1 |
| ⑤ `preflight.sh` 的某项 ✗ | 钉点不一致 ⇒ 改任务配置的 `core_head`／`framework_head`（或缺 `--skip-cards` 时卡被占）；**不是**引擎缺陷 |
| ⑤ `start_experiment.sh` 竟然派了 agent | 属引擎越界（编排该在主 Agent 手里）：报建设者 |
| ① 判不出身份 | 看 `AGENTS.md` 第一节开头的「同一套文件，两种身份**能改的东西完全不同**」 |

> 记住这条分界线：**「我该怎么配」问 `docs/CONFIG.md`；「引擎是不是对的」报建设者。**
