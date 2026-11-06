#!/usr/bin/env bash
# ── 骨架（无型号）────────────────────────────────────────────────────────────
# 照抄到 `<任务目录>/commands/` 后：① 把每个 `<...>` 换成真值 ② 把 `# <占位>` 的段落填上。
# 未替换的占位一律**当场拒绝**（fail-closed），不会带着占位去起作业。
# ─────────────────────────────────────────────────────────────────────────
# eval_cmd.sh —— **真评测命令形状**（**骨架**；照抄到 <任务目录>/commands/ 后替换占位）
#
# 归属：评测命令（场景参数只从任务配置取）＋ 技能 `eval-lm-eval`。
#
# 命令形状（来自早先实测的评测脚本，建设者侧只读材料，不随包；下称 `[E]`）：
#   · `[E]` 的 SHARD_ARGV —— 验过的 lm_eval argv（本任务**逐项**照抄，形状即
#     `drivers/lm_eval_driver.py` 的 `build_shard_argv()`）：
#       `--model hf --model_args pretrained=<HF 目录>,dtype=<dtype>,trust_remote_code=True,enable_thinking=False
#        --apply_chat_template --fewshot_as_multiturn --tasks <集1,集2> --num_fewshot <n>
#        --batch_size <n> --device <设备> --gen_kwargs max_gen_toks=<n> --output_path <结果>
#        --log_samples [--limit <n> | --samples '{"<task>": [...]}'] [EXTRA...]`
#   · `[E]` 的纪律：`LP_LMEVAL_SHARDS` 必须显式（不按卡数兜底）；分片索引轮转发牌。
#   · 解释器/驱动的唯一落点是任务配置的 `eval.lm_eval.{python,driver}`（不是本文件写死）。
#
# 与 `<另一个任务目录>/commands/eval_cmd.sh` 的**唯一差别**（两处，都是"把旧件真读的项也传下去"）：
#   ① 多传 `--dataset`（逗号分隔多集）与 `--protocols-json`（逐集生效口径）—— 口径事实，进口径清单；
#   ② 多传 `--harness-version` / `--cards` / `--shards` / `--num-samples` / `--eval-full`
#      （旧件里就是这几项），
#      **空值一律不传**（空串会被 argparse 当成"缺参数"⇒ 误报 2）。
#
# 口径的**唯一落点**是任务配置 `eval.protocol.*` ＋ `<轮次>/criterion.yaml` 的 `eval_protocol.*`；
# 本文件只把两边读到的值**拼进 argv**，不定义口径、不设默认值（缺一项 ⇒ 退出 2）。
#
# 用法：
#   bash <任务目录>/commands/eval_cmd.sh --print   # 只打印拼装出的 argv（本工程**从未真跑**）
#   bash <任务目录>/commands/eval_cmd.sh           # 真评测（会占卡；本工程从未执行过这条路径）
#
# 退出码：0 成功（或 --print 打印完）｜2 参数/配置/占位值问题（fail-closed 拒绝拼装）
set -euo pipefail

: "${LP_ROOT:?eval_cmd.sh 由三段入口调用时 LP_ROOT 一定存在；手工跑请先 export LP_ROOT=<工程根>}"
: "${LP_TASK_ID:?同上：LP_TASK_ID（任务名）}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_taskcfg.sh
source "${HERE}/_taskcfg.sh"

# 参数：`--print`／`--dry-run`（位置任意）、`--run`（忽略）、其余＝**轮次追加片段**。
# 三段的解析与"不许改的项"都在 _stage_args.sh 一处（0.18.29），模板里不再各写一份。
# shellcheck source=_stage_args.sh
source "${HERE}/_stage_args.sh"
lp_stage_args eval "$@" || exit 2

# 解释器：`LP_EVAL_PYTHON`（人临时覆盖）优先，否则读任务配置 `eval.lm_eval.python`
# —— 配置是该字段的唯一落点（venv 落点由它推出，见 docs/decisions/D-0002）。
py="${LP_EVAL_PYTHON:-}"
if [[ -z "$py" ]]; then
  py="$(taskcfg_value eval.lm_eval.python "评测 venv 的解释器（venv 落点由它推出，见 docs/decisions/D-0002）")"
else
  echo "[eval_cmd] 用环境变量里的 LP_EVAL_PYTHON=${py} 覆盖任务配置的解释器（优先级：环境变量 > 配置）" >&2
fi
driver_rel="$(taskcfg_value eval.lm_eval.driver "评测驱动（住在任务目录，接口见 drivers/README.md）")"
# ── 评测场景：从任务配置**一次**读出「多数据集 ＋ 逐集生效口径」──────────────────
#   唯一读者就在这一处：驱动**不读配置**（只吃 --tasks／--dataset／--protocols-json）。
#   生效口径 = `eval.protocol`（全局默认）⊕ 该集 `eval.datasets[].protocol`（逐键覆盖）；
#   覆盖写 `null` = **显式清空继承**（例：把 max_gen_toks 清掉 ⇒ 该集走 loglikelihood 口径）。
scene="$(python3 - "${LP_ROOT}/config/tasks/${LP_TASK_ID}.yaml" <<'PYSCENE'
import json, sys
import yaml
cfg = (yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}).get("eval") or {}
glob = cfg.get("protocol") or {}
gtype = cfg.get("task_type")
names, paths, protos = [], [], {}
for b in (cfg.get("datasets") or []):
    if not isinstance(b, dict) or not str(b.get("name") or "").strip():
        continue
    name = str(b["name"]).strip()
    eff = dict(glob)
    for k, v in (b.get("protocol") or {}).items():
        if v is None:
            eff.pop(k, None)
        else:
            eff[k] = v
    names.append(name)
    if b.get("path"):
        paths.append(str(b["path"]))
    protos[name] = {"task_type": (b.get("task_type") or gtype),
                    "num_fewshot": eff.get("num_fewshot"),
                    "max_gen_toks": eff.get("max_gen_toks"),
                    "batch_size": eff.get("batch_size"),
                    "prompt_type": eff.get("prompt_type")}
