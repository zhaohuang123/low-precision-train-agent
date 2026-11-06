#!/usr/bin/env bash
# start_experiment.sh —— **开跑的唯一入口**（preflight → 建轮次目录 → 告诉你该派谁）
#
# 归属：0.18.0 起（AGENTS.md §4.1「编排」的机械部分）。
#
# ★ 本文件**不派 agent**：派谁、怎么派是模型的判断（见 AGENTS.md §4.1），塞进脚本就等于又写一个引擎。
#   它只把"开跑前必须准备好的东西"准备好，并打印下一步该派谁。
# ★ 轮次目录**只有这里会建**（引擎其余部分从不自建轮次目录）：所以跳过本脚本就没法开跑 ——
#   不是靠提示词自觉，是靠"目录不存在，后面每一步都拒绝"。
#
# 用法：
#   bash scripts/start_experiment.sh <任务名> [轮次] [--skip-preflight] [--force]
#   轮次缺省 = 与 state 当前轮次一致（没有就 R-0001）。
#   退出 0 = 准备好（打印下一步）；退出 2 = 没准备好（preflight 不过／轮次目录已存在且非空）。
set -u

TASK="${1:-}"
[[ -n "$TASK" ]] || { echo "用法：bash scripts/start_experiment.sh <任务名> [轮次] [--skip-preflight] [--force]" >&2; exit 2; }
shift
ROUND=""; SKIP_PF=0; FORCE=0
for a in "$@"; do
  case "$a" in
    --skip-preflight) SKIP_PF=1 ;;
    --force)          FORCE=1 ;;
    -*) echo "start_experiment.sh：不认的参数 $a" >&2; exit 2 ;;
    *)  ROUND="$a" ;;
  esac
done

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
export LP_ROOT="$ROOT"

# ── 1. preflight ──────────────────────────────────────────────────────────────
if [[ "$SKIP_PF" == "1" ]]; then
  echo "[preflight] 已按 --skip-preflight 跳过（**不建议**：钉点/卡/环境都没查）"
else
  echo "[preflight]"
  bash "$ROOT/scripts/preflight.sh" "$TASK" || { echo "[start] preflight 不过 ⇒ 不建目录、不开跑" >&2; exit 2; }
fi

# ── 2. 轮次：缺省沿用 state 的当前轮次 ────────────────────────────────────────
if [[ -z "$ROUND" ]]; then
  ROUND="$(python3 - "$ROOT/state/current.json" "$TASK" <<'PY'
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
if p.is_file():
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("task_id") == sys.argv[2] and d.get("round"):
            print(d["round"]); raise SystemExit
    except SystemExit:
        raise
    except Exception:
        pass
print("R-0001")
PY
)"
fi
[[ "$ROUND" =~ ^R-[0-9]{4}$ ]] || { echo "轮次必须形如 R-0001（收到 $ROUND）⇒ 退出 2" >&2; exit 2; }

# ── 3. state（config_version 在这里钉住）──────────────────────────────────────
python3 "$ROOT/runtime/state.py" init --task "$TASK" --round "$ROUND" >/dev/null || {
  echo "[start] state.py init 失败 ⇒ 退出 2（状态机没过就不开跑）" >&2; exit 2; }
echo "[state]  current.json 已就绪（$TASK / $ROUND）"

# ── 4. 轮次目录：本工程**唯一**会建它的地方 ──────────────────────────────────
ART="$(python3 - "$ROOT" "$TASK" <<'PY'
import subprocess, sys, tempfile, json, os, pathlib
root, task = sys.argv[1], sys.argv[2]
out = tempfile.mktemp()
r = subprocess.run([sys.executable, f"{root}/runtime/config.py", "resolve-scheme",
                    f"{root}/config/tasks/{task}.yaml", "--out", out],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.stderr.write(r.stdout + r.stderr); raise SystemExit(2)
d = json.load(open(out, encoding="utf-8")); os.unlink(out)
v = (d.get("resolved") or {}).get("artifacts.root") or {}
print(v.get("value") or "")
PY
)"
[[ -n "$ART" ]] || { echo "[start] 解析不出 artifacts.root ⇒ 退出 2" >&2; exit 2; }
case "$ART" in /*) RDIR="$ART/rounds/$ROUND" ;; *) RDIR="$ROOT/$ART/rounds/$ROUND" ;; esac

if [[ -d "$RDIR" && -n "$(ls -A "$RDIR" 2>/dev/null)" && "$FORCE" != "1" ]]; then
  echo "[start] 轮次目录已存在且非空：$RDIR" >&2
  echo "        轮次目录一经冻结就不再改（要重开请用 --force，或换一个轮次号）⇒ 退出 2" >&2
  exit 2
fi
mkdir -p "$RDIR/patches" "$RDIR/sets"
for f in design.md criterion.yaml; do
  [[ -e "$RDIR/$f" ]] || cp "$ROOT/templates/$f" "$RDIR/$f"
done
echo "[round]   $RDIR（design.md / criterion.yaml 已从 templates 复制空壳）"

# ── 5. 打印下一步（派 agent 是主 Agent 的活，不是本脚本的）────────────────────
STAGE="$(python3 -c "import json;print(json.load(open('$ROOT/state/current.json'))['stage'])" 2>/dev/null || echo architect)"
NEXT="$(python3 -c "import json;print(json.load(open('$ROOT/state/current.json')).get('next_action',''))" 2>/dev/null || true)"
cat <<EOF

[start] 准备好了。下一步（**由主 Agent 执行**，本脚本不派 agent）：
  stage = $STAGE
  next  = $NEXT

  派法（按 AGENTS.md §4.1）：
    use_agent <角色> "任务 $TASK，轮次 $ROUND，按 agents/<角色>/AGENT.md 干活"
  （角色名以你装的那套为准：安装器默认装成 architect／developer／tester／experimenter；
    若你的注册表里给了前缀，按实际名字替换 —— 名字来自 AGENT.md 的 frontmatter 的 name 字段）
  子代理交回 TOKEN 后：
    python3 runtime/state.py advance --handoff <TOKEN>

  冻结判据是**人的闸门**：architect 出完 criterion.yaml 后，**必须问人**"就按这个判吗"，人点头才进 developer。
EOF
