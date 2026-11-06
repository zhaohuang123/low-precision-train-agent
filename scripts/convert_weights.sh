#!/usr/bin/env bash
# convert_weights.sh —— 训练起点权重转换：**HF → mcore**（幂等；目标已存在就不重复转换）
#
# 归属：0.18.9 起。配合任务配置的两个字段（**部署事实的唯一落点**都在那里）：
#   model.source.path          HF 原始权重目录（"从哪来"）
#   model.start.{format,path}  训练 `--load` 吃的那份（"这一轮用哪份"）
#   model.start.convert.*      仅当 format=mcore 且 path 还不存在时用（model_type_hf/tp/pp）
#
# 用法：
#   bash scripts/convert_weights.sh --task <任务名> [--root <配置根>] [--dry-run]
#                                    [--python <解释器>]
#
# 行为（每一行都是 fail-closed）：
#   1. `model.start.format != mcore` ⇒ 打印"不需要转换"并退出 0（起点就是 HF 或已就绪）。
#   2. 目标目录已存在 **且像一个 mcore 检查点** ⇒ 打印它的种类与迭代数后退出 0（**幂等**）。
#   3. 目标目录已存在但**不像** mcore 检查点 ⇒ 退出 2 并说明。★ 本脚本**从不删目录**：
#      "看起来像半成品"也可能是别人的产物，删不删由人决定（确认后手工删掉再跑）。
#   4. 目标不存在 ⇒ 用框架自带的 `convert_ckpt_v2.py`（`--load-model-type hf --save-model-type mg`）
#      转一次，然后**验产物**（只看退出码不够：转换是"命令成功但产物不对"的高发段）。
#
# 产物验证三条（缺一条就报不通过）：
#   ① `latest_checkpointed_iteration.txt` 存在，且值为 `1`（转换工具写死 1；训练产物是训到第几步）
#   ② `iter_*/mp_rank_*/*.pt` 至少一个且非空
#   ③ 产物总字节数 vs HF 权重总字节数在 ±10% 内（分片/并行方式不同会导致轻微差异）
#
# 退出码：0 成功（含"无需转换/已存在跳过"）｜2 前置条件或产物验证不过
set -euo pipefail

die() { echo "convert_weights.sh：$*" >&2; exit 2; }

task=""; root=""; dry=0; pyname="python3"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --task)     [[ $# -ge 2 ]] || die "--task 后面缺任务名"; task="$2"; shift 2 ;;
        --task=*)   task="${1#--task=}"; shift ;;
        --root)     [[ $# -ge 2 ]] || die "--root 后面缺配置根"; root="$2"; shift 2 ;;
        --root=*)   root="${1#--root=}"; shift ;;
        --python)   [[ $# -ge 2 ]] || die "--python 后面缺解释器"; pyname="$2"; shift 2 ;;
        --python=*) pyname="${1#--python=}"; shift ;;
        --dry-run)  dry=1; shift ;;
        -h|--help)  sed -n '2,29p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "不认识的参数：$1" ;;
    esac
done

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="${root:-$(cd "${here}/.." && pwd)}"
[[ -f "${root}/VERSION" && -f "${root}/config/project.yaml" ]] || die "不是工程根：${root}"
[[ -n "$task" ]] || die "用法：bash scripts/convert_weights.sh --task <任务名> [--dry-run]"

cfg="${root}/config/tasks/${task}.yaml"
[[ -f "$cfg" ]] || die "缺任务配置：${cfg}"

