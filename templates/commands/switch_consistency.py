#!/usr/bin/env python3
"""switch_consistency.py —— **开关一致性**闸门骨架（照抄到 <任务目录>/commands/ 再改）

"开关"指那些**会改变评测/训练含义**的取值（少样本数、生成长度、批大小、是否采样、
prompt 模板名…）。它们分散在两处，于是最容易漂：

    <轮次>/criterion.yaml 的 eval_protocol.*  ←→  config/tasks/<任务名>.yaml 的 eval.*

漂了的后果**不会报错**：两边都能跑完，数字照样出得来，只是这个差值量的可能是口径差、
不是方案差。所以这条闸门在**花算力之前**逐项比对，不一致就当场退出 6。

照抄时改这里：`MAPPING`（判据侧键 → 任务配置侧取值）。
★ 唯一映射表只许有一份 —— 在命令脚本里再抄一份口径，就是给同一个事实造第二个落点。

退出码：0 一致 ／ 6 口径不全或冲突（评测侧无效）／ 2 读不了文件、用法错。
"""

from __future__ import annotations

import sys

#: 判据侧键 → 任务配置侧**取值函数**（这里给形状，照抄时替换成真的读数）
MAPPING_SHAPE = {
    # "datasets":      lambda crit, cfg: [d.get("name") for d in (cfg.get("eval") or {}).get("datasets") or []],
    # "prompt_type":   lambda crit, cfg: ((cfg.get("eval") or {}).get("protocol") or {}).get("prompt_type"),
}


def main(argv) -> int:
    if len(argv) != 3:
        print("用法：switch_consistency.py <轮次>/criterion.yaml <config/tasks/任务名>.yaml",
              file=sys.stderr)
        return 2
    try:
        import yaml
    except ImportError:  # pragma: no cover
        print("[gate] 需要 PyYAML 才能比对口径", file=sys.stderr)
        return 2
    try:
        crit = yaml.safe_load(open(argv[1], encoding="utf-8")) or {}
        cfg = yaml.safe_load(open(argv[2], encoding="utf-8")) or {}
    except OSError as exc:
        print(f"[gate] 读不了文件：{exc}", file=sys.stderr)
        return 2
    except yaml.YAMLError as exc:
        print(f"[gate] YAML 解析不了：{exc}", file=sys.stderr)
        return 2

    proto = crit.get("eval_protocol")
    if not isinstance(proto, dict) or not proto:
        print("[gate] ✗ 判据里没有 eval_protocol（口径没写下来 ⇒ 结果不可比）", file=sys.stderr)
        return 6
    if not MAPPING_SHAPE:
        print("[gate] ✗ 本文件还是骨架：`MAPPING` 没填 ⇒ 拒绝放行（退出 2）。", file=sys.stderr)
        return 2

    bad = []
    for key, get in MAPPING_SHAPE.items():
        if key in proto and get(crit, cfg) is not None and proto[key] != get(crit, cfg):
            bad.append(f"{key}: 判据 {proto[key]!r} ≠ 任务配置 {get(crit, cfg)!r}")
    if bad:
        print("[gate] ✗ 口径不一致 ⇒ **评测侧无效（退出 6）**：结果不可比。", file=sys.stderr)
        for b in bad:
            print(f"[gate]   {b}", file=sys.stderr)
        return 6
    print("[gate] ✓ 口径一致")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
