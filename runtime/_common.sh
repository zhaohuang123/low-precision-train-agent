#!/usr/bin/env bash
# _common.sh —— 三段入口（train.sh / convert.sh / eval.sh）的**共用前导**，被 `source` 使用。
#
# 归属：根解析与三段前导（fail-closed，不许猜根），规则见 `runtime/README.md` §1。
# 实现步：**P4c**（P0–P4b 期间本文件是占位：被 source 即让调用方退出 2）。
# 旧对应物：`scaffold/_common.sh`（**实测 727 行**，只搬机制）。
#
# 它是什么：**不是**一个能跑的工具，是三段入口的**共用前导**。它把「这一次到底要跑什么、
# 往哪落、用哪几张卡」算清楚，然后交给 `runtime/executor.py` 去跑。
#
# ## 分工（**唯一落点**，不许三份入口各写一套）
#
#   本文件算的      参数、配置根、任务目录、轮次目录、run.env/round.env、卡、阈值、钩子
#   executor.py 干的 起子进程、逐行落日志、按观察在线早停、杀整个进程组、墙钟超时
#   三段入口干的     `source` 本文件 → 调 :func:`lp_setup` → （train/eval）:func:`lp_guard_devices`
#                    → :func:`lp_run_stage` → 把退出码翻成人话
#
# ★ 本文件**不做判定**：它只把「阈值」原样传给执行器。阈值只许来自
#   `config/tasks/<任务名>.yaml` 的 `stop_conditions.*` —— 这里**一行默认值都不写**
#   （写了默认值，就等于给了第二个阈值来源；见 runtime/README.md §2.1）。
#   0.18.18 前这些键住在 `<轮次>/criterion.yaml`，结果人填的任务配置没人读、要靠角色转抄。
#
# ## 三层输入的优先级（**环境变量 > run.env > 内建默认**）
#
# `source` 前若导出了 `LP_*`（或 `ASCEND_RT_VISIBLE_DEVICES`），它**压过** run.env 里的同名字；
# 因为「人在命令行上临时改一下」必须赢过「文件里写着的常态值」。做法是：先快照 `env`，
# source run.env，再把快照里的键值写回去（不是"判断谁非空"，那会漏掉"显式设为空"）。
#
# ## 规则 B ①（§5.3）本文件**机械地**卡住
#
# `round.env` 只许：① 改变量值 ② 追加 `LP_TRAIN_EXTRA_ARGS` / `LP_CONVERT_EXTRA_ARGS` / `LP_EVAL_EXTRA_ARGS`。
# **不许**重定义整条命令（`LP_TRAIN_CMD`/`LP_CONVERT_CMD`/`LP_EVAL_CMD`）、**不许**删除
# 任务级变量（改成空）。两条都在 source 后逐条比对，违反即退出 2 ——
# 「轮次要改就只允许改 round.env 变量或追加 argv 片段」这句话，靠这里落地。
#
# ## 规则 B ② 钩子（§5.3）
#
# `<轮次>/hooks/{pre_train,post_train,pre_eval,post_eval}.sh` **存在即执行**。
# 钩子只许「做事 ＋ 往 `evidence/` 落文件」。
#
# ## 退出码表（逐字见 runtime/README.md §2；§2.1 写明它相对旧工程的有意变更）
#
#   0 成功 / 1 运行期失败 / 2 约定不过 / 5 训练侧无效（发散·早停·NaN ＋ **墙钟超时**）/ 6 评测侧无效
#
# ## 跑前准备：`artifacts.root` 与冻结的 `<轮次>` 目录
#
# * `artifacts.root` —— **本工程要写的产物目录**：不存在就**创建**（`lp_prepare_artifacts_root`，
#   真跑路径 mkdir -p；`--dry-run` 只打一行预告、不改任何文件）。它缺失不是配置错。
# * `<轮次>` 目录 —— **冻结件**（design/criterion/round.env 是人放进去的）：**不存在就拒绝**，
#   本文件**从不自己建**（建了就等于轮次可以凭空出现）。
#
# ## dry-run 的**有声**放宽（只在 `--dry-run` 下；带前缀打出来，不是静默通过）
#
# 定不下卡（`devices.require_explicit: true` 且没人显式给卡）：真跑退出 2；`--dry-run`
# 打一条 WARN 继续 —— 因为 dry-run **不占卡**，卡定不下来不影响它只打印。
# ★ `artifacts.root` 的创建不是"放宽"：`--dry-run` 只是**不落盘**（它照实说将会创建哪个目录）。
# ★ 放宽都**带前缀打出来**；真跑路径仍然退出 2（有正负对照用例）。
#
# 用法（三段入口里）：
#   LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
#   source "$LP_ROOT/runtime/_common.sh"
#   lp_setup train "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" "$@"
#
# 自检：`bash -c 'source runtime/_common.sh; lp_selftest; echo rc=$?'`

set -u

# 直接执行 = 用法错误（它是被 source 的前导，不是一个命令）。fail-closed：退出 2。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "_common.sh 是三段入口的共用前导，**应当被 source**，不该被直接执行。" >&2
  echo "  用法：source runtime/_common.sh; lp_setup <train|convert|eval> <任务目录> \"\$@\"" >&2
  echo "  自检：bash -c 'source runtime/_common.sh; lp_selftest'" >&2
  exit 2
fi

# 退出码表（本工程唯一一份；`readonly` 二次 source 会报错，故先判）。
if [[ -z "${LP_EXIT_OK:-}" ]]; then
  readonly LP_EXIT_OK=0
  readonly LP_EXIT_CMD_FAILED=1
  readonly LP_EXIT_CONTRACT=2
  readonly LP_EXIT_TRAIN_INVALID=5
  readonly LP_EXIT_EVAL_INVALID=6
fi

# 三段入口共用的 globals（`lp_setup` 填）。
LP_STAGE=""
LP_ROOT=""
LP_TASK_DIR=""
LP_TASK_ID=""
LP_ROUND=""
LP_ROUND_DIR=""
LP_ARTIFACTS_ROOT=""
# ★ 0.18.34（CR-0006）：这一块其余变量都由 `lp_setup` 从 argv 重算，**只有 `LP_EV` 是
#   只能从环境/`round.env` 来的** —— 跟着一起清空，就等于把"人从 shell 导出的 LP_EV"这条路
#   堵死（`:374` 的默认分支永远赢，而 `:259` 的 env 快照也已经看不到它了）。
LP_EV="${LP_EV:-}"
LP_CRITERION=""
LP_RUNENV=""
LP_ROUNDENV=""
LP_DRY_RUN=0
LP_NO_EARLY_STOP=0
LP_ROOT_ARG=""
LP_ROUND_ARG=""
LP_HELP=0

#: 早停阈值键（在**任务配置**里读；**只做传递**）。键名的唯一落点：本数组。
LP_STOP_KEYS=("stop_conditions.loss.jump_factor"
              "stop_conditions.loss.rel_to_best"
              "stop_conditions.loss.min_points")

# ---------------------------------------------------------------------------
# 输出：全部带前缀，一眼能看出是谁在说话
# ---------------------------------------------------------------------------

lp_note() { printf '[common] %s\n' "$*" >&2; }
lp_warn() { printf '[common] ⚠ %s\n' "$*" >&2; }
lp_die() {
  local code="${LP_EXIT_CONTRACT}"
  if [[ "${1:-}" =~ ^[0-9]+$ ]]; then code="$1"; shift; fi
  local line
  while IFS= read -r line; do printf '[common] ✗ %s\n' "$line" >&2; done <<< "$*"
  printf '[common] ⇒ 退出 %s\n' "$code" >&2
  exit "$code"
}

lp_usage() {
  cat >&2 <<EOF
用法：bash <任务目录>/$1.sh --round <轮次> [--root <配置根>] [--dry-run] [--no-early-stop]

  --round <轮次>   必给。轮次目录 = <artifacts.root>/rounds/<轮次>/（脚本**从不自己猜**轮次）
  --root <配置根>  默认取入口脚本上两级（\$LP_ROOT 次之）；指错即退出 $LP_EXIT_CONTRACT
  --dry-run        只打印将要跑的命令与落盘位置，**不起进程、不占卡**
  --no-early-stop  关掉在线早停（非有限值熔断仍然生效）

  ★ 真正要跑的命令**不来自命令行**，只来自 <任务目录>/run.env（＋ <轮次>/round.env 追加片段）。
    这是故意的：命令行只能挑"跑哪一轮"，不能塞一条新命令。
EOF
}

# ---------------------------------------------------------------------------
# 配置读取（yaml）—— 唯一实现，别处不许再解析一遍 YAML
# ---------------------------------------------------------------------------

#: 读 `config/project.yaml` 的点号路径。找到打印值；找不到退出 3。
lp_cfg_get() {
  python3 -c '
import sys, yaml
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"读不了 {sys.argv[1]}：{exc}", file=sys.stderr); sys.exit(2)
cur = doc
for k in sys.argv[2].split("."):
    if not isinstance(cur, dict) or k not in cur:
        sys.exit(3)
    cur = cur[k]
if cur is None or cur == "":
    sys.exit(3)
print(cur)
' "${LP_ROOT}/config/project.yaml" "$1"
}

#: 读**任务配置** `config/tasks/<任务名>.yaml` 的点号路径。找不到退出 3。
lp_task_cfg_get() {
  python3 -c '
import sys, yaml
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"读不了 {sys.argv[1]}：{exc}", file=sys.stderr); sys.exit(2)
cur = doc
for k in sys.argv[2].split("."):
    if not isinstance(cur, dict) or k not in cur:
        sys.exit(3)
    cur = cur[k]
