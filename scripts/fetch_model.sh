#!/usr/bin/env bash
# scripts/fetch_model.sh —— 把一个 HF 模型仓拉到本机目录：**官方端点先试，失败换镜像**，下完自证。
#
# 归属：资产获取（模型侧）。落点复用任务配置 `model.source.{url,path}`（不新造第二个落点）：
#   `url`  = 从哪下（`hf:<org>/<repo>`／`https://huggingface.co/<org>/<repo>`／`https://hf-mirror.com/<org>/<repo>`）
#   `path` = 下到哪（本机目录；也是 `model.start` 的上游）
#
# 行为契约（fail-closed：说不清就退出 2，不许猜）：
#   1. 端点与镜像**只从 `config/project.yaml` 的 `fetch.*` 读**（缺段/缺键 ⇒ 内建默认，并打印「内建默认」）。
#      本脚本不写死任何 URL，也不猜模型名。
#   2. **幂等**：目标目录里已有 `config.json` ＋ 至少一个权重文件 ⇒ 视为已就绪，打印实测摘要后退出 0（不重下）。
#   3. 下载前查**目标盘空闲**（`fetch.min_free_gb`，默认 50）：不够 ⇒ 退出 2，并给「还差多少 / 放哪个盘」。
#   4. 工具只用官方实现：`hf` > `huggingface-cli` > `python -m` 的 `snapshot_download`；
#      三者都没有 ⇒ 退出 2 并给安装命令（不自己 pip 装：会改进环境而不留记录）。
#   5. 官方端点失败（rc≠0）才换镜像；两次都失败 ⇒ 退出 2，打印**两条可复现命令**与原样报错尾部。
#   6. 支持断点续传（官方工具默认行为），失败**不删**已下内容。
#   7. `--print`：只打印将执行的命令（含两个端点）后退出 0，不落盘、不联网。
#   8. `--dry-run`：查依赖/磁盘/目标状态；0 = 已就绪；3 = 需要下载（没下）；2 = 契约或环境不过。
#
# 用法：
#   bash scripts/fetch_model.sh --task <任务名|任务配置路径> [--print|--dry-run]
#   bash scripts/fetch_model.sh --repo <org/name> --dest <目录> [--revision <rev>] [--print|--dry-run]
#   可选：--revision <rev>（分支/tag/提交）｜--force（已就绪也重下）｜--mirror-only（跳过官方端点）
#
# 退出码：0 已就绪或下载并自证通过／3 仅 `--dry-run`：需要下载／2 契约或环境不过（参数、端点、磁盘、工具、下载失败）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$ROOT" "$@" <<'PY'
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
ARGS = sys.argv[2:]
DEFAULT_ENDPOINT = "https://huggingface.co"
DEFAULT_MIRROR = "https://hf-mirror.com"
DEFAULT_MIN_FREE_GB = 50

class Fail(Exception):
    """契约/环境不过：一律退出 2（与 `scripts/install_env.sh` 同规矩）。"""

def die(msg, code=2):
    raise Fail(msg)

def need_yaml(root):
    try:
        import yaml  # noqa: F401
    except ImportError:
        die("缺 PyYAML：本脚本要读 config/*.yaml ⇒ 先 `pip install pyyaml`（引擎也这么要求）")
    import yaml
    return yaml

