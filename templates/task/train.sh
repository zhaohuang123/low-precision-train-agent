#!/usr/bin/env bash
# train.sh —— **训练段入口**（任务级唯一一份；轮次目录不许放副本，见 AGENTS.md §2.7）
#
# 归属：三段入口的训练段（共用 `runtime/_common.sh` 前导）。
# 用法：bash <任务目录>/train.sh --round <轮次> [--dry-run] [--root <配置根>] [--no-early-stop]
#
# 它自己只做四件事（每一件都只有一份实现，别处不许再写一套）：
#   ① `lp_setup`      算清"跑什么、往哪落"：配置根 fail-closed、run.env/round.env、规则 B ①
#   ② **每轮门**      `runtime/validate_round.py <轮次>/design.md` —— 方案冻结件不过就**不许花卡**
#   ③ `lp_guard_devices` 起作业前查占用、定卡（卡号只从 `runtime/resources.py` 来）
#   ④ `lp_run_stage`  交给 `runtime/executor.py`：逐行落日志、按观察在线早停、杀整个进程组、墙钟超时
#
# ★ 本文件里**没有一条命令、没有一个阈值、没有一张卡号**：
#   命令在 `run.env`，阈值在 `<轮次>/criterion.yaml`，卡号在 `config/project.yaml` 的 `devices.*`。
set -euo pipefail

LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../runtime/_common.sh
source "${LP_ROOT}/runtime/_common.sh"

lp_setup train "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" "$@"

lp_effective_cmd "${LP_TRAIN_CMD:-}" LP_TRAIN_EXTRA_ARGS
[[ -n "$LP_TRAIN_CMD" ]] || lp_die "run.env 里没有 LP_TRAIN_CMD（命令只有一个落点：<任务目录>/run.env）。"

if [[ "$LP_DRY_RUN" == "1" ]]; then
  echo "--dry-run：本段**什么都不执行**（不起进程、不占卡、不改任何文件）；真跑时会依次做："
  echo "  1) 每轮门    python3 ${LP_ROOT}/runtime/validate_round.py ${LP_ROUND_DIR}/design.md"
  echo "  2) 设备守卫  python3 ${LP_ROOT}/runtime/resources.py cards / pick / check"
  echo "               （拿到的卡写进 ASCEND_RT_VISIBLE_DEVICES）"
  echo "  3) pre_train 钩子（存在即执行）：${LP_ROUND_DIR}/hooks/pre_train.sh"
  echo "  4) 训练      ${LP_CURRENT_CMD}"
  echo "               （executor.py：逐行落日志 → ${LP_EV}/train.log；按观察在线早停；杀整个进程组）"
  echo "  5) post_train 钩子（存在即执行）：${LP_ROUND_DIR}/hooks/post_train.sh"
  lp_run_stage train "$LP_CURRENT_CMD" 训练
  exit "$LP_EXIT_OK"
fi

# ② 每轮门：方案冻结件不过 ⇒ 拒绝花卡（门的实现只有 runtime/validate_round.py 一份）。
bash "${LP_TASK_DIR}/commands/validate_design.sh" "$LP_ROUND_DIR"

# ③ 设备守卫：不占卡的命令不介入；占卡的命令必须定得下卡、且卡现在空着。
lp_guard_devices 训练

# ④ 起训练（钩子前后各一次；post 即使阶段失败也要跑 —— 收尾不能因为作业死了就被跳过）。
lp_hooks pre
rc=0
lp_run_stage train "$LP_CURRENT_CMD" 训练 || rc=$?
hook_rc=0
lp_hooks post || hook_rc=$?
if [[ "$hook_rc" -ne 0 && "$rc" -eq 0 ]]; then rc="$hook_rc"; fi

case "$rc" in
  "$LP_EXIT_OK")
    lp_note "训练段完成（退出 0）。下一段：bash ${LP_TASK_DIR}/convert.sh --round ${LP_ROUND}"
    ;;
  "$LP_EXIT_TRAIN_INVALID")
    lp_warn "**训练侧无效**（发散 / 非有限值 / 墙钟超时，见 ${LP_EV}/early_stop.triggered）。"
    # ★ 双引号串里的**字面**反引号必须转义（`\``），否则被 shell 当命令替换。
    lp_warn "这是**观察**，不是精度结论：本轮别往下花算力（\`eval.sh\` 会拒绝开跑）。"
    lp_warn "★ 不许原样重跑：要重跑，必须说清改什么（判据/方案/资源），并把改动写进新轮次。"
    ;;
  "$LP_EXIT_CMD_FAILED")
    lp_warn "训练命令自己以非零码退出（未归类运行期失败）。日志尾部见 ${LP_EV}/train.log。"
    ;;
  *) lp_warn "训练段退出码 ${rc}（约定不过 ⇒ 看上面的 [common] ✗ 行）。" ;;
esac
exit "$rc"
