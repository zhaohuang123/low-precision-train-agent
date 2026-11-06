#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# install.sh —— 把 lpta 出厂包装进一个**目标工程根目录**（安装／升级／状态／卸载）
#
# 用法
#   bash deploy/install.sh <目标目录> [动作] [选项]
#
# 动作（默认 = 安装；目标已有安装 ⇒ 自动按升级走）
#   --status            只报「目标版本 vs 包版本」与逐文件差异，**不写任何东西**
#   --uninstall         卸载本工程：按安装记录删 managed；**seeded 一律保留**（使用者写过的内容不是我们的）
#   --uninstall-agents  顺带卸掉**已装成 subagent** 的四个角色（在 `--agents-dir` 里；默认不碰宿主）
#
# 选项
#   --with-agents       把四个角色**导出成 DSH subagent**（写进 `--agents-dir`，默认 `${DSH_HOME:-$HOME/.dsh}/agents`）
#   --agents-dir <DIR>  指定那个目录（给了它就等于给了 `--with-agents`）
#   --force-managed     覆盖「被改过的」managed 文件（覆盖前存 `<文件>.bak`）
#   --force-downgrade   允许装比目标**更旧**的版本
#   --no-git            不在目标目录 `git init`
#   --dry-run           只打印计划，不落盘
#
# ★ 四个角色要不要装成 subagent（两种用法都合法，别选错）
#   A 一个主 Agent 依次扮四个角色（自己读 `agents/<角色>/AGENT.md` ＋按 `AGENTS.md` §5 挂载 skill）
#     ⇒ **不用装**。工程文件齐了就够，默认就是这个模式。
#   B 真用 `use_agent architect` 之类**派子代理**
#     ⇒ **必须** `--with-agents`，且装完要**重启 dsh**（工具名册是装载时静态构建的）。
#   本脚本**默认不碰宿主注册表**，只在结尾提醒你选了哪种。
#   ⚠ 若跳过这一步却按 B 用，症状是 `use_agent architect` 报 unknown agent，
#     而 `agents/*/AGENT.md` 明明都在 —— 见 `PREREQUISITES.md` §2.1。
#
# 四条纪律（fail-closed）
#   ① **冲突先报后停**：有 managed 冲突却没给 `--force-managed` ⇒ 列全清单后退出 2，**一个字节都不写**；
#      给了 `--with-agents` 时，subagent 侧的预检也在**落盘之前**做，同样「先报后停」
#   ② **seeded 永不覆盖**：装一次就不再动（`config/project.yaml`、`knowledge/INDEX.md`、
#      `records/conclusions/_EXAMPLE.yaml` —— 使用者会往里写东西）
#   ③ **记录无时间戳**：`.lpta-install.tsv` 只有 `sha256<TAB>class<TAB>路径` ⇒ 同一份包装两次，记录逐字节相同
#   ④ **不动你没点名的盘**：subagent 只在给了 `--with-agents`／`--agents-dir` 时才写；
#      `--uninstall` **不**顺手删宿主里的角色（要删得显式 `--uninstall-agents`）——
#      agent 文件可能是别人手调过的 persona，不由项目安装器替人决定
#
# 退出码：0 成功｜2 前置条件/冲突不过（fail-closed）
set -euo pipefail

ACTION="install"
FORCE_MANAGED=0; FORCE_DOWNGRADE=0; NO_GIT=0; DRY=0
WITH_AGENTS=0; AGENTS_DIR_OPT=""
TARGET=""

