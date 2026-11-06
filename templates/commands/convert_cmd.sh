#!/usr/bin/env bash
# ── 骨架（无型号）────────────────────────────────────────────────────────────
# 照抄到 `<任务目录>/commands/` 后：① 把每个 `<...>` 换成真值 ② 把 `# <占位>` 的段落填上。
# 未替换的占位一律**当场拒绝**（fail-closed），不会带着占位去起作业。
# ─────────────────────────────────────────────────────────────────────────
# convert_cmd.sh —— **真转换命令形状**（**骨架**；照抄到 <任务目录>/commands/ 后替换占位）
#
# 归属：转换命令（任务目录的命令形状；场景参数只从任务配置取）。
#
# 命令形状（来自早先实测的转换脚本，建设者侧只读材料，不随包）：
#   · 验过的形状（② 转换段，
#     mcore → HF：评测侧要读 HF 目录）：
#       `cd <REPO_ROOT>; python3 convert_ckpt_v2.py --load-model-type mg --save-model-type hf \
#          --model-type-hf <hf 型号> --target-tensor-parallel-size <tp> --target-pipeline-parallel-size <pp> \
#          --load-dir <mcore> --save-dir <hf> --hf-cfg-dir <原 HF 配置目录>`
#   · 同一脚本里记着一个坑（**搬结论**）：训练侧写下的**旋转凭据**必须随权重一起搬到 HF 目录，
#     而「本臂要不要旋转」的唯一来源是**轮级声明**，不是训练进程里的派生值（派生值转换进程继承不到
#     ⇒ 会静默不搬凭据，等到评测入口的闸门处才拒跑）。本工程的判据字段里还没有这一项 ⇒
#     见文件末的 `TODO(P4f)`，**本文件不假装已经实现它**。
#
# 用法：
#   bash <任务目录>/commands/convert_cmd.sh --print   # 只打印拼装出的 argv（本工程 P4d **从未真跑**）
#   bash <任务目录>/commands/convert_cmd.sh           # 真转换（纯 CPU/磁盘；本工程从未执行过这条路径）
#
# 退出码：0 成功（或 --print 打印完）｜2 参数/配置/占位值问题（fail-closed 拒绝拼装）
set -euo pipefail

: "${LP_ROOT:?convert_cmd.sh 由三段入口调用时 LP_ROOT 一定存在；手工跑请先 export LP_ROOT=<工程根>}"
: "${LP_TASK_ID:?同上：LP_TASK_ID（任务名）}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_taskcfg.sh
source "${HERE}/_taskcfg.sh"

# 参数：`--print`／`--dry-run`（位置任意）、`--run`（忽略）、其余＝**轮次追加片段**。
# 三段的解析与"不许改的项"都在 _stage_args.sh 一处（0.18.29），模板里不再各写一份。
# shellcheck source=_stage_args.sh
source "${HERE}/_stage_args.sh"
lp_stage_args convert "$@" || exit 2

repo="$(taskcfg_value train.framework_repo "转换工具 convert_ckpt_v2.py 所在的检出")"
model_path="$(taskcfg_get model.source.path 2>/dev/null || true)"
[[ -n "$model_path" ]] || { echo "任务配置里取不到 model.source.path ⇒ 退出 2（没有要转的起点）。" >&2; exit 2; }
# ── `--hf-cfg-dir`：目标目录里必须有 `config.json`，否则**产物缺配置文件而 rc 还是 0** ──
# 为什么改（0.18.29 / R-03）：旧默认 `dirname(model_path)` 在"model.source.path 就是 HF 目录本身"
# 时给出**父目录**，而框架 `copy_hf_cfg` 只在目录**不存在**时才抛，正则命中 0 个也照常返回 ⇒
# 转换 rc=0、产物缺 config.json，一路坏到评测段才以"评测侧无效"的面目炸出来（归因完全错位）。
if [[ -n "${LP_HF_CFG_DIR:-}" ]]; then
  hf_cfg_dir="${LP_HF_CFG_DIR}"
elif [[ -f "${model_path}/config.json" ]]; then
  hf_cfg_dir="${model_path}"                 # 源路径本身就是 HF 目录
else
  hf_cfg_dir="$(dirname "${model_path}")"    # 源路径是权重文件 ⇒ 取所在目录