print(",".join(names))
print(",".join(paths))
print(json.dumps(protos, ensure_ascii=False, separators=(",", ":")))
PYSCENE
)" || { echo "[eval_cmd] ✗ 读不出 eval.datasets ⇒ 退出 2（命令形状不许猜）" >&2; exit 2; }
tasks="$(printf '%s\n' "$scene" | sed -n 1p)"
dataset="$(printf '%s\n' "$scene" | sed -n 2p)"
protocols="$(printf '%s\n' "$scene" | sed -n 3p)"
[[ -n "$tasks" ]] || { echo "[eval_cmd] ✗ eval.datasets 里没有可用的 name ⇒ 退出 2" >&2; exit 2; }
# 这三项是**全局默认**口径：缺省就不传（每集的生效值由 --protocols-json 给出，驱动逐组校验）。
nfew="$(taskcfg_get eval.protocol.num_fewshot 2>/dev/null || true)"
max_gen="$(taskcfg_get eval.protocol.max_gen_toks 2>/dev/null || true)"
batch="$(taskcfg_get eval.protocol.batch_size 2>/dev/null || true)"
hver="$(taskcfg_get eval.lm_eval.version 2>/dev/null || true)"            # 只记录
# ★ CR-0004（0.20.6）：本地数据集（无网／用仓库自带 task yaml）必须把目录传给 lm_eval，
#   否则它只认 Hub 上的任务名 ⇒ 离线机器必炸 ConnectionError。相对路径按**配置根**解析。
incp="$(taskcfg_get eval.lm_eval.include_path 2>/dev/null || true)"
if [[ -n "$incp" && "$incp" != /* ]]; then incp="${LP_ROOT}/${incp}"; fi

# 驱动路径相对**配置根**解析（与 config.py 的路径纪律一致：相对路径不相对当前目录）。
case "$driver_rel" in
  /*) driver="$driver_rel" ;;
  *)  driver="${LP_ROOT}/${driver_rel}" ;;
esac

work="${LP_WORK_DIR:-${LP_ROOT}/experiments/${LP_TASK_ID}}"
model="${LP_EVAL_MODEL:-${work}/rounds/${LP_ROUND:-<轮次>}/hf}"
out="${LP_EVAL_OUT:-${LP_EV:-${work}/rounds/${LP_ROUND:-<轮次>}/evidence}/eval_target.json}"
dtype="${LP_EVAL_DTYPE:-bfloat16}"
device="${LP_EVAL_DEVICE:-npu}"

cmd="${py} ${driver} --model ${model} --tasks ${tasks}"
# 全局默认口径：缺省不传（生效值由 --protocols-json 逐集给，驱动逐组校验非空）
[[ -n "$nfew" ]]    && cmd="${cmd} --num_fewshot ${nfew}"
[[ -n "$max_gen" ]] && cmd="${cmd} --max_gen_toks ${max_gen}"
[[ -n "$batch" ]]   && cmd="${cmd} --batch_size ${batch}"
cmd="${cmd} --output_path ${out}"
cmd="${cmd} --dtype ${dtype} --device ${device}"
[[ -n "$protocols" ]]      && cmd="${cmd} --protocols-json '${protocols}'"   # 多数据集逐集口径
# ── 以下全部"有值才传"（出处见文件头；空值传下去会被 argparse 当成缺参数 ⇒ 误报 2）──
[[ -n "$dataset" ]]              && cmd="${cmd} --dataset ${dataset}"                 # [E]:71/84
[[ -n "$incp" ]]                 && cmd="${cmd} --include-path '${incp}'"             # CR-0004：本地 task yaml/数据目录
[[ -n "$hver" ]]                 && cmd="${cmd} --harness-version ${hver}"            # [E]:86-91
[[ -n "${LP_CARDS:-}" ]]         && cmd="${cmd} --cards ${LP_CARDS}"                  # [E]:167
[[ -n "${LP_LMEVAL_SHARDS:-}" ]]     && cmd="${cmd} --shards ${LP_LMEVAL_SHARDS}"           # [E]:161-166
[[ -n "${LP_LMEVAL_NUM_SAMPLES:-}" ]] && cmd="${cmd} --num-samples ${LP_LMEVAL_NUM_SAMPLES}" # [E]:185
[[ -n "${LP_EVAL_FULL:-}" ]]     && cmd="${cmd} --eval-full ${LP_EVAL_FULL}"          # [E]:118
cmd="$(lp_stage_append "$cmd")"   # 轮次追加片段落到命令末尾（没片段时原样不动）

if [[ "$PRINT" == "1" ]]; then
  echo "[print] 评测命令**拼装结果**（未执行、未占卡）："
  echo "  ${cmd}"
  lp_stage_print_note
  echo "[print] 口径来源：${LP_ROOT}/config/tasks/${LP_TASK_ID}.yaml 的 eval.*（逐项与 <轮次>/criterion.yaml 的 eval_protocol.* 对账）"
  exit 0
fi

[[ -f "$driver" ]] || { echo "评测驱动不存在：${driver}（eval.lm_eval.driver = ${driver_rel}）⇒ 退出 2。" >&2; exit 2; }
[[ -x "$py" || -f "$py" ]] || { echo "评测解释器不存在：${py} ⇒ 退出 2（先跑 scripts/install_env.sh 建 venv）。" >&2; exit 2; }
echo "[eval_cmd] py=${py} tasks=${tasks} → ${out}" >&2
exec bash -c "$cmd"
