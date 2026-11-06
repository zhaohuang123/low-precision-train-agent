#!/usr/bin/env bash
# init_task_dir.sh —— 一条命令建出 `<任务目录>/` 的骨架（引擎件的机械拷贝，不含任何任务取值）
#
# 归属：0.18.8 起。它替掉的是"手工 cp 七八次、每次都记不全"。
#
# 用法：
#   bash scripts/init_task_dir.sh <任务名> [--root <配置根>] [--refresh-scripts]
#     --refresh-scripts：把 <任务目录>/{train,convert,eval}.sh **覆盖**成当前模板的一份
#                        （升级后对齐三段入口用；只这三份，别的文件一律不动）
#
# 前提：`config/tasks/<任务名>.yaml` 已存在（本脚本**不替人建任务配置**：模型/精度/口径是人的输入）。
#
# 它拷的每一份都是**引擎件**（`templates/` 里与任务目录里逐字相同，不含任何任务取值）：
#   train.sh / convert.sh / eval.sh          三段入口
#   run.env                                  变量与命令落点（占位，必须人填）
#   commands/{_taskcfg,train_cmd,convert_cmd,eval_cmd}.sh ＋ train_argv.txt
#   commands/{validate_design.sh,eval_protocol_gate.sh}   两个闸门
#   drivers/lm_eval_driver.py                评测驱动
#   sets/README.md                           清单格式指针
#
# 它**不填**三样东西（那是任务事实，填错是静默跑错，必须人/developer 来填）：
#   ① `commands/train_argv.txt` 的模型几何  ② `sets/<集合名>.txt` 的题单  ③ `run.env` 的三条 `LP_*_CMD`
#
# 幂等且不破坏：目标目录已存在时**只补缺失件**，已存在的文件一律不动。
# 退出码：0 成功（含"只补了缺失件"）｜2 用法/前提不满足
set -euo pipefail

die() { echo "init_task_dir.sh：$*" >&2; exit 2; }

task=""
root=""
REFRESH_SCRIPTS=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --root)   [[ $# -ge 2 ]] || die "--root 后面缺配置根"; root="$2"; shift 2 ;;
        --root=*) root="${1#--root=}"; shift ;;
        --refresh-scripts) REFRESH_SCRIPTS=1; shift ;;
        -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) die "不认识的参数：$1" ;;
        *)  [[ -z "$task" ]] || die "只接受一个任务名（多给了：$1）"; task="$1"; shift ;;
    esac
done

[[ -n "$task" ]] || die "用法：bash scripts/init_task_dir.sh <任务名> [--root <配置根>]"

# 任务名要同时能当目录名和 `config/tasks/<任务名>.yaml` 的文件名 ⇒ 不许有分隔符、不许 . / ..
[[ "$task" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "任务名不合法：${task}（只许字母数字和 . _ -，且不以符号开头）"
[[ "$task" != *..* ]] || die "任务名不许含 .."

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="${root:-$(cd "${here}/.." && pwd)}"
[[ -d "$root" ]] || die "配置根不存在：${root}"
[[ -f "${root}/VERSION" && -f "${root}/config/project.yaml" ]] || die "不是工程根：${root}（差 VERSION 或 config/project.yaml）"

# 任务配置必须在：没有它，后面 `_common.sh` 读不到任何取值（早失败胜过跑一半）
task_cfg="${root}/config/tasks/${task}.yaml"
if [[ ! -f "$task_cfg" ]]; then
    die "缺任务配置 ${task_cfg}
  先照模板建一份：cp ${root}/config/tasks/_TEMPLATE.yaml ${task_cfg}，填完再跑本脚本。
  （模型/精度/评测口径是**人的输入**，本脚本不替人猜。）"
fi

# 任务目录落在哪：`paths.experiments`（config/project.yaml）；读不出来就退回 `experiments`
experiments_rel="$(python3 - "$root/config/project.yaml" <<'PY' 2>/dev/null || true
import sys
try:
    import yaml
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
    print(((doc.get("paths") or {}).get("experiments") or "experiments").rstrip("/"))
except Exception:
    print("experiments")
PY
)"
[[ -n "$experiments_rel" ]] || experiments_rel="experiments"
task_dir="${root}/${experiments_rel}/${task}"

created=0
skipped=0

# put <源文件> <目标文件>：目标已存在就不动它（幂等，绝不用模板覆盖人改过的东西）
put() {
    local src="$1" dst="$2"
    [[ -f "$src" ]] || die "模板缺件：${src}（工程不完整）"
    if [[ -e "$dst" ]]; then
        echo "  已存在，跳过  ${dst#"${root}"/}"
        skipped=$((skipped + 1))
    else
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        case "$dst" in *.sh|*.py) chmod +x "$dst" ;; esac
        echo "  新建          ${dst#"${root}"/}"
        created=$((created + 1))
    fi
}

echo "[init] 任务 ${task} → ${task_dir}"

put "${root}/templates/task/train.sh"   "${task_dir}/train.sh"
put "${root}/templates/task/convert.sh" "${task_dir}/convert.sh"
put "${root}/templates/task/eval.sh"    "${task_dir}/eval.sh"

