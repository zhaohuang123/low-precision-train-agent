#!/usr/bin/env bash
# framework_patch.sh —— 挂 patch → 跑 → **还原 → 机械校验**（还原是流程里的一个正式步骤）。
#
# 归属：patch 挂/还原与快照校验（`apply`／`restore`／`verify`／`roundtrip`）。
#
# 为什么必须是脚本（§6.3 原话）：「还原是流程里的一个正式步骤，不是记得清理」；不做成脚本就是记性活。
# 两条铁律（§12.3）：① 框架目录本身**永不提交改动**（检出保持干净）；
#                    ② 改动用 patch 挂进去、跑完即还原，前后 `rev-parse HEAD` ＋ `status --porcelain` 必须一致。
#
# 行为契约（逐条来自 §12.3，本文件逐条实现）：
#   ① 跑前：记录框架起点，挂上 patch（**统一用 git apply，不用软链**）
#        git -C "$WT" rev-parse HEAD        > "$P/framework_head.before"
#        git -C "$WT" status --porcelain=v1 > "$P/framework_status.before"     # 必须为空（干净）
#        git -C "$WT" apply --check "$P/$Q" && git -C "$WT" apply "$P/$Q"
#   ② 跑实验（<任务目录>/train.sh …；评测侧同理）—— **不由本脚本执行**。
#   ③ 跑完（正式步骤）：还原 ＋ 机械校验；下列 diff 任一有差异 ⇒ **本轮失败**
#        git -C "$WT" apply -R "$P/$Q"
#        git -C "$WT" rev-parse HEAD        > "$P/framework_head.after"
#        git -C "$WT" status --porcelain=v1 > "$P/framework_status.after"
#        diff -u "$P/framework_head.before"   "$P/framework_head.after"
#        diff -u "$P/framework_status.before" "$P/framework_status.after"
#   ④ 框架检出用 **git worktree**：`git -C <框架检出> worktree add <干净工作树> <framework_head>`，
#      按需切、不常驻；patch **只 apply 到这份工作树**（本文件的 `--worktree` 指工作树，不是检出本体）；
#      还原后可 `git -C <检出> worktree remove <工作树>` 或 `git -C <检出> worktree prune`。
#      本轮 `framework_head`（40 位 sha）钉在 ①任务配置的 `train.framework_head`。
#   ⑤ **禁止**：不改框架检出的既有历史，**不在检出里提交**（含其主工作区与工作树）—— 本脚本只做
#      `git apply` / `git apply -R` / `worktree add` / `worktree remove`，**没有任何 `commit`/`add`/`checkout`**。
#   ⑥ patch 每份必须带三栏：**改了哪个文件 / 为什么 / 怎么验证**；单轮私有改动**不放**
#      `knowledge/frameworks/patches/`（那里只放跨多轮复用、已证明稳定的公共 patch）。
#
# ★ 两条「不把空输出当干净 / 不把没挂上当挂上」的 fail-closed 设计（对应 runtime/README.md §3 的坑 5、6）：
#   * 快照的写入**必须来自一条成功的 git 命令**：命令失败即退出 2，绝不留下一个「空文件 ＝ 看起来干净」。
#   * 挂完 patch 后立即断言 `status --porcelain` **非空**（patch 真的改到了工作树）；
#     空 ⇒ 退出 2，因为「补丁没生效」与「补丁生效但没改任何行」在日志里长得一样。
#
# 用法：
#   bash runtime/framework_patch.sh apply     --repo <框架检出> --worktree <工作树> --patches <轮次>/patches [--patch <名>]...
#   bash runtime/framework_patch.sh restore   --repo <框架检出> --worktree <工作树> --patches <轮次>/patches [--patch <名>]...
#   bash runtime/framework_patch.sh verify    --repo <框架检出> --worktree <工作树> --patches <轮次>/patches
#   bash runtime/framework_patch.sh roundtrip --repo <框架检出> --worktree <工作树> --patches <轮次>/patches [--patch <名>]... [--head <sha>]
#
#   ★ `--patch` **可重复**（0.18.29）：按出现顺序一次挂上（快照只有一对）；不写则要求
#     该目录里**恰好一份** `*.patch`（多份且没点名 ⇒ 退出 2，不猜顺序、不自动合并）。
#
#   --head <sha>          仅 roundtrip：工作树不存在时用 `git worktree add` 按这个 sha 切一份干净工作树
#   --remove-worktree     仅 roundtrip：演练完把工作树移除（默认**保留**：§16.1 P5 的验收要在
#                         演练**之后**读 `<工作树>` 与 `<检出>` 两处的 `status --porcelain`）
#
# 退出码（本工程唯一一份在 runtime/README.md §2）：`0` 成功；`2` 约定/契约不过（fail-closed）。