# 头部的用法块：从第 3 行打到 `set -euo` 之前。**不写死行号** —— 否则头部一长就读不全。
usage() { awk 'NR>2 && /^set -euo pipefail/{exit} NR>2' "$0" | sed 's/^#\s\{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --install) ACTION="install" ;;
    --upgrade) ACTION="upgrade" ;;
    --status)  ACTION="status" ;;
    --uninstall) ACTION="uninstall" ;;
    --uninstall-agents) ACTION="uninstall-agents" ;;
    --with-agents) WITH_AGENTS=1 ;;
    --agents-dir) [ $# -ge 2 ] || { echo "install.sh：--agents-dir 后面缺目录" >&2; exit 2; }
                  AGENTS_DIR_OPT="$2"; WITH_AGENTS=1; shift ;;
    --force-managed)   FORCE_MANAGED=1 ;;
    --force-downgrade) FORCE_DOWNGRADE=1 ;;
    --no-git) NO_GIT=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "install.sh：未知选项 $1" >&2; exit 2 ;;
    *) if [ -z "$TARGET" ]; then TARGET="$1"; else echo "install.sh：多余参数 $1" >&2; exit 2; fi ;;
  esac
  shift
done

die() { echo "install.sh：$*" >&2; exit 2; }
note() { echo "  $*"; }

[ -n "$TARGET" ] || { [ "$ACTION" = "uninstall-agents" ] && TARGET="(不涉及工程目录)" || { usage; exit 2; }; }
if [ "$ACTION" != "uninstall-agents" ]; then
  [ -d "$TARGET" ] || die "目标目录不存在：$TARGET（本安装器不替人建工程根，先 mkdir）"
  # 绝对化：本脚本不改自己的 cwd，但把相对路径规范化能避免「在不同目录调用 → 记录里写相对路径」这类隐患
  TARGET="$(cd "$TARGET" && pwd)"
fi

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$PKG_ROOT/MANIFEST.tsv"
SEED_DIRS="$PKG_ROOT/SEED_DIRS.txt"
RECORD_REL=".lpta-install.tsv"

[ -f "$MANIFEST" ] || die "找不到 $MANIFEST —— 这不是一个完整的出厂包"
[ -f "$PKG_ROOT/VERSION" ] || die "找不到 $PKG_ROOT/VERSION"
PKG_VERSION="$(tr -d '[:space:]' < "$PKG_ROOT/VERSION")"

sha() { if [ -f "$1" ]; then sha256sum "$1" | cut -d' ' -f1; else echo "-"; fi; }
# 从记录里取某个路径上次装下去时的 sha
rec_sha() { [ -f "$TARGET/$RECORD_REL" ] || { echo "-"; return; }; awk -F'\t' -v p="$1" '$3==p{print $1}' "$TARGET/$RECORD_REL" | head -1; }
rec_has() { [ -f "$TARGET/$RECORD_REL" ] || return 1; awk -F'\t' -v p="$1" '$3==p{found=1} END{exit !found}' "$TARGET/$RECORD_REL"; }

# ── subagent 侧：四个角色导出成 DSH subagent。**只在被点名时才碰宿主**（纪律④）──────
# 注意它写的是**另一个盘**（`${DSH_HOME:-$HOME/.dsh}/agents`），不是目标工程目录。
AGENTS_SH="$PKG_ROOT/scripts/install_agents.sh"
UNINSTALL_AGENTS_SH="$PKG_ROOT/scripts/uninstall_agents.sh"
AGENTS_DIR=""
if [ "$WITH_AGENTS" = 1 ] || [ "$ACTION" = "uninstall-agents" ]; then
  AGENTS_DIR="${AGENTS_DIR_OPT:-${DSH_HOME:-$HOME/.dsh}/agents}"
  case "$AGENTS_DIR" in "~/"*) AGENTS_DIR="$HOME/${AGENTS_DIR#\~/}" ;; esac
  [ -f "$AGENTS_SH" ] || die "包里找不到 scripts/install_agents.sh —— 这不是一个完整的出厂包"
fi

