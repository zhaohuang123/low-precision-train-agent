#!/usr/bin/env bash
# scripts/install_env.sh —— 建评测用的 venv 并**钉** `lm_eval` 版本（P10 已实现；0.18.13 起判"能不能跑"）。
#
# 归属：评测环境构建（读任务配置的 `eval.lm_eval.{package,version,python}`）。
#
# 行为契约（逐条实现，全部 fail-closed：说不清就退出 2，不许猜、不许静默换版本）：
#   1. 读任务配置的评测字段（**唯一落点**）：`eval.engine`、`eval.lm_eval.{package,version,python}`。
#      先经 `python3 runtime/config.py <任务配置>` 校验；校验不过 ⇒ 退出 2（不再动手）。
#   2. venv 落点**由配置推出来**（不另设第二个落点）：`eval.lm_eval.python` 形如
#      `<venv 根>/bin/python` ⇒ 建 venv 到 `<venv 根>`，把 `version` 精确钉成 `<package>==<version>`。
#   3. **建法固定为继承**（0.18.13）：`python3 -m venv --system-site-packages <venv 根>` —— 评测必须用
#      **与训练同一个** torch / torch_npu。隔离建 venv 只会装到裸 `lm-eval`（它的 torch/transformers 在
#      `hf` extra 里，裸装不拉），而 `lm_eval --model hf` 在 `lm_eval/models/huggingface.py:10` 就 import torch
#      ⇒ 隔离建出来的环境"装上了但跑不了"，且会在**训练卡花完之后**才炸。
#   4. **验收以"能 import"为准，不以 dist-info 存在为准**（0.18.13）：装完回读版本后，再用目标解释器跑一次
#      `import torch, transformers, lm_eval, torch_npu`；任一失败 ⇒ 退出 2（指名缺哪个、给修法）。
#      只查 `importlib.metadata.version()` = 静默失败（C5：验收三条全过、实跑没有 torch）。
#   5. 幂等：解释器已存在、包版本一致、**且可运行性过** ⇒ 不重装、退出 0；版本不一致 ⇒ 退出 2
#      （不许静默换版本）；装上了但跑不了 ⇒ 退出 2（**不自动 `pip install torch`**：那会用 PyPI 的 CPU
#      torch 悄悄换掉 Ascend 栈，评测口径随之变化而无人记录）。
#   6. `--dry-run`：打印将创建/安装什么、建法、可运行性，**不落盘**；退出码**必须可判定**：
#      0 = 已就绪（版本逐字一致 ＋ 可运行性过）／3 = 需要安装（解释器缺／包缺／版本不一致）／
#      4 = 需修（主环境或 venv 缺 torch/torch_npu/transformers，或 NPU 不可见 ⇒ 跑一次也装不好，得人来决定）。
#      只打印不看码 =
#      preflight 的假阳性（`preflight.sh` ④ 曾恒绿灯）。
#   7. 只对工程**外部**的 venv 目录操作：不碰框架检出、不碰旧工程、不写 `git` 任何东西。
#   8. 安装记录写到 `<venv 根>/.lpta-env-install.json`（schema 2）：包名/版本/解释器/任务配置 ＋
#      **建法**（含基解释器）＋ **实际生效的 torch / torch_npu / transformers / accelerate / datasets 版本**
#      ＋ NPU 可见性 ＋ 被 venv 遮住的包（`shadowed`）。内容（除两个时间戳）不变就不重写，保持逐字节稳定。
#
# 用法：
#   bash scripts/install_env.sh --task <任务名|任务配置路径> --dry-run
#   bash scripts/install_env.sh --task <任务名|任务配置路径>
#
# 退出码：0 成功／已是目标状态；2 契约不过（字段缺、占位值、配置校验不过、版本对不上、用法错）；
#         3 仅 `--dry-run`：还需要安装；4 仅 `--dry-run`：需修（缺运行所需的包／NPU 不可见）。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 配置根：解析不出来就退出 2（fail-closed）

