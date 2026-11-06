#!/usr/bin/env bash
# scripts/install_skills.sh —— 把 `skills/<skill>/**` 装到目标 skill 目录，并留 manifest。
#
# 归属：skill 安装（与 Agent 装卸同四条规矩）。
#
# 规矩（与 install_agents.sh 同源）：
#   ① **一个 skill 装成一棵树，不是一个文件**：装 `<目标目录>/<skill>/SKILL.md` **以及该目录下的全部文件**
#      （现在的实际内容就是 `SKILL.md` ＋ `references/*.md`）。★ 只拷 `SKILL.md` 是**断链安装**：
#      九份 `SKILL.md` **全部**以内联相对路径引用 `references/…`，而 skill 的相对路径按**该 skill 自己的目录**
#      解析（`skill-filesystem` 的 `resourceBase = locator.directory`）⇒ 少拷一个 `references/` 就是死链。
#   ② 留 manifest `<目标目录>/.lpta-install.json`（路径 ＋ sha256 ＋ 来源）；manifest 是卸载的**唯一依据**。
#   ③ 卸载只删 manifest 里列出的、且 sha256 未变的文件；被改过就报错退出 `2`，manifest 里没有的一律不碰；
#      删完把**已空**的 skill 目录（含 `references/`）按由深到浅的顺序清掉。
#   ④ `--dry-run` 两边都支持；install 连跑两次结果一致（幂等，manifest **不写时间戳**）。
#   ⑤ 目标目录里**非本工程装的文件一律不碰**（install 拒绝覆盖）。
#   ⑥ ★ **`SKILL.md` 写盘之前必须过 skill frontmatter 校验**：`skill-filesystem` 的 `parseSkillFile` 遇到
#      「没有 frontmatter／frontmatter 不是合法 YAML／不是映射／缺 `name` 或 `description`／`name` 不是
#      小写 kebab-case／invocation 键非法」时**只打一条 `logger.warn` 就 `return`**，`discoverRoot` 随即
#      `continue` —— 也就是**静默不加载**：文件装上了、"安装成功"，会话里却根本没有这个 skill。
#      故本脚本照该实现**逐条复算**（规则出处 `@deepseek-ai/dsh-skill-filesystem/lib/index.js` 的
#      `parseSkillFile`／`parseFrontmatter`／`parseInvocationPolicy` ＋ `@deepseek-ai/dsh-skill/lib/index.js`
#      的 `SKILL_NAME`），不合规 ⇒ **拒绝安装退出 `2`** 并指名文件＋字段。
#      ★ 另一条一致性要求：`frontmatter.name` 必须**等于 skill 目录名** —— 工程侧（`AGENTS.md` §5 挂载表、
#        `agents/*/AGENT.md` 的 `skills:` 路径、`devtools/validate_agents.py`）一律按**目录名**指认 skill。
#      ★ 已知边界：此处用 PyYAML（YAML 1.1）复算目标机的 npm `yaml`（YAML 1.2）；纯量取值上二者对
#        `on/off/yes/no` 这类**裸词**的判定不同，本工程九份 `SKILL.md` 都不含这种裸值，故不影响；
#        若将来有人在 frontmatter 里写裸 `yes`，应以目标机实际加载为准。
#   ⑦ ★ **本工程装过、但被本地改过的文件 ⇒ 拒绝覆盖**（与 install_agents.sh／uninstall 同一条纪律）；
#      确认要覆盖就显式加 `--force`。
#
# ★ 文档说明：早先的 `scripts/` 文件清单里**没有** `uninstall_skills.sh`
#   （只有 README.md / install_agents.sh / uninstall_agents.sh / install_skills.sh / install_env.sh）。
#   为了不新增文档未列的文件，skill 的卸载能力**并入本脚本**的 `--uninstall` 模式（同一份 manifest、同一套规矩）。
#   若上游要求拆成独立文件，属 P10 的清单变更，需先改文档再改代码。
#
# 用法：
#   bash scripts/install_skills.sh   --target "$T" --dry-run
#   bash scripts/install_skills.sh   --target "$T"
#   bash scripts/install_skills.sh   --target "$T" --force      # 显式覆盖被本地改过的 skill 文件（⑦）
#   bash scripts/install_skills.sh   --target "$T" --uninstall --dry-run
#   bash scripts/install_skills.sh   --target "$T" --uninstall

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec python3 - --root "$ROOT" "$@" <<'PY'
"""install_skills.sh 的实现体（嵌入式，避免额外文件）。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # 目标机缺依赖时给人话，别甩 traceback
    print(
        "install_skills.sh: 需要 PyYAML 才能复算 SKILL.md frontmatter（目标机先 `pip install pyyaml`）",
        file=sys.stderr,
    )
    raise SystemExit(2)

MANIFEST_NAME = ".lpta-install.json"
EXIT_CONTRACT = 2

# ── skill frontmatter 校验用的常量（照 skill-filesystem / dsh-skill 复算，见文件头 ⑥）──
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_INVOCATION_KEYS = ("disableModelInvocation", "modelInvocable", "userInvocable")


def die(msg: str) -> "None":
    print(f"install_skills.sh: {msg}", file=sys.stderr)
    raise SystemExit(EXIT_CONTRACT)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ════════════════════════════════════════════════════════════════════════════
# ⑥ skill frontmatter 复算 —— 与 skill-filesystem 的 parseSkillFile 逐条对应
# ════════════════════════════════════════════════════════════════════════════
def _frontmatter_block(raw: str) -> "tuple[str, str] | tuple[None, str]":
    """照 parseFrontmatter：首行须恰为 `---`（容许行尾 CR），且存在闭合的 `---` 行。

    返回 (块内容, 错误说明)；成功时错误说明为空串。
    """
    first_end = raw.find("\n")
    if first_end < 0 or raw[:first_end].rstrip("\r") != "---":
        return None, "没有 YAML frontmatter（首行必须恰为 `---`）"
    start = first_end + 1
    pos = start
    while pos <= len(raw):
        nl = raw.find("\n", pos)
        line_end = len(raw) if nl < 0 else nl
        if raw[pos:line_end].rstrip("\r") == "---":
            return raw[start:pos], ""
        if nl < 0:
            break
        pos = nl + 1
    return None, "frontmatter 没有闭合的 `---` 行"


def _boolish_ok(value: object) -> bool:
    """照 parseInvocationPolicy 的 frontmatterBoolean：boolean／1／0／'1'／'0'／
    true|yes|on|false|no|off（大小写不敏感）；其余（含 list/dict/其他串）一律拒绝。"""
    if isinstance(value, bool):
        return True
    if isinstance(value, int) and value in (0, 1):
        return True
    if isinstance(value, str):
        return value.lower() in ("1", "0", "true", "yes", "on", "false", "no", "off")
    return False


def skill_problems(raw: str, skill: str) -> list[str]:
    """返回**会被 skill-filesystem 静默丢弃**的原因清单；空 = 该 skill 能真加载。

    逐条对照 `parseSkillFile`（此处只复算，不改写规则）：frontmatter 存在且是合法 YAML 映射；
    `name` 是非空字符串且匹配 SKILL_NAME 文法；`description` 是非空字符串；invocation 键不含旧名、
    取值必须是布尔可判的。
    """
    block, err = _frontmatter_block(raw)
    if block is None:
        return [err]
    try:
        data = yaml.safe_load(block)
    except Exception as exc:
        return [f"frontmatter 不是合法 YAML（{exc}）——skill-filesystem 会 `logger.warn` 后丢弃"]
    if not isinstance(data, dict):
        return ["frontmatter 解析出来不是映射（对象）——会被静默丢弃"]

    problems: list[str] = []
    name = data.get("name")
    if not isinstance(name, str) or not name:
        problems.append("缺必填键 `name`（非空字符串）")
    elif not SKILL_NAME_RE.match(name):
        problems.append(f"`name` 必须是小写 kebab-case（^[a-z0-9]+(-[a-z0-9]+)*$），实得 {name!r}")
    elif name != skill:
        problems.append(f"`name: {name}` ≠ skill 目录名 `{skill}`（工程侧一律按目录名指认 skill）")

    description = data.get("description")
    if not isinstance(description, str) or not description:
        problems.append("缺必填键 `description`（非空字符串）")

    for key in LEGACY_INVOCATION_KEYS:
        if key in data:
            problems.append(f"用了被拒的旧 invocation 键 `{key}`（换用 `disable-model-invocation` / `user-invocable`）")
    for key in ("disable-model-invocation", "user-invocable"):
        if key in data and not _boolish_ok(data[key]):
            problems.append(f"`{key}` 必须是布尔（true/false、yes/no、on/off、1/0），实得 {data[key]!r}")

    return problems


def discover(root: Path) -> list[tuple[str, Path, str]]:
    """返回 [(skill, 源文件, 相对目标根的路径)]，覆盖每个 skill 目录下的**全部文件**（排序稳定）。"""
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        die(f"找不到 skills/ 目录：{skills_dir}（配置根解析错了吗？）")
    out: list[tuple[str, Path, str]] = []
    for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
        if not (skill_dir / "SKILL.md").is_file():
            die(f"skills/{skill_dir.name}/ 缺 SKILL.md（agentskills 规范的最小集合）")
        for src in sorted(f for f in skill_dir.rglob("*") if f.is_file()):
            out.append((skill_dir.name, src, f"{skill_dir.name}/{src.relative_to(skill_dir).as_posix()}"))
    if not out:
        die("skills/ 下没有找到任何 skill")
    return out


def load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.is_file():
        return {"files": []}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"已存在的 manifest 无法解析（{manifest_path}）：{exc}")
        raise  # 不可达


def do_uninstall(target: Path, manifest_path: Path, dry_run: bool) -> int:
    manifest = load_manifest(manifest_path)
    if not manifest["files"]:
        die(f"没有 manifest（{manifest_path}）⇒ 无从判断哪些文件是本工程装的；**一个都不碰**。")

    changed, to_delete, missing = [], [], []
    for entry in manifest["files"]:
        dest = target / entry["path"]
        if not dest.exists():
            missing.append(entry["path"])
            continue
        actual = sha256_bytes(dest.read_bytes())
        if actual != entry["sha256"]:
            changed.append((entry["path"], entry["sha256"], actual))
            continue
        to_delete.append(dest)

    if changed:
        print("install_skills.sh: 以下文件已被改动，拒绝删除（不许静默删掉用户改过的东西）：", file=sys.stderr)
        for path, recorded, actual in changed:
            print(f"  {path}\n    记录 sha256={recorded}\n    实际 sha256={actual}", file=sys.stderr)
        print("  ⇒ 退出 2。请人工确认后处理（本脚本不做任何删除）。", file=sys.stderr)
        raise SystemExit(EXIT_CONTRACT)

    # 删完要清的空目录：被删文件的各级父目录（到 target 为止），由深到浅
    candidates: set[Path] = set()
    for dest in to_delete:
        d = dest.parent
        while d != target:
            try:
                d.relative_to(target)
            except ValueError:
                break
            candidates.add(d)
            if d == d.parent:
                break
            d = d.parent

    if dry_run:
        for dest in to_delete:
            print(f"[dry-run] 将删除 {dest}")
        for path in missing:
            print(f"[dry-run] 已不存在（跳过）：{path}")
        print(f"[dry-run] 将清理已空的目录（由深到浅）：{[str(d) for d in sorted(candidates, key=lambda p: len(p.parts), reverse=True)]}")
        print(f"[dry-run] 将删除 manifest {manifest_path}")
        print("[dry-run] 未落盘。")
        return 0

    for dest in to_delete:
        dest.unlink()
    for d in sorted(candidates, key=lambda p: len(p.parts), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()                   # 只清本工程装的、且已空的目录（含 references/）
    manifest_path.unlink()
    print(f"已卸载 {len(to_delete)} 个 skill 文件；manifest 已删除。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="安装/卸载 skills（默认安装；幂等）")
    ap.add_argument("--target", required=True, help="目标 skill 目录，例如 ${DSH_HOME:-$HOME/.dsh}/skills")
    ap.add_argument("--root", default=None, help="配置根（默认由脚本位置推出）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将写入/删除的路径，不落盘")
    ap.add_argument("--uninstall", action="store_true", help="按 manifest 卸载（只删未改动的本工程文件）")
    ap.add_argument("--force", action="store_true",
                    help="显式覆盖「本工程装过但被本地改过」的 skill 文件（默认拒绝，见规矩 ⑦）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path.cwd()
    target = Path(args.target).expanduser()
    manifest_path = target / MANIFEST_NAME

    if args.uninstall:
        return do_uninstall(target, manifest_path, args.dry_run)

    version_file = root / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "unknown"

    known: dict[str, str] = {}
    for e in load_manifest(manifest_path)["files"]:
        known[e["path"]] = e["sha256"]

    plan: list[dict] = []
    problems: list[str] = []
    for skill, src, rel in discover(root):
        data = src.read_bytes()
        if src.name == "SKILL.md":
            problems.extend(f"{rel}：{p}" for p in skill_problems(data.decode("utf-8"), skill))
        plan.append(
            {
                "path": rel,
                "skill": skill,
                "source": f"skills/{rel}",
                "sha256": sha256_bytes(data),
                "bytes": len(data),
                "_data": data,
            }
        )

    # ⑥ 不合规 ⇒ 拒绝安装（**写入之前**；静默不加载是这里最贵的失败）
    if problems:
        print(
            "install_skills.sh: SKILL.md frontmatter 不过 skill-filesystem 规则 ⇒ **拒绝安装**。\n"
            "  该实现在这些情况下只打一条 `logger.warn` 就丢弃整个 skill —— 也就是\n"
            "  「安装成功」并不等于「加载成功」，会话里根本看不到它：",
            file=sys.stderr,
        )
        for p in problems:
            print(f"    - {p}", file=sys.stderr)
        raise SystemExit(EXIT_CONTRACT)

    # ⑤ 非本工程装的文件一律不碰
    for entry in plan:
        dest = target / entry["path"]
        if dest.exists() and entry["path"] not in known:
            die(f"目标目录里已有非本工程安装的文件，拒绝覆盖：{dest}（manifest 里没有它）")

    # ⑦ 本工程装过、但被本地改过 ⇒ 拒绝
    drifted: list[tuple[Path, str, str]] = []
    for entry in plan:
        dest = target / entry["path"]
        if dest.is_file() and entry["path"] in known:
            actual = sha256_bytes(dest.read_bytes())
            if actual != known[entry["path"]]:
                drifted.append((dest, known[entry["path"]], actual))
    if drifted and not args.force:
        print(
            "install_skills.sh: 下列 skill 文件被本地改过（sha256 与 manifest 不符）⇒ **拒绝覆盖**。\n"
            "  本脚本不静默抹掉别人的编辑（与 uninstall 同一条纪律）；确认要覆盖就显式加 `--force`。",
            file=sys.stderr,
        )
        for dest, was, now in drifted:
            print(f"    - {dest}\n        manifest: {was}\n        磁盘现在: {now}", file=sys.stderr)
        raise SystemExit(EXIT_CONTRACT)

    if args.dry_run:
        print(f"[dry-run] root   = {root}")
        print(f"[dry-run] target = {target}")
        for entry in plan:
            print(f"[dry-run] 将写入 {target / entry['path']}  sha256={entry['sha256']}")
        print(f"[dry-run] 将写入 {manifest_path}（{len(plan)} 个文件 ＝ {len({e['skill'] for e in plan})} 个 skill）")
        if drifted:
            print(f"[dry-run] 注意：{len(drifted)} 个文件被本地改过，本次带 --force ⇒ 会覆盖")
        print("[dry-run] 未落盘。")
        return 0

    for entry in plan:
        dest = target / entry["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(entry.pop("_data"))

    manifest = {
        "schema": 1,
        "generator": "low-precision-train-agent/scripts/install_skills.sh",
        "framework_version": version,
        "target_dir": str(target),
        "files": [{k: e[k] for k in ("path", "skill", "source", "sha256", "bytes")} for e in plan],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    skills = sorted({e["skill"] for e in plan})
    print(f"已安装 {len(plan)} 个文件（{len(skills)} 个 skill，含各自的 references/）到 {target}")
    for entry in manifest["files"]:
        print(f"  {entry['path']}  sha256={entry['sha256']}")
    print(f"manifest: {manifest_path}")
    print("生效时机：新装的 skill 要出现在会话的 skill 目录里需**重启 dsh**（推荐顺序：先装、后开会话）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