# --refresh-scripts：三段入口在模板里就是"与任务目录逐字相同"的引擎件，人本来就不该改它们。
# `put` 的语义是"已存在就跳过"，于是**升级后旧入口脚本会一直留在原地** —— 0.18.38 修
# `eval.sh` 的训练观察门（读 stop_kind）就是这一类：只改模板，已建好的任务目录改不到。
# 所以给一条显式覆盖路径；只覆盖这三份，run.env / commands / sets 一个字都不碰。
if [[ "$REFRESH_SCRIPTS" == "1" ]]; then
    echo "[refresh-scripts] 用当前模板覆盖三段入口（只这三份）"
    for _s in train convert eval; do
        _src="${root}/templates/task/${_s}.sh"
        _dst="${task_dir}/${_s}.sh"
        [[ -f "$_src" ]] || die "模板缺件：${_src}（工程不完整）"
        if [[ -f "$_dst" ]] && cmp -s "$_src" "$_dst"; then
            echo "  已一致        ${_dst#"${root}"/}"
        else
            mkdir -p "$(dirname "$_dst")"
            cp "$_src" "$_dst"; chmod +x "$_dst"
            echo "  已刷新        ${_dst#"${root}"/}（旧内容被覆盖）"
        fi
    done
fi
put "${root}/templates/run.env"         "${task_dir}/run.env"

for f in _taskcfg.sh train_cmd.sh convert_cmd.sh eval_cmd.sh train_argv.txt \
         validate_design.sh eval_protocol_gate.sh; do
    put "${root}/templates/commands/${f}" "${task_dir}/commands/${f}"
done

put "${root}/templates/drivers/lm_eval_driver.py" "${task_dir}/drivers/lm_eval_driver.py"
put "${root}/templates/sets/README.md"            "${task_dir}/sets/README.md"

# 任务自有 README：只写"这份目录属于谁、还差什么"，不抄引擎件的规则（一个事实一个落点）
readme="${task_dir}/README.md"
if [[ ! -e "$readme" ]]; then
    mkdir -p "$task_dir"
    cat > "$readme" <<EOF
# \`${task}\` —— 任务目录

本目录属于任务 \`${task}\`（任务配置：\`config/tasks/${task}.yaml\`）。

## 里有什么

| 文件 | 是什么 | 谁填 |
|---|---|---|
| \`train.sh\`／\`convert.sh\`／\`eval.sh\` | 三段入口（引擎件，**与别处逐字相同，别改**） | 不用填 |
| \`run.env\` | 变量与命令落点 | **人**：三条 \`LP_*_CMD\` ＋ 路径 |
| \`commands/{train,convert,eval}_cmd.sh\` | 三段命令体 | **developer**：按方案改 argv |
| \`commands/train_argv.txt\` | 训练 argv 的占位模板 | **developer**：模型几何 |
| \`commands/{validate_design.sh,eval_protocol_gate.sh}\` | 两个闸门（入口脚本自动调用，人不用管） | 不用填 |
| \`drivers/lm_eval_driver.py\` | 评测驱动 | 一般不用改；改协议见文件头 |
| \`sets/\` | 本轮评测覆盖哪些题（纯声明） | **人**：一行一个题目 id ＋ \`# count: N\` |

## 还差什么（新建后必做）

1. \`commands/train_argv.txt\`：填模型几何（层数/隐藏维/专家数这类），照文件里的占位说明。
2. \`sets/<集合名>.txt\`：填这一轮要评的题单，文件头写 \`# count: N\`（格式见 \`experiments/README.md\`）。
3. \`run.env\`：填三条 \`LP_*_CMD\`（指向上面三段命令体）与数据/权重路径。

## 开跑前

\`\`\`bash
bash scripts/install_env.sh --task ${task} --dry-run   # 评测 venv 会建到哪（见 skills/bootstrap-eval-env）
bash scripts/preflight.sh ${task}                      # 配置／两仓钉点／卡／评测环境 四项
bash scripts/start_experiment.sh ${task}               # 建 <轮次>/ 并钉 state
\`\`\`
EOF
    echo "  新建          ${readme#"${root}"/}"
    created=$((created + 1))
else
    echo "  已存在，跳过  ${readme#"${root}"/}"
    skipped=$((skipped + 1))
fi

cat <<EOF

[init] 完成：新建 ${created} 件，跳过 ${skipped} 件（已存在的不动）。

★ 还差三样，**必须人/developer 填**（填错不会报错，会静默跑错）：
  1) ${experiments_rel}/${task}/commands/train_argv.txt   模型几何
  2) ${experiments_rel}/${task}/sets/<集合名>.txt          题单（文件头 # count: N）
  3) ${experiments_rel}/${task}/run.env                    三条 LP_*_CMD 与路径

★ 任务配置里两处**部署事实**也别忘了（preflight 不查它们，训练拼装时才拦）：
   - model.start.{format,path}   训练 --load 吃哪份；目录不在就先转一次：
                                 bash scripts/convert_weights.sh --task ${task}
   - train.data_path             训练语料路径

★ 然后：bash scripts/preflight.sh ${task}
  （评测 venv 还没建就先看 skills/bootstrap-eval-env：install_env.sh 建、回填、自证）
EOF
