#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# verify_install.sh —— 装完之后用它自证「引擎真的在目标容器里跑得起来」
#
# 用法
#   bash deploy/verify_install.sh <目标目录>
#
# 它跑九件事（**全部在目标目录里跑**，不碰建设者侧的任何东西）：
#   ① 依赖：`python3` ≥ 3.8 ＋ **`PyYAML`**（引擎唯一的第三方依赖，缺即 fail-closed）
#   ② 出厂形态：`devtools/` 与 `tests/` **必须不存在**（它们不随包；存在 ⇒ 有人自己补了一份）
#   ③ 开跑入口：`scripts/{preflight,start_experiment}.sh` 存在且 `bash -n` 过（0.18.0 起）
#   ④ 引擎自检：`metrics.py`／`validate_round.py`／`executor.py`／`resources.py`／`_common.sh` 各跑 `--selftest`
#   ⑤ 契约加载：`python3 runtime/config.py validate config/tasks/_TEMPLATE.yaml`（rc=0）
#   ⑥ 安装记录：`.lpta-install.tsv` 存在且行数与包清单一致
#   ⑦ 部署值：`config/project.yaml` 还有 `<…>` 占位 / `data.root` 不是现有目录 ⇒ **只警告不失败**（不是错误，是还没填）
#   ⑧ 状态目录：`state/current.json` 不存在 ⇒ 提示跑 `runtime/state.py init`
#   ⑨ subagent：四个角色**没**装进 `${DSH_HOME:-$HOME/.dsh}/agents` ⇒ **只警告不失败**
#      （用法 A「一个主 Agent 扮四个角色」不需要装；用法 B「真派子代理」需要 ⇒ 见 PREREQUISITES.md §2.1）
#
# 退出码：0 全过｜2 有硬失败（fail-closed；逐项名字与 rc 打在 stderr）
set -uo pipefail

TARGET="${1:-}"
die() { echo "verify_install.sh：$*" >&2; exit 2; }
[ -n "$TARGET" ] || die "用法：bash deploy/verify_install.sh <目标目录>"
[ -d "$TARGET" ] || die "目标目录不存在：$TARGET"
# ★ 两件都必须在 `cd` **之前**算成绝对路径：否则用相对路径调用时
#   `$(dirname "$0")/..` 与 `$TARGET/...` 都会相对**新**工作目录解析 ⇒ 指错地方。
PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$(cd "$TARGET" && pwd)"
cd "$TARGET" || die "进不去 $TARGET"

FAIL=0
step() { # step <名字> <命令...>
  local name="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ "$rc" -eq 0 ]; then
    printf '  ✅ %-46s rc=0\n' "$name"
  else
    printf '  ❌ %-46s rc=%d\n' "$name" "$rc" >&2
    printf '%s\n' "$out" | tail -12 | sed 's/^/       /' >&2
    FAIL=1
  fi
}

echo "verify_install.sh：在 $TARGET 里自证（版本 $(cat VERSION 2>/dev/null || echo '?'))"

echo "① 依赖"
if python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)' 2>/dev/null; then
  printf '  ✅ %-46s %s\n' "python3 ≥ 3.8" "$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
else
  echo "  ❌ python3 版本低于 3.8（引擎要求 ≥ 3.8）" >&2; FAIL=1
fi
# ★ PyYAML 是**唯一**的第三方依赖，且是硬依赖（读 config/*.yaml 与 state/ 全靠它；没有回退）
if pyyaml_ver="$(python3 -c 'import yaml;print(yaml.__version__)' 2>/dev/null)"; then
  printf '  ✅ %-46s %s\n' "PyYAML（唯一第三方依赖）" "$pyyaml_ver"
else
  echo "  ❌ 缺 PyYAML：引擎读 config/*.yaml 全靠它，缺即 fail-closed" >&2
  echo "     处置：pip install pyyaml（或 conda install pyyaml）后重跑本脚本" >&2
  FAIL=1
fi

echo "② 出厂形态"
for d in devtools tests; do
  if [ -e "$TARGET/$d" ]; then
    echo "  ❌ $d/ 不该出现在出厂包里（它不随包分发）" >&2; FAIL=1
  else
    printf '  ✅ %-46s 不存在（正确）\n' "$d/"
  fi
done

echo "③ 开跑入口（0.18.0 起；只验语法与存在性，不跑）"
for f in scripts/preflight.sh scripts/start_experiment.sh; do
  if [ ! -f "$TARGET/$f" ]; then
    echo "  ❌ 缺 $f（0.18.0 起的开跑入口，出厂包必须有）" >&2; FAIL=1
  elif bash -n "$TARGET/$f" 2>/dev/null; then
    printf '  ✅ %-46s 存在且语法正确\n' "$f"
  else
    echo "  ❌ $f 语法错误（bash -n 不过）" >&2; FAIL=1
  fi
