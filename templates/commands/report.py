#!/usr/bin/env python3
"""report.py —— **报告可引用字段清单**骨架（照抄到 <任务目录>/commands/ 再改）

报告里的每个数字都必须能在 `<轮次>/metrics.json` 里找到对应字段（"不改数字"）。
可是写报告的人经常不知道有哪些字段可引，于是会出现"手抄一个数"——而手抄的数没有人能核对。

这个小工具把 `metrics.json` 的所有叶子路径打印出来（含值），于是：

  * 写报告时**照抄路径**，不照抄数；
  * review 时能一眼看出"这句话里的数在 metrics.json 里有没有对应字段"。

用法：python3 report.py <轮次>/metrics.json
退出码：0 打印成功 ／ 2 读不了/不是 JSON。
"""

from __future__ import annotations

import json
import sys


def walk(node, prefix=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        yield f"{prefix}[]  ({len(node)} 项)"
    else:
        yield f"{prefix} = {node!r}"


def main(argv) -> int:
    if len(argv) != 2:
        print("用法：report.py <轮次>/metrics.json", file=sys.stderr)
        return 2
    try:
        doc = json.load(open(argv[1], encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[report] 读不了 {argv[1]}：{exc}", file=sys.stderr)
        return 2
    print(f"# {argv[1]} 里可引用的字段（报告里引用**路径**，不要手抄数字）")
    for line in walk(doc):
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
