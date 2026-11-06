#!/usr/bin/env bash
# detect_heads.sh —— 读出两个框架检出当前的 head，直接给出可粘贴进任务配置的 yaml 片段
#
# 归属：0.18.7 起（主 Agent 开跑前填 `train.framework_head`／`train.core_head` 用）。
#
# 用法：
#   bash scripts/detect_heads.sh <MindSpeed-LLM 检出> <MindSpeed 检出>
#   两个参数都是**目录**（相对路径按当前目录解析）；顺序 = LLM 在前、核心层在后，
#   与任务配置里 `framework_*`（LLM）／`core_*`（核心层）的命名一一对应。
#
# 它只做一件事：**报事实**。不判断这两个 head 是好是坏，也不替你改配置。
#   ★ `config.py validate` 只查这两个目录**存在**、`preflight.sh` 第 ② 项才比对 head ——
#     所以"填错了"要到 preflight 才响；先跑本脚本能把这一步提前。
# 退出码：0 成功｜2 参数不对/不是 git 仓库
set -u

die() { echo "detect_heads.sh：$*" >&2; exit 2; }

[[ $# -eq 2 ]] || die "用法：bash scripts/detect_heads.sh <MindSpeed-LLM 检出> <MindSpeed 检出>"

llm_dir="$1"
core_dir="$2"

read_repo() {                       # $1=目录 $2=配置前缀（framework／core）
    local dir="$1" prefix="$2" abs head short branch dirty ahead
    [[ -d "$dir" ]] || die "不是目录：$dir"
    abs="$(cd "$dir" && pwd)" || die "进不去：$dir"
    git -C "$abs" rev-parse --git-dir >/dev/null 2>&1 || die "不是 git 仓库：$abs"

    head="$(git -C "$abs" rev-parse HEAD 2>/dev/null)" || die "读不出 HEAD：$abs"
    short="$(git -C "$abs" rev-parse --short=8 HEAD 2>/dev/null)"
    branch="$(git -C "$abs" rev-parse --abbrev-ref HEAD 2>/dev/null)"

    # 脏树：HEAD 描述不了工作区 —— preflight ② 只比 HEAD，所以**它照样会 ✓**，
    # 但"钉点"就成了半句真话（代码和提交号不一致）。这里必须喊出来。
    dirty="$(git -C "$abs" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"

    # 领先上游多少（有 origin/master 才算）；本工程习惯钉"上游 + N 个提交"，N 要人知道。
    ahead=""
    if git -C "$abs" rev-parse --verify -q origin/master >/dev/null 2>&1; then
        ahead="$(git -C "$abs" rev-list --count origin/master..HEAD 2>/dev/null || echo "?")"
    fi

    echo "  # $abs（分支 $branch，${short}${ahead:+，领先 origin/master ${ahead} 个提交}）"
    echo "  ${prefix}_repo: \"$abs\""
    echo "  ${prefix}_head: \"$head\""
    if [[ "$dirty" != "0" ]]; then
        echo "  # ⚠ 工作区有 ${dirty} 处未提交改动：HEAD 描述不了当前代码 ⇒ 先提交/还原，钉点才算数" >&2
    fi
}

echo "# 贴进 config/tasks/<任务名>.yaml 的 train: 块（把上面那两行 repo/head 换成下面四行）"
read_repo "$llm_dir" framework
read_repo "$core_dir" core
echo
echo "# 交叉核对（会比对 head 与配置是否一致）："
echo "#   bash scripts/preflight.sh <任务名>"
