#!/usr/bin/env bash
# convert.sh —— **转换段入口**（任务级唯一一份；轮次目录不许放副本）
#
# 归属：三段入口的转换段。用法同 train.sh：
#   bash <任务目录>/convert.sh --round <轮次> [--dry-run] [--root <配置根>]
#
# 与训练段的**两处不同**（其余前导完全共用）：
#   ① **不查卡**：权重格式转换是纯 CPU/磁盘活儿。给它套设备守卫，只会让"没有空闲卡"这种
#      与它无关的理由把它拦下（误拦一次，人就会绕过整个守卫）。
#   ② **不早停**：转换没有 loss 轨迹。但**墙钟上限仍然要有**（超时归 5，见 runtime/README.md §2.1）——
#      转换卡死比转换失败更常见，没人看着就永远占着。
set -euo pipefail

LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../../runtime/_common.sh
source "${LP_ROOT}/runtime/_common.sh"

lp_setup convert "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" "$@"

lp_effective_cmd "${LP_CONVERT_CMD:-}" LP_CONVERT_EXTRA_ARGS
[[ -n "$LP_CONVERT_CMD" ]] || lp_die "run.env 里没有 LP_CONVERT_CMD（命令只有一个落点）。"

if [[ "$LP_DRY_RUN" == "1" ]]; then
  echo "--dry-run：本段**什么都不执行**；真跑时会依次做："
  echo "  1) pre_convert 钩子（存在即执行）：${LP_ROUND_DIR}/hooks/pre_convert.sh"
  echo "  2) 转换      ${LP_CURRENT_CMD}"
  echo "               （executor.py：逐行落日志 → ${LP_EV}/convert.log；到点杀整个进程组，退出 ${LP_EXIT_TRAIN_INVALID}）"
  echo "  3) post_convert 钩子（存在即执行）：${LP_ROUND_DIR}/hooks/post_convert.sh"
  echo "  说明：转换段**不查卡**（纯 CPU/磁盘活儿），也不早停（没有 loss 轨迹）。"
  lp_run_stage convert "$LP_CURRENT_CMD" 转换
  exit "$LP_EXIT_OK"
fi

lp_hooks pre
rc=0
lp_run_stage convert "$LP_CURRENT_CMD" 转换 || rc=$?
hook_rc=0
lp_hooks post || hook_rc=$?
if [[ "$hook_rc" -ne 0 && "$rc" -eq 0 ]]; then rc="$hook_rc"; fi

case "$rc" in
  "$LP_EXIT_OK") lp_note "转换段完成（退出 0）。下一段：bash ${LP_TASK_DIR}/eval.sh --round ${LP_ROUND}" ;;
  "$LP_EXIT_TRAIN_INVALID") lp_warn "转换**超墙钟被杀**（归训练侧无效 5，见 §2.1）。看 ${LP_EV}/convert.log 的尾部。" ;;
  "$LP_EXIT_CMD_FAILED") lp_warn "转换命令自己以非零码退出；日志尾部见 ${LP_EV}/convert.log。" ;;
  *) lp_warn "转换段退出码 ${rc}。" ;;
esac
exit "$rc"