if cur is None or cur == "":
    sys.exit(3)
print(cur)
' "${LP_ROOT}/config/tasks/${LP_TASK_ID}.yaml" "$1"
}

#: 读 `<轮次>/criterion.yaml` 的点号路径。找到打印值；找不到退出 3（调用方决定是否致命）。
lp_criterion_get() {
  python3 -c '
import sys, yaml
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"读不了 {sys.argv[1]}：{exc}", file=sys.stderr); sys.exit(2)
cur = doc
for k in sys.argv[2].split("."):
    if not isinstance(cur, dict) or k not in cur:
        sys.exit(3)
    cur = cur[k]
if cur is None or cur == "":
    sys.exit(3)
print(cur)
' "$1" "$2"
}

# ---------------------------------------------------------------------------
# 前导：算清楚"跑什么、往哪落"
# ---------------------------------------------------------------------------

#: 解析参数：只认四个开关 + 两个带值开关；别的**一律退出 2**（不许静默忽略）。
lp_parse_args() {
  LP_DRY_RUN=0
  LP_NO_EARLY_STOP=0
  LP_RESUME_ARG=""
  LP_ROOT_ARG=""
  LP_ROUND_ARG=""
  LP_HELP=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --root)    [[ $# -ge 2 ]] || lp_die "--root 后面缺配置根"; LP_ROOT_ARG="$2"; shift 2 ;;
      --root=*)  LP_ROOT_ARG="${1#--root=}"; shift ;;
      --round)   [[ $# -ge 2 ]] || lp_die "--round 后面缺轮次"; LP_ROUND_ARG="$2"; shift 2 ;;
      --round=*) LP_ROUND_ARG="${1#--round=}"; shift ;;
      --dry-run) LP_DRY_RUN=1; shift ;;
      --no-early-stop) LP_NO_EARLY_STOP=1; shift ;;
      --resume)  [[ $# -ge 2 ]] || lp_die "--resume 后面缺续跑点（latest 或 ckpt 目录）"; LP_RESUME_ARG="$2"; shift 2 ;;
      --resume=*) LP_RESUME_ARG="${1#--resume=}"; shift ;;
      -h|--help) LP_HELP=1; shift ;;
      *) lp_die "看不懂的参数：$1"$'\n'"（三段入口只认 --round/--root/--dry-run/--no-early-stop/--resume/--help；"$'\n'" 要跑的命令只来自 run.env，命令行塞不进去）" ;;
    esac
  done
}

#: 参数解析：结果写进 `LP_ROOT_ARG` / `LP_ROUND_ARG` / `LP_DRY_RUN` / `LP_NO_EARLY_STOP` / `LP_HELP`。
#: ★ **不许用 `$(lp_parse_args ...)`**：命令替换是子 shell，赋值出不来（踩过：--round 看着给了却报"缺 --round"）。

#: 配置根：`--root` > `$LP_ROOT` > 入口脚本上两级。**解析不出来/校验不过即退出 2**（§6.4）。
lp_resolve_root() {
  local here="$1" cand=""
  if [[ -n "$LP_ROOT_ARG" ]]; then
    cand="$LP_ROOT_ARG"
  elif [[ -n "${LP_ROOT:-}" ]]; then
    cand="$LP_ROOT"
  else
    cand="$(cd "$here/../.." 2>/dev/null && pwd)" || cand=""
  fi
  [[ -n "$cand" && -d "$cand" ]] || lp_die \
    "配置根解析不出来（给的是 ${cand:-（空）}）。"$'\n'\
    "  三段入口第一行必须写：LP_ROOT=\"\$(cd \"\$(dirname \"\${BASH_SOURCE[0]}\")/../..\" && pwd)\""$'\n'\
    "  不许按当前工作目录反推 —— 从这个仓库之外执行脚本时会指到别处。"
  LP_ROOT="$(cd "$cand" && pwd)"
  # 约定层 fail-closed：这三个东西少了，后面全是猜。
  [[ -f "$LP_ROOT/runtime/executor.py" ]] || lp_die \
    "配置根 ${LP_ROOT} 下没有 runtime/executor.py ⇒ 约定层没实现/根指错了。"$'\n'\
    "  （fail-closed：宁可现在退出 $LP_EXIT_CONTRACT，也不要跑到一半才发现。）"
  [[ -f "$LP_ROOT/config/project.yaml" ]] || lp_die "配置根 ${LP_ROOT} 下没有 config/project.yaml。"
  [[ -f "$LP_ROOT/VERSION" ]] || lp_die "配置根 ${LP_ROOT} 下没有 VERSION（不是一个工程根）。"
}

#: 读 `<任务目录>/run.env`：环境变量优先；记录规则 B ① 的基线。
lp_load_task_env() {
  LP_RUNENV="${LP_TASK_DIR}/run.env"
  [[ -f "$LP_RUNENV" ]] || lp_die \
    "找不到 ${LP_RUNENV}。"$'\n'\
    "  任务级配置只有一个落点：<任务目录>/run.env（照抄 templates/run.env）。"$'\n'\
    "  ★ 命令不许写在入口脚本里：脚本里写死命令，轮次就改不动它了。"
  # 「环境变量 > run.env」：快照 env 里的 LP_* 与 ASCEND_RT_VISIBLE_DEVICES，source 完再写回。
  local snap
  snap="$(env | grep -E '^(LP_[A-Za-z0-9_]+|ASCEND_RT_VISIBLE_DEVICES)=' || true)"
  # ★ run.env 里允许引用 LP_DATA_ROOT：它由 config/project.yaml 的 data.root 预置。
  #   本文件对 `set -u` 是**开着**的（typo 要响，不要静默变空），所以能在 run.env 里引用的变量
  #   必须是**读它之前就已经存在**的：LP_ROOT / LP_TASK_DIR / LP_DATA_ROOT。
  if [[ -z "${LP_DATA_ROOT:-}" ]]; then
    LP_DATA_ROOT="$(lp_cfg_get data.root 2>/dev/null)" || LP_DATA_ROOT=""
  fi
  export LP_DATA_ROOT
  set -a
  # shellcheck disable=SC1090
  source "$LP_RUNENV" || lp_die "source ${LP_RUNENV} 失败"
  set +a
  if [[ -n "$snap" ]]; then
    local line k
    while IFS= read -r line; do
      [[ -n "$line" ]] || continue
      k="${line%%=*}"
      export "$k=${line#*=}"
    done <<< "$snap"
    lp_note "环境变量压过 run.env 的同名键（人临时改的赢过文件里的常态值）：$(printf '%s' "$snap" | cut -d= -f1 | tr '\n' ' ')"
  fi
  LP_TASK_ID="${LP_TASK_ID:-$(basename "$LP_TASK_DIR")}"
  export LP_TASK_ID
  # ★ `LP_WORK_DIR` 的**默认**落点：`config/project.yaml` 的 `data.runs` ＋ 任务名。
  #   为什么默认值必须在这里给（而不是在 `templates/run.env` 里再写一份）：三段产物真正写到哪，
  #   与 `state.py` 记进 `artifacts.runtime_root` 的路径**必须是同一个值**；两处各写一份默认值，
  #   迟早不一致（0.18.14 之前正是如此：`data.runs` 记一个地方、东西在另一个地方）。
  #   run.env 只在**偏离**时覆盖它 —— `state.py` 会照 run.env 读，所以"覆盖"不再等于"分叉"。
  if [[ -z "${LP_WORK_DIR:-}" ]]; then
    local _runs_root
    _runs_root="$(lp_cfg_get data.runs 2>/dev/null)" || _runs_root=""
    [[ -n "$_runs_root" ]] || _runs_root="${LP_DATA_ROOT%/}/runs"
    LP_WORK_DIR="${_runs_root%/}/${LP_TASK_ID}"
  fi
  export LP_WORK_DIR
  # 规则 B ① 的基线：任务级命令原样，以及"哪些任务级 LP_* 是非空的"。
  LP_BASE_TRAIN_CMD="${LP_TRAIN_CMD:-}"
  LP_BASE_CONVERT_CMD="${LP_CONVERT_CMD:-}"
  LP_BASE_EVAL_CMD="${LP_EVAL_CMD:-}"
  LP_BASE_KEYS="$(env | grep -E '^LP_[A-Za-z0-9_]+=' | grep -v '=$' | cut -d= -f1 | sort || true)"
}

