#!/usr/bin/env bash
# scripts/install_agents.sh —— 把 agents/<角色>/AGENT.md **扁平导出**成 <目标目录>/<角色>.md，并留 manifest。
#
# 归属：Agent 安装/卸载（四条规矩，都可机械判）。
#
# 规矩（本脚本逐条实现）：
#   ① **安装 = 扁平导出，不是复制整个目录**：本机注册表要求 agent 文件**平铺**在目录顶层、且对未知键静默忽略，
#      所以把 `agents/<角色>/AGENT.md` 导出成 `<目标目录>/<角色>.md`，并把工程专属的 `skills:` 键转成**注释**。
#   ② **安装必须留 manifest**：每个被写出的文件在 `<目标目录>/.lpta-install.json` 记一条（路径 ＋ sha256 ＋ 来源），
#      **连同 skill 落点**；manifest 是卸载的**唯一依据**。
#   ③ **卸载只删 manifest 里列出的、且 sha256 未变的文件**（见 uninstall_agents.sh）；文件被改过就报错退出 2。
#   ④ **两边都先支持 `--dry-run`**：打印将写入的路径而不落盘；install 连跑两次结果一致（幂等）。
#   ⑤ 说清**生效时机**：新写出的文件**可立即按名调用**（派发时从磁盘重读），但工具名册是**装载时静态构建**的，
#      要出现在名册里需**重启 dsh**；目标目录里**非本工程装的文件一律不碰**。
#   ⑥ ★ **frontmatter 必须先过注册表校验**（F8）：注册表的解析是**严格**的，`name`/`deep`/`thinking`/
#      `background`/`maxRounds` 任一不合规 ⇒ 它把**整份文件丢弃**（名册里没有）或派发时抛错。
#      那是**静默**失败：文件明明躺在目录里，"安装成功"却根本没注册上。所以本脚本在**写入之前**照
#      `@aiwayds/dsh-subagent-registry` 的 `parseAgentMarkdown` **逐条复算**，不合规就拒绝安装并指名文件＋字段。
#      复算的规则出处（只读引用，本脚本不 import 它）：
#        lib/agents-dir.js      `parseAgentMarkdown` / `THINKING_LEVELS` / `stripQuotes` / `KEY_LINE`
#        lib/tool-run-agent.js  `buildRoster`（名册与 nameList 用的是 **frontmatter `name`**）
#                               `loadAgent`（派发用的是**文件名** `<name>.md`）
#      ★ 由此得一条注册表自己**不查但会炸**的约束：`frontmatter.name` 必须**等于文件名**（＝角色名），
#        否则名册里会有一个**永远调不通**的名字（名册显示 `name`，派发去找 `<name>.md`）。
#   ⑦ ★ **本工程装过的文件被改过 ⇒ 拒绝覆盖**（F9）：目标文件在 manifest 里、但磁盘 sha256 与 manifest 记的
#      不一致 ⇒ 报错退出 2 并列出（与 uninstall_agents.sh 的「改过就拒删」对齐）；`--force` 才覆盖。
#
# 用法：
#   bash scripts/install_agents.sh --target "$T" --dry-run   # 先看要写什么；不落盘（同样跑 ⑥）
#   bash scripts/install_agents.sh --target "$T"             # 装；再跑一次结果一致（幂等）
#   bash scripts/install_agents.sh --target "$T" --force     # 显式覆盖被本地改过的角色文件
#   bash scripts/uninstall_agents.sh --target "$T"           # 卸；之后目标目录回到安装前

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 配置根：解析不出来就退出 2（fail-closed）

