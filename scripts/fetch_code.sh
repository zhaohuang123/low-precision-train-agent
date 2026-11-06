#!/usr/bin/env bash
# scripts/fetch_code.sh —— 代码仓的**下载**与**切换**：clone 到指定分支/tag/提交，或把已有检出切到指定 ref。切完自证。
#
# 归属：资产获取（代码侧）。落点复用任务配置 `train.{framework_repo,framework_url,framework_head}` /
# `train.{core_repo,core_url,core_head}`（不新造第二个落点）。
#
# ★ 与钉点的关系（本脚本最容易被误用的地方，写死在这里）：
#   `framework_head`／`core_head` 是**本轮起点的钉点**，`scripts/preflight.sh` 会拿它跟 `git rev-parse HEAD` 比对。
#   所以：**切换 ref ⇒ 钉点必变**。本脚本**只切换、不改配置**，切完把「要改成什么」打印出来；
#   不同步改钉点就开跑 ⇒ preflight 拒绝（这是设计如此，不是 bug）。
#   **轮次进行中不许用本脚本**（会打碎本轮钉点）：先停轮次，或按 `requests/README.md` 提诉求。
#
# 行为契约：
#   1. 读任务配置（唯一落点）定位 repo/pin；`--repo train|core` 选哪一个。
#   2. 已有检出时**先看脏不脏**：`git status --porcelain` 非空 ⇒ 退出 2（不 `reset --hard`、不丢改动）；
#      确认要硬切由人显式加 `--allow-dirty`（仍然不丢改动，只是允许带着脏树切）。
#   3. `--clone`：目标不存在（或空目录）时从 `--url`（缺省用任务配置的 `*_url`，再缺省用现有检出的
#      `git remote get-url origin`）克隆，再切到 `--ref`（缺省＝钉点）。
#   4. `--ref <ref>`：已有检出上 `git fetch origin <ref>`（拿不到就试全量 `git fetch origin`）＋ `git checkout <ref>`。
#   5. `--check`（无 `--ref`/`--clone` 时的默认动作）：只比对「当前 HEAD vs 钉点」＋「工作树干净」，不切换。
#   6. 每一步后用 `rev-parse HEAD` 与 `status --porcelain` **自证**；失败一律退出 2。
#   7. 只碰目标仓；不 commit、不 push、不改配置、不碰别的仓。
#
# 用法：
#   bash scripts/fetch_code.sh --task <任务名|任务配置路径> --repo train [--check]
#   bash scripts/fetch_code.sh --task <任务名|任务配置路径> --repo core --clone --ref <分支或提交>
#   bash scripts/fetch_code.sh --task <任务名|任务配置路径> --repo train --ref <分支> [--print]
#   可选：--url <远端>｜--dest <目录>｜--allow-dirty
#
# 退出码：0 成功/已一致／2 契约或环境不过（脏树、ref 拿不到、自证不符、参数错）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$ROOT" "$@" <<'PY'
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
ARGS = sys.argv[2:]

class Fail(Exception):
    pass

def die(msg, code=2):
    raise Fail(msg)

def need_yaml():
    try:
        import yaml
    except ImportError:
        die("缺 PyYAML：本脚本要读 config/tasks/*.yaml ⇒ 先 `pip install pyyaml`")
    return yaml