# ── 动作：uninstall-agents（宿主级；**只删本工程装过且未改动**的四个角色）─────────────
# 交给 scripts/uninstall_agents.sh：它按 `$AGENTS_DIR/.lpta-install.json` 只删 sha256 未变的文件，
# 被改过就报错退出 2（那是别人手调过的 persona，不由我们抹掉）。
if [ "$ACTION" = "uninstall-agents" ]; then
  echo "install.sh：卸载 subagent"
  note "目标目录 : $AGENTS_DIR"
  [ -d "$AGENTS_DIR" ] || die "目录不存在：$AGENTS_DIR（不是本工程装过的地方 ⇒ 一个都不碰）"
  [ -f "$AGENTS_DIR/.lpta-install.json" ] || die "$AGENTS_DIR 里没有 .lpta-install.json（不是本工程装的）⇒ 一个都不碰"
  if [ "$DRY" = 1 ]; then
    bash "$UNINSTALL_AGENTS_SH" --target "$AGENTS_DIR" --dry-run || exit 2
  else
    bash "$UNINSTALL_AGENTS_SH" --target "$AGENTS_DIR" || exit 2
  fi
  exit 0
fi

# ── 读包清单 ────────────────────────────────────────────────────────────────
MANAGED=(); SEEDED=()
while IFS=$'\t' read -r s c r; do
  [ -n "${r:-}" ] || continue
  case "$c" in
    managed) MANAGED+=("$s|$r") ;;
    seeded)  SEEDED+=("$s|$r") ;;
    *) die "MANIFEST.tsv 里有未知 class：$c（本安装器只认 managed/seeded）" ;;
  esac
done < "$MANIFEST"

say_plan() { echo "  包版本   : $PKG_VERSION"; note "目标目录 : $TARGET"; note "managed  : ${#MANAGED[@]} 个文件"; note "seeded   : ${#SEEDED[@]} 个文件"; }

# ── 动作：status ────────────────────────────────────────────────────────────
if [ "$ACTION" = "status" ]; then
  echo "install.sh：状态（只读，未写任何文件）"
  TGT_VER="(未安装)"; [ -f "$TARGET/VERSION" ] && TGT_VER="$(tr -d '[:space:]' < "$TARGET/VERSION")"
  note "包版本   : $PKG_VERSION"
  note "目标版本 : $TGT_VER"
  n_missing=0; n_same=0; n_diff=0; n_new=0
  for e in "${MANAGED[@]}"; do
    s="${e%%|*}"; r="${e#*|}"
    if [ ! -f "$TARGET/$r" ]; then n_missing=$((n_missing+1)); printf '    %-10s %s\n' "缺失" "$r"
    elif [ "$(sha "$TARGET/$r")" = "$s" ]; then n_same=$((n_same+1))
    elif rec_has "$r" && [ "$(sha "$TARGET/$r")" = "$(rec_sha "$r")" ]; then n_diff=$((n_diff+1)); printf '    %-10s %s\n' "可升级" "$r"
    else n_new=$((n_new+1)); printf '    %-10s %s\n' "冲突(改过)" "$r"; fi
  done
  note "managed：一致 $n_same ｜ 可升级 $n_diff ｜ 缺失 $n_missing ｜ 冲突(被改过) $n_new"
  n_keep=0
  for e in "${SEEDED[@]}"; do s="${e%%|*}"; r="${e#*|}"; [ -f "$TARGET/$r" ] && n_keep=$((n_keep+1)); done
  note "seeded ：已存在 $n_keep ／ ${#SEEDED[@]}（永不覆盖）"
  exit 0
fi