done

echo "④ 引擎自检"
for m in metrics validate_round executor resources; do
  step "runtime/$m.py --selftest" python3 "runtime/$m.py" --selftest
done
step "_common.sh lp_selftest" bash -c 'source runtime/_common.sh; lp_selftest'

echo "⑤ 契约加载"
step "config.py validate config/tasks/_TEMPLATE.yaml" python3 runtime/config.py validate config/tasks/_TEMPLATE.yaml

echo "⑥ 安装记录"
if [ -f "$TARGET/.lpta-install.tsv" ]; then
  n_rec="$(wc -l < "$TARGET/.lpta-install.tsv" | tr -d ' ')"
  n_man="$(wc -l < "$PKG_ROOT/MANIFEST.tsv" | tr -d ' ')"
  if [ "$n_rec" = "$n_man" ]; then printf '  ✅ %-46s %s 行\n' ".lpta-install.tsv 行数对得上" "$n_rec"
  else printf '  ❌ %-46s 记录 %s 行 ≠ 清单 %s 行\n' ".lpta-install.tsv 行数对不上" "$n_rec" "$n_man" >&2; FAIL=1; fi
elif [ -f "$TARGET/deploy/install.sh" ]; then
  # 还带着 deploy/ ⇒ 这是**刚解压、还没 install** 的原始包：没有记录是正常的（不算失败）
  echo "  ⚠ 还没装（包里还有 deploy/install.sh）⇒ 记录要等 install.sh 跑完才有；装过之后再跑本项"
else
  echo "  ❌ 找不到 .lpta-install.tsv（既没记录、又不像原始包：这个目录被谁动过？）" >&2; FAIL=1
fi

echo "⑦ 部署值（警告不算失败）"
# ★ 0.18.33（CR-0004）：`/data` **不是**"没填"的判据 —— 大盘真的挂在 `/data` 就是真值，
#   按它判会让这条警告恒红，于是真正该看的 `<…>` 也被一起忽略。
#   口径与 docs/CONFIG.md §3 一致：① 只有成对尖括号 `<…>` 算占位；② `data.root` 看目录在不在。
DEP_HITS="$(grep -nE '^\s*[A-Za-z_]+:\s*"?<[^>]+>' "$TARGET/config/project.yaml" 2>/dev/null || true)"
DATA_ROOT="$(python3 - "$TARGET/config/project.yaml" <<'PYROOT' 2>/dev/null || true
import sys, yaml
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception:
    sys.exit(0)
root = (doc.get("data") or {}).get("root")
print("" if root is None else str(root))
PYROOT
)"
if [ -n "$DEP_HITS" ]; then
  printf '%s\n' "$DEP_HITS" | sed 's/^/       /'
  echo "  ⚠ config/project.yaml 里还有 <…> 占位值（doc 见 docs/CONFIG.md §3）——**装完必须先填**"
fi
if [ -z "$DATA_ROOT" ]; then
  echo "  ⚠ config/project.yaml 里没有 data.root（大盘/产物根的根目录）——装完必须先填（docs/CONFIG.md §3）"
elif [ ! -d "$DATA_ROOT" ]; then
  echo "  ⚠ data.root=${DATA_ROOT} 指向的目录不存在 ⇒ 产物无处可落（docs/CONFIG.md §3）"
fi

echo "⑧ 状态目录"
if [ -f "$TARGET/state/current.json" ]; then printf '  ✅ %-46s 已初始化\n' "state/current.json"
else echo "  ⚠ state/ 未初始化 ⇒ 跑：cd $TARGET && python3 runtime/state.py init"; fi

echo "⑨ subagent（警告不算失败）"
AG_DIR="${DSH_HOME:-$HOME/.dsh}/agents"
ag_missing=""
for r in architect developer tester experimenter; do
  [ -f "$AG_DIR/$r.md" ] || ag_missing="$ag_missing $r"
done
if [ -z "$ag_missing" ]; then
  printf '  ✅ %-46s %s\n' "四个角色都装成了 subagent" "$AG_DIR"
else
  echo "  ⚠ 这四个角色**没**装成 DSH subagent：${ag_missing# }"
  echo "     · 用法 A（一个主 Agent 依次扮四个角色）⇒ **正常**，不用管；"
  echo "     · 用法 B（要 \`use_agent architect\` 派子代理）⇒ 跑下面这条，然后**重启 dsh**："
  echo "         bash deploy/install.sh $(printf '%q' "$TARGET") --with-agents"
  echo "     详见 PREREQUISITES.md §2.1。"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "verify_install.sh：✅ 全过 —— 引擎在这个容器里跑得起来"
else
  echo "verify_install.sh：❌ 有硬失败（见上）" >&2
fi
exit "$FAIL"