exec python3 - --root "$ROOT" "$@" <<'PY'
"""install_env.sh 的实现体（嵌入式，避免额外文件）。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = ".lpta-env-install.json"
EXIT_CONTRACT = 2      # 约定/契约不过（fail-closed）
EXIT_NEED_INSTALL = 3  # 仅 --dry-run：还需要安装（跑一次能装好）
EXIT_NEED_FIX = 4      # 仅 --dry-run：需修（跑一次也装不好：缺 torch/torch_npu/transformers，或 NPU 不可见）

# 评测段**真的会 import** 的模块（`lm_eval --model hf` 在 `lm_eval/models/huggingface.py:10` 就 import
# torch/transformers）。**硬要求，一个都不许少**：装上了 ≠ 跑得了。
NEED_MODULES = ("torch", "transformers", "lm_eval", "torch_npu")
# 主环境必须能提供的（`lm_eval` 是自己要装的那个，不算）
BASE_NEED = ("torch", "transformers", "torch_npu")
# 记录里要回答"这份环境到底用了哪个 torch / torch_npu"（不变量：继承来的也要记）
KEY_MODULES = ("torch", "torch_npu", "transformers", "accelerate", "datasets")

PROBE_CODE = r'''
import importlib, json
mods = ("torch", "torch_npu", "transformers", "accelerate", "datasets", "lm_eval")
versions, missing = {}, {}
for m in mods:
    try:
        versions[m] = getattr(importlib.import_module(m), "__version__", None)
    except Exception as exc:
        missing[m] = f"{type(exc).__name__}: {exc}".splitlines()[0][:200]
npu = None
if "torch" in versions:
    try:
        import torch
        npu = {"available": bool(torch.npu.is_available()), "device_count": int(torch.npu.device_count())}
    except Exception as exc:
        npu = {"available": False, "device_count": 0, "error": f"{type(exc).__name__}: {exc}"[:200]}
print(json.dumps({"versions": versions, "missing": missing, "npu": npu}))
'''

try:
    import yaml
except Exception:  # pragma: no cover
    print("install_env.sh: 缺 PyYAML ⇒ 退出 2（配置是唯一的字段落点，解析不了就不许动手）", file=sys.stderr)
    raise SystemExit(EXIT_CONTRACT)


def die(msg: str) -> "None":
    print(f"install_env.sh: {msg}", file=sys.stderr)
    raise SystemExit(EXIT_CONTRACT)


def resolve_root(path: Path) -> Path:
    """配置根：`config/project.yaml` 与 `VERSION` 都在才算数（指错不回退）。"""
    root = path.resolve()
    if not (root / "config" / "project.yaml").is_file() or not (root / "VERSION").is_file():
        die(f"配置根解析不出来：{root} 里没有 config/project.yaml 或 VERSION")
    return root


def pick_task_config(root: Path, arg: "str | None") -> Path:
    """`--task` 给名字（`config/tasks/<名>.yaml`）或路径（以 .yaml 结尾，相对当前目录）。"""
    if arg:
        if arg.endswith(".yaml") or "/" in arg:
            path = Path(arg).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            if not path.is_file():
                die(f"任务配置不存在：{path}")
            return path.resolve()
        path = root / "config" / "tasks" / f"{arg}.yaml"
        if not path.is_file():
            die(f"任务配置不存在：{path}")
        return path
    cands = sorted(p for p in (root / "config" / "tasks").glob("*.yaml") if not p.name.startswith("_"))
    if len(cands) == 1:
        return cands[0]
    die(f"没有指名 --task，且 config/tasks/ 下非模板任务配置有 {len(cands)} 份"
        f"（{', '.join(p.name for p in cands) if cands else '0 份'}）⇒ 不猜，请用 --task 指名")


def validate_config(root: Path, task_config: Path) -> None:
    """经 `runtime/config.py validate` 校验（校验实现唯一一份，不在这里重写）。"""
    helper = root / "runtime" / "config.py"
    if not helper.is_file():
        die(f"找不到校验器：{helper}（配置校验实现唯一一份，缺它就没有字段级判据）")
    proc = subprocess.run(
        [sys.executable, str(helper), "--root", str(root), str(task_config)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        die(f"任务配置校验不过（runtime/config.py rc={proc.returncode}）：{task_config}")


def read_field(doc: dict, *keys: str):
    cur = doc
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def is_placeholder(value) -> bool:
    """占位值：空串、`<...>` 形式（与 runtime/config.py 的占位值规则同一口径）。"""
    if not isinstance(value, str) or not value.strip():
        return True
    return "<" in value and ">" in value


def read_back_version(python: Path, package: str) -> "tuple[int, str]":
    """回读已安装版本；返回 (rc, 输出/错误)。包不在时 importlib.metadata 抛 PackageNotFoundError。"""
    code = (
        "import importlib.metadata as m\n"
        f"print(m.version({package!r}))\n"
    )
    proc = subprocess.run([str(python), "-c", code], capture_output=True, text=True)
    if proc.returncode != 0:
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    return 0, proc.stdout.strip()


def probe(python: Path) -> dict:
    """用 `python` 跑一次真实 import，拿到版本、缺什么、NPU 可见性。

    这是"能不能跑"的唯一判据实现 —— `importlib.metadata` 只证明 dist-info 存在，证明不了可运行。
    """
    proc = subprocess.run([str(python), "-c", PROBE_CODE], capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip().splitlines()
        return {"versions": {}, "missing": {"<探测解释器失败>": detail[-1][:200] if detail else "rc!=0"}, "npu": None}
    try:
        data = json.loads(proc.stdout)
    except Exception as exc:  # 探测脚本被别的输出污染
        return {"versions": {}, "missing": {"<探测输出不是 JSON>": str(exc)[:200]}, "npu": None}
    data.setdefault("versions", {})
    data.setdefault("missing", {})
    data.setdefault("npu", None)
    return data


def venv_info(venv_root: Path) -> dict:
    """从 `pyvenv.cfg` 读建法（记录用，**不拿它当判据** —— 判据只看能不能 import）。"""
    cfg = venv_root / "pyvenv.cfg"
    fields: dict[str, str] = {}
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                fields[key.strip()] = value.strip()
    inherited = fields.get("include-system-site-packages", "").lower() == "true"
    base = fields.get("executable")
    if not base and fields.get("home"):
        base = str(Path(fields["home"]) / "python3")
    return {
        "mode": "system-site-packages" if inherited else "isolated",
        "system_site": inherited,
        "base_interpreter": base,
    }


def judge(python: Path, package: str, version: str) -> "tuple[int, str, list[str]]":
    """**唯一判据**（`--dry-run` 与真跑共用，避免两套标准）：

    返回 (rc, 状态, 明细行)；rc：0 已就绪／3 需安装（跑一次能装好）／2 需修（跑一次装不好，得人决定）。
    """
    if not python.is_file():
        return EXIT_NEED_INSTALL, "需安装", [f"解释器不存在 ⇒ 将创建 {python.parent.parent}"]
    rc, got = read_back_version(python, package)
    if rc != 0:
        return EXIT_NEED_INSTALL, "需安装", [f"包读不出来（{package} 不在这个解释器里）⇒ 需安装"]
    if got != version:
        return EXIT_NEED_INSTALL, "需安装", [f"版本不一致（现装 {got}，配置要 {version}）⇒ 需升级"]

    info = probe(python)
    versions = info["versions"]
    missing = [m for m in NEED_MODULES if m in info["missing"]]
    if missing:
        lines = [f"{package} == {got} ✓，但**跑不了**：缺 {', '.join(missing)}"]
        for m in missing:
            lines.append(f"  {m}: {info['missing'][m]}")
        lines.append("  为什么算「跑不了」：`lm_eval --model hf` 在 lm_eval/models/huggingface.py:10 就 import torch")
        lines.append(f"  修法：rm -rf {python.parent.parent} && bash scripts/install_env.sh --task <任务>")
        lines.append("        （脚本用 `--system-site-packages` 建，继承主环境的 torch/torch_npu）")
        return EXIT_NEED_FIX, "需修", lines

    npu = info.get("npu") or {}
    if not npu.get("available"):
        return EXIT_NEED_FIX, "需修", [
            f"{package} == {got} ✓、import 全过，但 **NPU 不可见**（torch.npu.is_available() = False）",
            f"  torch.npu.device_count() = {npu.get('device_count', 0)}"
            + (f"；{npu['error']}" if npu.get("error") else ""),
            "  评测要和训练同一个 Ascend 栈；NPU 不可见时跑出来的分数没有意义",
            "  修法：确认 `npu-smi info` 能看到卡、且主环境的 torch 与 torch_npu 是配对的",
        ]

    shown = "｜".join(f"{m} {versions.get(m, '?')}" for m in NEED_MODULES)
    return 0, "已就绪", [f"{package} == {got}｜可运行性 ✓（{shown}）"]


def base_probe() -> dict:
    """主环境（当前 python3）能不能提供继承所需的三件。"""
    return probe(Path(sys.executable))


def build_record(*, task_config: Path, engine: str, package: str, version: str,
                 python: Path, venv_root: Path, info: dict) -> dict:
    """`.lpta-env-install.json` 的**非时间戳**部分（内容不变就不重写文件）。"""
    versions = info["versions"]
    venv = venv_info(venv_root)

    shadowed: dict[str, dict] = {}
    base = venv.get("base_interpreter")
    if base and Path(base).is_file() and str(Path(base)) != str(python):
        base_info = probe(Path(base))
        for mod in KEY_MODULES:
            here = versions.get(mod)
            there = base_info["versions"].get(mod)
            if here and there and here != there:
                shadowed[mod] = {"venv": here, "base": there}

    return {
        "schema": 2,
        "generator": "low-precision-train-agent/scripts/install_env.sh",
        "task_config": str(task_config),
        "engine": engine,
        "package": package,
        "version": version,
        "python": str(python),
        "venv_root": str(venv_root),
        "build": venv,
        "runnable_check": {
            "ok": True,
            "modules": list(NEED_MODULES),
            "cmd": f"{python} -c \"import {', '.join(NEED_MODULES)}\"",
        },
        "inherited_versions": {mod: versions.get(mod) for mod in KEY_MODULES},
        "npu": info.get("npu") or {},
        "shadowed": shadowed,
    }


def write_record(record_path: Path, payload: dict) -> str:
    """写安装记录；除两个时间戳外内容不变 ⇒ 不重写（连跑两次逐字节稳定）。返回 written/unchanged。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = None
    if record_path.is_file():
        try:
            old = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception:
            old = None
    new = dict(payload)
    new["installed_at"] = (old or {}).get("installed_at") or now
    new["verified_at"] = now

    def stable(doc: dict) -> str:
        return json.dumps({k: v for k, v in doc.items() if k not in ("installed_at", "verified_at")},
                          ensure_ascii=False, sort_keys=True)

    if old is not None and stable(old) == stable(new):
        return "unchanged"
    record_path.write_text(json.dumps(new, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return "written"


def main() -> int:
    ap = argparse.ArgumentParser(add_help=True, description="建评测 venv 并钉 lm_eval 版本（幂等）")
    ap.add_argument("--root", required=True, help=argparse.SUPPRESS)
    ap.add_argument("--task", default=None, help="任务名（config/tasks/<名>.yaml）或任务配置路径")
    ap.add_argument("--dry-run", action="store_true", help="只打印将创建/安装什么与判据结果，不落盘")
    args = ap.parse_args()

    root = resolve_root(Path(args.root))
    task_config = pick_task_config(root, args.task)
    validate_config(root, task_config)

    doc = yaml.safe_load(task_config.read_text(encoding="utf-8")) or {}
    engine = read_field(doc, "eval", "engine")
    package = read_field(doc, "eval", "lm_eval", "package")
    version = read_field(doc, "eval", "lm_eval", "version")
    python = read_field(doc, "eval", "lm_eval", "python")
    for field, value in (("eval.engine", engine), ("eval.lm_eval.package", package),
                         ("eval.lm_eval.version", version), ("eval.lm_eval.python", python)):
        if is_placeholder(value):
            die(f"占位值没换：{field} = {value!r}（先把任务配置填成真值，见 docs/CONFIG.md §5）")
    if engine != "lm_eval":
        die(f"eval.engine = {engine!r} 不认识（当前只实现 lm_eval）")

    python_path = Path(str(python)).expanduser()
    if not python_path.is_absolute():
        python_path = (root / python_path).resolve()
    if python_path.name not in ("python", "python3") or python_path.parent.name != "bin":
        die(f"eval.lm_eval.python = {python!r} 不是 `<venv 根>/bin/python` 形状 ⇒ 由它推不出 venv 落点，退出 2")
    venv_root = python_path.parent.parent
    record_path = venv_root / MANIFEST_NAME
    pinned = f"{package}=={version}"

    # ── 判据（唯一一份；dry-run 与真跑共用）
    rc, state, lines = judge(python_path, package, version)

    if args.dry_run:
        exists = python_path.is_file()
        print(f"[dry-run] root        = {root}")
        print(f"[dry-run] 任务配置    = {task_config}（已过 runtime/config.py 校验）")
        print(f"[dry-run] venv 根     = {venv_root}")
        print(f"[dry-run] 建法        = --system-site-packages（继承主环境的 torch/torch_npu）")
        print(f"[dry-run] 解释器      = {python_path}（{'已存在' if exists else '将创建'}）")
        print(f"[dry-run] 将安装      = {pinned}")
        if exists:
            print(f"[dry-run] 包版本      = {package}（配置要 {version}）")
            print(f"[dry-run] 判据        = {'✓' if rc == 0 else '✗'} {lines[0]}")
            for line in lines[1:]:
                print(f"[dry-run] {'':12s}  {line}")
        else:
            # 还没有 venv：先看主环境能不能提供继承所需的三件（否则建出来也跑不了）
            base = base_probe()
            miss = [m for m in BASE_NEED if m in base["missing"]]
            if miss:
                print(f"[dry-run] 主环境      = ✗ 缺 {', '.join(miss)} ⇒ 继承拿不到，建出来也跑不了")
                state = "需修"
                rc = EXIT_NEED_FIX
            else:
                shown = "｜".join(f"{m} {base['versions'].get(m, '?')}" for m in BASE_NEED)
                print(f"[dry-run] 主环境      = ✓ {shown}")
        print(f"[dry-run] 安装记录    = {record_path}")
        print(f"[dry-run] 状态        = {state}")
        print("[dry-run] 未落盘。")
        return rc

    if python_path.is_file():
        if rc == EXIT_NEED_FIX:  # 装上了但跑不了：跑一次也修不好，必须人来决定
            for line in lines:
                print(f"  {line}", file=sys.stderr)
            die(f"评测环境不可运行（{state}）⇒ 退出 2。许不许换 torch 不归脚本决定（见上方修法）")
        if rc == 0:
            written = write_record(record_path, build_record(
                task_config=task_config, engine=engine, package=package, version=version,
                python=python_path, venv_root=venv_root, info=probe(python_path)))
            print(f"已是目标状态：{python_path} 的 {package} == {version}")
            print(f"可运行性：{lines[0]}")
            print(f"安装记录：{record_path}（{'已刷新' if written == 'written' else '内容未变，未重写'}）")
            return 0
        # rc == 3：包缺 ⇒ 补装；版本不一致 ⇒ 退出 2（不许静默换版本）
        back_rc, got = read_back_version(python_path, package)
        if back_rc == 0 and got != version:
            die(f"版本不一致：{python_path} 里 {package} == {got}，配置要 {version} ⇒ "
                f"退出 2（不许静默换版本；人工确认后重建 venv）")
    else:
        # 建之前先确认主环境能提供 Ascend 栈 —— 否则建完才发现跑不了（白建一个 venv）
        base = base_probe()
        miss = [m for m in BASE_NEED if m in base["missing"]]
        if miss:
            for m in miss:
                print(f"  {m}: {base['missing'][m]}", file=sys.stderr)
            die(f"主环境缺 {', '.join(miss)} ⇒ 继承（--system-site-packages）拿不到它们，"
                f"评测跑不起来（`lm_eval --model hf` 会 import torch）。先按项目要求把 Ascend 栈装好")
        venv_root.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv_root)],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout + proc.stderr)
            die(f"建 venv 失败（python3 -m venv --system-site-packages {venv_root}）")
        if not python_path.is_file():
            die(f"建完 venv 仍找不到解释器：{python_path}")

    proc = subprocess.run([str(python_path), "-m", "pip", "install", pinned], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        die(f"安装失败：{pinned}")

    # ② 回读自证（版本必须与配置逐字相同）＋ ③ 可运行性（能 import 才算装好）
    rc, state, lines = judge(python_path, package, version)
    if rc != 0:
        for line in lines:
            print(f"  {line}", file=sys.stderr)
        die(f"装完仍不可运行（{state}）⇒ 退出 2；见上方明细")

    info = probe(python_path)
    written = write_record(record_path, build_record(
        task_config=task_config, engine=engine, package=package, version=version,
        python=python_path, venv_root=venv_root, info=info))
    print(f"已安装并回读自证：{pinned}（解释器 {python_path}）")
    print(f"可运行性：{lines[0]}")
    print(f"安装记录：{record_path}（{'已写入' if written == 'written' else '内容未变，未重写'}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