# ── 动作：uninstall ─────────────────────────────────────────────────────────
if [ "$ACTION" = "uninstall" ]; then
  [ -f "$TARGET/$RECORD_REL" ] || die "$TARGET 里没有 $RECORD_REL —— 不是本安装器装的，拒绝卸载"
  echo "install.sh：卸载（只删 managed；seeded 一律保留）"
  changed=(); removed=0
  while IFS=$'\t' read -r s c r; do
    [ "$c" = "managed" ] || continue
    [ -f "$TARGET/$r" ] || continue
    if [ "$(sha "$TARGET/$r")" != "$s" ]; then changed+=("$r"); continue; fi
    [ "$DRY" = 1 ] || rm -f "$TARGET/$r"; removed=$((removed+1))
  done < "$TARGET/$RECORD_REL"
  if [ ${#changed[@]} -gt 0 ] && [ "$FORCE_MANAGED" != 1 ]; then
    echo "install.sh：❌ 这些 managed 文件**被改过**，不是我们装下去的样子；拒绝删（未删任何文件）：" >&2
    printf '    %s\n' "${changed[@]}" >&2
    echo "    处置：人工确认后重跑并加 --force-managed。" >&2
    exit 2
  fi
  if [ ${#changed[@]} -gt 0 ]; then for r in "${changed[@]}"; do [ "$DRY" = 1 ] || rm -f "$TARGET/$r"; removed=$((removed+1)); done; fi
  # 收空目录（由深到浅），只收**变空**的，不碰 seeded 目录
  if [ "$DRY" != 1 ]; then
    # 自检跑出来的派生物（不是我们装下去的文件，也不该留下）
    find "$TARGET" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
    find "$TARGET" -mindepth 1 -type d -empty -not -path "$TARGET/.git/*" -delete 2>/dev/null || true
    rm -f "$TARGET/$RECORD_REL"
  fi
  note "已删 $removed 个 managed 文件；seeded 文件与目录**全部保留**"
  note "★ 宿主里的四个 subagent（若装过）**本步没动** —— 要卸单跑：bash deploy/install.sh --uninstall-agents"
  exit 0
fi

# ★ 目标已有安装 ⇒ 按升级走（头部用法承诺的就是这个）。`$ACTION` 只影响打印哪行字和
#   要不要打指引指针；写盘计划、seeded 保留、降级检查都不看它 —— 所以这里不需要再记
#   "是不是人显式给的 --install"（为一个标签养一个标志位，是 0.18.37 收掉的东西）。
if [ "$ACTION" = "install" ] && [ -f "$TARGET/$RECORD_REL" ]; then
  ACTION="upgrade"
fi

# ── 动作：install / upgrade —— 先算全量计划，再决定写不写 ──────────────────
if [ -f "$TARGET/VERSION" ] && [ "$FORCE_DOWNGRADE" != 1 ]; then
  TGT_VER="$(tr -d '[:space:]' < "$TARGET/VERSION")"
  if [ "$TGT_VER" != "$PKG_VERSION" ]; then
    newest="$(printf '%s\n%s\n' "$TGT_VER" "$PKG_VERSION" | sort -V | tail -1)"
    [ "$newest" = "$PKG_VERSION" ] || die "拒绝降级：目标已是 $TGT_VER，包是 $PKG_VERSION（要降级加 --force-downgrade）"
  fi
fi

echo "install.sh：$([ "$ACTION" = "install" ] && echo 安装 || echo 升级)"
if [ "$ACTION" = "upgrade" ]; then
  note "升级指引：deploy/UPGRADE.md（会拦住升级的 5 件事 ＋ 任务目录要手工同步的文件）"
fi
say_plan

PLAN=()      # "write|rel" / "keep|rel"
CONFLICT=()
for e in "${MANAGED[@]}"; do
  s="${e%%|*}"; r="${e#*|}"
  if [ ! -f "$TARGET/$r" ]; then PLAN+=("write|$r"); continue; fi
  if [ "$(sha "$TARGET/$r")" = "$s" ]; then PLAN+=("same|$r"); continue; fi
  if rec_has "$r" && [ "$(sha "$TARGET/$r")" = "$(rec_sha "$r")" ]; then PLAN+=("write|$r"); continue; fi
  # 冲突：**照样进计划**（给了 --force-managed 才走得到这里），
  # 否则「报了冲突却没计划写」⇒ --force-managed 变成空操作，下面写记录时还会把漂移洗白。
  PLAN+=("write|$r")
  CONFLICT+=("$r")
done
STALE_SEEDED=()   # seeded 已存在、但内容与**本包**里的不同 ⇒ 升级不覆盖（设计如此），但要喊一声
for e in "${SEEDED[@]}"; do
  r="${e#*|}"
  if [ -f "$TARGET/$r" ]; then
    PLAN+=("keep|$r")
    # 出厂版的那份在解包目录里；比对不上就说明"你这份比新包里旧（或你改过）"
    if [ -f "$PKG_ROOT/$r" ] && [ "$(sha "$TARGET/$r")" != "$(sha "$PKG_ROOT/$r")" ]; then
      STALE_SEEDED+=("$r")
    fi
  else
    PLAN+=("write|$r")
  fi
done

if [ ${#CONFLICT[@]} -gt 0 ] && [ "$FORCE_MANAGED" != 1 ]; then
  echo "install.sh：❌ 有 ${#CONFLICT[@]} 个 managed 文件在目标里**被改过**（内容 ≠ 上次装下去的样子）；" >&2
  echo "           按①「冲突先报后停」，**一个字节都没写**：" >&2
  printf '    %s\n' "${CONFLICT[@]}" >&2
  echo "    处置二选一：" >&2
  echo "      · 你的改动要保留 ⇒ 先自己备份/合并，再重跑（仍会报冲突，直到文件回到我们装下去的样子）" >&2
  echo "      · 你的改动不要了   ⇒ 重跑并加 --force-managed（覆盖前自动存 <文件>.bak）" >&2
  exit 2
fi

# ── subagent 侧**预检**：必须在写任何文件之前（纪律①「先报后停」）──────────────────
# 静默预检一次：subagent 侧若过不了（frontmatter 不合规会被注册表整份丢弃／目标里已有同名角色
# 却非本工程所装／被本地改过），就在**本工程一个字节都没写**的状态下停住，让使用者单独处置。
if [ "$WITH_AGENTS" = 1 ] && [ "$DRY" != 1 ]; then
  if ! ag_pre="$(bash "$AGENTS_SH" --target "$AGENTS_DIR" --dry-run 2>&1)"; then
    { echo "install.sh：❌ subagent 侧预检不过 ⇒ 按①「冲突先报后停」，**本工程一个字节都没写**："
      printf '%s\n' "$ag_pre" | sed 's/^/    /'
      echo "    处置：先单独跑下面这条看细节、按它的提示处理，再回来装；"
      echo "          或在 「--agents-dir <另一个目录>」 另指一个干净目录。"
      echo "      bash '$AGENTS_SH' --target '$AGENTS_DIR'"; } >&2
    exit 2
  fi
fi

if [ "$DRY" = 1 ]; then
  echo "install.sh：[dry-run] 不写盘。计划："
  for p in "${PLAN[@]}"; do printf '    %-6s %s\n' "${p%%|*}" "${p#*|}"; done
  [ ${#CONFLICT[@]} -gt 0 ] && note "此外 ${#CONFLICT[@]} 个冲突（因给了 --force-managed 会被覆盖并存 .bak）"
  if [ "$WITH_AGENTS" = 1 ]; then
    echo "install.sh：[dry-run] subagent 侧（--agents-dir $AGENTS_DIR）："
    bash "$AGENTS_SH" --target "$AGENTS_DIR" --dry-run || exit 2
  else
    note "subagent 侧：未点名 ⇒ 本次不碰 ${DSH_HOME:-$HOME/.dsh}/agents（要装见 --with-agents）"
  fi
  exit 0
fi

# ── 落盘 ────────────────────────────────────────────────────────────────────
n_w=0; n_s=0; n_k=0
for p in "${PLAN[@]}"; do
  kind="${p%%|*}"; r="${p#*|}"
  case "$kind" in
    same) n_s=$((n_s+1)) ;;
    keep) n_k=$((n_k+1)) ;;
    write)
      mkdir -p "$TARGET/$(dirname "$r")"
      if [ -f "$TARGET/$r" ] && [ "$FORCE_MANAGED" = 1 ]; then cp -p "$TARGET/$r" "$TARGET/$r.bak"; fi
      cp -p "$PKG_ROOT/$r" "$TARGET/$r"
      n_w=$((n_w+1)) ;;
  esac
done

# 空内容目录（seeded 的容器）：只在缺失时建
if [ -f "$SEED_DIRS" ]; then
  while IFS= read -r d; do [ -n "$d" ] || continue; mkdir -p "$TARGET/$d"; done < "$SEED_DIRS"
fi

# 安装记录（无时间戳 ⇒ 幂等）
# ★ managed 记**包里那一份的 sha**（＝我们装下去的样子），不记磁盘现值 ——
#   否则「我没覆盖它，却把它的现值记成基线」会把漂移洗白，下次就当成没被动过。
{ for e in "${MANAGED[@]}"; do s="${e%%|*}"; r="${e#*|}"; printf '%s\tmanaged\t%s\n' "$s" "$r"; done
  for e in "${SEEDED[@]}";  do s="${e%%|*}"; r="${e#*|}"; printf '%s\tseeded\t%s\n'  "$(sha "$TARGET/$r")" "$r"; done
} > "$TARGET/$RECORD_REL"

# 让 AGENTS.md 从**任意子目录**都能被找到：目标根没有 git 就 init 一个（不提交）
if [ "$NO_GIT" != 1 ] && [ ! -d "$TARGET/.git" ]; then
  if command -v git >/dev/null 2>&1; then
    git -C "$TARGET" init -q && note "已 git init（让 AGENTS.md 从子目录也能被找到；**没有**替你做任何提交）"
  else
    note "⚠ 目标目录没有 .git 且找不到 git 命令 —— 请从工程根启动，或自行 git init"
  fi
fi

# ── subagent 侧**落盘**（给了 --with-agents／--agents-dir 才走得到这里）──────────────
AG_LINE="未装（默认；见下）"
if [ "$WITH_AGENTS" = 1 ]; then
  if ag_out="$(bash "$AGENTS_SH" --target "$AGENTS_DIR" 2>&1)"; then
    AG_LINE="已装 4 个角色 ⇒ $AGENTS_DIR"
    printf '%s\n' "$ag_out" | sed 's/^/  /'
  else
    { echo "install.sh：❌ 工程已装好，但 subagent 侧写入失败 ⇒ 退出 2。"
      printf '%s\n' "$ag_out" | sed 's/^/    /'
      echo "    工程文件本身是完整的（它们已经写好了）。单跑这条重试："
      echo "      bash scripts/install_agents.sh --target '$AGENTS_DIR'   # 在 $TARGET 下"; } >&2
    exit 2
  fi
fi

echo "install.sh：✅ 完成"
note "写入/覆盖 $n_w ｜ 已一致 $n_s ｜ seeded 保留 $n_k"
note "安装记录 : $TARGET/$RECORD_REL（${#MANAGED[@]}+${#SEEDED[@]} 行，无时间戳）"
if [ ${#STALE_SEEDED[@]} -gt 0 ]; then
  note "⚠ 有 ${#STALE_SEEDED[@]} 个 seeded 文件**保留了你这边的版本**、但内容与出厂版不同（永不覆盖，设计如此）："
  for r in "${STALE_SEEDED[@]}"; do
    note "    $r"
    note "      出厂版：$PKG_ROOT/$r ｜ 你的：$TARGET/$r"
  done
  note "    要对比：diff -u \"$TARGET/<文件>\" \"$PKG_ROOT/<文件>\"；要采用出厂版就手动覆盖（升级绝不替你决定）"
fi
note "subagent : $AG_LINE"
if [ "$WITH_AGENTS" != 1 ]; then
  echo "  ── 四个角色这次**没有**装成 DSH subagent（默认）。两种用法二选一，别选错："
  echo "     A 一个主 Agent 依次扮四个角色（自己读 agents/<角色>/AGENT.md ＋按 AGENTS.md §5 挂 skill）"
  echo "       ⇒ **不用装**，工程文件齐了就够。"
  echo "     B 要真的 \`use_agent architect\` 派子代理"
  echo "       ⇒ 重跑并加 --with-agents，然后**重启 dsh**（工具名册是装载时静态构建的）。"
  echo "     跳过它却按 B 用 ⇒ \`use_agent architect\` 报 unknown agent，而 agents/*/AGENT.md 明明都在。"
fi
note "下一步   : ① 填 $TARGET/config/project.yaml ② bash deploy/verify_install.sh $TARGET"
