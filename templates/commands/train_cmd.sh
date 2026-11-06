#!/usr/bin/env bash
# ── 骨架（无型号）────────────────────────────────────────────────────────────
# 照抄到 `<任务目录>/commands/` 后：① 把每个 `<...>` 换成真值 ② 把 `# <占位>` 的段落填上。
# 未替换的占位一律**当场拒绝**（fail-closed），不会带着占位去起作业。
# ─────────────────────────────────────────────────────────────────────────
# train_cmd.sh —— **真训练命令形状**（**骨架**；照抄到 <任务目录>/commands/ 后替换占位）
#
# 归属：训练命令（三段入口 ＋ 任务目录的命令形状；场景参数只从任务配置取）。
#
# 命令形状（来自早先实测的训练脚本，建设者侧只读材料，不随包；本文件不搬它的数据本体与具体名）：
#   · 验过的形状：
#       `cd <REPO_ROOT>; torchrun <distributed_args> posttrain_gpt.py <args> \
#            --distributed-backend nccl --load <ckpt> --save <ckpt> --transformer-impl local`
#   · 参数默认值也是从那儿读出来的（不是本文件自造）：
#       train-iters=300 ｜ seq-length=8192 ｜ mbs=1 ｜ gbs=64 ｜ master_port=6040
#
# 本文件只做两件事：**参数拼装**（占位符 ← 任务配置 ＋ 环境变量）与**文本接线**（把拼装结果交给框架）。
#   参数模板的唯一落点是同目录的 `train_argv.txt`（0.18.0 起从任务配置搬来）；本文件不另写一条命令。
#   卡号不由本文件决定：只读入口 `lp_guard_devices`（`runtime/resources.py`）定好后 export 的可见集合。
#
# 用法：
#   bash <任务目录>/commands/train_cmd.sh --print   # 只打印拼装出的 argv（本工程 P4d **从未真跑**）
#   bash <任务目录>/commands/train_cmd.sh           # 真起训练（会占卡；本工程从未执行过这条路径）
#
# 退出码：0 成功（或 --print 打印完）｜2 参数/配置/占位值问题（fail-closed 拒绝拼装）
set -euo pipefail

: "${LP_ROOT:?train_cmd.sh 由三段入口调用时 LP_ROOT 一定存在；手工跑请先 export LP_ROOT=<工程根>}"
: "${LP_TASK_ID:?同上：LP_TASK_ID（任务名）}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_taskcfg.sh
source "${HERE}/_taskcfg.sh"

# 参数：`--print`／`--dry-run`（位置任意）、`--run`（忽略）、其余＝**轮次追加片段**。
# 三段的解析与"不许改的项"都在 _stage_args.sh 一处（0.18.29），模板里不再各写一份。
# shellcheck source=_stage_args.sh
source "${HERE}/_stage_args.sh"
lp_stage_args train "$@" || exit 2

repo="$(taskcfg_value train.framework_repo "训练框架检出（命令要在它下面跑）")"
argv_file="${HERE}/train_argv.txt"
[[ -f "$argv_file" ]] || { echo "缺 ${argv_file} —— 训练 argv 形状的唯一落点（0.18.0 起在任务目录，不再在任务配置里）⇒ 退出 2。" >&2; exit 2; }
template="$(cat "$argv_file")"
max_steps="$(taskcfg_value stop_conditions.max_steps "训练步数上限")"
# ★ 0.18.26：ckpt 存盘间隔的唯一落点＝任务配置（此前 argv 里写死 10，真跑里被人手改成 300）。
save_interval="$(taskcfg_value train.checkpoint.save_interval_steps \
  "ckpt 存盘间隔步数（train.checkpoint.save_interval_steps）")"

# ── 参数：任务配置优先；没有的从环境变量来（默认值出处见文件头）──────────────────
model_path="$(taskcfg_get model.source.path 2>/dev/null || true)"
[[ -n "$model_path" ]] || {
  echo "任务配置里取不到 model.source.path ⇒ 退出 2（原始来源是复现出处，必须写）" >&2; exit 2; }