#: 轮次目录 = `<artifacts.root>/rounds/<轮次>/`（§5.3）。任务配置缺失即退出 2。
lp_resolve_round_dir() {
  local cfg="${LP_ROOT}/config/tasks/${LP_TASK_ID}.yaml"
  [[ -f "$cfg" ]] || lp_die \
    "找不到任务配置 ${cfg}。"$'\n'\
    "  任务配置是场景的唯一落点（模型/评测/产物根都在它里面）⇒ 拒绝猜产物根，退出 $LP_EXIT_CONTRACT。"
  local art
  art="$(lp_task_cfg_get artifacts.root)" || art="default"
  local base
  if [[ "$art" == "default" || -z "$art" ]]; then
    base="$LP_TASK_DIR"                       # 展开为 <paths.experiments>/<任务名>
  elif [[ "$art" == /* ]]; then
    base="$art"
  else
    base="${LP_ROOT}/${art}"
  fi
  LP_ARTIFACTS_ROOT="$base"
  # ★ 先建**本工程要写的产物根**，再要求**冻结的轮次目录**存在 —— 两件事的 fail 方向相反
  #   （前者该建，后者不存在就拒）。顺序反了就会把"产物根没建"误报成"轮次目录不存在"。
  lp_prepare_artifacts_root
  LP_ROUND_DIR="${base}/rounds/${LP_ROUND}"
  [[ -d "$LP_ROUND_DIR" ]] || lp_die \
    "轮次目录不存在：${LP_ROUND_DIR}"$'\n'\
    "  轮次目录由人/流水线在方案冻结时建好（本文件**从不自己建** —— 建了就等于轮次可以凭空出现）。"$'\n'\
    "  它必须含 design.md / criterion.yaml / round.env，且**不含**三段脚本副本（devtools/check_round_layout.py 会查）。"
}

#: 读 `<轮次>/round.env` 并**机械地**执行规则 B ①。
lp_load_round_env() {
  LP_ROUNDENV="${LP_ROUND_DIR}/round.env"
  [[ -f "$LP_ROUNDENV" ]] || lp_die \
    "找不到 ${LP_ROUNDENV}（轮次目录必须含 design.md / criterion.yaml / round.env）。"
  set -a
  # shellcheck disable=SC1090
  source "$LP_ROUNDENV" || lp_die "source ${LP_ROUNDENV} 失败"
  set +a
  # ① 不许重定义整条命令
  local pair var now was
  for pair in "LP_TRAIN_CMD:${LP_BASE_TRAIN_CMD}" \
              "LP_CONVERT_CMD:${LP_BASE_CONVERT_CMD}" \
              "LP_EVAL_CMD:${LP_BASE_EVAL_CMD}"; do
    var="${pair%%:*}"; was="${pair#*:}"
    eval "now=\${${var}:-}"
    if [[ "$now" != "$was" ]]; then
      lp_die \
        "round.env 重定义了整条命令 ${var}（规则 B ① 明令禁止）。"$'\n'\
        "  任务级原命令：${was:0:120}"$'\n'\
        "  round.env 之后：${now:0:120}"$'\n'\
        "  轮次要改命令，只许改 round.env 里的**变量值**或追加 LP_TRAIN_EXTRA_ARGS / LP_CONVERT_EXTRA_ARGS / LP_EVAL_EXTRA_ARGS。"$'\n'\
        "  （命令只有一个落点：<任务目录>/run.env。两边都能定义命令，轮次就不可复现了。）"
    fi
  done
  # ② 不许删除任务级变量
  local k
  while IFS= read -r k; do
    [[ -n "$k" ]] || continue
    eval "now=\${${k}:-}"
    if [[ -z "$now" ]]; then
      lp_die "round.env 删掉了任务级变量 ${k}（规则 B ①：不改变量值 ⇒ 把它设成空了）。"
    fi
  done <<< "${LP_BASE_KEYS:-}"
  # 允许的追加片段：只有这三个（**每段一个槽**，别串用）
  LP_TRAIN_EXTRA_ARGS="${LP_TRAIN_EXTRA_ARGS:-}"
  LP_CONVERT_EXTRA_ARGS="${LP_CONVERT_EXTRA_ARGS:-}"
  LP_EVAL_EXTRA_ARGS="${LP_EVAL_EXTRA_ARGS:-}"
  LP_CRITERION="${LP_CRITERION:-${LP_ROUND_DIR}/criterion.yaml}"
  # ★ `LP_EV`（0.18.31 起**文档化**）：这一段跑的**证据目录**。日志、`<段>.exec.json`、
  #   `loss.txt`、早停留痕、评测默认落点、探针产物**全部**跟着它走 —— 所以它是
  #   "这一次跑的留痕放哪"的唯一落点（`templates/run.env` 有键表，`round.env` 也能改它）。
  #   典型用法：冒烟（10 步）指到 `<轮次>/evidence/smoke`，正式跑不带 ⇒ 两遍不撞名。
  #   **必须是绝对路径**：相对路径会被 `mkdir -p` 按当前 cwd 解释，日志就落到别处了。
  LP_EV="${LP_EV:-${LP_ROUND_DIR}/evidence}"
  case "$LP_EV" in
    /*) ;;
    *) lp_die "LP_EV 必须是绝对路径（给的是 ${LP_EV}）。"$'\n'\
              "  它是**证据目录**：日志/exec.json/loss/探针产物都写进它；"$'\n'\
              "  相对路径会按当前 cwd 解释 ⇒ 留痕落到别处，抽数就找不到。" ;;
  esac
  # ★ 钩子/子进程要用到的路径**必须 export**：不 export 时 `$LP_ROUND_DIR` 在钩子里是空的，
  #   于是 `> "$LP_ROUND_DIR/metrics.json"` 会往 `/metrics.json` 写 —— 而 root 下**写得进去**，
  #   表现就是"钩子改了只读件却没人发现"（实测踩过，见 [8] 的对照用例）。
  # ★ ckpt 落点（0.18.26）：默认算式与 `commands/train_cmd.sh` **同一份**，靠 LP_TRAIN_OUT 传递。
  #   两处各算一遍必然漂移（0.18.14 的教训）——这里算完 export，train_cmd.sh 优先读它。
  if [[ -z "${LP_TRAIN_OUT:-}" ]]; then
    LP_TRAIN_OUT="${LP_WORK_DIR:-${LP_ROOT}/experiments/${LP_TASK_ID}}/rounds/${LP_ROUND}/ckpt"
  fi
  export LP_TRAIN_OUT
  export LP_ROOT LP_TASK_DIR LP_TASK_ID LP_ROUND LP_ROUND_DIR LP_CRITERION LP_EV
  [[ -f "$LP_CRITERION" ]] || lp_die "找不到判据 ${LP_CRITERION}（判据管「算不算成」与评测口径：success／falsification／eval_protocol／baseline_ref；早停与墙钟阈值**不在这里**，在 config/tasks/${LP_TASK_ID}.yaml 的 stop_conditions）。"
  mkdir -p "$LP_EV" || lp_die "建不了证据目录 ${LP_EV}"
}

#: 本工程**要写**的产物目录（`artifacts.root`）：不存在就**创建**（真跑路径）。
#: `--dry-run` 只预告、不落盘。它是**本工程要写**的产物根，不是外部输入。
lp_prepare_artifacts_root() {
  [[ -n "${LP_ARTIFACTS_ROOT:-}" ]] || lp_die \
    "内部不一致：LP_ARTIFACTS_ROOT 还没算出来（应先跑 lp_resolve_round_dir）。"
  if [[ -d "$LP_ARTIFACTS_ROOT" ]]; then
    lp_note "产物根已存在：${LP_ARTIFACTS_ROOT}（本工程要写的目录）"
    return 0
  fi
  if [[ "$LP_DRY_RUN" == "1" ]]; then
    lp_note "产物根不存在：${LP_ARTIFACTS_ROOT} ⇒ 真跑会在起作业前创建它（--dry-run 不落盘）"
    return 0
  fi
  mkdir -p "$LP_ARTIFACTS_ROOT" || lp_die \
    "建不了产物根 ${LP_ARTIFACTS_ROOT} ⇒ 退出 ${LP_EXIT_CONTRACT}。"$'\n'\
    "  artifacts.root 是**本工程要写的产物目录**（该建就建）。"
  lp_note "产物根不存在 ⇒ 已创建：${LP_ARTIFACTS_ROOT}（本工程要写的目录）"
}

#: 三段入口的总前导。用法：`lp_setup <stage> <任务目录> "$@"`
lp_setup() {
  [[ $# -ge 2 ]] || lp_die "lp_setup 用法：lp_setup <train|convert|eval> <任务目录> \"\$@\""
  LP_STAGE="$1"
  case "$LP_STAGE" in train|convert|eval) ;; *) lp_die "阶段名只认 train/convert/eval，给的是 ${LP_STAGE}";; esac
  LP_TASK_DIR="$(cd "$2" 2>/dev/null && pwd)" || lp_die "任务目录不存在：$2"
  shift 2

  lp_parse_args "$@"
  if [[ "$LP_HELP" == "1" ]]; then lp_usage "$LP_STAGE"; exit "$LP_EXIT_OK"; fi
  [[ -n "$LP_ROUND_ARG" ]] || lp_die \
    "缺 --round <轮次>。"$'\n'\
    "  三段入口都要求显式给轮次：脚本**从不自己猜**「现在跑哪一轮」——"$'\n'\
    "  猜错的方向是静默的（数字落到别的轮次目录里，报告却指向这一轮）。"
  LP_ROUND="$LP_ROUND_ARG"

  lp_resolve_root "$LP_TASK_DIR"
  lp_load_task_env
  export LP_STAGE LP_ROUND   # 放在读 run.env **之后**：否则它们会被当成"人给的环境变量"混进留痕
  lp_resolve_round_dir
  lp_load_round_env

  lp_note "阶段=${LP_STAGE} 任务=${LP_TASK_ID} 轮次=${LP_ROUND}"
  lp_note "任务目录  ${LP_TASK_DIR}"
  lp_note "轮次目录  ${LP_ROUND_DIR}"
  lp_note "判据      ${LP_CRITERION}"
  lp_note "证据目录  ${LP_EV}"
  [[ "$LP_DRY_RUN" == "1" ]] && lp_note "**--dry-run**：只打印，不起进程、不占卡"
  [[ "$LP_NO_EARLY_STOP" == "1" ]] && lp_note "**--no-early-stop**：关掉在线早停（非有限值熔断仍在）"
  lp_resolve_resume
  return 0
}

# ---------------------------------------------------------------------------
# 阈值：只传递，不设默认值
# ---------------------------------------------------------------------------

#: 读**任务配置**的 `stop_conditions.wall_clock_hours` 并校验取值；成功时打印值。
#  失败时返回非 0（由调用方决定"退出几"）—— 在命令替换里 lp_die 只会杀掉子 shell，不解决问题。
lp_wall_hours() {
  local wh
  wh="$(lp_task_cfg_get stop_conditions.wall_clock_hours)" || return 3
  python3 - "$wh" <<'PY' || return 2
import sys
try:
    wh = float(sys.argv[1])
except ValueError:
    print(f"wall_clock_hours={sys.argv[1]!r} 不是数字", file=sys.stderr); sys.exit(2)
if not wh > 0:
    print(f"wall_clock_hours={wh}：必须 > 0 —— 0 或负数等于**关掉墙钟闸**"
          f"（执行器会把它当成没有上限，于是无限等一张卡）", file=sys.stderr); sys.exit(2)
if wh > 24 * 30:
    print(f"wall_clock_hours={wh}：> 720 小时，看着像单位填错（秒/小时？）", file=sys.stderr); sys.exit(2)
PY
  printf '%s' "$wh"
}

#: 把 `--resume <latest|目录>` 解析成 `LP_RESUME_FROM`（0.18.26）。空 ⇒ 不动（从基座开跑）。
#  ★ 只在 train 段有意义；值不合法 ⇒ 退出 2（**不许猜** —— 猜错的方向是"从第 0 步重跑但看起来像续跑"）。
lp_resolve_resume() {
  LP_RESUME_FROM=""
  [[ -n "${LP_RESUME_ARG:-}" ]] || return 0
  [[ "$LP_STAGE" == "train" ]] || lp_die "--resume 只对 train 段有意义（当前阶段 ${LP_STAGE}）"
  local want="$LP_RESUME_ARG"
  if [[ "$want" == "latest" ]]; then want="$LP_TRAIN_OUT"; fi
  [[ -d "$want" ]] || lp_die \
    "--resume 指向的目录不存在：${want}"$'\n'\
    "  用法：--resume latest（=<轮次>/ckpt）或 --resume <ckpt 目录>"
  if [[ ! -f "${want}/latest_checkpointed_iteration.txt" ]] \
     && ! compgen -G "${want}/iter_*" >/dev/null; then
    lp_die \
      "--resume 目录里既没有 latest_checkpointed_iteration.txt 也没有 iter_*：${want}"$'\n'\
      "  这不是一个 ckpt 目录。基座权重目录请填任务配置 model.start.path，别当续跑点。"
  fi
  LP_RESUME_FROM="$(cd "$want" && pwd)"
  export LP_RESUME_FROM
  lp_note "--resume：从 ${LP_RESUME_FROM} 续跑（去掉 --finetune 与 --no-load-*；迭代数由框架从 ckpt 恢复）"
}

#: 组装早停阈值 argv 到全局数组 `LP_STOP_ARGS`。缺任一项即退出 2（**不猜**）。
#  ★ 唯一落点是**任务配置**（0.18.18 起）：`loss.*`／`wall_clock_hours`／`max_steps` 全部从
#    `config/tasks/<任务名>.yaml` 的 `stop_conditions.*` 读 —— 人只填那一份，能力就真接上了。
#    判据只管"算不算成"（`success`／`falsification`／`eval_protocol`）。历史：这两组曾是判据字段，
#    于是人填的任务配置没人读、要靠角色转抄 ⇒ **能力等于没有**（0.18.18 迁回）。
lp_build_stop_args() {
  local jf rb mp wh="" ms=""
  jf="$(lp_task_cfg_get "${LP_STOP_KEYS[0]}")" || lp_die \
    "任务配置里没有 ${LP_STOP_KEYS[0]} ⇒ 在线早停没有阈值可用。"$'\n'\
    "  唯一落点是 config/tasks/${LP_TASK_ID}.yaml（本文件一行默认值都不写）。"$'\n'\
    "  要关掉在线早停请显式给 --no-early-stop（那也不许在这里补一个默认阈值）。"
  rb="$(lp_task_cfg_get "${LP_STOP_KEYS[1]}")" || lp_die "任务配置里没有 ${LP_STOP_KEYS[1]}。"
  mp="$(lp_task_cfg_get "${LP_STOP_KEYS[2]}")" || lp_die "任务配置里没有 ${LP_STOP_KEYS[2]}。"
  wh="$(lp_wall_hours)" || lp_die \
    "任务配置的 stop_conditions.wall_clock_hours 缺失或取值不合法。"$'\n'\
    "  墙钟上限**必须有且 > 0**（超时归 $LP_EXIT_TRAIN_INVALID，见 runtime/README.md §2.1）—— 不许无限等一张卡。"
  # 单向闸：阈值写反了（比如 jump_factor < 1）当即退出 2，别等它误杀作业。
  python3 - "$jf" "$rb" "$mp" <<'PY' || exit $LP_EXIT_CONTRACT
import sys
jf, rb, mp = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
bad = []
if not jf > 1: bad.append(f"jump_factor={jf}（必须 > 1：小于 1 等于把正常波动判成发散）")
if not rb > 1: bad.append(f"rel_to_best={rb}（必须 > 1）")
if mp < 1: bad.append(f"min_points={mp}（必须 >= 1）")
if bad:
    print("阈值取值不合法：" + "；".join(bad), file=sys.stderr); sys.exit(2)
PY
  LP_STOP_ARGS=("--jump-factor" "$jf" "--rel-to-best" "$rb" "--min-points" "$mp"
                "--max-wall-hours" "$wh")
  # `max_steps` 是**透传事实**（执行器只记录，不据此杀进程；到点收工是训练侧 `--train-iters` 的事）。
  # ★ `quant_error_max` **不在**这里：它的唯一落点是**任务配置**，由 `train_cmd.sh` 换算成
  #   `QAT_QSNR_FLOOR_DB` 注入训练进程（探针看门狗据此停跑）。criterion 里不再有同名字段 ——
  #   同一个阈值两处各写一份，就是"人在 YAML 里改、机器按别处跑"（0.18.13 之前的样子）。
  local ms
  ms="$(lp_task_cfg_get stop_conditions.max_steps)" && LP_STOP_ARGS+=("--max-steps" "$ms")
  lp_note "早停阈值（来源 config/tasks/${LP_TASK_ID}.yaml）：jump_factor=${jf} rel_to_best=${rb} min_points=${mp} 墙钟=${wh}h"
  [[ -n "${ms:-}" ]] && lp_note "透传事实：max_steps=${ms}（执行器只记录，判定归 metrics.py）"

  # ★ 平台早停（0.18.26，**可选**）：整块不配 ⇒ 不传（行为同 0.18.25）；配一半 ⇒ 退出 2。
  #   命中 ⇒ converged ＋ 退出 0（**合法收工**），不是 5。
  local pw="" pg="" pp="" pm=""
  if pw="$(lp_task_cfg_get stop_conditions.plateau.window_steps 2>/dev/null)"; then
    pg="$(lp_task_cfg_get stop_conditions.plateau.min_gain_pct 2>/dev/null)" || lp_die \
      "任务配置有 stop_conditions.plateau.window_steps，却缺 min_gain_pct（整块要四件齐全）。"
    pp="$(lp_task_cfg_get stop_conditions.plateau.patience 2>/dev/null)" || lp_die \
      "任务配置有 stop_conditions.plateau.window_steps，却缺 patience（整块要四件齐全）。"
    pm="$(lp_task_cfg_get stop_conditions.plateau.min_steps 2>/dev/null)" || lp_die \
      "任务配置有 stop_conditions.plateau.window_steps，却缺 min_steps（整块要四件齐全）。"
    # ★ 正文必须顶格：`<<'PY2'`（不带 `-`）**不剥离任何缩进**，正文缩进就是 Python 的
    #   IndentationError（0.18.32 之前这里缩进了 2 空格 ⇒ 只要配了 plateau，训练段一律退 2）。
    python3 - "$pw" "$pg" "$pp" "$pm" <<'PY2' || exit $LP_EXIT_CONTRACT
import sys
pw, pg, pp, pm = int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
bad = []
if pw < 2: bad.append(f"window_steps={pw}（必须 >= 2）")
if not pg > 0: bad.append(f"min_gain_pct={pg}（必须 > 0）")
if pp < 1: bad.append(f"patience={pp}（必须 >= 1）")
if pm < 1: bad.append(f"min_steps={pm}（必须 >= 1）")
if bad:
    print("平台早停取值不合法：" + "；".join(bad), file=sys.stderr); sys.exit(2)
PY2
    LP_STOP_ARGS+=(--plateau-window "$pw" --plateau-min-gain-pct "$pg"
                   --plateau-patience "$pp" --plateau-min-steps "$pm")
    lp_note "平台早停（来源 config/tasks/${LP_TASK_ID}.yaml）：window=${pw} min_gain_pct=${pg}% patience=${pp} min_steps=${pm} ⇒ 命中记 converged、退出 0"

  fi
  # ★ held-out racing（0.19.0，**可选**）：整块不配 ⇒ 不传（行为同 0.18.x）；
  #   三个阈值同进同出，缺一即退出 2。参照**不是配置项** —— 由 executor 从
  #   `records/best/<任务名>__*.yaml` 的 `round:` 现算（0.19.0 定：best 那一轮天然
  #   "跑完 ＋ 通过判定 ＋ 证据齐全"）。参照不存在 ⇒ 本轮不判（止损仍在），**不猜**。
  local hm="" hg="" hp=""
  if hm="$(lp_task_cfg_get stop_conditions.holdout.min_step 2>/dev/null)"; then
    hg="$(lp_task_cfg_get stop_conditions.holdout.max_gap_pct 2>/dev/null)" || lp_die \
      "任务配置有 stop_conditions.holdout.min_step，却缺 max_gap_pct（整块要三件齐全）。"
    hp="$(lp_task_cfg_get stop_conditions.holdout.patience 2>/dev/null)" || lp_die \
      "任务配置有 stop_conditions.holdout.min_step，却缺 patience（整块要三件齐全）。"
    # 正文必须顶格（`<<'PY5'` 不剥缩进）—— 0.18.32 那个 IndentationError 的同一个坑。
    python3 - "$hm" "$hg" "$hp" <<'PY5' || exit $LP_EXIT_CONTRACT
import sys
hm, hg, hp = int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
bad = []
if hm < 1: bad.append(f"min_step={hm}（必须 >= 1）")
if hg < 0: bad.append(f"max_gap_pct={hg}（必须 >= 0）")
if hp < 1: bad.append(f"patience={hp}（必须 >= 1）")
if bad:
    print("held-out racing 取值不合法：" + "；".join(bad), file=sys.stderr); sys.exit(2)
PY5
    LP_STOP_ARGS+=(--holdout-min-step "$hm" --holdout-max-gap-pct "$hg"
                   --holdout-patience "$hp")
    # 两个路径由本文件给（executor 不猜工程根）：best 档案目录 ＋ 轮次根。
    local rb="${LP_ROOT}/records/best"
    local rr="${LP_ARTIFACTS_ROOT:-${LP_TASK_DIR:-}}/rounds"
    LP_STOP_ARGS+=(--holdout-best-dir "$rb" --holdout-rounds-dir "$rr"
                   --holdout-cell "$LP_TASK_ID")
    lp_note "held-out racing（来源 config/tasks/${LP_TASK_ID}.yaml）：min_step=${hm} max_gap_pct=${hg} patience=${hp}"
    lp_note "  参照轮：${rb}/${LP_TASK_ID}__*.yaml 的 round:（找不到 ⇒ 本轮不判，止损仍在）"
    # ★ 与验证集口径联动：racing 需要训练 argv 真的打验证行。这里只**提示**、不改 argv
    #   （训练 argv 的唯一落点是 <任务目录>/commands/train_argv.txt）；executor 会在
    #   开跑前 fail-closed 核对 `--split` / `--eval-iters`，不靠运气。
    lp_note "  验证集口径：<任务目录>/commands/train_argv.txt 的 --split（第二段 > 0）或"
    lp_note "  --valid-data-path，且 --eval-iters > 0；executor 开跑前会核对。"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# 设备守卫：卡只从 runtime/resources.py 来（本文件不写死任何卡号）
# ---------------------------------------------------------------------------

#: 起作业前过一遍设备守卫（§6.3 第 2 行：**扫占用 ＋ 三层定卡**）。
#: dry-run 时"定不下卡"只 WARN（它不占卡）。
lp_guard_devices() {
  local what="${1:-作业}"
  local res="${LP_ROOT}/runtime/resources.py"
  [[ -f "$res" ]] || lp_die "找不到 ${res} ⇒ 取卡没有落点（本文件不写死卡号）。"

  # ① 定卡（三层：策略／实测／决策）。卡号只在 resources.py 里定。
  local prc=0 pjson=""
  pjson="$(python3 "$res" pick --json 2>/dev/null)" || prc=$?
  if [[ "$prc" -ne "$LP_EXIT_OK" || -z "$pjson" ]]; then
    local why
    why="$(python3 "$res" pick 2>&1 | sed 's/^/    /' || true)"
    if [[ "$LP_DRY_RUN" == "1" ]]; then
      lp_warn "定不下卡 —— 但这是 --dry-run，**只警告不拦**（dry-run 不占卡）："
      printf '%s\n' "$why" >&2
      return 0
    fi
    lp_die "定不下本轮用哪几张卡（${what}）⇒ 不起作业（退出 ${LP_EXIT_CONTRACT}）。"$'\n'"${why}"$'\n'\
      "  ★ 卡号只有一个落点：runtime/resources.py（策略层读 config/project.yaml 的 devices.*）。"$'\n'\
      "    自动选卡永不选 reserved 卡；显式点名 reserved 卡同样被拒。"
  fi
  local cards source
  cards="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("export",""))' <<< "$pjson")"
  source="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("source",""))' <<< "$pjson")"
  [[ -n "$cards" ]] || lp_die "resources.py pick 成功了却没给出卡号（内部不一致）⇒ 退出 ${LP_EXIT_CONTRACT}。"
  lp_note "本轮用卡 ${cards}（来源：${source}）"
  export ASCEND_RT_VISIBLE_DEVICES="$cards"

  # ② 这组卡现在有没有被占（可靠来源 BLOCK / 不可靠来源只 WARN）
  local crc=0 cout=""
  cout="$(python3 "$res" check --cards "$cards" 2>&1)" || crc=$?
  if [[ "$crc" -ne "$LP_EXIT_OK" ]]; then
    if [[ "$LP_DRY_RUN" == "1" ]]; then
      lp_warn "占用检查发现冲突 —— 但这是 --dry-run，**只警告不拦**（dry-run 不占卡）："
      printf '%s\n' "$cout" | sed 's/^/    /' >&2
      return 0
    fi
    printf '%s\n' "$cout" >&2
    lp_die "卡 ${cards} 现在被占（${what}）⇒ **现在不能起作业**（退出 ${LP_EXIT_CONTRACT}）。"$'\n'\
      "  这不是判定：说的是「现在不能起」，不是「方案不好」。等它跑完，或换卡。"
  else
    printf '%s\n' "$cout" | sed 's/^/  /' >&2
  fi
}

# ---------------------------------------------------------------------------
# 钩子（§5.3：存在即执行）
# ---------------------------------------------------------------------------

#: `lp_hooks <pre|post>`。钩子只许做事 ＋ 往 evidence/ 落文件。
lp_hooks() {
  local when="$1"
  local h="${LP_ROUND_DIR}/hooks/${when}_${LP_STAGE}.sh"
  [[ -f "$h" ]] || return 0
  lp_note "钩子 ${when}_${LP_STAGE}.sh：存在即执行 → ${h}"
  bash "$h" || lp_die "钩子 ${h} 失败（退出 $?）⇒ 本轮不继续（钩子说'不能跑'就得听）。"
  lp_note "钩子 ${when}_${LP_STAGE}.sh 通过"
}

# ---------------------------------------------------------------------------
# 起阶段：交给 executor.py
# ---------------------------------------------------------------------------

#: 生效命令 = 任务级原命令 ＋ 轮次级追加片段。**两段都打出来**（可核对）。
lp_effective_cmd() {
  local base="$1" extras_var="$2" extras=""
  eval "extras=\${${extras_var}:-}"
  LP_CURRENT_BASE="$base"
  LP_CURRENT_EXTRAS="$extras"
  if [[ -n "$extras" ]]; then
    LP_CURRENT_CMD="${base} ${extras}"
  else
    LP_CURRENT_CMD="$base"
  fi
}

#: 真跑（或 dry-run 只打印）。用法：`lp_run_stage <阶段> <命令字符串> <人话标签>`
lp_run_stage() {
  local stage="$1" cmd="$2" label="${3:-$1}"
  local log="${LP_EV}/${stage}.log"
  local meta="${LP_EV}/${stage}.exec.json"

  if [[ "$LP_DRY_RUN" == "1" ]]; then
    echo "--dry-run：以下**不执行**，只打印（不起进程、不占卡）"
    echo "  阶段            ${stage}（${label}）"
    echo "  任务级 run.env 原命令（逐字）：${LP_CURRENT_BASE:-$cmd}"
    echo "  轮次级追加 argv 片段：${LP_CURRENT_EXTRAS:-(无)}"
    # ★ 调用方传进来的 $cmd **就是**生效命令（`lp_effective_cmd` 的产物）；这里不许再拼一次片段 ——
    #   P4c 实测踩过：再拼一次会让片段出现两遍（打印成 `... --dry-run --dry-run`），
    #   谁照抄这行去手工执行就会拿到一个多一个参数的 argv。
    echo "  生效命令（effective）：${cmd}"
    echo "  日志落点        ${log}"
    # 0.18.18：dry-run 也把**生效的保险丝**打出来（早停阈值/墙钟）——与真跑同一个读者、
    # 同一套守卫。人在花卡之前就能看到"我填进任务配置的那几个数到底认不认"；
    # 缺值/写反 ⇒ 这里就退出 2，不是等真跑才炸。
    if [[ "$stage" == "train" && "$LP_NO_EARLY_STOP" != "1" ]]; then
      lp_build_stop_args
      echo "  早停/墙钟生效值：${LP_STOP_ARGS[*]}"
    elif [[ "$stage" == "convert" || "$stage" == "eval" ]]; then
      local _wh
      _wh="$(lp_wall_hours)" || lp_die \
        "任务配置的 stop_conditions.wall_clock_hours 缺失或取值不合法（${stage} 段也要墙钟）。"
      echo "  墙钟生效值      --max-wall-hours ${_wh}"
    fi
    echo "  产不出数字 —— dry-run 不产生任何证据，别拿它当结论。"
    return "$LP_EXIT_OK"
  fi

  local -a argv=(python3 "${LP_ROOT}/runtime/executor.py"
                 --round "$LP_ROUND" --stage "$stage"
                 --log "$log" --meta "$meta")
  if [[ "$stage" == "train" ]]; then
    argv+=(--loss-out "${LP_EV}/loss.txt" --valid-out "${LP_EV}/valid.txt"
           --marker "${LP_EV}/early_stop.triggered")
    # ckpt 保留（0.18.26）：keep_last 来自任务配置；缺失/非法 ⇒ executor **不删**（fail-closed）。
    local ck_keep=""
    if ck_keep="$(lp_task_cfg_get train.checkpoint.keep_last 2>/dev/null)"; then
      argv+=(--ckpt-dir "$LP_TRAIN_OUT" --ckpt-keep-last "$ck_keep"
             --retention-log "${LP_EV}/ckpt-retention.log")
    fi
    [[ -n "${LP_RESUME_FROM:-}" ]] && argv+=(--resume-from "$LP_RESUME_FROM")
    if [[ "$LP_NO_EARLY_STOP" == "1" ]]; then
      argv+=(--no-early-stop)
    else
      lp_build_stop_args
      argv+=("${LP_STOP_ARGS[@]}")
    fi
  elif [[ "$stage" == "convert" || "$stage" == "eval" ]]; then
    # 这两段没有 loss 轨迹：不早停，但**墙钟上限仍然要**（超时归 5，见 §2.1）。
    argv+=(--no-early-stop)
    local wh
    wh="$(lp_wall_hours)" || lp_die \
      "任务配置的 stop_conditions.wall_clock_hours 缺失或取值不合法（${stage} 段也要墙钟）。"$'\n'\
      "  唯一落点：config/tasks/${LP_TASK_ID}.yaml；值必须 > 0。"
    argv+=(--max-wall-hours "$wh")
  fi

  lp_note "起 ${stage}：$( [[ "$stage" == train ]] && echo "在线早停 $([[ "$LP_NO_EARLY_STOP" == 1 ]] && echo 关闭 || echo 开启)" )"
  # ★ 片段**已经在 $cmd 里**（调用方传的是 lp_effective_cmd 的产物）—— 这里再拼一次就是打两遍，
  #   人会以为命令里真重复了参数（0.18.28 前就是这样，dry-run 分支已修、真跑分支漏了）。
  lp_note "命令：${cmd}"
  local rc=0
  "${argv[@]}" -- bash -c "$cmd" || rc=$?
  lp_note "${stage} 退出码=${rc}（执行器原始码；翻成人话由入口负责）"
  return "$rc"
}

lp_selftest() {
  local checks=0 fails=0
  _lp_case() { # <名字> <0=ok>
    checks=$((checks + 1))
    if [[ "$2" == "0" ]]; then
      printf '  ok    %s\n' "$1"
    else
      printf '  FAIL  %s    rc=%s\n' "$1" "$2"
      fails=$((fails + 1))
    fi
  }
  echo "======================================================================"
  echo "_common.sh lp_selftest（被 source 的那个 shell 里跑；用 /tmp 夹具）"
  echo "======================================================================"

  local real_root tmp fxroot rc
  real_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  tmp="$(mktemp -d)"
  # ★ 夹具根：一个**自足**的临时配置根。为什么不直接用真根当 LP_ROOT：真根下只有真实任务配置，
  #   夹具一旦引用真实任务名，引擎层就带上了具体任务名 —— `devtools/check_decoupling.py` 会当场判红
  #   （`runtime/` 只许出现 `<任务名>` 这类占位）。所以：runtime/ 软链过来、config/ 整份复制过来、
  #   任务配置用**中性夹具名**。
  fxroot="${tmp}/root"
  mkdir -p "${fxroot}"
  ln -s "${real_root}/runtime" "${fxroot}/runtime"
  cp -r "${real_root}/config" "${fxroot}/config"
  cp "${real_root}/VERSION" "${fxroot}/VERSION"
  cat > "${fxroot}/config/tasks/fx-task.yaml" <<'EOC'
task_id: fx-task
model:
  name: fixture-model
eval:
  metrics:
    - fixture_metric
artifacts:
  root: default
stop_conditions:
  max_steps: 20
  wall_clock_hours: 1
  loss: {jump_factor: 4.0, rel_to_best: 2.5, min_points: 5}
EOC

  echo
  echo "[1] 被 source 之后，函数都在（source 本身 rc=0、不打印不做事）"
  local f
  for f in lp_setup lp_parse_args lp_resolve_root lp_load_task_env lp_resolve_round_dir \
           lp_load_round_env lp_criterion_get lp_task_cfg_get lp_wall_hours \
           lp_build_stop_args lp_guard_devices \
           lp_hooks lp_run_stage lp_effective_cmd lp_prepare_artifacts_root; do
    declare -F "$f" >/dev/null && _lp_case "函数 ${f} 已定义" 0 || _lp_case "函数 ${f} 已定义" 1
  done
  _lp_case "函数 _lp_case 已定义" 0

  echo
  echo "[2] 直接执行 = 用法错误（退出 2），只有被 source 才继续"
  bash "${real_root}/runtime/_common.sh" >/dev/null 2>&1
  _lp_case "bash runtime/_common.sh ⇒ 2" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"

  # ── 夹具：一个临时任务目录 + 轮次目录 ──
  local task="$tmp/task" round="$tmp/task/rounds/R-0001"
  mkdir -p "$round/evidence" "$round/hooks"
  cat > "$task/run.env" <<'EOF'
LP_TASK_ID="fx-task"
LP_WORK_DIR="$LP_DATA_ROOT/runs"
LP_TRAIN_CMD="python3 -m fake.train --steps 20 --tag alpha"
LP_CONVERT_CMD="python3 -m fake.convert --in a --out b"
LP_EVAL_PYTHON="python3"
LP_EVAL_CMD="python3 -m fake.eval --set s"
LP_TRAIN_EXTRA_ARGS=""
LP_CONVERT_EXTRA_ARGS=""
LP_EVAL_EXTRA_ARGS=""
EOF
  # 0.18.18 起判据**不再有** stop_conditions：这里故意留一份**旧口径 999**，
  # 用来证明"判据里写了也不被读"（迁移的回归防线）。
  cat > "$round/criterion.yaml" <<'EOF'
stop_conditions:
  loss: {jump_factor: 999.0, rel_to_best: 999.0, min_points: 99}
  max_steps: 999
  wall_clock_hours: 999
EOF
  echo '# 本轮不追加任何片段（夹具）' > "$round/round.env"

  echo
  echo "[3] 根解析 fail-closed：--root 指不存在的树 ⇒ 退出 2；--help ⇒ 0"
  ( lp_setup train "$task" --root /nonexistent-tree-LPTA --round R-0001 --dry-run ) >/dev/null 2>&1
  _lp_case "--root /nonexistent ⇒ 2" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  ( lp_setup train "$task" --round R-0001 --help ) >/dev/null 2>&1
  _lp_case "--help ⇒ 0" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  ( lp_setup train "$task" --dry-run ) >/dev/null 2>&1
  _lp_case "缺 --round ⇒ 2（不猜轮次）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  ( lp_setup train "$task" --round R-0001 --dry-run --bogus ) >/dev/null 2>&1
  _lp_case "看不懂的参数 ⇒ 2（不静默忽略）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"

  echo
  echo "[4] 正常前导：落盘位置/命令/阈值都对得上（--dry-run，不占卡）"
  local out
  rc=0
  out="$( lp_setup train "$task" --root "$fxroot" --round R-0001 --dry-run 2>&1 )" || rc=$?
  _lp_case "lp_setup 正常 rc=0" "$([[ "$rc" == "0" ]] && echo 0 || echo 1)"
  rc=0
  out="$( export LP_ROOT="$fxroot"
          lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
          lp_effective_cmd "$LP_TRAIN_CMD" LP_TRAIN_EXTRA_ARGS
          lp_run_stage train "$LP_CURRENT_CMD" 训练 )" || rc=$?
  grep -q "生效命令" <<< "$out" && _lp_case "dry-run 打印了生效命令（原命令＋片段）" 0 \
    || _lp_case "dry-run 打印了生效命令（原命令＋片段）" 1
  # 夹具里 run.env 的 LP_TRAIN_CMD（逐字）；这里不引用 $LP_TRAIN_CMD ——
  # 上面的 lp_setup 跑在命令替换的子 shell 里，变量出不来（同一个坑，前面刚踩过一次）。
  grep -qF 'python3 -m fake.train --steps 20 --tag alpha' <<< "$out" \
    && _lp_case "打印里含任务级原命令逐字" 0 || _lp_case "打印里含任务级原命令逐字" 1
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    [[ "$LP_ROUND_DIR" == "$round" ]] && [[ "$LP_CRITERION" == "$round/criterion.yaml" ]] )
  _lp_case "轮次目录/判据路径算对" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  # ★ 0.18.31：`LP_EV` 扶正（证据目录旋钮）—— 相对路径必须当场拒，绝对路径必须被采纳。
  ( LP_ROOT="$fxroot" LP_EV=relative/evidence \
    lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1 )
  _lp_case "LP_EV 相对路径 ⇒ 2（否则留痕按 cwd 落，抽数找不到）" \
    "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  out="$( LP_ROOT="$fxroot" LP_EV="$round/evidence/smoke" \
          lp_setup train "$task" --round R-0001 --dry-run 2>&1 )"
  grep -qF "证据目录  $round/evidence/smoke" <<< "$out" \
    && _lp_case "LP_EV 绝对路径 ⇒ 采纳它并打印（冒烟指到 smoke/ 就靠这条）" 0 \
    || _lp_case "LP_EV 绝对路径 ⇒ 采纳它并打印（冒烟指到 smoke/ 就靠这条）" 1

  # ★ 0.18.34（CR-0006）：**真实形状** —— `LP_EV` 在**外层进程**导出，`source` 之后还在。
  #   0.18.31 的 `LP_EV=""` 会在 source 那一刻把它抹掉，而上面那条用例的赋值挂在 `lp_setup`
  #   的前缀上（晚于 source）⇒ 形状绕开缺陷，59 条全绿也漏。
  #   这条只钉"活过 source"这一环；"被 `:374` 采纳"由上面那条 ＋ 本环共同保证
  #   （夹具的 task 目录名不是 fx-task，整链干跑会因 `LP_TASK_ID` 重算而找不到任务配置）。
  out="$( LP_ROOT="$fxroot" LP_TASK_ID=fx-task LP_EV="$round/evidence/smoke" \
          bash -c 'source "$1" >/dev/null 2>&1
                   echo "after-source=[$LP_EV]"
                   lp_setup train "$2" --round R-0001 --dry-run 2>&1' \
          _ "${real_root}/runtime/_common.sh" "$task" )"
  grep -qF "after-source=[$round/evidence/smoke]" <<< "$out" \
    && _lp_case "外层导出的 LP_EV 活过 source（CR-0006 的回归）" 0 \
    || _lp_case "外层导出的 LP_EV 活过 source（CR-0006 的回归）" 1

  echo
  echo "[5] 阈值只从**任务配置**读（唯一落点）：齐了给 argv，缺了/写反了退出 2"
  # 0.18.18 迁移后的核心验收：值来自 config/tasks/<任务>.yaml，判据里那份**不被读**。
  ( LP_ROOT="$fxroot" LP_TASK_ID=fx-task lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args >/dev/null 2>&1 || exit 1
    want=(--jump-factor 4.0 --rel-to-best 2.5 --min-points 5 --max-wall-hours 1 --max-steps 20)
    [[ "${LP_STOP_ARGS[*]}" == "${want[*]}" ]] || { echo "得到：${LP_STOP_ARGS[*]}"; exit 1; } )
  _lp_case "任务配置齐 ⇒ argv 逐项正确（max_steps 是透传事实）" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  _lp_case "判据里写 999 也不被读（迁移回归：证明唯一落点是任务配置）" \
    "$( grep -q 'jump_factor: 999.0' "$round/criterion.yaml" && echo 0 || echo 1 )"
  # ★ 0.18.33：平台早停（可选项）——配了就必须能拼出 argv，且四件缺一即退 2。
  #   这条用例的来历：0.18.26 加 plateau 时 heredoc 正文跟着函数体缩进 ⇒ python3 收到
  #   缩进源码 ⇒ IndentationError ⇒ **只要配了 plateau，训练段一律退 2**，而 57 条自检
  #   里没有一条带 plateau，全绿也漏（CR-0001）。
  python3 - "$fxroot/config/tasks/fx-task.yaml" <<'PY3'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8"))
doc["stop_conditions"]["plateau"] = {"window_steps": 20, "min_gain_pct": 1.0,
                                     "patience": 2, "min_steps": 5}
yaml.safe_dump(doc, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY3
  ( LP_ROOT="$fxroot" LP_TASK_ID=fx-task lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args >/dev/null 2>&1 || exit 1
    want=(--plateau-window 20 --plateau-min-gain-pct 1.0 --plateau-patience 2 --plateau-min-steps 5)
    [[ "${LP_STOP_ARGS[*]}" == *"${want[*]}"* ]] || { echo "得到：${LP_STOP_ARGS[*]}"; exit 1; } )
  _lp_case "配置带 plateau ⇒ rc=0 且 --plateau-* 四项正确（0.18.33 的缩进回归）" \
    "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  python3 - "$fxroot/config/tasks/fx-task.yaml" <<'PY4'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8"))
del doc["stop_conditions"]["plateau"]["min_steps"]
yaml.safe_dump(doc, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY4
  ( LP_ROOT="$fxroot" LP_TASK_ID=fx-task lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args ) >/dev/null 2>&1
  _lp_case "plateau 缺 min_steps ⇒ 2（整块要四件齐全）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  # 还原：后面几条 loss/墙钟用例必须在**没有 plateau** 的夹具上跑，否则它们会因为
  # 平台早停缺件提前退 2 而"假通过"（过了，但过的原因不对）。
  python3 - "$fxroot/config/tasks/fx-task.yaml" <<'PY5'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8"))
doc["stop_conditions"].pop("plateau", None)
yaml.safe_dump(doc, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY5
  # ★ 0.19.0：held-out racing（可选项）——配了就必须拼出三项阈值 ＋ 两个路径；
  #   缺一件退 2。这条用例的来历与 plateau 那条同源：heredoc 正文跟着函数体缩进会让
  #   python 收到缩进源码 ⇒ IndentationError ⇒ **只要配了 racing，训练段一律退 2**。
  python3 - "$fxroot/config/tasks/fx-task.yaml" <<'PY6'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8"))
doc["stop_conditions"]["holdout"] = {"min_step": 50, "max_gap_pct": 0.05, "patience": 2}
yaml.safe_dump(doc, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY6
  ( LP_ROOT="$fxroot" LP_TASK_ID=fx-task lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args >/dev/null 2>&1 || exit 1
    want=(--holdout-min-step 50 --holdout-max-gap-pct 0.05 --holdout-patience 2
          --holdout-best-dir --holdout-rounds-dir --holdout-cell fx-task)
    for w in "${want[@]}"; do [[ " ${LP_STOP_ARGS[*]} " == *" ${w} "* ]] || \
      { echo "缺 ${w}：${LP_STOP_ARGS[*]}"; exit 1; }; done )
  _lp_case "配置带 holdout ⇒ rc=0 且三项阈值/两个路径/任务名齐全（0.19.0）" \
    "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  python3 - "$fxroot/config/tasks/fx-task.yaml" <<'PY7'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8"))
del doc["stop_conditions"]["holdout"]["patience"]
yaml.safe_dump(doc, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY7
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args ) >/dev/null 2>&1
  _lp_case "holdout 缺 patience ⇒ 2（整块要三件齐全）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  python3 - "$fxroot/config/tasks/fx-task.yaml" <<'PY8'
import sys, yaml
p = sys.argv[1]
doc = yaml.safe_load(open(p, encoding="utf-8"))
doc["stop_conditions"].pop("holdout", None)
yaml.safe_dump(doc, open(p, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
PY8
  cp "${fxroot}/config/tasks/fx-task.yaml" "${fxroot}/config/tasks/fx-task.yaml.bak"
  sed -i '/jump_factor/d' "${fxroot}/config/tasks/fx-task.yaml"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args ) >/dev/null 2>&1
  _lp_case "任务配置缺 loss.jump_factor ⇒ 2（本文件不补默认值）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  cp "${fxroot}/config/tasks/fx-task.yaml.bak" "${fxroot}/config/tasks/fx-task.yaml"
  sed -i 's/jump_factor: 4.0/jump_factor: 0.5/; s/min_points: 5/min_points: 0/' "${fxroot}/config/tasks/fx-task.yaml"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args ) >/dev/null 2>&1
  _lp_case "阈值写反（jump_factor 0.5 / min_points 0）⇒ 2" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  cp "${fxroot}/config/tasks/fx-task.yaml.bak" "${fxroot}/config/tasks/fx-task.yaml"
  # 墙钟：0 / 负数 / 缺失 三种都必须退出 2（0 以前是静默"没有上限"）
  for bad in 0 -3; do
    sed -i "s/wall_clock_hours: .*/wall_clock_hours: ${bad}/" "${fxroot}/config/tasks/fx-task.yaml"
    ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
      lp_build_stop_args ) >/dev/null 2>&1
    _lp_case "wall_clock_hours=${bad} ⇒ 2（0/负数不等于没有上限）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  done
  sed -i '/wall_clock_hours: /d' "${fxroot}/config/tasks/fx-task.yaml"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_build_stop_args ) >/dev/null 2>&1
  _lp_case "任务配置缺 wall_clock_hours ⇒ 2（不许无限等一张卡）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  cp "${fxroot}/config/tasks/fx-task.yaml.bak" "${fxroot}/config/tasks/fx-task.yaml"
  rm -f "${fxroot}/config/tasks/fx-task.yaml.bak"
  
  echo "[5b] LP_WORK_DIR 默认落点 = data.runs ＋ 任务名（0.18.14；与 state.py 同源）"
  cp "$task/run.env" "$task/run.env.bak"
  sed -i '/^LP_WORK_DIR=/d' "$task/run.env"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    exp="$(LP_ROOT="$fxroot" lp_cfg_get data.runs 2>/dev/null)" || exp=""
    [[ -n "$exp" && "$LP_WORK_DIR" == "${exp%/}/fx-task" ]] )
  _lp_case "run.env 不写 ⇒ LP_WORK_DIR = <data.runs>/<任务名>" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  ( LP_ROOT="$fxroot" LP_WORK_DIR="/tmp/x" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    [[ "$LP_WORK_DIR" == "/tmp/x" ]] )
  _lp_case "环境变量给了 LP_WORK_DIR ⇒ 压过默认值（人临时改的赢过文件常态）" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  mv "$task/run.env.bak" "$task/run.env"

  echo
  echo "[6] 规则 B ①：round.env 只能改变量值/追加片段"
  cat > "$round/criterion.yaml" <<'EOF'
