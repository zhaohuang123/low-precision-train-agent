#!/usr/bin/env bash
# preflight.sh —— **开跑前的四项检查**（把已有校验器串成一个退出码）
#
# 归属：0.18.0 起（`start_experiment.sh` 的第一段；也可单独手跑排障）。
#
# 为什么是 bash 而不是新增 py 引擎：它**不做任何判断逻辑**，只是把四个已经有实现的校验器
# 依次调起来、把退出码翻成人话。判断归那四件，这里只负责"汇总 + 一个退出码"。
#
# 用法：
#   bash scripts/preflight.sh <任务名> [--skip-cards]
#   退出 0 = 可以开跑；退出 2 = 不能开跑（逐条打印缺什么）。
#
# 四项：
#   ① 任务配置合法        runtime/config.py validate
#   ② 两个框架仓都在钉点上  git rev-parse HEAD vs 任务配置的 framework_head / core_head
#   ③ 卡现在能用          runtime/resources.py check（可靠来源发现冲突 ⇒ 2）
#   ④ 评测环境齐          scripts/install_env.sh --dry-run --task <任务名>
set -u

TASK="${1:-}"
[[ -n "$TASK" ]] || { echo "用法：bash scripts/preflight.sh <任务名> [--skip-cards]" >&2; exit 2; }
shift || true
SKIP_CARDS=0
for a in "$@"; do
  case "$a" in
    --skip-cards) SKIP_CARDS=1 ;;
    *) echo "preflight.sh：不认的参数 $a（只认 --skip-cards）⇒ 退出 2" >&2; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LP_ROOT="$(cd "$HERE/.." && pwd)"
export LP_ROOT
export LP_TASK_ID="$TASK"
ROOT="$LP_ROOT"

fail=0
say_ok()  { echo "  ✓ $*"; }
say_bad() { echo "  ✗ $*"; fail=1; }

echo "preflight：任务 $TASK（配置根 $ROOT）"

# ── ① 任务配置合法 ────────────────────────────────────────────────────────────
CFG="$ROOT/config/tasks/$TASK.yaml"
if [[ ! -f "$CFG" ]]; then
  say_bad "任务配置不存在：$CFG（先创建它，或用 config/tasks/_TEMPLATE.yaml 照抄）"
  echo "preflight：不能开跑" >&2; exit 2
fi
if out="$(python3 "$ROOT/runtime/config.py" validate "$CFG" 2>&1)"; then
  say_ok "任务配置通过字段校验"
else
  say_bad "任务配置不合法："
  printf '%s\n' "$out" | sed 's/^/      /'
  echo "preflight：不能开跑" >&2; exit 2
fi

# ── ② 两个框架仓都在钉点上 ────────────────────────────────────────────────────
# 任务配置的读取只有一份实现：`templates/commands/_taskcfg.sh`（骨架与实例都 source 它）。
# shellcheck source=../templates/commands/_taskcfg.sh
source "$ROOT/templates/commands/_taskcfg.sh"

pin_check() {  # <点号路径本体> <点号路径 head> <人话>
  local repo want have
  repo="$(taskcfg_get "$1" 2>/dev/null || true)"
  want="$(taskcfg_get "$2" 2>/dev/null || true)"
  if [[ -z "$repo" || -z "$want" ]]; then
    say_ok "$3：未配置（跳过 —— 单仓框架可以没有这个键）"
    return 0
  fi
  case "$repo" in *'<'*'>'*) say_ok "$3：仍是占位值（跳过）"; return 0 ;; esac
  if [[ ! -d "$repo" ]]; then say_bad "$3：检出不存在（$repo）"; return 0; fi
  if ! have="$(git -C "$repo" rev-parse HEAD 2>/dev/null)"; then
    say_bad "$3：不是 git 检出（$repo）"; return 0
  fi
  if [[ "$have" == "$want" ]]; then
    say_ok "$3：${have:0:12} 与配置一致"
  else
    say_bad "$3：检出在 ${have:0:12}，配置钉的是 $want ⇒ 跑出来复现不了"
    echo "      修法：把任务配置里的钉点改成上面那个 40 位提交号（或把检出切回配置钉的那个提交）" >&2
  fi
}
pin_check "train.framework_repo" "train.framework_head" "LLM 层仓"
pin_check "train.core_repo"      "train.core_head"      "核心层仓"

# ── ③ 卡现在能用 ──────────────────────────────────────────────────────────────
if [[ "$SKIP_CARDS" == "1" ]]; then
  say_ok "卡检查：已按 --skip-cards 跳过"
else
  if out="$(python3 "$ROOT/runtime/resources.py" check 2>&1)"; then
    say_ok "卡没有可靠来源的冲突"
  else
    say_bad "卡现在不能起作业："
    printf '%s\n' "$out" | grep -E 'BLOCK|ERROR' | head -3 | sed 's/^/      /'
    echo "      （机器上已有作业占用；等它跑完，或用 --skip-cards 只做其余三项）" >&2
  fi
fi

# ── ④ 评测环境齐 ──────────────────────────────────────────────────────────────
# 判据只能用 `install_env.sh --dry-run` 的**退出码**，且它自己就要判"能不能跑"：
#   0 已就绪／3 需要安装（跑一次能装好）／4 需修（缺 torch 等，跑一次装不好）／其它 不可判定。
# 曾经这里只看"这条命令能不能跑完"⇒ 永远绿灯；0.18.12 只看 metadata ⇒ "装上了但没 torch"仍绿灯（C5）。
out="$(bash "$ROOT/scripts/install_env.sh" --task "$TASK" --dry-run 2>&1)" && env_rc=0 || env_rc=$?
case "$env_rc" in
  0) say_ok "评测环境已就绪（版本与配置一致 ＋ 可运行性通过：torch/torch_npu/transformers/lm_eval）" ;;
  3) say_bad "评测环境还需要装（训练不受影响，评测段会失败）："
     printf '%s\n' "$out" | grep -E '\[dry-run\] (解释器|将安装|主环境|包版本|判据|状态)' | head -5 | sed 's/^/      /'
     echo "      修法：bash scripts/install_env.sh --task $TASK" >&2 ;;
  4) say_bad "评测环境装上了但**跑不了**（需修：跑一次 install_env.sh 也修不好）："
     printf '%s\n' "$out" | grep -E '\[dry-run\] (包版本|判据|主环境)' | head -4 | sed 's/^/      /'
     venv_root="$(printf '%s\n' "$out" | sed -n 's/^\[dry-run\] venv 根     = //p')"
     echo "      修法：先让主环境有配对的 torch/torch_npu/transformers 且 NPU 可见，再重建：" >&2
     echo "            rm -rf \"$venv_root\" && bash scripts/install_env.sh --task $TASK" >&2 ;;
  *) say_bad "评测环境不可判定（install_env.sh 退出 $env_rc）："
     printf '%s\n' "$out" | tail -3 | sed 's/^/      /' ;;
esac

if [[ "$fail" -ne 0 ]]; then
  echo "preflight：不能开跑（上面 ✗ 的项先补齐）" >&2
  exit 2
fi
echo "preflight：可以开跑"
