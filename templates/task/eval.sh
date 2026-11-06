#!/usr/bin/env bash
# eval.sh —— **评测段入口**（任务级唯一一份；轮次目录不许放副本）
#
# 归属：三段入口的评测段。用法同 train.sh：
#   bash <任务目录>/eval.sh --round <轮次> [--dry-run] [--root <配置根>]
#
# 与训练段的**三处不同**（其余前导完全共用）：
#   ① **先看训练观察，但要读 `stop_kind`**（0.18.38）：
#      `converged`（平台早停）＝ **合法收工** ⇒ 放行，只打一行"停止轮次"说明；
#      `invalid`／读不出 kind（发散、非有限值、墙钟超时、旧格式留痕）⇒ 退出 5。
#      依据：`runtime/executor.py::stage_exit_code()` 与 `templates/report.md` §2
#      的停止轮次口径 —— 平台停下时模型参数照常可用，拒绝评测等于白烧训练。
#   ② **口径门**：`commands/eval_protocol_gate.sh`
#      不一致 ⇒ 退出 **6**（评测侧无效：口径不全/结果不可比），**不出数字**。
#   ③ **命令失败归 6**：训练命令挂了是"运行期失败（1）"，评测驱动挂了是"**评测侧无效（6）**"
#      —— 两者对报告的含义不同（后者意味着这一轮的分数根本不该被引用）。
set -euo pipefail

LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../runtime/_common.sh
source "${LP_ROOT}/runtime/_common.sh"

lp_setup eval "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" "$@"

lp_effective_cmd "${LP_EVAL_CMD:-}" LP_EVAL_EXTRA_ARGS
[[ -n "$LP_EVAL_CMD" ]] || lp_die "run.env 里没有 LP_EVAL_CMD（命令只有一个落点）。"

marker="${LP_EV}/early_stop.triggered"
if [[ "$LP_DRY_RUN" == "1" ]]; then
  echo "--dry-run：本段**什么都不执行**；真跑时会依次做："
  echo "  0) 训练观察  ${marker}（$([[ -f "$marker" ]] && echo '存在 ⇒ 看 stop_kind：converged 放行并标注停止步；其余退 5' || echo '不存在'）)"
  echo "  1) 口径门    bash ${LP_TASK_DIR}/commands/eval_protocol_gate.sh ${LP_ROUND_DIR}"
  echo "               （不一致 ⇒ 退出 ${LP_EXIT_EVAL_INVALID}，不出数字）"
  echo "  2) 设备守卫  python3 ${LP_ROOT}/runtime/resources.py cards / pick / check"
  echo "  3) pre_eval  钩子（存在即执行）：${LP_ROUND_DIR}/hooks/pre_eval.sh"
  echo "  4) 评测      ${LP_CURRENT_CMD}"
  echo "               （命令失败归 ${LP_EXIT_EVAL_INVALID}：**评测侧无效**，不是「运行期失败」）"
  echo "  5) post_eval 钩子（存在即执行）：${LP_ROUND_DIR}/hooks/post_eval.sh"
  lp_run_stage eval "$LP_CURRENT_CMD" 评测
  exit "$LP_EXIT_OK"
fi

# ① 训练观察命中 ⇒ **按 stop_kind 分两种去向**（0.18.38）：
#    converged（平台早停）＝ 合法收工 ⇒ 放行，只打一行说明；
#    invalid／读不出 kind ⇒ 拒绝开跑（别拿算力去买一个已知无效的数）。
if [[ -f "$marker" ]]; then
  stop_kind="$(sed -n 's/^[[:space:]]*stop_kind[[:space:]]*[:=][[:space:]]*//p' "$marker" \
    | head -1 | tr -d '[:space:]')"
  if [[ "$stop_kind" == "converged" ]]; then
    stop_step="$(sed -n 's/^[[:space:]]*stopped_at_step[[:space:]]*[:=][[:space:]]*//p' "$marker" \
      | head -1 | tr -d '[:space:]')"
    lp_note "本轮是**停止轮次**（平台早停：stop_kind=converged，停在第 ${stop_step:-?} 步）⇒ 继续评测。"
    lp_note "  下游评测数可比（各自停止点上的模型质量）；训练侧 loss 不得与跑满轮次直接比。"
  else
    lp_warn "训练观察留痕存在（stop_kind=${stop_kind:-无法识别}）：${marker}"
    sed 's/^/    /' "$marker" >&2 || true
    lp_die "$LP_EXIT_TRAIN_INVALID" \
      "训练侧无效（发散/非有限值/墙钟超时，或留痕里读不出 stop_kind）⇒ **评测段拒绝开跑**。"$'\n'\
      "  这一轮不该出分数：训练都没跑完，评出来的数不是这个方案的数。"$'\n'\
      "  ★ 不许原样重跑（AGENTS.md §4）：要重跑必须说清改什么，并把改动写进新轮次。"
  fi
fi

# ② 口径门：不一致 ⇒ 评测侧无效（6）。
proto_rc=0
bash "${LP_TASK_DIR}/commands/eval_protocol_gate.sh" "$LP_ROUND_DIR" || proto_rc=$?
if [[ "$proto_rc" -ne 0 ]]; then
  lp_warn "评测口径门不过（退出 ${proto_rc}）⇒ 这一轮不出数字。"
  exit "$proto_rc"
fi

# ③ 设备守卫（评测要跑在卡上）+ 钩子 + 执行。
lp_guard_devices 评测
lp_hooks pre
rc=0
lp_run_stage eval "$LP_CURRENT_CMD" 评测 || rc=$?
hook_rc=0
lp_hooks post || hook_rc=$?
if [[ "$hook_rc" -ne 0 && "$rc" -eq 0 ]]; then rc="$hook_rc"; fi

case "$rc" in
  "$LP_EXIT_OK")
    lp_note "评测段完成（退出 0）。下一步：抽数（runtime/metrics.py）＋ 写 report.md / conclusions/。"
    ;;
  "$LP_EXIT_CMD_FAILED")
    lp_warn "评测驱动异常 ⇒ 翻成**评测侧无效**（退出 ${LP_EXIT_EVAL_INVALID}）：结果不可比、不出数字。"
    rc="$LP_EXIT_EVAL_INVALID"
    ;;
  "$LP_EXIT_EVAL_INVALID")
    lp_warn "评测侧无效（口径不全/驱动异常/结果不可比）：**不产生指标**，也别拿它跟基线比。"
    ;;
  *) lp_warn "评测段退出码 ${rc}。" ;;
esac
exit "$rc"