stop_conditions:
  loss: {jump_factor: 4.0, rel_to_best: 2.5, min_points: 5}
  max_steps: 20
  wall_clock_hours: 1
EOF
  cat > "$round/round.env" <<'EOF'
LP_TRAIN_EXTRA_ARGS="--dry-run"
LP_EVAL_EXTRA_ARGS="--limit 8"
EOF
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_effective_cmd "$LP_TRAIN_CMD" LP_TRAIN_EXTRA_ARGS
    [[ "$LP_CURRENT_CMD" == "python3 -m fake.train --steps 20 --tag alpha --dry-run" ]] ) 
  _lp_case "只追加片段 ⇒ 通过，生效命令 = 原命令 ＋ 片段" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  cat > "$round/round.env" <<'EOF'
LP_TRAIN_CMD="python3 -m other.train"
EOF
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run ) >/dev/null 2>&1
  _lp_case "重定义整条命令 ⇒ 2" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  cat > "$round/round.env" <<'EOF'
LP_EVAL_CMD=""
EOF
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run ) >/dev/null 2>&1
  _lp_case "把任务级变量设成空（删除）⇒ 2" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  cat > "$round/round.env" <<'EOF'
LP_TRAIN_EXTRA_ARGS="--dry-run"
EOF

  echo
  echo "[7] 环境变量 > run.env（人临时改的赢过文件里的常态值）"
  ( LP_ROOT="$fxroot" LP_TRAIN_CMD="python3 -m env.wins" \
      lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    [[ "$LP_TRAIN_CMD" == "python3 -m env.wins" ]] )
  _lp_case "导出的 LP_TRAIN_CMD 压过 run.env" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"

  echo
  echo "[8] 钩子（§5.3）：存在即执行；钩子自己失败即退出 2"
  cat > "$round/hooks/pre_train.sh" <<'EOF'