# ── 训练起点 ＋ 语料：**部署事实的唯一落点都在任务配置**，任务目录只做占位符替换 ──
model_start="$(taskcfg_get model.start.path 2>/dev/null || true)"
start_format="$(taskcfg_get model.start.format 2>/dev/null || true)"
data_path="$(taskcfg_get train.data_path 2>/dev/null || true)"
[[ -n "$model_start" ]] || {
  echo "任务配置里取不到 model.start.path ⇒ 退出 2（训练**加载**哪份权重必须有明确落点）" >&2
  echo "  source=从哪来、start=这一轮 --load 吃哪份 —— 两个事实，别合并。" >&2
  echo "  MindSpeed 只吃 mcore ⇒ 填转换产物的绝对路径；转换见 skills/weights-convert。" >&2; exit 2; }
[[ -n "$start_format" ]] || { echo "任务配置里取不到 model.start.format（hf|mcore）⇒ 退出 2" >&2; exit 2; }
[[ -n "$data_path" ]] || { echo "任务配置里取不到 train.data_path（训练语料路径）⇒ 退出 2" >&2; exit 2; }
[[ -n "$model_path" ]] || { echo "任务配置里取不到 model.source.path ⇒ 退出 2（没有起点权重就没法训练）。" >&2; exit 2; }

cards="$(taskcfg_visible_cards)"
port="${LP_MASTER_PORT:-6040}"                                     # 旧 train_qat_rotate.sh:533
seq_len="${LP_SEQ_LEN:-8192}"                                      # 旧 :518
micro_bs="${LP_MICRO_BS:-1}"                                       # 旧 :516
global_bs="${LP_GLOBAL_BS:-64}"                                    # 旧 :517
qat_scheme="${LP_QAT_SCHEME:-$(taskcfg_get model.precision 2>/dev/null || true)}"
[[ -n "$qat_scheme" ]] || { echo "取不到量化方案（LP_QAT_SCHEME / model.precision 都没有）⇒ 退出 2。" >&2; exit 2; }
out_dir="${LP_TRAIN_OUT:-${LP_WORK_DIR:-${LP_ROOT}/experiments/${LP_TASK_ID}}/rounds/${LP_ROUND:-<轮次>}/ckpt}"

# ── 续跑（--resume）的**三个替换点**（0.18.26）──────────────────────────────
#   `LP_RESUME_FROM` 由 `runtime/_common.sh` 的 `lp_resolve_resume` 解析并校验好；
#   这里只负责让 argv 变成"接着跑"的形状：
#     ① --load 指向 ckpt 父目录（框架读 latest_checkpointed_iteration.txt 定迭代数）
#     ② 去掉 --finetune（finetune 语义会把 args.iteration 清零 ⇒ 变成"再来 300 步"）
#     ③ 去掉 --no-load-optim/--no-load-rng（续跑要把优化器与 RNG 一起恢复）
#   为什么不在这里判断"文件在不在"：那是 `--resume` 参数的校验，归 _common.sh（一处）。
finetune_flag="--finetune"
load_state_flags="--no-load-optim --no-load-rng"
if [[ -n "${LP_RESUME_FROM:-}" ]]; then
  model_start="$LP_RESUME_FROM"
  finetune_flag=""
  load_state_flags=""
fi

# ── 在线量化误差探针（`QAT_QSNR_PROBE`）—— 记录项，**不是**判定项 ──────────────
#   为什么在训练命令这一层开：探针活在训练进程里，框架只在建好模型后按环境变量装它
#   （核心层实现 + LLM 层接线，两处都在任务配置的钉点上）。
#   **声明即开关**：任务配置 `train.monitor_metrics` 里写了 `quant_error` 就打开 ——
#   不另造一个开关，否则"声明了要监控"与"实际没测"又会分家。
#   `LP_QSNR_PROBE=0` 可显式关掉（例如只想跑 5 步冒烟）。
#   ★ `QAT_QSNR_OUT` 必须指到本轮 `evidence/`：不给它探针会落到 cwd，抽数就找不到留痕
#     （`runtime/metrics.py` 只读 `<轮次>/evidence/eval_clamp_qsnr.json`）。
#   ★ `QAT_QSNR_LABELS`：本轮身份标签（JSON 对象）—— 框架侧不认识"轮次/任务"，
#     这些词由我们这一侧给，探针原样透传进产物（`labels` 字段）。
round_dir="${LP_WORK_DIR:-${LP_ROOT}/experiments/${LP_TASK_ID}}/rounds/${LP_ROUND:-<轮次>}"
_monitor="$(taskcfg_get train.monitor_metrics 2>/dev/null || true)"

