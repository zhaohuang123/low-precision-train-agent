#!/usr/bin/env bash
# validate_design.sh —— **闸门**：每轮门（方案冻结件不过 ⇒ 拒绝花卡）
#
# 归属：设计方案预检 ＋ AGENTS.md §3（每轮必跑的门只有 `runtime/validate_round.py` 一个）。
# 用法：bash <任务目录>/commands/validate_design.sh <轮次目录>
#
# ★ 规则的实现**不在这里**：这里只是"从三段入口里把门调起来"的那一行。
#   门的规则只有一份实现 —— `runtime/validate_round.py`（`devtools/validate_design.py` 也共用它）。
#   在这里再写一套判据，就是给同一个事实造第二个落点。
#
# 退出码：0 过 ／ 2 不过（错误行由 `validate_round.py` 写进 `<轮次>/test.md`、`<轮次>/report.md`）
set -euo pipefail

LP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

round_dir="${1:-}"
if [[ -z "$round_dir" ]]; then
  echo "用法：bash <任务目录>/commands/validate_design.sh <轮次目录>" >&2
  exit 2
fi
design="${round_dir}/design.md"
if [[ ! -f "$design" ]]; then
  echo "[gate] ✗ 找不到方案文件 ${design} ⇒ 拒绝开跑（退出 2）。" >&2
  exit 2
fi

echo "[gate] 每轮门：python3 ${LP_ROOT}/runtime/validate_round.py ${design}"
rc=0
python3 "${LP_ROOT}/runtime/validate_round.py" "$design" || rc=$?
if [[ "$rc" -ne 0 ]]; then
  echo "[gate] ✗ 每轮门不过（退出 ${rc}）⇒ **拒绝花卡**。" >&2
  echo "[gate]   显式错误行在：${round_dir}/test.md 与 ${round_dir}/report.md" >&2
  echo "[gate]   修完方案/实现再跑一次；不许把门调松来换一个绿。" >&2
fi
exit "$rc"