exec python3 - --root "$ROOT" "$@" <<'PY'
"""install_agents.sh 的实现体（嵌入式，避免额外文件）。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROLES = ("architect", "developer", "tester", "experimenter")
MANIFEST_NAME = ".lpta-install.json"
EXIT_CONTRACT = 2  # 约定/契约不过（fail-closed）

# ── 注册表校验用的常量（照 lib/agents-dir.js 逐字复算，见文件头 ⑥）──────────────
THINKING_LEVELS = ("off", "low", "medium", "high", "max")
KEY_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
NON_NEG_INT = re.compile(r"^\d+$")

PROVENANCE = (
    "<!-- 本文件由 low-precision-train-agent 的 scripts/install_agents.sh 导出（来源：{source}）。\n"
    "     `skills:` 是工程专属键：本机注册表没有它（未知键会被静默忽略），故导出时转为注释；\n"
    "     skill 挂载由工程侧履行（见 AGENTS.md §5）。请勿手改本文件 ——\n"
    "     手改后再卸载会因 sha256 不符而报错退出 2。 -->\n"
)


def die(msg: str) -> "None":
    print(f"install_agents.sh: {msg}", file=sys.stderr)
    raise SystemExit(EXIT_CONTRACT)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def split_frontmatter(text: str) -> tuple[str, str]:
    """切出 YAML frontmatter（含两端 ---）与其余正文；没有 frontmatter 即视为不合法。"""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[: i + 1]), "".join(lines[i + 1:])
    return "", text


def comment_skills(frontmatter: str) -> str:
    """把工程专属的 `skills:` 键及其列表项转成注释（其余键一字不动）。"""
    out: list[str] = []
    commenting = False
    for ln in frontmatter.splitlines(keepends=True):
        if commenting:
            if ln[:1] in (" ", "\t"):           # 仍属 skills 列表的缩进行
                out.append("# " + ln)
                continue
            commenting = False
        if ln.startswith("skills:"):
            out.append("# " + ln)
            commenting = True
            continue
        out.append(ln)
    return "".join(out)


def skills_refs(frontmatter: str) -> list[str]:
    """从 frontmatter 取出 `skills:` 列表里的路径（路径相对配置根）。"""
    refs: list[str] = []
    in_skills = False
    for ln in frontmatter.splitlines():
        if ln.startswith("skills:"):
            in_skills = True
            continue
        if in_skills:
            s = ln.strip()
            if s.startswith("- "):
                ref = s[2:].split("#", 1)[0].strip()
                if ref:
                    refs.append(ref)
            elif s and not ln[:1].isspace():
                in_skills = False
    return refs


# ════════════════════════════════════════════════════════════════════════════
# ⑥ 注册表 frontmatter 复算 —— 与 lib/agents-dir.js 的 parseAgentMarkdown 逐条对应
# ════════════════════════════════════════════════════════════════════════════
def _strip_quotes(value: str) -> str:
    """照 agents-dir.js 的 stripQuotes：只剥**一对**相配的首尾引号。"""
    if len(value) >= 2:
        first, last = value[0], value[-1]
        if (first == '"' and last == '"') or (first == "'" and last == "'"):
            return value[1:-1]
    return value


def _frontmatter_values(text: str) -> dict[str, str]:
    """照 parseFrontmatterValues：非键行跳过；重复键**后者胜**；值先 trim 再剥引号。"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return {}
    values: dict[str, str] = {}
    for i in range(1, close):
        m = KEY_LINE.match(lines[i])
        if m is None:
            continue
        values[m.group(1)] = _strip_quotes(m.group(2).strip())
    return values