# ── 量化误差上限（`stop_conditions.quant_error_max`）—— **唯一落点是任务配置** ────────
#   写的是**相对误差**（0.05 = 5%）；引擎换算成探针看门狗要的 dB 地板：floor = −20·log10(ε)
#   （与 `runtime/metrics.py` 的 `qsnr_db_to_rel_err` 同一个公式，方向相反）。
#   为什么换算放引擎：探针跑在训练进程里、只认 dB；让人在 YAML 里写 dB 等于要求人肉开计算器。
#   合法域 (0, 1)：0 会让地板无穷大，≥1 会让地板 ≤ 0 —— 都不是"误差上限"。
qemax="$(taskcfg_get stop_conditions.quant_error_max 2>/dev/null || true)"
qs_floor=""
if [[ -n "$qemax" ]]; then
  qs_floor="$(python3 - "$qemax" <<'PY'
import sys, math
try:
    eps = float(sys.argv[1])
except ValueError:
    sys.exit(2)
if not (0.0 < eps < 1.0):
    sys.exit(3)
print(f"{-20.0 * math.log10(eps):.2f}")
PY
)" || { echo "stop_conditions.quant_error_max=${qemax} 不合法：要 (0,1) 之间的相对误差（0.05 表示 5%）⇒ 退出 2。" >&2; exit 2; }
  export QAT_QSNR_FLOOR_DB="$qs_floor"
fi

if [[ "${LP_QSNR_PROBE:-1}" != "0" ]] \
   && { grep -qw 'quant_error' <<< "$_monitor" || [[ -n "$qemax" ]]; }; then
  export QAT_QSNR_PROBE=1
  # ★ 0.18.26：采样频率的唯一落点＝任务配置 `train.qat_probe.every_n_steps`（默认 10）。
  #   此前只有环境变量默认 50 ⇒ 300 步只有 6 个点，`metrics.json` 只能记「不能判趋势」。
  _every="$(taskcfg_get train.qat_probe.every_n_steps 2>/dev/null || true)"
  [[ -n "$_every" ]] || {
    echo "任务配置里取不到 train.qat_probe.every_n_steps ⇒ 退出 2" >&2
    echo "  探针采样频率是**任务配置**的字段（唯一落点），不在这里给默认值。" >&2; exit 2; }
  python3 - "$_every" <<'PYX' || { echo "train.qat_probe.every_n_steps=${_every} 不合法（必须 >= 1 的整数）⇒ 退出 2" >&2; exit 2; }
import sys
try:
    n = int(sys.argv[1])
except ValueError:
    sys.exit(2)
sys.exit(0 if n >= 1 else 2)
PYX
  export QAT_QSNR_EVERY="$_every"
  # ★ 落点跟随 `LP_EV`（0.18.31 起它是**文档化的**证据目录旋钮）：冒烟把 `LP_EV`
  #   指到 `<轮次>/evidence/smoke` 时，探针跟着走 —— 正式跑与冒烟不会写同一个文件名。
  #   不带 `LP_EV` 时退回轮次目录下的 `evidence/`（老行为）。
  export QAT_QSNR_OUT="${QAT_QSNR_OUT:-${LP_EV:-${round_dir}/evidence}}"
  export QAT_QSNR_LABELS="{\"round\": \"${LP_ROUND:-unknown}\", \"task\": \"${LP_TASK_ID}\"}"
  # `--print` 把探针落点也打出来：冒烟/正式不撞名靠的就是这一行，看不见就没法核对。
  # 写成 if 而不是 `[[ … ]] && echo`（后者 rc=1，在 `set -e` 下是地雷）。
  if [[ "$PRINT" == "1" ]]; then
    echo "[print] 探针产物 → ${QAT_QSNR_OUT}（LP_EV=${LP_EV:-未设}）"
  fi
  # 看门狗（= 训练中途直接 kill 的那条护栏）默认开；只想观测的一轮给 LP_QSNR_WATCHDOG=0。
  # ★ 写成 if 而不是 `[[ … ]] && export`：后者的退出码是 1，在 `set -e` 下是颗地雷。
  if [[ "${LP_QSNR_WATCHDOG:-1}" == "0" ]]; then
    export QAT_QSNR_WATCHDOG=0
  fi
  # ★ 阈值接了但探针被人为关掉 ⇒ 当场说清楚，不许让它"看起来在拦"。
