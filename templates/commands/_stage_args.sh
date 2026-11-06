#!/usr/bin/env bash
# _stage_args.sh —— 三段模板共用的「轮次追加片段」解析器（0.18.29）
#
# 为什么要有它：`<轮次>/round.env` 的片段是**追加到生效命令末尾**的（`runtime/_common.sh` 的
# `lp_effective_cmd` 干这件事），而生效命令的第一段就是本模板脚本 ⇒ 模板必须接得住这些参数。
# 0.18.28 前三段各写一个 `case "${1:-}"`，只认**一个**位置参数 ⇒ 任何片段都被判"不认的参数"
# 退 2；引擎认为合法、模板认为非法，而且**不用片段的全量跑一切正常**（看起来像"这次参数写错了"）。
#
# 用法（在 `<任务目录>/commands/{train,convert,eval}_cmd.sh` 里）：
#     source "${HERE}/_stage_args.sh"
#     lp_stage_args <train|convert|eval> "$@" || exit 2     # 得到 PRINT / STAGE_EXTRAS
#     ...
#     cmd="$(lp_stage_append "$cmd")"                       # 拼到命令末尾（%q 逐项归一）
#
# 语义（与 `lp_effective_cmd` 一致，别自己再写一份）：
#   · `--print` / `--dry-run`：位置任意，只打印不执行
#   · `--run`：忽略（"真跑"是默认）
#   · `--`：其后全部作为片段（片段里带 `-` 开头也不怕）
#   · 其余参数：当作轮次追加片段**原样转交**
#
# ★ 有一条硬线：**值必须在任务配置里**的项一律拒（rc=2）并指名"该改哪个键"。否则同一个事实
#   两个落点，改一处就静默不同步 —— 这正是本工程反复在躲的那类问题。

STAGE_EXTRAS=()
PRINT=0

#: 片段里**不许**出现的 flag → 唯一落点的人话说明（不认识的 flag 一律放行：那是"临时试试"）。
_lp_stage_owner() { # <stage> <flag>  → 回显"该改哪个键"；空 = 放行
  local stage="$1" flag="$2"
  case "$stage" in
    train)
      case "$flag" in
        --train-iters|--iters|--max-steps)   echo "stop_conditions.max_steps（任务配置）" ;;
        --save-interval)                     echo "train.checkpoint.save_interval_steps（任务配置）" ;;
        --seq-length)                        echo "run.env 的 LP_SEQ_LEN" ;;
        --micro-batch-size)                  echo "run.env 的 LP_MICRO_BS" ;;
        --global-batch-size)                 echo "run.env 的 LP_GLOBAL_BS" ;;
        --qat-scheme)                        echo "model.precision（任务配置）" ;;
        --load)                              echo "model.start.path（任务配置）" ;;
        --save)                              echo "ckpt 落点（由 LP_TRAIN_OUT 给，别手写）" ;;
        --finetune|--no-finetune)            echo "续跑策略（由 --resume 决定，见 runtime/README.md §2.0）" ;;
        --tensor-model-parallel-size)        echo "run.env 的 LP_TP" ;;
        --pipeline-model-parallel-size)      echo "run.env 的 LP_PP" ;;
      esac ;;
    convert)
      case "$flag" in
        --load-dir|--save-dir)               echo "run.env 的 LP_CONVERT_IN / LP_CONVERT_OUT" ;;
        --hf-cfg-dir)                        echo "LP_HF_CFG_DIR（人或 run.env 给）或 model.source.path（任务配置）" ;;
        --model-type-hf)                     echo "model.start.convert.model_type_hf（任务配置）" ;;
        --target-tensor-parallel-size)       echo "model.start.convert.tp（任务配置）" ;;
        --target-pipeline-parallel-size)     echo "model.start.convert.pp（任务配置）" ;;
      esac ;;
    eval)
      case "$flag" in
        --model)                             echo "本轮 hf 产物（由落点推出来，别手写）" ;;
        --tasks)                             echo "eval.datasets（任务配置）" ;;
        --dataset)                           echo "eval.datasets 的 data_path（任务配置）" ;;
        --protocols-json)                    echo "criterion.yaml 的 eval_protocol.*（口径必须跑前冻结）" ;;
        --num_fewshot|--max_gen_toks|--batch_size) echo "eval.protocol（任务配置）" ;;
        --include-path)                      echo "eval.lm_eval.include_path（任务配置）" ;;
        --output_path)                       echo "evidence/ 落点（自动）" ;;
        --dtype)                             echo "run.env 的 LP_EVAL_DTYPE" ;;
        --device)                            echo "run.env 的 LP_EVAL_DEVICE" ;;
      esac ;;
  esac
}

lp_stage_args() { # <train|convert|eval> "$@"
  local stage="${1:-}"; shift || true
  case "$stage" in
    train|convert|eval) ;;
    *) echo "_stage_args.sh：第一个参数必须是 train／convert／eval，收到 ${stage:-（空）} ⇒ 退出 2" >&2; return 2 ;;
  esac
  local -a extras=()
  local arg owner
  while [[ $# -gt 0 ]]; do
    arg="$1"
    case "$arg" in
      --print|--dry-run) PRINT=1 ;;
      --run) ;;
      --) shift; while [[ $# -gt 0 ]]; do extras+=("$1"); shift; done; break ;;
      *)
        owner="$(_lp_stage_owner "$stage" "${arg%%=*}")"
        if [[ -n "$owner" ]]; then
          echo "${stage}_cmd.sh：不接受参数 ${arg}（**这个值有唯一落点**，别用片段改）⇒ 退出 2" >&2
          echo "  该改：${owner}" >&2
          echo "  ★ 片段只许改"这一段既不改变口径、也不改变落点"的东西（例如 --log-interval）；" >&2
          echo "    两处各写一份，改一处就会静默不同步。" >&2
          return 2
        fi
        extras+=("$arg")
        ;;
    esac
    shift
  done
  STAGE_EXTRAS=("${extras[@]}")
  return 0
}

lp_stage_append() { # <已拼好的命令> → 回显"命令 ＋ 片段"（%q 逐项归一，空格/引号不会被吞）
  local cmd="$1" x
  for x in "${STAGE_EXTRAS[@]}"; do
    cmd+=" $(printf '%q' "$x")"
  done
  printf '%s' "$cmd"
}

lp_stage_print_note() { # --print 时把片段单独打一行（命令里也能看到；这一行便于对账）
  [[ ${#STAGE_EXTRAS[@]} -eq 0 ]] && return 0
  printf '  轮次追加片段    %s（原样转交，位置在命令末尾）\n' "${STAGE_EXTRAS[*]}"
}