def parse(argv):
    opts = {"task": None, "repo": None, "ref": None, "url": None, "dest": None,
            "check": False, "clone": False, "print": False, "allow_dirty": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print("用法：bash scripts/fetch_code.sh --task <任务名|任务配置> --repo <train|core> [--check|--clone] [--ref <ref>]")
            print("可选：--url <远端>｜--dest <目录>｜--allow-dirty｜--print；退出码 0/2")
            raise SystemExit(0)
        if a in ("--check", "--clone", "--print", "--allow-dirty"):
            opts[a.lstrip("-").replace("-", "_")] = True
            i += 1
            continue
        if a in ("--task", "--repo", "--ref", "--url", "--dest"):
            if i + 1 >= len(argv):
                die(f"`{a}` 后面缺值")
            opts[a.lstrip("-")] = argv[i + 1]
            i += 2
            continue
        die(f"不认识的参数：{a!r}（见文件头用法）")
    if not opts["repo"] or opts["repo"] not in ("train", "core"):
        die("必须给 `--repo train` 或 `--repo core`（选哪个仓）")
    if not opts["task"]:
        die("必须给 `--task <任务名|任务配置路径>`（钉点与落点只从任务配置读）")
    return opts

def load_task(name):
    yaml = need_yaml()
    if name.endswith(".yaml") or "/" in name:
        p = Path(name) if os.path.isabs(name) else (Path.cwd() / name)
    else:
        p = ROOT / "config" / "tasks" / f"{name}.yaml"
    if not p.is_file():
        die(f"任务配置不存在：{p}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        die(f"任务配置读不出来：{p}（{exc}）")
    if not isinstance(doc, dict) or not isinstance(doc.get("train"), dict):
        die(f"任务配置缺 train 段：{p}")
    return p, doc

def git(dest, *args, check=True):
    res = subprocess.run(["git", "-C", str(dest), *args], capture_output=True, text=True)
    if check and res.returncode != 0:
        die(f"git {' '.join(args)} 失败（{dest}）：{(res.stderr or res.stdout).strip()[-500:]}")
    return res

def head(dest):
    res = git(dest, "rev-parse", "HEAD", check=False)
    return res.stdout.strip() if res.returncode == 0 else ""

def dirty(dest):
    res = git(dest, "status", "--porcelain", check=False)
    return res.stdout.strip() if res.returncode == 0 else ""

def remote_of(dest):
    res = git(dest, "remote", "get-url", "origin", check=False)
    return res.stdout.strip() if res.returncode == 0 else ""

def same_ref(a, b):
    if not a or not b:
        return False
    return a == b or a.startswith(b) or b.startswith(a)

def plan_clone(url, dest, ref):
    return [["git", "clone", url, str(dest)],
            ["git", "-C", str(dest), "checkout", ref] if ref else ["git", "-C", str(dest), "status", "--porcelain"]]

def plan_switch(dest, ref):
    return [["git", "-C", str(dest), "fetch", "origin", ref],
            ["git", "-C", str(dest), "checkout", ref]]

def main():
    opts = parse(ARGS)
    task_path, task = load_task(opts["task"])
    train = task["train"]
    key = "framework" if opts["repo"] == "train" else "core"
    dest_raw = train.get(f"{key}_repo")
    pin = train.get(f"{key}_head")
    url = opts["url"] or train.get(f"{key}_url")
    print(f"仓：{key}（来自 {task_path}#train.{key}_repo）")
    if not dest_raw or str(dest_raw).strip() in ("", "default") or str(dest_raw).startswith("<"):
        die(f"任务配置 {task_path} 的 train.{key}_repo 还是占位（{dest_raw!r}）；先填部署事实，再下载/切换")
    dest = Path(str(dest_raw))
    pin = "" if pin is None or str(pin).startswith("<") else str(pin).strip()
    print(f"落点：{dest}")
    print(f"钉点：{key}_head = {pin or '（未填）'}")

    exists = dest.is_dir() and (dest / ".git").exists()
    ref = opts["ref"] or pin or ""

    # ── 默认动作：只比对 ──
    if opts["check"] or (not opts["ref"] and not opts["clone"]):
        if not exists:
            die(f"{dest} 不是 git 检出（没有 .git）；要下载就加 `--clone`，要切换就给它一个已有检出")
        cur = head(dest)
        d = dirty(dest)
        ok_pin = same_ref(cur, pin) if pin else None
        print(f"当前 HEAD：{cur}")
        print(f"工作树：{'干净' if not d else '有未提交改动'}")
        if pin:
            print(f"与钉点{'一致' if ok_pin else '**不一致**'}：{pin}")
        if pin and not ok_pin:
            die("钉点不一致 ⇒ preflight 会拒绝开跑。处置：① 切回钉点（`--ref <钉点>`）② 或按新 ref 同步改钉点")
        if d:
            die("工作树不干净：本脚本不 reset、不丢改动；先自己处理（stash/commit/还原）再来")
        print("自证：工作树干净" + ("、HEAD 与钉点一致 ⇒ 可以开跑" if pin else "（任务配置没填钉点 ⇒ 未比钉点）"))
        return 0

    if not ref:
        die("没给 `--ref`，任务配置也没有钉点 ⇒ 说不清要切到哪（不许猜）")

    # ── --print ──
    if opts["print"]:
        plan = plan_clone(url or "<缺：--url 或 train.*_url>", dest, ref) if (opts["clone"] or not exists) \
               else plan_switch(dest, ref)
        print("将要执行：")
        for argv in plan:
            print("  " + " ".join(argv))
        return 0

    if not exists:
        if not opts["clone"]:
            die(f"{dest} 不存在（或不是 git 检出）；要下载就加 `--clone`（会先建目录）")
        if not url:
            die("不知道从哪克隆：给 `--url`，或在任务配置里填 train." + key + "_url")
        if dest.exists() and any(dest.iterdir()):
            die(f"{dest} 已存在且非空，不能克隆进去；换个落点或先清空（不替你删）")
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"克隆：git clone {url} {dest}")
        res = subprocess.run(["git", "clone", url, str(dest)], capture_output=True, text=True)
        if res.returncode != 0:
            die(f"git clone 失败：{(res.stderr or res.stdout).strip()[-600:]}")
        print(f"切换到：{ref}")
        git(dest, "checkout", ref)
    else:
        d = dirty(dest)
        if d and not opts["allow_dirty"]:
            die("工作树有未提交改动（本脚本不 reset、不丢改动）：\n" + d[:600] +
                "\n处置：先处理干净，或显式加 `--allow-dirty`（仍然不丢你的改动，只是允许带着脏树切）")
        print(f"拉取：git fetch origin {ref}")
        res = git(dest, "fetch", "origin", ref, check=False)
        if res.returncode != 0:
            print("  （定向 fetch 失败，改试全量 fetch origin）")
            git(dest, "fetch", "origin")
        print(f"切换：git checkout {ref}")
        try:
            git(dest, "checkout", ref)
        except Fail:
            print("  （本地没有该 ref，按远端分支建）")
            git(dest, "checkout", "-B", ref, f"origin/{ref}")

    # ── 自证 ──
    cur = head(dest)
    d = dirty(dest)
    if not cur:
        die("自证失败：取不到 HEAD")
    print(f"切换完成，HEAD = {cur}")
    if d:
        print(f"工作树仍有改动（--allow-dirty 场景）：\n{d[:400]}")
    if not pin:
        print(f"（任务配置没填 train.{key}_head ⇒ **未做钉点比对**；"
              f"填上它，preflight 才知道该在哪个提交上开跑）")
    elif not same_ref(cur, pin):
        print("★ 钉点需要同步（本脚本不改配置）：")
        print(f"    {task_path}#train.{key}_head: {pin or '（空）'} → {cur}")
        print("  不改就开跑 ⇒ scripts/preflight.sh 会拒绝（设计如此）。")
    else:
        print("与钉点一致，无需改配置。")
    return 0

try:
    sys.exit(main())
except Fail as exc:
    print(f"fetch_code.sh：{exc}", file=sys.stderr)
    sys.exit(2)
except KeyboardInterrupt:
    print("fetch_code.sh：被中断", file=sys.stderr)
    sys.exit(2)
PY