def parse(argv):
    opts = {"task": None, "repo": None, "dest": None, "revision": None,
            "print": False, "dry_run": False, "force": False, "mirror_only": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--help"):
            print("用法：bash scripts/fetch_model.sh --task <任务名|任务配置> [--print|--dry-run]")
            print("      bash scripts/fetch_model.sh --repo <org/name> --dest <目录> [--revision <rev>]")
            print("可选：--force（已就绪也重下）｜--mirror-only（跳过官方端点）；退出码 0/3/2")
            raise SystemExit(0)
        if a in ("--print", "--dry-run", "--force", "--mirror-only"):
            opts[a.lstrip("-").replace("-", "_")] = True
            i += 1
            continue
        if a in ("--task", "--repo", "--dest", "--revision"):
            if i + 1 >= len(argv):
                die(f"`{a}` 后面缺值")
            opts[a.lstrip("-")] = argv[i + 1]
            i += 2
            continue
        die(f"不认识的参数：{a!r}（见文件头用法）")
    return opts

def load_project(root):
    yaml = need_yaml(root)
    p = root / "config" / "project.yaml"
    if not p.is_file():
        die(f"配置根指错、不回退：{root} 里没有 config/project.yaml")
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        die("config/project.yaml 顶层必须是键值表")
    return doc

def fetch_cfg(project):
    """端点/镜像/最小空闲 GB：**只从工程级配置读**；缺 ⇒ 内建默认并打印来源。"""
    raw = project.get("fetch") or {}
    if not isinstance(raw, dict):
        die("config/project.yaml 的 fetch 必须是键值表")
    rows = []
    def pick(key, default):
        val = raw.get(key)
        if val is None:
            rows.append((key, default, f"内建默认（config/project.yaml 没有 fetch.{key}）"))
            return default
        if isinstance(val, str) and not val.strip():
            rows.append((key, default, f"config/project.yaml#fetch.{key} 是空串 ⇒ 内建默认"))
            return default
        rows.append((key, val, "config/project.yaml#fetch." + key))
        return val
    endpoint = str(pick("hf_endpoint", DEFAULT_ENDPOINT)).strip().rstrip("/")
    mirror = str(pick("hf_mirror", DEFAULT_MIRROR)).strip().rstrip("/")
    gb = pick("min_free_gb", DEFAULT_MIN_FREE_GB)
    try:
        gb = float(gb) if str(gb).strip() not in ("", "None") else float(DEFAULT_MIN_FREE_GB)
    except (TypeError, ValueError):
        die(f"fetch.min_free_gb 不是数字：{gb!r}")
    return endpoint, mirror, gb, rows

def load_task(root, name):
    yaml = need_yaml(root)
    if name.endswith(".yaml") or "/" in name:
        p = Path(name) if os.path.isabs(name) else (Path.cwd() / name)
        if not p.is_file():
            die(f"任务配置不存在：{p}")
    else:
        p = root / "config" / "tasks" / f"{name}.yaml"
        if not p.is_file():
            die(f"任务配置不存在：{p}")
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        die(f"任务配置读不出来：{p}（{exc}）")
    if not isinstance(doc, dict):
        die(f"任务配置顶层必须是键值表：{p}")
    return p, doc

def parse_hf_url(url):
    """把任务配置里的 url 解析成 HF 仓 id；不是 HF 形状 ⇒ 返回 None（不猜）。"""
    text = "" if url is None else str(url).strip()
    if not text:
        return None
    for prefix in ("hf:", "hf://"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    for host in ("https://huggingface.co/", "http://huggingface.co/",
                 "https://hf-mirror.com/", "http://hf-mirror.com/"):
        if text.startswith(host):
            text = text[len(host):]
    text = text.strip("/")
    if text.startswith("http://") or text.startswith("https://") or text.startswith("/"):
        return None
    # 允许尾随 `@revision`
    return text or None

def which_tool():
    if shutil.which("hf"):
        return ("hf", None)
    if shutil.which("huggingface-cli"):
        return ("huggingface-cli", None)
    probe = subprocess.run([sys.executable, "-c", "import huggingface_hub"], capture_output=True)
    if probe.returncode == 0:
        return ("python", sys.executable)
    return (None, None)

def is_ready(dest):
    """已就绪的判据（有一条不满足就算没就绪）：config.json 在且能解析，且至少一个权重文件非空。"""
    if not dest.is_dir():
        return False, "目录不存在"
    cfg = dest / "config.json"
    if not cfg.is_file():
        return False, "缺 config.json"
    try:
        import json
        json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return False, "config.json 解析不了"
    weights = [p for p in dest.rglob("*")
               if p.is_file() and p.suffix in (".safetensors", ".bin", ".pt", ".gguf", ".pth") and p.stat().st_size > 0]
    if not weights:
        return False, "没有非空权重文件"
    return True, f"{len(weights)} 个权重文件"

def summarize(dest):
    files = [p for p in dest.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    return f"{dest}：{len(files)} 个文件，{total / (1024 ** 3):.2f} GiB"

def free_gib(path):
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / (1024 ** 3)

def commands(tool, repo, dest, rev, endpoint, extra_env=None):
    """返回 [(人读说明, argv)] —— `--print` 与真跑用的是**同一份** argv（不各写一套）。"""
    extra = [f"--revision={rev}"] if rev else []
    env = {"HF_ENDPOINT": endpoint}
    env.update(extra_env or {})
    desc = " ".join(f"{k}={v}" for k, v in env.items())
    if tool == "hf":
        return [(desc, ["hf", "download", repo, f"--local-dir={dest}", *extra])], env
    if tool == "huggingface-cli":
        return [(desc, ["huggingface-cli", "download", repo, "--local-dir", str(dest), *extra])], env
    if tool == "python":
        code = ("import sys\nfrom huggingface_hub import snapshot_download\n"
                "snapshot_download(repo_id=sys.argv[1], local_dir=sys.argv[2],"
                " revision=(sys.argv[3] or None))\n")
        argv = [sys.executable, "-c", code, repo, str(dest), rev or ""]
        return [(desc, argv)], env
    return [], env


def reachable(url, timeout=3.0):
    """端点能不能在建连超时内接上。**只用来省掉官方工具的长重试**，不代表下载一定成功。"""
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def run(argv, env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(argv, env=env, capture_output=True, text=True)

def main():
    opts = parse(ARGS)
    project = load_project(ROOT)
    endpoint, mirror, min_gb, cfg_rows = fetch_cfg(project)

    repo, dest, rev, task_path = opts["repo"], opts["dest"], opts["revision"], None
    if opts["task"]:
        task_path, task = load_task(ROOT, opts["task"])
        src = task.get("model", {}).get("source", {}) if isinstance(task.get("model"), dict) else {}
        src = src if isinstance(src, dict) else {}
        if not repo:
            parsed = parse_hf_url(src.get("url"))
            if not parsed:
                die(f"任务配置 {task_path} 的 model.source.url 解析不出 HF 仓（值：{src.get('url')!r}）；"
                    f"要么改成 `hf:<org>/<repo>`，要么用 `--repo` 指名")
            repo = parsed
            print(f"仓库：{repo}（来自 {task_path}#model.source.url）")
        if not dest:
            dest = src.get("path")
            if not dest or str(dest).strip() in ("", "default") or str(dest).startswith("<"):
                die(f"任务配置 {task_path} 的 model.source.path 还是占位（{dest!r}）；用 `--dest` 指名落点")
            print(f"落点：{dest}（来自 {task_path}#model.source.path）")
    if not repo:
        die("缺 `--repo`（或 `--task` 且任务配置有 model.source.url）")
    if not dest:
        die("缺 `--dest`（或 `--task` 且任务配置有 model.source.path）")
    dest = Path(str(dest))

    for key, val, src in cfg_rows:
        print(f"fetch.{key} = {val}（{src}）")

    ready, why = is_ready(dest)
    if ready and not opts["force"]:
        print(f"已就绪，跳过下载：{summarize(dest)}（判据：config.json 可解析 ＋ {why}）")
        return 0

    tool, _ = which_tool()
    if tool is None:
        die("找不到下载工具：`hf`／`huggingface-cli`／python 包 huggingface_hub 都没有。\n"
            "     装一个：pip install -U huggingface_hub   （装完重跑本脚本）")

    # 官方端点先**探一下可达性**（3s）：连不上就不必让官方工具白重试几分钟。
    ends = []
    if not opts["mirror_only"]:
        # `--print` 不探测：只打印计划，两次跑必须字面一致（真跑的探测放在执行前）。
        if opts["print"] or reachable(endpoint):
            ends.append(("官方", endpoint))
        else:
            print(f"跳过官方端点：{endpoint} 3s 内连不上（不让官方工具在那儿空转重试）")
    # ★ 镜像一律关掉 Xet：`hf` 1.x 的大文件走 Xet CAS（`cas-server.xethub.hf.co`），
    #   镜像不代理那个域 ⇒ 元数据能下、权重 401。`HF_HUB_DISABLE_XET=1` 让它走普通 HTTP 分片。
    ends.append(("镜像", mirror))
    plan = []
    for label, ep in ends:
        extra_env = {"HF_HUB_DISABLE_XET": "1"} if label == "镜像" else None
        cmds, env = commands(tool, repo, dest, rev, ep, extra_env)
        plan.append((label, ep, cmds, env))

    if opts["print"]:
        if not opts["mirror_only"]:
            print("（真跑时先用 3s 探测官方端点：连不上就跳过，省掉官方工具的长重试）")
        print("将要执行（按顺序，前一条失败才试下一条）：")
        for label, ep, cmds, _env in plan:
            for desc, argv in cmds:
                print(f"  [{'%s端点' % label}] {desc} {' '.join(argv)}")
        print(f"落点：{dest}（已存在则官方工具默认续传）")
        return 0

    if opts["dry_run"]:
        free = free_gib(dest.parent if dest.parent.exists() else ROOT)
        print(f"目标盘空闲：{free:.1f} GiB（要求 ≥ {min_gb:g} GiB）")
        if free < min_gb:
            die(f"目标盘空闲不够：{free:.1f} GiB < {min_gb:g} GiB ⇒ 换盘或删东西后再来")
        print(f"状态：需要下载（当前问题：{why}）")
        print("（--dry-run 不落盘；去掉它才真下）")
        return 3

    free = free_gib(dest.parent if dest.parent.exists() else ROOT)
    if free < min_gb:
        die(f"目标盘空闲不够：{free:.1f} GiB < {min_gb:g} GiB ⇒ 换盘或删东西后再来（不许半途而废）")
    dest.parent.mkdir(parents=True, exist_ok=True)

    errors = []
    for label, ep, cmds, env in plan:
        for desc, argv in cmds:
            print(f"[{label}端点] {desc} {' '.join(argv)}")
        res = run(argv, env) if cmds else None
        if res is not None and res.returncode == 0:
            ok, why2 = is_ready(dest)
            if ok:
                print(f"下载完成并自证通过（{label}端点）：{summarize(dest)}")
                print(f"要填进任务配置的值：model.source.path = {dest}")
                return 0
            errors.append(f"{label}端点：命令成功但自证不过（{why2}）")
        else:
            tail = ((res.stderr or res.stdout or "")[-600:].strip() if res else "命令没生成")
            errors.append(f"{label}端点 rc={getattr(res, 'returncode', '?')}：{tail}")

    print("两条路都没成，原样报错如下：", file=sys.stderr)
    for e in errors:
        print(f"  - {e}", file=sys.stderr)
    print("可复现命令（自己重跑一条看完整输出）：", file=sys.stderr)
    for label, ep, cmds, _env in plan:
        for desc, argv in cmds:
            print(f"  {desc} {' '.join(argv)}", file=sys.stderr)
    die("下载失败：这属于**环境未就绪**，不归训练/评测无效（不是 5/6）。排查顺序：网络 → 端点可达 → 磁盘 → 权限")

try:
    sys.exit(main())
except Fail as exc:
    print(f"fetch_model.sh：{exc}", file=sys.stderr)
    sys.exit(2)
except KeyboardInterrupt:
    print("fetch_model.sh：被中断（已下内容保留，重跑会续传）", file=sys.stderr)
    sys.exit(2)
PY