# ── 从任务配置取四件事（部署事实只认配置这一处）────────────────────────────
read_cfg() {
    "$pyname" - "$cfg" <<'PY'
import sys
try:
    import yaml
except ImportError:
    print("ERR\t需要 PyYAML 才能读任务配置")
    raise SystemExit(0)
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception as exc:  # noqa: BLE001
    print(f"ERR\t配置读不出来：{exc}")
    raise SystemExit(0)
model = doc.get("model") or {}
start = model.get("start") or {}
conv = start.get("convert") or {}
train = doc.get("train") or {}
vals = {
    "HF": (model.get("source") or {}).get("path") or "",
    "FMT": start.get("format") or "",
    "TARGET": start.get("path") or "",
    "MTYPE": conv.get("model_type_hf") or "",
    "TP": str(conv.get("tp") or 1),
    "PP": str(conv.get("pp") or 1),
    "REPO": train.get("framework_repo") or "",
}
for k, v in vals.items():
    print(f"{k}\t{v}")
PY
}
raw="$(read_cfg)"
grep -q $'^ERR\t' <<<"$raw" && die "$(grep -m1 $'^ERR\t' <<<"$raw" | cut -f2-)"
get() { grep -m1 "^$1	" <<<"$raw" | cut -f2-; }
HF="$(get HF)"; FMT="$(get FMT)"; TARGET="$(get TARGET)"
# ★ CR-0005（0.20.6）：**路径先归一再去尾斜杠**。否则 `dirname "<目标>/"` 退化成父目录，
#   而 `launch="${TARGET}.launch.txt"` 会落进**尚未存在**的目标目录 ⇒ tee 打不开 ⇒ 转换前 rc=1。
#   已存在的目标同样要归一（幂等判定与产品路径都不该因一个尾字符而变）。
while [[ "$TARGET" == */ && "$TARGET" != "/" ]]; do TARGET="${TARGET%/}"; done
HF="${HF%/}"; [[ -n "$HF" ]] || HF="/"
MTYPE="$(get MTYPE)"; TP="$(get TP)"; PP="$(get PP)"; REPO="$(get REPO)"

[[ -n "$FMT" ]] || die "配置里缺 model.start.format（hf|mcore）"
[[ -n "$TARGET" ]] || die "配置里缺 model.start.path（起点目录的绝对路径）"

if [[ "$FMT" != "mcore" ]]; then
    echo "[convert] 起点格式是 ${FMT} ⇒ 不需要 HF→mcore 转换（本脚本只做这一个方向）。"
    exit 0
fi

# ── 判定"目标是否已是可用的 mcore 检查点"（存在 ≠ 可用）──────────────────────
iter_value() { [[ -f "${1}/latest_checkpointed_iteration.txt" ]] && tr -d '[:space:]' < "${1}/latest_checkpointed_iteration.txt" || echo ""; }
has_pt() { compgen -G "${1}/iter_*/mp_rank_*/*.pt" >/dev/null 2>&1; }
bytes_of() {  # $1=glob
    local total=0 f
    while IFS= read -r f; do total=$(( total + $(stat -c %s "$f") )); done < <(compgen -G "$1" || true)
    echo "$total"
}

describe_ckpt() {  # 打印"转换产物/训练产物 + 迭代数"
    local d="$1" it; it="$(iter_value "$d")"
    if [[ "$it" == "1" ]]; then echo "iter=${it}（转换产物）"; else echo "iter=${it:-未知}（训练产物或异常）"; fi
}

