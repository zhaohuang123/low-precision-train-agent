# `train-recipe` 深化材料：三段形状 / 退出码处置 / `run.env` 变量约定

> 本文件是 `skills/train-recipe/SKILL.md` 的**渐进披露层**：正文只留入口一句话，长内容在这里。
> 本工程内的权威落点：`runtime/README.md`（退出码表与已知坑）。
> 纪律：命令的**唯一落点**是 `<任务目录>/run.env`；本文件只给形状，不给任何具体命令。

## 1. 三段入口的形状（写一次、每轮复用）

| 入口 | 只做三件事 | 为什么在任务级 |
|---|---|---|
| `<任务目录>/train.sh` | ① 从 `BASH_SOURCE` 解析配置根 ② `source "$LP_ROOT/runtime/_common.sh"` ③ 调 `runtime/executor.py` | argv、模型加载随任务变 |
| `<任务目录>/convert.sh` | 同构（换 `--stage convert`） | 转换格式/量化参数随任务变 |
| `<任务目录>/eval.sh` | 同构（换 `--stage eval`） | 评测口径/驱动随任务变 |

**fail-closed（不许猜根）**：入口第一行

```bash
LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
```

随后由 `_common.sh` **校验** `$LP_ROOT/runtime/executor.py` 存在；不存在就退出 `2`。
解析不出根也退出 `2` —— 不许按当前工作目录反推（旧工程踩过「根解析错时不报错，反而把产物正常写进错的树」）。
相对路径一律相对配置根，不相对当前工作目录、不相对脚本所在目录。

**轮次差异只允许两种**（`AGENTS.md` §2 第 6 条：规则 B）：
① `<轮次>/round.env` 改**变量值**或**追加** argv 片段（`LP_TRAIN_EXTRA_ARGS`／`LP_CONVERT_EXTRA_ARGS`／`LP_EVAL_EXTRA_ARGS`）——
不允许重定义整条命令、不允许删除任务级变量；② `<轮次>/hooks/{pre_train,post_train,pre_eval,post_eval}.sh`（存在即执行，
前后各一次，只允许「做事 ＋ 往 `evidence/` 落文件」）。**轮次目录里不许出现三段脚本副本**。

## 2. 退出码表与处置（约定层唯一一份）

| 码 | 含义 | 处置 |
|---|---|---|
| `0` | 成功（**含平台早停 `stop_kind=converged`**：合法收工，只是没跑满） | 继续下一段；报告写明「停在第 N 步」 |
| `1` | 未分类的运行期失败（段内命令失败且未归类） | 读日志归类；不是"重试"的理由 |
| `2` | 约定/契约/门不过（配置校验不过、门不过、根解析不出、目标已被人改过…） | **不许重试**；修约定或配置 |
| `5` | 训练侧无效（发散/非有限值一类，**以及墙钟超时**，都由判据阈值触发） | `EXPERIMENT_INVALID`（说清重跑要改什么） |
| `6` | 评测侧无效（口径不全、驱动异常、结果不可比） | 本轮不产生精度结论 |

**判据**：每一类都要有对应的下一步动作；**不把 5/6 含糊成 1**（5/6 是「有归类的无效」，1 是「还没归类」）。

> **P4 已定案**：旧三段脚本把 `5` 记作「在线早停触发」、`6` 记作「超过墙钟上限」；本工程把码按
> 「**哪一段无效**」切 —— `5`＝训练侧无效（含墙钟超时）、`6`＝评测侧无效（旧表没有这一码）。
> **0.18.26 起**：平台早停（`stop_kind=converged`）不再算「训练侧无效」，执行器退 `0`。
> 对照表与理由在 `runtime/README.md` §2.1（本文件不复述旧工程路径与行号）。

## 3. `run.env` 变量约定（只登记已定名的，其余等 P4）

已由本工程点名的键：

| 键 | 谁读 | 说明 |
|---|---|---|
| `LP_ROOT` | `_common.sh` 与三段入口 | 配置根；由入口第一行解析 |
| `LP_ROUND` | `_common.sh`／`executor.py` | 本轮轮次（形如 `R-0001`） |
| `LP_TRAIN_EXTRA_ARGS` / `LP_CONVERT_EXTRA_ARGS` / `LP_EVAL_EXTRA_ARGS` | 三段入口 | 轮次**追加** argv 片段；**一段一个槽**，串用会把上一段的 flag 塞进这一段 |
| `LP_EVAL_PYTHON` | `eval.sh`／评测 | 评测解释器（版本钉在任务配置 `eval.lm_eval.*`） |
| `LP_EV` | `_common.sh`（`train.sh`／`convert.sh`／`eval.sh`）＋探针 | 这一段的**证据目录**（日志／`exec.json`／`loss`／探针产物／评测默认落点全跟着它；默认 `<轮次>/evidence`，**必须绝对路径**）。冒烟一律指到 `<轮次>/evidence/smoke`，正式跑不带 |

**键清单的唯一落点（P4c 已落盘）**：字段表在 `templates/run.env` 顶部，**实例**在 `<任务目录>/run.env`；
读它的实现只有 `runtime/_common.sh` 的 `lp_load_task_env`（优先级：**环境变量 > `run.env` > 内建默认**）。
本文件**不复制**键清单 —— 抄一份就会漂（一个事实一个落点）。

实测到的三处与"直觉"不同的地方（P4c）：

* 三段命令在 `run.env` 里是**单行字符串**（不是数组）：字符串才能与 `train.sh --dry-run` 打印出来的命令
  **逐字**比对（数组展开时引号/空格会被重新解释）。
* `run.env` 里**只允许**引用 `LP_ROOT`／`LP_TASK_DIR`／`LP_DATA_ROOT`（后两个由前导层预置）；
  `set -u` 开着 ⇒ 引用别的变量当场报错（故意的：typo 不许静默变空）。
* `<轮次>/round.env` 只能**改变量值**或**追加** `LP_TRAIN_EXTRA_ARGS`／`LP_CONVERT_EXTRA_ARGS`／`LP_EVAL_EXTRA_ARGS`；
  重定义整条命令或把任务级变量设成空 ⇒ `_common.sh` 退出 `2`（规则 B ①）。

## 4. `--dry-run` 逐字对账（每轮开工前的机械卡口）

```bash
bash <任务目录>/train.sh --dry-run --round R-0001      # 退出 0
```

打印出来的命令必须与 `run.env` 里的命令**逐字相等**（`grep -F` 比对）。判据（P4 验收行）：
「`--dry-run` 退出 `0` 且打印的命令与 `run.env` 逐字相等」；并另有一条负对照：
**故意把 `LP_ROOT` 指向不存在的树 ⇒ 退出 `2`**。

## 5. 别把这几样写进脚本

- **阈值**：来自任务配置 `<任务名>.yaml` 的 `stop_conditions.*`（0.18.18 起的唯一落点），由调用方传入执行器；
  `budget.*` 是判据里的本轮计划量（记录用）；
  **执行器不存阈值**（`runtime/README.md` §2.1）。
- **评测口径常量**（few-shot 数、生成长度、模板名、批大小）：只在任务配置 `eval.protocol.*` 与
  `<轮次>/criterion.yaml` 的 `eval_protocol.*`，两者逐项一致。
- **卡号**：由 `runtime/resources.py` 给「策略／实测／决策＋来源」；任何脚本不许再写一遍卡号。