def registry_problems(text: str, role: str) -> list[str]:
    """返回**会被注册表整份丢弃**的原因清单；空 = 该文件能进名册。

    逐条对照 lib/agents-dir.js `parseAgentMarkdown`（此处只复算，不改写规则）：
      name       缺/空                       → 丢弃
      deep       出现则必须 `^\\d+$`（非负整数；空值**也算错**） → 丢弃
      thinking   出现且非空则必须在 THINKING_LEVELS（大小写敏感） → 丢弃
      background 出现且非空则必须严格 true/false               → 丢弃
      maxRounds  出现且非空则必须 `^\\d+$` 且 ≥1                → 丢弃
    外加一条注册表**不查但会炸**的：name 必须等于文件名（见文件头 ⑥ 末段）。
    """
    problems: list[str] = []
    values = _frontmatter_values(text)

    name = (values.get("name") or "").strip()
    if not name:
        problems.append("缺必填键 `name`（注册表会把整份文件丢弃）")
    elif name != role:
        problems.append(
            f"`name: {name}` ≠ 文件名 `{role}`：名册显示的是 `name`，派发找的是 `{name}.md` "
            f"⇒ 名册里会有一个永远调不通的名字"
        )

    if "deep" in values:
        raw = values["deep"].strip()
        if not NON_NEG_INT.match(raw):
            problems.append(f"`deep` 必须是非负整数（0=叶子），实得 {raw!r}")

    if "thinking" in values:
        got = values["thinking"].strip()
        if got and got not in THINKING_LEVELS:
            problems.append(
                f"`thinking` 必须是 {'/'.join(THINKING_LEVELS)} 之一（**大小写敏感**），实得 {got!r}"
            )

    if "background" in values:
        got = values["background"].strip()
        if got and got not in ("true", "false"):
            problems.append(f"`background` 必须是严格的 true/false（无缩写、无大小写变体），实得 {got!r}")

    if "maxRounds" in values:
        got = values["maxRounds"].strip()
        if got and (not NON_NEG_INT.match(got) or int(got) < 1):
            problems.append(f"`maxRounds` 必须是正整数，实得 {got!r}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="扁平导出四个角色到目标目录（幂等）")
    ap.add_argument("--target", required=True, help="目标 agent 目录，例如 ${DSH_HOME:-$HOME/.dsh}/agents")
    ap.add_argument("--root", default=None, help="配置根（默认由脚本位置推出）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将写入的路径与 sha256，不落盘")
    ap.add_argument("--force", action="store_true",
                    help="显式覆盖「本工程装过但被本地改过」的角色文件（默认拒绝，见规矩 ⑦）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path.cwd()
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        die(f"找不到 agents/ 目录：{agents_dir}（配置根解析错了吗？）")

    version_file = root / "VERSION"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else "unknown"

    target = Path(args.target).expanduser()
    manifest_path = target / MANIFEST_NAME
    known: dict[str, str] = {}                    # path → 上次安装记下的 sha256
    if manifest_path.is_file():
        try:
            for e in json.loads(manifest_path.read_text(encoding="utf-8"))["files"]:
                known[e["path"]] = e["sha256"]
        except Exception as exc:  # manifest 坏掉时不许猜
            die(f"已存在的 manifest 无法解析（{manifest_path}）：{exc}")

    plan: list[dict] = []
    skills_plan: list[dict] = []
    problems: list[str] = []
    for role in ROLES:
        src_rel = f"agents/{role}/AGENT.md"
        src = root / src_rel
        if not src.is_file():
            die(f"缺少角色文件：{src_rel}")
        text = src.read_text(encoding="utf-8")
        frontmatter, rest = split_frontmatter(text)
        if not frontmatter:
            die(f"{src_rel} 没有 YAML frontmatter（首行必须是 ---）")
        exported = comment_skills(frontmatter) + PROVENANCE.format(source=src_rel) + rest
        # ⑥ 校验**导出后**的文本（那才是真正会被注册表读的东西）
        problems.extend(f"{role}.md ← {src_rel}：{p}" for p in registry_problems(exported, role))
        plan.append(
            {
                "path": f"{role}.md",
                "role": role,
                "source": src_rel,
                "sha256": sha256_text(exported),
                "bytes": len(exported.encode("utf-8")),
                "_data": exported,
            }
        )
        for ref in skills_refs(frontmatter):
            skills_plan.append(
                {
                    "role": role,
                    "source": ref,          # 相对配置根
                    "target": None,         # skill 不由本脚本复制（安装 skill 用 install_skills.sh）
                    "note": "skill 挂载由工程侧履行；本脚本只登记落点",
                }
            )

    # ⑥ 不合规 ⇒ 拒绝安装（**写入之前**；静默丢弃是这里最贵的失败）
    if problems:
        print(
            "install_agents.sh: frontmatter 不过注册表规则 ⇒ **拒绝安装**。\n"
            "  照 @aiwayds/dsh-subagent-registry 的 parseAgentMarkdown 复算，下列文件装上去会被**整份丢弃**\n"
            "  （名册里没有它）或在派发时抛错 —— 也就是说「安装成功」并不等于「注册成功」：",
            file=sys.stderr,
        )
        for p in problems:
            print(f"    - {p}", file=sys.stderr)
        raise SystemExit(EXIT_CONTRACT)

    # ⑤ 非本工程装的文件一律不碰：目标已存在同名文件但不在 manifest 里 ⇒ 拒绝覆盖
    for entry in plan:
        dest = target / entry["path"]
        if dest.exists() and entry["path"] not in known:
            die(f"目标目录里已有非本工程安装的文件，拒绝覆盖：{dest}（manifest 里没有它）")

    # ⑦ 本工程装过、但被本地改过 ⇒ 拒绝（与 uninstall_agents.sh 的「改过就拒删」对齐）
    drifted: list[tuple[Path, str, str]] = []
    for entry in plan:
        dest = target / entry["path"]
        if dest.is_file() and entry["path"] in known:
            current = sha256_file(dest)
            if current != known[entry["path"]]:
                drifted.append((dest, known[entry["path"]], current))
    if drifted and not args.force:
        print(
            "install_agents.sh: 下列角色文件被本地改过（sha256 与 manifest 不符）⇒ **拒绝覆盖**。\n"
            "  它们可能是手调过的 persona；本脚本不静默抹掉别人的编辑（与 uninstall_agents.sh 同一条纪律）。\n"
            "  确认要覆盖就显式加 `--force`。",
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
        print(f"[dry-run] 将写入 {manifest_path}（{len(plan)} 个文件 ＋ {len(skills_plan)} 条 skill 落点登记）")
        if drifted:
            print(f"[dry-run] 注意：{len(drifted)} 个文件被本地改过，本次带 --force ⇒ 会覆盖")
        print("[dry-run] 未落盘。")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    for entry in plan:
        (target / entry["path"]).write_text(entry.pop("_data"), encoding="utf-8")

    manifest = {
        "schema": 1,
        "generator": "low-precision-train-agent/scripts/install_agents.sh",
        "framework_version": version,
        "target_dir": str(target),
        # 刻意不写时间戳：保证 install 连跑两次**逐字节一致**（幂等可机械核对）
        "files": [
            {k: e[k] for k in ("path", "role", "source", "sha256", "bytes")} for e in plan
        ],
        "skills": skills_plan,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"已安装 {len(plan)} 个角色文件到 {target}")
    for entry in manifest["files"]:
        print(f"  {entry['path']}  sha256={entry['sha256']}")
    print(f"manifest: {manifest_path}（卸载的唯一依据）")
    print("生效时机（照注册表实现，见 scripts/README.md §1 规矩⑤）：")
    print("  · 改已有角色文件：下次 use_agent 调用即生效，**不用**重启 dsh；")
    print("  · 新增角色文件：可**立即按名调用**，但要出现在 use_agent 的工具名册里需**重启 dsh**。")
    print("  ⇒ 推荐顺序：**先装、后开会话**（会话在安装之后启动，名册里就带上这四个角色）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