if [[ -d "$TARGET" ]]; then
    if [[ -n "$(iter_value "$TARGET")" ]] && has_pt "$TARGET"; then
        echo "[convert] 目标已存在，**跳过转换**（幂等）：${TARGET}"
        echo "[convert]   种类：$(describe_ckpt "$TARGET")"
        exit 0
    fi
    die "目标目录存在但不像 mcore 检查点：${TARGET}
  （缺 latest_checkpointed_iteration.txt 或没有 iter_*/mp_rank_*/*.pt）
  ⇒ 半成品/别的格式。确认后手工删掉再跑；本脚本从不替你删。"
fi

# ── 前置：HF 源、框架转换工具、型号 ────────────────────────────────────────
[[ -n "$HF" ]] || die "配置里缺 model.source.path（HF 原始权重目录）"
[[ -f "${HF}/config.json" ]] || die "HF 权重目录不完整（没有 config.json）：${HF}"
REPO="${REPO:-$( [[ -d "${root}/../MindSpeed-LLM" ]] && cd "${root}/../MindSpeed-LLM" && pwd || true )}"
[[ -n "$REPO" && -d "$REPO" ]] || die "取不到 train.framework_repo（框架检出），转换工具在它下面"
[[ -f "${REPO}/convert_ckpt_v2.py" ]] || die "框架检出里没有 convert_ckpt_v2.py：${REPO}（不是 MindSpeed-LLM 检出？）"
[[ -n "$MTYPE" ]] || die "缺 model.start.convert.model_type_hf（框架的 --model-type-hf，如 qwen3）
  ★ 不许猜：写错型号会转出一份"看着正常"的错误权重。"

launch="${TARGET}.launch.txt"
log="${TARGET}.convert.log"

if [[ "$dry" == "1" ]]; then
    echo "[dry-run] 将执行："
    echo "  cd ${REPO} && ${pyname} convert_ckpt_v2.py \\"
    echo "      --load-model-type hf --save-model-type mg \\"
    echo "      --target-tensor-parallel-size ${TP} --target-pipeline-parallel-size ${PP} \\"
    echo "      --load-dir ${HF} --save-dir ${TARGET} --model-type-hf ${MTYPE}"
    echo "[dry-run] 日志 ${log}；执行记录 ${launch}"
    exit 0
fi

# ── 转 ──────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$TARGET")"
{
    echo "[convert] $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[convert] load   = ${HF}"
    echo "[convert] save   = ${TARGET}"
    echo "[convert] model  = ${MTYPE}  tp/pp = ${TP}/${PP}"
    echo "[convert] repo   = ${REPO}"
} | tee "$launch"

set +e
( cd "$REPO" && "$pyname" convert_ckpt_v2.py \
    --load-model-type hf \
    --save-model-type mg \
    --target-tensor-parallel-size "$TP" \
    --target-pipeline-parallel-size "$PP" \
    --load-dir "$HF" \
    --save-dir "$TARGET" \
    --model-type-hf "$MTYPE" ) > "$log" 2>&1
rc=$?
set -e
if [[ "$rc" -ne 0 ]]; then
    echo "convert_weights.sh：转换命令退出 ${rc}（日志尾部见下，完整日志 ${log}）" >&2
    tail -n 15 "$log" | sed 's/^/    /' >&2
    exit 2
fi

# ── 验产物（三条）──────────────────────────────────────────────────────────
it="$(iter_value "$TARGET")"
[[ "$it" == "1" ]] || die "产物验证失败：latest_checkpointed_iteration.txt 应为 1，实际 '${it:-缺失}'
  转换工具写死 1；不是 1 ⇒ 这不是转换产物（目录里有别的东西？）"
has_pt "$TARGET" || die "产物验证失败：${TARGET} 下没有 iter_*/mp_rank_*/*.pt"

hf_bytes="$(bytes_of "${HF}/model*.safetensors")"
mc_bytes="$(bytes_of "${TARGET}/iter_*/mp_rank_*/*.pt")"
[[ "$hf_bytes" -gt 0 ]] || die "HF 侧没有 model*.safetensors ⇒ 源目录不是 HF safetensors 格式：${HF}"
ratio="$( "$pyname" -c "print(f'{$mc_bytes/$hf_bytes:.3f}')" )"
ok="$("$pyname" -c "print(1 if 0.9 <= $mc_bytes/$hf_bytes <= 1.1 else 0)")"
[[ "$ok" == "1" ]] || die "产物验证失败：产物 ${mc_bytes} B vs HF ${hf_bytes} B（比值 ${ratio}，允许 0.90–1.10）
  ⇒ 多半是转换中途断了或型号写错。日志：${log}"

echo
echo "[convert] ✓ 转换完成并验过：${TARGET}"
echo "[convert]   种类：$(describe_ckpt "$TARGET")"
echo "[convert]   体积：mcore ${mc_bytes} B ＝ HF ${hf_bytes} B × ${ratio}"
echo "[convert]   记录：${launch}"
echo "[convert]   日志：${log}"
echo "[convert] ⇒ 目标已存在，**下次再跑本脚本会直接跳过**（幂等）。"