elif [[ "${LP_QSNR_PROBE:-1}" == "0" && -n "$qemax" ]]; then
  echo "⚠ 任务配置写了 stop_conditions.quant_error_max=${qemax}，但 LP_QSNR_PROBE=0 ⇒" >&2
  echo "  这一轮探针不开、该阈值不会生效（要它生效就别关探针）。" >&2
fi

# ── 占位符替换（显式逐条替换，不用 eval）──────────────────────────────────────
cmd="$template"
cmd="${cmd//\$\{cards\}/$cards}"
cmd="${cmd//\$\{port\}/$port}"
cmd="${cmd//\$\{model_path\}/$model_path}"
cmd="${cmd//\$\{model_start\}/$model_start}"
cmd="${cmd//\$\{data_path\}/$data_path}"
cmd="${cmd//\$\{max_steps\}/$max_steps}"
cmd="${cmd//\$\{seq_len\}/$seq_len}"
cmd="${cmd//\$\{micro_bs\}/$micro_bs}"
cmd="${cmd//\$\{global_bs\}/$global_bs}"
cmd="${cmd//\$\{qat_scheme\}/$qat_scheme}"
cmd="${cmd//\$\{out_dir\}/$out_dir}"
cmd="${cmd//\$\{save_interval\}/$save_interval}"
cmd="${cmd//\$\{finetune_flag\}/$finetune_flag}"
cmd="${cmd//\$\{load_state_flags\}/$load_state_flags}"

# 「没配置」与「配了占位」必须分开（旧 README:157-159 的结论）。
placeholder=""
case "$model_path" in *'<'*'>'*) placeholder="$placeholder model.source.path=$model_path" ;; esac
case "$model_start" in *'<'*'>'*) placeholder="$placeholder model.start.path=$model_start" ;; esac
case "$data_path" in *'<'*'>'*) placeholder="$placeholder train.data_path=$data_path" ;; esac
# 注释行里的 `${...}` 无害（真跑时 bash 当注释）：只对**有效行**判残留，否则假警报会盖住真问题。
case "$(sed "s/#.*//" <<<"$cmd")" in *'${'*) placeholder="$placeholder 模板里还有没替换的占位符" ;; esac
# ★ 0.18.33：**配置/本轮给了、argv 没消费** ⇒ 该字段静默失效（CR-0002）。
#   判据只看占位符在不在 `train_argv.txt` 里 —— 不猜框架的旗标名，也不看拼出来的
#   命令长什么样（两者一猜就会误报）。真跑与 `--print` **同样打印**，且**不退出**：
#   它不改变行为，只把"静默"变"可见"。
#   ★ 0.18.34（CR-0007）：只认**有效 argv** —— `train_argv.txt` 头部注释里逐一列出了全部
#   14 个占位符，直接 grep 整份原文时"注释"也算消费 ⇒ 旧骨架（真用法被写死、注释照旧）
#   恰好命中，告警永远不响（假绿）。口径与 `metrics.py` 读日志、本文件判"残留占位符"一致：
#   **注释不是命令**。
_argv_has() { sed 's/#.*//' "$argv_file" 2>/dev/null | grep -qF "\${$1}"; }
unconsumed=""
if [[ -n "$save_interval" ]] && ! _argv_has save_interval; then
  unconsumed+="ckpt 存盘间隔 train.checkpoint.save_interval_steps=${save_interval}（argv 里没有 \${save_interval}）"
fi
if [[ -n "${LP_RESUME_FROM:-}" ]] && { ! _argv_has load_state_flags || ! _argv_has finetune_flag; }; then
  unconsumed+="${unconsumed:+；}续跑 --resume ${LP_RESUME_FROM}（argv 缺 \${load_state_flags}/\${finetune_flag} ⇒ 载入参数拼不进去）"