fi
if [[ ! -d "${hf_cfg_dir}" ]]; then
  echo "convert_cmd.sh：配置目录不存在：${hf_cfg_dir} ⇒ 退出 2" >&2
  echo "  来源：${LP_HF_CFG_DIR:+LP_HF_CFG_DIR}${LP_HF_CFG_DIR:-按 model.source.path 推得}" >&2
  exit 2
fi
if [[ ! -f "${hf_cfg_dir}/config.json" ]]; then
  echo "convert_cmd.sh：${hf_cfg_dir} 里没有 config.json ⇒ 退出 2（**不许**转换出缺配置的产物）" >&2
  echo "  model.source.path = ${model_path}（来源：任务配置 model 块）" >&2
  echo "  ⇒ HF 目录请填 model.source.path 本身；要另指配置目录，用 LP_HF_CFG_DIR 显式指定。" >&2
  exit 2
fi
backend="${LP_CPT_BACKEND:-python3}"

# 落点：转换产物落在**本轮**的工作目录下（不是轮次目录里 —— 轮次目录只放输入与档案）。
work="${LP_WORK_DIR:-${LP_ROOT}/experiments/${LP_TASK_ID}}"
load_dir="${LP_CONVERT_IN:-${work}/rounds/${LP_ROUND:-<轮次>}/ckpt}"
save_dir="${LP_CONVERT_OUT:-${work}/rounds/${LP_ROUND:-<轮次>}/hf}"
tp="${LP_TP:-1}"          # 旧 mcore2hf 脚本默认 1/1（单机更好调）
pp="${LP_PP:-1}"
model_type_hf="${LP_MODEL_TYPE_HF:-qwen3}"   # 旧脚本的 `MODEL_TYPE_HF` 默认值

cmd="${backend} convert_ckpt_v2.py"
cmd="${cmd} --load-model-type mg --save-model-type hf"
cmd="${cmd} --model-type-hf ${model_type_hf}"
cmd="${cmd} --target-tensor-parallel-size ${tp} --target-pipeline-parallel-size ${pp}"
cmd="${cmd} --load-dir ${load_dir} --save-dir ${save_dir} --hf-cfg-dir ${hf_cfg_dir}"
cmd="$(lp_stage_append "$cmd")"
# `train.extra_pythonpath[]` ⇒ PYTHONPATH 前缀（唯一落点；**eval 段不拼**，见 docs/CONFIG.md）
# 没配 ⇒ 一个字都不加（不造空 PYTHONPATH：空值等于把当前目录塞进 sys.path）。
py_extra="$(taskcfg_extra_pythonpath)" || exit 2
if [[ -n "$py_extra" ]]; then
  # 我们给的目录优先（顺序＝sys.path 顺序）；原有 PYTHONPATH 接在后面，不覆盖。
  cmd="PYTHONPATH=${py_extra}${PYTHONPATH:+:${PYTHONPATH}} ${cmd}"
fi
   # 轮次追加片段落到命令末尾（没片段时原样不动）

TODO_NOTE="TODO(P4f)：旋转凭据随权重一起搬（旧 convert_ckpt_qwen3_4b_mcore2hf.sh:75- 的坑）本工程还没实现 —— 判据里没有「本臂要不要旋转」的轮级声明字段，故本脚本**不**造空凭据、也不假装搬过。"

if [[ "$PRINT" == "1" ]]; then
  echo "[print] 转换命令**拼装结果**（未执行）："
  echo "  cd ${repo} && ${cmd}"
  # 只作人读对账：真正的硬判据是上面"必须有 config.json"（不把框架正则抄成契约，免得它一改我们就误报）
  _hf_n="$(python3 - "${hf_cfg_dir}" <<'PYHF'
import os, re, sys
pat = re.compile(r'^(?:.*\.json|.*\.model(?:\.[\w\d]+)?|.*\.jinja|merges\.txt|'
                 r'(?:modeling|configuration|tokenization)_[\w_]+\.py|sample_finetune\.py)$')
d = sys.argv[1]
print(sum(1 for f in os.listdir(d)
          if pat.match(f) and os.path.isfile(os.path.join(d, f))))
PYHF
  )" 2>/dev/null || _hf_n="?"
  echo "  配置目录        ${hf_cfg_dir}（将随检出 ${_hf_n} 个文件）"
  lp_stage_print_note
  echo "[print] 说明：${TODO_NOTE}"
  exit 0
fi

echo "[convert_cmd] repo=${repo} ${load_dir} -> ${save_dir}（tp/pp=${tp}/${pp}）" >&2
cd "$repo"
exec bash -c "$cmd"
