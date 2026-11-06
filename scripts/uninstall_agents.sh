#!/usr/bin/env bash
# scripts/uninstall_agents.sh —— 按 manifest 卸载：**只删 manifest 里列出的、且 sha256 未变的文件**。
#
# 归属：Agent 卸载（装卸四条规矩的 ③④）。
#   ③ **卸载只删 manifest 里列出的、且 sha256 未变的文件**：文件被改过就报错退出 `2`，
#      **不许静默删掉用户改过的东西**；manifest 里没有的一律不碰。
#   ④ `--dry-run`：打印将删除的路径而不落盘；`uninstall` 后目标目录回到安装前的状态。
#
# 用法：
#   bash scripts/uninstall_agents.sh --target "$T" --dry-run
#   bash scripts/uninstall_agents.sh --target "$T"

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 - --root "$ROOT" "$@" <<'PY'
"""uninstall_agents.sh 的实现体（嵌入式，避免额外文件）。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

MANIFEST_NAME = ".lpta-install.json"
EXIT_CONTRACT = 2


def die(msg: str) -> "None":
    print(f"uninstall_agents.sh: {msg}", file=sys.stderr)
    raise SystemExit(EXIT_CONTRACT)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="按 manifest 卸载（只删未改动的本工程文件）")
    ap.add_argument("--target", required=True, help="目标 agent 目录")
    ap.add_argument("--root", default=None, help="配置根（默认由脚本位置推出）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将删除的路径，不落盘")
    args = ap.parse_args()

    target = Path(args.target).expanduser()
    manifest_path = target / MANIFEST_NAME
    if not manifest_path.is_file():
        die(f"没有 manifest（{manifest_path}）⇒ 无从判断哪些文件是本工程装的；**一个都不碰**。")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = list(manifest["files"])
    except Exception as exc:
        die(f"manifest 无法解析（{manifest_path}）：{exc}")

    # 先全量校验，再决定删不删：任一文件被改过 ⇒ 退出 2，且不删任何东西
    changed: list[tuple[str, str, str]] = []   # (path, recorded, actual)
    to_delete: list[Path] = []
    missing: list[str] = []
    for entry in entries:
        dest = target / entry["path"]
        if not dest.exists():
            missing.append(entry["path"])
            continue
        actual = sha256_file(dest)
        if actual != entry["sha256"]:
            changed.append((entry["path"], entry["sha256"], actual))
            continue
        to_delete.append(dest)

    if changed:
        print("uninstall_agents.sh: 以下文件已被改动，拒绝删除（不许静默删掉用户改过的东西）：", file=sys.stderr)
        for path, recorded, actual in changed:
            print(f"  {path}\n    记录 sha256={recorded}\n    实际 sha256={actual}", file=sys.stderr)
        print("  ⇒ 退出 2。请人工确认后处理（本脚本不做任何删除）。", file=sys.stderr)
        raise SystemExit(EXIT_CONTRACT)

    if args.dry_run:
        print(f"[dry-run] target = {target}")
        for dest in to_delete:
            print(f"[dry-run] 将删除 {dest}")
        for path in missing:
            print(f"[dry-run] 已不存在（跳过）：{path}")
        print(f"[dry-run] 将删除 manifest {manifest_path}")
        print("[dry-run] 未落盘。")
        return 0

    for dest in to_delete:
        dest.unlink()
    manifest_path.unlink()
    print(f"已卸载 {len(to_delete)} 个文件；manifest 已删除。")
    for path in missing:
        print(f"  已不存在（跳过）：{path}")
    print(f"目标目录已回到安装前的状态（只删了本工程装的文件）：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