echo "hook ran" > "$LP_EV/hook_pre_train.txt"
EOF
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_hooks pre >/dev/null 2>&1
    [[ -f "$LP_EV/hook_pre_train.txt" ]] )
  _lp_case "pre_train 钩子被真的执行了（副作用文件在）" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  cat > "$round/hooks/pre_train.sh" <<'EOF'
echo "hook ran again" > "$LP_EV/hook_pre_train_2.txt"
EOF
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_hooks post >/dev/null 2>&1
    [[ ! -f "$LP_EV/hook_pre_train_2.txt" ]] )
  _lp_case "钩子文件名按 <when>_<stage> 拼（post 不执行 pre 那份）" \
    "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  cat > "$round/hooks/pre_train.sh" <<'EOF'
exit 3
EOF
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_hooks pre ) >/dev/null 2>&1
  _lp_case "钩子自己失败 ⇒ 2（钩子说不能跑就得听）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  rm -f "$round/hooks/pre_train.sh"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_hooks pre ) >/dev/null 2>&1
  _lp_case "没有钩子文件 ⇒ 静默跳过（不是失败）" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"

  echo
  echo "[9] 设备守卫（§6.3 第 2 行：扫占用＋三层定卡）：dry-run 只警告不拦；真跑退出 2"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_guard_devices 训练 ) >/dev/null 2>&1
  _lp_case "定不下卡（require_explicit）在 --dry-run ⇒ 只警告不拦（rc=0）" \
    "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 >/dev/null 2>&1
    lp_guard_devices 训练 ) >/dev/null 2>&1
  _lp_case "同一个定不下卡在真跑 ⇒ 退出 2（两条路必须不同）" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"

  echo
  echo "[10] 工程级配置读得出来（config/project.yaml 是唯一落点）"
  local usable
  usable="$( LP_ROOT="$fxroot" lp_cfg_get devices.usable )"
  _lp_case "devices.usable 读出来非空（${usable}）" "$([[ -n "$usable" ]] && echo 0 || echo 1)"
  usable="$( LP_ROOT="$fxroot" lp_cfg_get devices.nope_x 2>/dev/null )"
  _lp_case "不存在的键 ⇒ 退出 3（不返回空串冒充）" "$([[ $? -eq 3 ]] && echo 0 || echo 1)"

  echo
  echo "[11] 跑前准备：本工程要写的产物根不存在 ⇒ 创建（真跑）；--dry-run 只预告"
  # 产物根（**本工程要写**的目录）：不存在 ⇒ 创建（真跑路径）
  LP_ARTIFACTS_ROOT="$tmp/brand-new-artifacts-root"
  LP_DRY_RUN=0
  lp_prepare_artifacts_root >/dev/null 2>&1
  _lp_case "artifacts.root 不存在 ⇒ 真跑路径创建它（rc=0 且目录在）" \
    "$([[ $? -eq 0 && -d "$LP_ARTIFACTS_ROOT" ]] && echo 0 || echo 1)"
  LP_ARTIFACTS_ROOT="$tmp/brand-new-artifacts-root-2"
  LP_DRY_RUN=1
  lp_prepare_artifacts_root >/dev/null 2>&1
  _lp_case "同一个缺失路径在 --dry-run ⇒ 只预告、不落盘（目录仍不在）" \
    "$([[ $? -eq 0 && ! -d "$LP_ARTIFACTS_ROOT" ]] && echo 0 || echo 1)"

  echo "[12] --resume（0.18.26）：值不合法/阶段不对 ⇒ 2；latest 指向空 ckpt 目录 ⇒ 2"
  LP_DRY_RUN=1
  ( lp_setup train "$task" --root "$fxroot" --round R-0001 --dry-run --resume /nonexistent-ckpt ) >/dev/null 2>&1
  _lp_case "--resume 指向不存在的目录 ⇒ 2" "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  mkdir -p "$tmp/ckpt-empty"
  ( lp_setup train "$task" --root "$fxroot" --round R-0001 --dry-run --resume "$tmp/ckpt-empty" ) >/dev/null 2>&1
  _lp_case "--resume 目录里没有 tracker 也没有 iter_* ⇒ 2（不许拿基座目录当续跑点）" \
    "$([[ $? -eq 2 ]] && echo 0 || echo 1)"
  mkdir -p "$tmp/ckpt-good/iter_0000050"
  printf '50\n' > "$tmp/ckpt-good/latest_checkpointed_iteration.txt"
  local rres rrc
  rres="$( ( lp_setup train "$task" --root "$fxroot" --round R-0001 --dry-run \
             --resume "$tmp/ckpt-good" >/dev/null 2>&1
             echo "rc=$? resume=${LP_RESUME_FROM:-UNSET}" ) 2>&1 )"
  rrc=0
  [[ "$rres" == "rc=0 resume=$tmp/ckpt-good" ]] || rrc=1
  _lp_case "合法 ckpt 目录 ⇒ 0，且 LP_RESUME_FROM 被设上" "$rrc"
  ( lp_setup convert "$task" --root "$fxroot" --round R-0001 --dry-run --resume latest ) >/dev/null 2>&1
  _lp_case "--resume 用在 convert 段 ⇒ 2（只对 train 有意义）" \
    "$([[ $? -eq 2 ]] && echo 0 || echo 1)"

  echo
  echo "[13] 片段槽按段隔离（0.18.28）：convert 不再吃训练那个槽；生效命令不重复拼片段"
  cat > "$round/round.env" <<'EOF'
