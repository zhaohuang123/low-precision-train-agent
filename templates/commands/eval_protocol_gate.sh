#!/usr/bin/env bash
# eval_protocol_gate.sh —— **闸门**：评测口径一致性（口径不全／不一致 ⇒ 评测侧无效 6）
#
# 归属：评测口径闸门 ＋ `runtime/README.md` §2 的退出码 6（评测侧无效：口径不全、
#       驱动异常、结果不可比）。用法：bash <任务目录>/commands/eval_protocol_gate.sh <轮次目录>
#
# 它治的是什么：**评测口径漂了，数字照样出得来。** 判据里写 `prompt_type: A`、任务配置里写
# `prompt_type: B`，两边都不报错，最后拿到一个"比基线高 0.01"的结论 —— 而这个差值量的
# 可能是口径差，不是方案差。所以这条比对必须在**花算力之前**做，且**不一致就不许出数字**。
#
# 唯一落点：判据侧 = `<轮次>/criterion.yaml` 的 `eval_protocol.datasets[]`（**逐数据集**，0.17.0 起）；
#           任务侧 = `config/tasks/<任务名>.yaml` 的 `eval.datasets[]` ＋ `eval.protocol.*`
#           （某集的**生效口径** = 全局 protocol ⊕ 该集 protocol 覆盖；覆盖写 null = 显式清空）。
#           **不允许**在命令脚本里再抄一份口径。
#
# 退出码：0 一致 ／ 6 口径不全或与任务配置冲突（评测侧无效）／ 2 读不了文件、用法错（约定不过）
set -euo pipefail

task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LP_ROOT="${LP_ROOT:-$(cd "${task_dir}/../.." && pwd)}"
task_id="${LP_TASK_ID:-$(basename "$task_dir")}"

round_dir="${1:-}"
if [[ -z "$round_dir" ]]; then
  echo "用法：bash <任务目录>/commands/eval_protocol_gate.sh <轮次目录>" >&2
  exit 2
fi
criterion="${LP_CRITERION:-${round_dir}/criterion.yaml}"
task_cfg="${LP_ROOT}/config/tasks/${task_id}.yaml"

rc=0
# ★ `|| rc=$?`：`set -e` 开着，python 的非零码**必须**在这里被接住 ——
#   否则退出 6（评测侧无效）会先被 set -e 变成"脚本自己死了"，而 6 这个语义就丢了。
python3 - "$criterion" "$task_cfg" <<'PY' || rc=$?
import sys

try:
    import yaml
except ImportError:  # pragma: no cover
    print("[gate] 需要 PyYAML 才能比对评测口径", file=sys.stderr)
    sys.exit(2)

try:
    crit = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
    cfg = yaml.safe_load(open(sys.argv[2], encoding="utf-8")) or {}
except OSError as exc:
    print(f"[gate] 读不了文件：{exc}", file=sys.stderr)
    sys.exit(2)
except yaml.YAMLError as exc:
    print(f"[gate] YAML 解析不了：{exc}", file=sys.stderr)
    sys.exit(2)

PROTO_KEYS = ("prompt_type", "max_gen_toks", "batch_size", "num_fewshot")

proto = crit.get("eval_protocol")
if not isinstance(proto, dict) or not proto:
    print("[gate] ✗ 判据里没有 eval_protocol（口径没写下来 ⇒ 结果不可比）", file=sys.stderr)
    sys.exit(6)
crit_ds = proto.get("datasets")
if not isinstance(crit_ds, list) or not crit_ds:
    print("[gate] ✗ 判据的 eval_protocol.datasets 不是非空列表 —— 0.17.0 起口径必须**逐数据集**"
          "写下来（旧的单值 eval_protocol.dataset 已删：单值写不出多个数据集的口径）",
          file=sys.stderr)
    sys.exit(6)

eval_cfg = cfg.get("eval") or {}
cfg_ds = eval_cfg.get("datasets") or []
g_proto = eval_cfg.get("protocol") or {}
g_type = eval_cfg.get("task_type")


def _eff(block):
    """任务侧某数据集的**生效口径**：全局 protocol ⊕ 逐键覆盖（覆盖值写 null = 显式清空）。"""
    eff = dict(g_proto)
    for k, v in (block.get("protocol") or {}).items():
        if v is None:
            eff.pop(k, None)        # 显式清空：这个键**不继承**全局
        else:
            eff[k] = v
    return eff, (block.get("task_type") or g_type)


by_name = {}
for b in cfg_ds:
    if isinstance(b, dict) and isinstance(b.get("name"), str) and b["name"].strip():
        by_name[b["name"].strip()] = b

bad, unchecked, crit_names = [], [], []
for b in crit_ds:
    nm = b.get("name") if isinstance(b, dict) else None
    if not isinstance(nm, str) or not nm.strip():
        bad.append(f"判据 eval_protocol.datasets 里有一块没有 name（{b!r}）")
        continue
    crit_names.append(nm.strip())

miss_cfg = [n for n in crit_names if n not in by_name]
if miss_cfg:
    bad.append(f"判据里的数据集 {miss_cfg} 在任务配置 eval.datasets 里没有"
               f"（任务配置已声明：{sorted(by_name)}）")
miss_crit = [n for n in by_name if n not in crit_names]
if miss_crit:
    bad.append(f"任务配置 eval.datasets 里的 {miss_crit} 在判据 eval_protocol.datasets 里没有"
               f"（这几个集的口径没被冻结 ⇒ 结果不可比）")

for b in crit_ds:
    if not isinstance(b, dict):
        continue
    name = b["name"].strip() if isinstance(b.get("name"), str) else ""
    block = by_name.get(name)
    if block is None:
        continue                    # 已在上面记 bad
    eff, t_type = _eff(block)
    local = {"task_type": t_type}
    local.update({k: eff.get(k) for k in PROTO_KEYS})
    for k, v in b.items():
        if k == "name":
            continue
        if k in local:
            want = local[k]
            if want is None:
                unchecked.append(f"{name}.{k}={v!r}（任务配置未声明，本闸门不比对）")
            elif v != want:
                bad.append(f"{name}.{k}: 判据 {v!r} ≠ 任务配置 {want!r}")
        else:
            unchecked.append(f"{name}.{k}={v!r}（任务配置里没有对应字段）")

for line in unchecked:
    print(f"[gate] · {line}")
if bad:
    print("[gate] ✗ 评测口径不一致 ⇒ **评测侧无效（退出 6）**：结果不可比。", file=sys.stderr)
    for x in bad:
        print(f"[gate]   {x}", file=sys.stderr)
    print("[gate]   修法：改判据或改任务配置（两者必须逐数据集逐项一致），"
          "**不许**在命令脚本里补一份口径。", file=sys.stderr)
    sys.exit(6)

print(f"[gate] ✓ 评测口径一致：{len(crit_names)} 个数据集 "
      f"({', '.join(crit_names)})，逐数据集逐项比对通过")
PY
if [[ "$rc" -eq 0 ]]; then exit 0; fi
if [[ "$rc" -eq 6 ]]; then
  echo "[gate] 结论：**评测侧无效**（退出 6）—— 不产生指标，也别拿它跟基线比。" >&2
  exit 6
fi
echo "[gate] 闸门自己失败（退出 ${rc}）⇒ 约定不过。" >&2
exit 2