set -u
set -o pipefail

readonly PROG="runtime/framework_patch.sh"
readonly EXIT_CONTRACT=2

die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit "$EXIT_CONTRACT"; }

usage() {
  cat <<'EOF'
framework_patch.sh —— 挂 patch / 还原 / 校验 / 演练（挂→还原→校验）

子命令：
  apply      记录起点快照 → git apply --check → git apply
  restore    git apply -R → 写 after 快照 → 两份 diff 必须无差异
  verify     复核 before/after 快照 diff ＋ 工作树与检出两处 status --porcelain 必须为空
  roundtrip  apply → restore → verify（§16.1 P5 的「挂 → 还原 → 校验」演练）

公共参数：
  --repo <dir>       框架检出（git 仓库；只读，永不提交）
  --worktree <dir>   干净工作树（patch **只**挂这里；不许等于 --repo）
  --patches <dir>    轮次归档的 patches 目录（快照 framework_head/status.{before,after} 写在这里）
  --patch <name>     指定 patches 目录下的某一个 patch（默认：目录里恰好一个 *.patch 时才自取，多个即报错不猜）

roundtrip 专有：
  --head <sha>       工作树不存在时按此 sha 切一份干净工作树（git worktree add）
  --remove-worktree  演练后移除工作树（默认保留）
  -h, --help         本帮助

退出码：0 成功；2 约定/契约不过（fail-closed）。
EOF
}

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
cmd="${1:-}"
if [ -z "$cmd" ]; then usage >&2; die "缺少子命令"; fi
shift || true

case "$cmd" in
  -h|--help) usage; exit 0 ;;
  apply|restore|verify|roundtrip) : ;;
  *) usage >&2; die "未知子命令：$cmd" ;;
esac

REPO=""; WT=""; PATCHES=""; HEAD_SHA=""; REMOVE_WT=0
PATCH_ARGS=()   # 顺序＝挂载顺序（`--patch` 可重复）
while [ $# -gt 0 ]; do
  case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    --repo)     [ $# -ge 2 ] || die "--repo 缺参数"; REPO="$2"; shift 2 ;;
    --worktree) [ $# -ge 2 ] || die "--worktree 缺参数"; WT="$2"; shift 2 ;;
    --patches)  [ $# -ge 2 ] || die "--patches 缺参数"; PATCHES="$2"; shift 2 ;;
    --patch)    [ $# -ge 2 ] || die "--patch 缺参数"; PATCH_ARGS+=("$2"); shift 2 ;;
    --head)     [ $# -ge 2 ] || die "--head 缺参数"; HEAD_SHA="$2"; shift 2 ;;
    --remove-worktree) REMOVE_WT=1; shift ;;
    --repo=*)     REPO="${1#*=}"; shift ;;
    --worktree=*) WT="${1#*=}"; shift ;;
    --patches=*)  PATCHES="${1#*=}"; shift ;;
    --patch=*)    PATCH_ARGS+=("${1#*=}"); shift ;;
    --head=*)     HEAD_SHA="${1#*=}"; shift ;;
    *) die "未知参数：${1:-}" ;;
  esac
done

[ -n "$REPO" ]    || die "--repo 是必需的"
[ -n "$WT" ]      || die "--worktree 是必需的"
[ -n "$PATCHES" ] || die "--patches 是必需的"

# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
abspath() {  # 目标可以不存在（roundtrip 可能要新建工作树）
  if [ -d "$1" ]; then (cd "$1" && pwd -P); else
    local d b; d="$(dirname "$1")"; b="$(basename "$1")"
    if [ -d "$d" ]; then printf '%s/%s\n' "$(cd "$d" && pwd -P)" "$b"; else printf '%s\n' "$1"; fi
  fi
}

require_git() {  # $1=目录 $2=人话名字
  [ -e "$1" ] || die "$2 不存在：$1（路径不存在或读不到即失败，不把空输出当成干净）"
  git -C "$1" rev-parse --git-dir >/dev/null 2>&1 \
    || die "$2 不是可读的 git 仓库：$1（路径不存在或读不到即失败，不把空输出当成干净）"
}

assert_not_same() {
  local a b; a="$(abspath "$REPO")"; b="$(abspath "$WT")"
  [ "$a" != "$b" ] || die "--worktree 不许等于 --repo：patch 只许挂到「干净工作树」，不许挂到框架检出本体（§12.3）"
}

resolve_patch() {
  [ -d "$PATCHES" ] || die "--patches 不是目录：$PATCHES"
  # ★ 绝对化（0.18.28）：`git -C "$WT" apply "$PATCH"` 会把**相对**的 $PATCH 解析到工作树里，
  #   于是"从工程根敲的相对路径"在 git 眼里变成"工作树里不存在的文件" —— 报错信息还只字不提 cwd。
  PATCHES="$(abspath "$PATCHES")"
  PATCH_FILES=()
  local name f n=0
  if [ "${#PATCH_ARGS[@]}" -gt 0 ]; then
    # 显式点名（一份或多份，顺序即挂载顺序）
    for name in "${PATCH_ARGS[@]}"; do
      case "$name" in
        /*) f="$name" ;;                       # 直接给绝对路径
        *)  f="$PATCHES/$name" ;;
      esac
      [ -f "$f" ] || die "patch 不存在：$f（--patches 已解析为 $PATCHES）"
      [ -s "$f" ] || die "patch 是空文件：$f"
      PATCH_FILES+=("$(abspath "$f")")
    done
  else
    # 没点名：目录里必须**恰好一份**（多份是"要不要全挂/什么顺序"没法猜，不替人决定）
    for f in "$PATCHES"/*.patch; do
      [ -e "$f" ] || continue
      n=$((n + 1)); PATCH_FILES+=("$(abspath "$f")")
    done
    [ "$n" -ge 1 ] || die "patches 目录里没有 *.patch：$PATCHES"
    [ "$n" -eq 1 ] || die "patches 目录里有 $n 个 patch，不猜 —— 请用 --patch <名> 逐个指定（$PATCHES）"
  fi
  [ "${#PATCH_FILES[@]}" -gt 0 ] || die "没有可挂的 patch（--patches=$PATCHES）"
}

# 写 before 快照：命令必须成功；工作树必须干净（空 status ⇒ 才是干净）
snapshot_before() {
  git -C "$WT" rev-parse HEAD > "$PATCHES/framework_head.before" 2>/dev/null \
    || die "读不到工作树 HEAD（$WT）—— 快照未写，不许把它当成干净"
  [ -s "$PATCHES/framework_head.before" ] || die "HEAD 快照为空：$PATCHES/framework_head.before"
  git -C "$WT" status --porcelain=v1 > "$PATCHES/framework_status.before" 2>/dev/null \
    || die "读不到工作树 status（$WT）—— 快照未写，不许把它当成干净"
  if [ -s "$PATCHES/framework_status.before" ]; then
    printf '%s: 工作树不干净，拒绝挂 patch：%s\n' "$PROG" "$WT" >&2
    cat "$PATCHES/framework_status.before" >&2
    die "先在干净工作树上作业（这些改动从哪来要说清；§12.3 铁律①）"
  fi
}

snapshot_after() {
  git -C "$WT" rev-parse HEAD > "$PATCHES/framework_head.after" 2>/dev/null \
    || die "还原后读不到工作树 HEAD（$WT）"
  [ -s "$PATCHES/framework_head.after" ] || die "还原后 HEAD 快照为空：$PATCHES/framework_head.after"
  git -C "$WT" status --porcelain=v1 > "$PATCHES/framework_status.after" 2>/dev/null \
    || die "还原后读不到工作树 status（$WT）"
}

diff_snapshots() {  # 两份 diff 任一有差异 ⇒ 本轮失败；$1=人话标签
  local k bad=0 label="${1:-还原校验}"
  for k in head status; do
    if ! diff -u "$PATCHES/framework_${k}.before" "$PATCHES/framework_${k}.after"; then
      printf '%s: ★ framework_%s.before/after 有差异 ⇒ 本轮失败（§12.3：还原是正式步骤）\n' "$PROG" "$k" >&2
      bad=1
    fi
  done
  [ "$bad" -eq 0 ] || die "$label 不通过（差异见上）：$PATCHES"
  printf '%s: %s：framework_head / framework_status 两份 diff 均无差异 ✓\n' "$PROG" "$label"
}

assert_clean() {  # $1=目录 $2=人话名字
  local tmp; tmp="$(mktemp)"
  if ! git -C "$1" status --porcelain > "$tmp" 2>/dev/null; then
    rm -f "$tmp"
    die "读不到 $2 的 status：$1（路径不存在或读不到即失败，不把空输出当成干净）"
  fi
  if [ -s "$tmp" ]; then
    printf '%s: %s 不干净（还原后必须为空）：%s\n' "$PROG" "$2" "$1" >&2
    cat "$tmp" >&2
    rm -f "$tmp"
    die "$2 未还原干净"
  fi
  rm -f "$tmp"
  printf '%s: %s 干净（status --porcelain 为空）✓\n' "$PROG" "$2"
}

# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
do_apply() {
  require_git "$REPO" "框架检出"
  require_git "$WT"   "框架工作树"
  assert_not_same
  resolve_patch
  snapshot_before
  # 先**全体** --check 再一次性 apply：一份不过就一份都不挂（不留"挂了一半"的树）
  git -C "$WT" apply --check "${PATCH_FILES[@]}" \
    || die "git apply --check 不过：${PATCH_FILES[*]} 与工作树 $WT 不匹配（不许猜、不许绕过）"
  git -C "$WT" apply "${PATCH_FILES[@]}" || die "git apply 失败：${PATCH_FILES[*]}"
  # ★ 机制生效检查：挂了 patch 之后工作树必须真的变脏，否则「没挂上」会被当成「挂上了」
  if [ -z "$(git -C "$WT" status --porcelain=v1)" ]; then
    die "patch 应用后工作树 status 仍为空 ⇒ patch 未生效（没启用 ≠ 搜了没搜到，README §3 坑 5）"
  fi
  printf '%s: 已挂 %s 份 patch → %s\n' "$PROG" "${#PATCH_FILES[@]}" "$WT"
  local one
  for one in "${PATCH_FILES[@]}"; do
    printf '  · %s  sha256=%s\n' "$one" "$(sha256sum "$one" | awk '{print $1}')"
  done
  printf '  起点 head=%s\n' "$(cat "$PATCHES/framework_head.before")"
}

do_restore() {
  require_git "$REPO" "框架检出"
  require_git "$WT"   "框架工作树"
  resolve_patch
  [ -f "$PATCHES/framework_head.before" ]   || die "缺少起点快照：$PATCHES/framework_head.before"
  [ -f "$PATCHES/framework_status.before" ] || die "缺少起点快照：$PATCHES/framework_status.before"
  # ★ 逆序还原（后挂的先摘）：按挂载顺序反向，才与"挂载"严格互为逆操作
  local -a rev=()
  local i
  for (( i=${#PATCH_FILES[@]}-1; i>=0; i-- )); do rev+=("${PATCH_FILES[$i]}"); done
  git -C "$WT" apply -R --check "${rev[@]}" \
    || die "反向 --check 不过：patch 没挂上或工作树已被改动 ⇒ 无法还原（${rev[*]}）"
  git -C "$WT" apply -R "${rev[@]}" || die "git apply -R 失败：${rev[*]}"
  snapshot_after
  diff_snapshots
}

do_verify() {
  require_git "$REPO" "框架检出"
  require_git "$WT"   "框架工作树"
  local k
  for k in framework_head.before framework_status.before framework_head.after framework_status.after; do
    [ -f "$PATCHES/$k" ] || die "缺少快照：$PATCHES/$k（缺哪份即失败）"
  done
  [ -s "$PATCHES/framework_head.before" ] || die "起点 HEAD 快照为空：$PATCHES/framework_head.before"
  [ -s "$PATCHES/framework_head.after" ]  || die "终点 HEAD 快照为空：$PATCHES/framework_head.after"
  # ★ status 快照「干净」时**合法地就是 0 字节** ⇒ 这里只判存在性（见 §16.1 P5 验收行的同类缺陷说明）。
  diff_snapshots "还原后复核"
  assert_clean "$WT"   "框架工作树"
  assert_clean "$REPO" "框架检出"
}

do_roundtrip() {
  require_git "$REPO" "框架检出"
  resolve_patch
  if [ ! -d "$WT" ]; then
    [ -n "$HEAD_SHA" ] || die "工作树不存在（$WT）；roundtrip 要新建它，必须给 --head <sha>（§12.3 worktree add）"
    git -C "$REPO" worktree add "$WT" "$HEAD_SHA" \
      || die "git worktree add 失败：$REPO → $WT @ $HEAD_SHA"
    printf '%s: 已切干净工作树：%s @ %s\n' "$PROG" "$WT" "$HEAD_SHA"
  fi
  # ★ 工作树**已存在**时 `git worktree add` 根本不会被跑到（上一轮默认保留工作树）⇒ `--head`
  #   会**完全被忽略**。不比对的话「跑在钉点上」只是纪律：工作树停在旧 sha 上照样挂 patch、
  #   照样出数，而 `train.framework_head` 与 `framework_head.before` 对不上只有人肉能发现。
  #   这里比对「工作树真实 HEAD」vs「调用方给的 --head」，两边都**先解析成完整 sha**
  #   （所以短 sha／分支名也对得上）。「--head 是否等于任务配置的 train.framework_head」
  #   不归本脚本管：脚本不读任务配置，传参是调用方的责任，再设一个权威只会两处漂移。
  if [ -n "$HEAD_SHA" ]; then
    _want_head="$(git -C "$REPO" rev-parse --verify --quiet "${HEAD_SHA}^{commit}")" \
      || die "钉点解析不出提交：--head ${HEAD_SHA}（框架检出 $REPO）"
    _actual_head="$(git -C "$WT" rev-parse HEAD 2>/dev/null)" \
      || die "读不出工作树的 HEAD：$WT"
    [ "$_actual_head" = "$_want_head" ] \
      || die "工作树不在钉点上：$WT @ ${_actual_head}（要求 --head ${HEAD_SHA} → ${_want_head}）⇒ 拒绝挂 patch（换工作树或先 worktree remove）"
  fi
  assert_not_same
  do_apply
  do_restore
  do_verify
  if [ "$REMOVE_WT" -eq 1 ]; then
    git -C "$REPO" worktree remove "$WT" || die "git worktree remove 失败：$WT"
    printf '%s: 已移除工作树：%s\n' "$PROG" "$WT"
  else
    printf '%s: 工作树保留（§16.1 P5 验收要在演练后读它）：%s\n' "$PROG" "$WT"
    printf '  需要移除时：git -C %s worktree remove %s\n' "$REPO" "$WT"
  fi
  printf '%s: roundtrip 完成 —— 挂、还原、校验三段都过 ✓\n' "$PROG"
}

case "$cmd" in
  apply)     do_apply ;;
  restore)   do_restore ;;
  verify)    do_verify ;;
  roundtrip) do_roundtrip ;;
esac
exit 0