fi
if [[ -n "$unconsumed" ]]; then
  echo "⚠ 任务配置/本轮给了，但训练 argv 没消费 ⇒ **该字段不生效**：${unconsumed}" >&2
  echo "  ⇒ commands/train_argv.txt 还是旧骨架（0.18.26 起 14 个占位符）；同步方式见 deploy/UPGRADE.md §3" >&2
fi

cmd="$(lp_stage_append "$cmd")"
# `train.extra_pythonpath[]` ⇒ PYTHONPATH 前缀（唯一落点；**eval 段不拼**，见 docs/CONFIG.md）
# 没配 ⇒ 一个字都不加（不造空 PYTHONPATH：空值等于把当前目录塞进 sys.path）。
py_extra="$(taskcfg_extra_pythonpath)" || exit 2
if [[ -n "$py_extra" ]]; then
  # 我们给的目录优先（顺序＝sys.path 顺序）；原有 PYTHONPATH 接在后面，不覆盖。
  cmd="PYTHONPATH=${py_extra}${PYTHONPATH:+:${PYTHONPATH}} ${cmd}"
fi
   # 轮次追加片段落到命令末尾（没片段时原样不动）

if [[ "$PRINT" == "1" ]]; then
  echo "[print] 训练命令**拼装结果**（未执行、未占卡）："
  echo "  cd ${repo} && ${cmd}"
  lp_stage_print_note
  echo "  ckpt 间隔       --save-interval ${save_interval}（来源任务配置 train.checkpoint.*）"
  if [[ -n "${LP_RESUME_FROM:-}" ]]; then
    echo "  续跑来源        ${LP_RESUME_FROM}（已去掉 --finetune 与 --no-load-*；迭代数由框架从 ckpt 恢复）"
  fi
  if [[ -n "$qs_floor" ]]; then
    echo "[print] 量化误差上限 quant_error_max=${qemax}（相对误差）⇒ 注入 QAT_QSNR_FLOOR_DB=${qs_floor} dB"
  fi
  if [[ -n "$placeholder" ]]; then
    echo "[print] ⚠ 仍含占位值：${placeholder}"
    echo "[print]   ⇒ --print 照印（拼装逻辑可核对）；**真跑**会退出 2，不会拿着占位去起作业。"
  fi
  exit 0
fi

[[ -z "$placeholder" ]] || {
  echo "训练命令里有占位值：${placeholder}" >&2
  echo "  ⇒ 退出 2（fail-closed）：拿占位值起作业，跑出来的是'看着正常'的实验。" >&2
  exit 2
}

# ── 起点／语料的**实跑**守卫（`--print` 不查：它正是用来核对拼装的）───────────
#   为什么在真跑这条路上查：起点写错不会报错，会**静默从错权重开训** —— 那比崩掉更贵。
[[ -d "$model_start" ]] || {
  echo "训练起点不存在：${model_start}" >&2
  echo "  若它应是 mcore 转换产物 ⇒ 先转一次：bash scripts/convert_weights.sh --task ${LP_TASK_ID}" >&2
  echo "  （幂等：目标已存在就不重复转换；流程见 skills/weights-convert）" >&2
  exit 2; }
case "$start_format" in
  mcore)
    [[ -f "${model_start}/latest_checkpointed_iteration.txt" ]] || {
      echo "起点声明 format=mcore，但 ${model_start} 里没有 latest_checkpointed_iteration.txt" >&2
      echo "  ⇒ 它不是 Megatron/mcore 检查点（HF 目录？）。要么改 model.start.format，要么转换一次。" >&2
      exit 2; } ;;
  hf)
    [[ -f "${model_start}/config.json" ]] || {
      echo "起点声明 format=hf，但 ${model_start} 里没有 config.json ⇒ 不是 HF 目录。" >&2
      exit 2; } ;;
  *)
    echo "model.start.format 只认 hf|mcore，拿到的是 '${start_format}' ⇒ 退出 2" >&2
    exit 2 ;;
esac
echo "[train_cmd] repo=${repo} cards=${cards} steps=${max_steps} → ${cmd}" >&2
cd "$repo"
exec bash -c "$cmd"