LP_TRAIN_EXTRA_ARGS="--tag beta"
LP_CONVERT_EXTRA_ARGS="--save-model-type hf"
EOF
  ( LP_ROOT="$fxroot" lp_setup convert "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_effective_cmd "$LP_CONVERT_CMD" LP_CONVERT_EXTRA_ARGS
    [[ "$LP_CURRENT_CMD" == "python3 -m fake.convert --in a --out b --save-model-type hf" ]] )
  _lp_case "convert 追加片段 ⇒ 末尾带上它" "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  ( LP_ROOT="$fxroot" lp_setup train "$task" --round R-0001 --dry-run >/dev/null 2>&1
    lp_effective_cmd "$LP_TRAIN_CMD" LP_TRAIN_EXTRA_ARGS
    [[ "$LP_CURRENT_CMD" == "python3 -m fake.train --steps 20 --tag alpha --tag beta" ]] )
  _lp_case "同一份 round.env 下 train 只拿自己那一槽（convert 的 flag 不串进来）" \
    "$([[ $? -eq 0 ]] && echo 0 || echo 1)"
  local ncnt
  ncnt="$( ( LP_ROOT="$fxroot" lp_setup train "$task" --root "$fxroot" --round R-0001 --dry-run >/dev/null 2>&1
              lp_run_stage train "python3 -m fake.train --tag beta" 训练 ) 2>&1 \
            | grep '生效命令' | grep -o -- '--tag beta' | wc -l )"
  _lp_case "生效命令里片段只出现一次（不再拼两遍）" "$([[ "$ncnt" -eq 1 ]] && echo 0 || echo 1)"

  rm -rf "$tmp"
  echo
  echo "======================================================================"
  if [[ "$fails" -gt 0 ]]; then
    printf 'FAILED: %s/%s\n' "$((checks - fails))" "$checks"
    return 1
  fi
  printf 'PASSED: %s/%s\n' "$checks" "$checks"
  return 0
}
