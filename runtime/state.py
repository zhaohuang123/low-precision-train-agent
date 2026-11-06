#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""state.py —— 状态接口的**唯一**写者：`state/{current.json,rounds.jsonl,STATUS.md}`。

归属：状态接口（交接 token、十条、一个 token 只有一个生产者）。

行为契约（P7 已实现）：
  1. 子命令：`init` / `advance --handoff <TOKEN>` / `close --conclusion C-<序号> --outcome <adopt|reject|inconclusive>`。
  2. `state/current.json`（整体覆盖，字段表见 §14.2）：`schema`/`task_id`/`round`/`stage`/
     `framework_version`（读 `VERSION`）/`config_version`（任务配置**规范化内容**的 sha256 前 8 位，形如 `cfg-9f2c1a40`；
     剔掉 `intents` 与注释 —— 见 `_fingerprint_bytes`）/
     `artifacts.{root,round_dir,runtime_root}`/`framework_state.{head,clean}`/`last_handoff`/
     `last_conclusion`/`next_action`/`loop`/`blockers`。
  3. `state/rounds.jsonl`（**append-only**）：每轮结束**恰好追加一行**，字段见 §14.3 与
     `templates/state-entry.json`（`round`/`task_id`/`stage_at_close`/`framework_version`/`config_version`/
     `conclusion`/`outcome`/`metric{name,value,baseline,delta}`/`artifacts{root,round_dir,metrics}`/
     `framework_restored`/`loop`/`closed_at`）。数字**只引用** `<轮次>/metrics.json`，不许重算。
     `init` 只在该文件**不存在**时写入一行 `_note` 骨架说明行（与 `records/ledger.jsonl`
     同一约定的「骨架说明行」，解析方按 `_note` 跳过）；**已存在则一字不动**（append-only）。
  4. `state/STATUS.md`（整体覆盖，人读六段）：当前阶段／当前轮次／版本（框架＋配置）／产物路径／
     上一步结论／下一步与卡点 —— 由 `current.json` **渲染**，不是第二个真相。
  5. **非法 token ⇒ 退出 `2`**（token 词表见 §13.2 的 10 条；一个 token 只有一个生产者）。
     token 合法但**当前 `stage` 不是它的生产者** ⇒ 同样退出 `2`（fail-closed：不在那个阶段就不许替它交接）。
     合法 token 后：`stage` 变、`rounds.jsonl` 行数**不变**（只有 `close` 才追加轮次行）。
  6. `advance`/`close` 只改 `state/`，不碰轮次目录、不碰 `records/`（结论入库是 experimenter 的职责）。

P7 实现里几个**落点选择**（写在这里，避免"看起来对"的静默分歧）：
  * 配置根解析：`--root` → 环境变量 `LP_ROOT` → 本文件上一级。**指错不回退**（那棵树里没有
    `config/project.yaml` 或 `VERSION` ⇒ 退出 `2`），与 `runtime/metrics.py`／`runtime/validate_round.py` 同规矩。
  * 任务配置：`--task <名|路径>` 优先；未给时取 `config/tasks/*.yaml` 里**唯一**一份非 `_TEMPLATE.yaml` 者；
    一份都没有 ⇒ 退回 `_TEMPLATE.yaml`（模板占位，`task_id`／`artifacts.root` 即模板值，并在 `blockers`
    里登记「尚无真实任务配置」）；有**多份**且未指名 ⇒ 退出 `2`（不猜）。
  * `config_version`：真实任务配置 ⇒ **规范化内容**（去 `intents`、去注释）的 `sha256` 前 8 位
    （`cfg-<8hex>`）⇒ 追加实验意图、补注释都**不会**改它；改模型/精度/口径/钉点才会。若取到的是
    `_TEMPLATE.yaml`（尚无真实任务配置）⇒ `cfg-00000000`（本工程 0.1.0–0.3.0 段落沿用的占位值，见 `ReleaseNotes.md`）。
  * `artifacts.root` 的**展开来源**（§14.2 说「含展开来源」／`runtime/config.py` 契约第 2 条）：展开后的值进
    `current.json`；来源在 `init` 的输出里打印一行（`artifacts.root=default ⇒ <paths.experiments>/<任务名>`）。
    §14.2 把 `artifacts.*` 钉成 `str`、附录 F 的示例也是纯路径 ⇒ **不新增字段**（新增字段＝自造规格）。
  * `framework_state.clean`／`framework_restored`：本文件**不跑 git、不猜**。初始化时 `clean=null`（未核验）；
    `close` 只在调用方显式给出 `--framework-restored {true,false}` 时落该事实，否则记 `null`。
    「空输出不等于干净」（§16.1 P5），所以缺证据时不许填 `true`。
  * `close` 的数字：`metric.name` 取自本轮 `<轮次>/criterion.yaml` 的 `success.require` 第一条里的
       `<数据集>/<尺子>`（跑前冻结；旧判据的 `success.metric` 仍优先，兼容历史轮次）；
    `value`＝`<轮次>/metrics.json` 的 `eval.target.metrics[name]`；`baseline`＝`eval.baseline.metrics[name]`（可为 `null`）；
    `delta`＝`eval.comparisons.vs_<基线轮次>[name].delta`（可为 `null`）。**只引用，不重算**；`metrics.json`
    或该主指标项缺失 ⇒ 退出 `2`（数字的唯一落点不在，不许收口、不许编）。
    ★ 对照节点由 `runtime/metrics.py` 保证**只有一个**（键名按 `criterion` 的 `success.baseline_ref`
    现算：`vs_<基线轮次>`；`baseline_ref` 为 null ⇒ 键 `vs_baseline`、值是 `null`）⇒ 这里按前缀取那一个。
  * `advance --handoff NEXT_ROUND` 时 `round` 自增（`R-000N` → `R-000(N+1)`），其余 token 不改 `round`。

纪律：本文件不含任何模型名／任务名／数据集名／阈值（`devtools/check_decoupling.py` 会查）；状态字段值来自配置，不写死。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # 配置全是 YAML；缺依赖即 fail-closed，不猜
    import yaml
except Exception:  # pragma: no cover
    yaml = None

# §2 退出码表：0 成功｜2 契约/门不过（fail-closed）。本文件只用到这两个码。
EXIT_OK = 0
EXIT_CONTRACT = 2

SCHEMA = 1
MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = MODULE_DIR.parent

# §0.1：`paths.*` 的内建默认（优先级最低一层；正常情况由 config/project.yaml 给出）
BUILTIN_PATHS = {"tasks": "config/tasks", "experiments": "experiments", "state": "state"}
TEMPLATE_TASK_NAME = "_TEMPLATE.yaml"
PLACEHOLDER_CONFIG_VERSION = "cfg-00000000"
ROUND_DEFAULT = "R-0001"
ROUND_RE = re.compile(r"^R-(\d+)$")
CONCLUSION_RE = re.compile(r"^C-\d+$")
OUTCOMES = ("adopt", "reject", "inconclusive")
STAGES = ("architect", "developer", "tester", "experimenter", "done", "abort")
STATE_FILENAMES = ("current.json", "rounds.jsonl", "STATUS.md")

# §13.2 状态转移表（十条；`frm` ＝ 生产者／`to` ＝ 消费者）。token 词表是这里的键集合本身。
TOKENS = {
    "ARCHITECT_READY": {
        "frm": "architect", "to": "developer",
        "action": "派 developer：按 <轮次>/{design.md,criterion.yaml} 落地（CODE_READY / CODE_FAILED）",
        "blocker": None,
    },
    "ARCHITECT_FAILED": {
        "frm": "architect", "to": "abort",
        "action": "本线终止（abort）：需求在当前硬件/框架下不可满足，卡点须指名",
        "blocker": "ARCHITECT_FAILED：需求在当前硬件/框架下不可满足（卡点说明见交接物）",
    },
    "CODE_READY": {
        "frm": "developer", "to": "tester",
        "action": "派 tester：冒烟＋扫参，产出 <轮次>/{test.md,round.env}（TEST_READY / TEST_BLOCKED）",
        "blocker": None,
    },
    "CODE_FAILED": {
        "frm": "developer", "to": "architect",
        "action": "派 architect：框架表达不了该方案，须指名缺哪个分支",
        "blocker": "CODE_FAILED：框架表达不了该方案（不许填假参数静默降级；缺哪个分支见交接物）",
    },
    "TEST_READY": {
        "frm": "tester", "to": "experimenter",
        "action": "派 experimenter：三段执行＋抽数＋结论入库（EXPERIMENT_DONE / EXPERIMENT_INVALID）",
        "blocker": None,
    },
    "TEST_BLOCKED": {
        "frm": "tester", "to": "developer",
        "action": "派 developer：测试暴露的是代码缺陷，按复现命令修（不许靠调参绕过）",
        "blocker": "TEST_BLOCKED：代码缺陷（报错原文与复现命令见交接物）",
    },
    "EXPERIMENT_INVALID": {
        "frm": "experimenter", "to": "experimenter",
        "action": "派 experimenter：本轮训练无效，先说明重跑要改什么，再改后重跑（不许原样重跑）",
        "blocker": "EXPERIMENT_INVALID：训练侧无效（触发阈值与步数见失败证据）",
    },
    "EXPERIMENT_DONE": {
        "frm": "experimenter", "to": "architect",
        "action": "派 architect：按 report.md ＋ conclusions/ 沉淀知识，并决定 NEXT_ROUND / LOOP_STOP",
        "blocker": None,
    },
    "NEXT_ROUND": {
        "frm": "architect", "to": "developer",
        "action": "派 developer：开新一轮（新一轮须与上一轮有可指名的差别）",
        "blocker": None,
    },
    "LOOP_STOP": {
        "frm": "architect", "to": "done",
        "action": "本线收口（done）：停止理由与知识增补记录已由 architect 交出",
        "blocker": None,
    },
}

# `init` 之后的 first action（还没发生任何交接）
NEXT_ACTION_INIT = "派 architect：出本轮 <轮次>/{design.md,criterion.yaml}（方案冻结、花卡前先过 runtime/validate_round.py）"
NEXT_ACTION_CLOSED = "本轮已收口（{conclusion} {outcome}）：等 architect 按 report.md ＋ conclusions/ 决定 NEXT_ROUND / LOOP_STOP"
ROUNDS_NOTE = (
    "state/rounds.jsonl —— 每轮结束由 runtime/state.py close **恰好追加一行**（append-only，写完不许回头改）。"
    "本行是骨架说明行，解析方按 _note 跳过；轮次行字段定义见 templates/state-entry.json。"
)


# ---------------------------------------------------------------------------
# 一、基础设施：配置根、YAML、退出
# ---------------------------------------------------------------------------

def _fail(msg: str) -> int:
    print(f"runtime/state.py：{msg}", file=sys.stderr)
    return EXIT_CONTRACT


def _load_yaml(path: Path) -> dict:
    """读一份 YAML；读不到/解析不出 ⇒ 抛 `_ContractError`（外层转退出 2）。"""
    if yaml is None:
        raise _ContractError("PyYAML 不可用（配置全是 YAML）⇒ 拒绝执行")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _ContractError(f"配置读不出来：{path}（{exc}）") from exc
    return doc if isinstance(doc, dict) else {}


class _ContractError(Exception):
    """契约层错误 ⇒ 退出 2（fail-closed）。"""


def _resolve_root(explicit: str | None) -> Path:
    """`--root` → `LP_ROOT` → 本文件上一级；指错不回退（§6.4／§0.1）。"""
    cand = explicit or os.environ.get("LP_ROOT")
    if cand:
        root = Path(cand).expanduser().resolve()
        if not (root / "config" / "project.yaml").is_file() or not (root / "VERSION").is_file():
            raise _ContractError(
                f"配置根指错、不回退：{root} 里没有 config/project.yaml 或 VERSION"
            )
        return root
    root = DEFAULT_ROOT
    if not (root / "config" / "project.yaml").is_file() or not (root / "VERSION").is_file():
        raise _ContractError(f"配置根解析不出来：{root} 里没有 config/project.yaml 或 VERSION")
    return root


def _read_version(root: Path) -> str:
    try:
        text = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise _ContractError(f"VERSION 读不出来：{exc}") from exc
    if not text:
        raise _ContractError("VERSION 是空的 —— 框架版本是状态的一部分，不许留空")
    return text


def _builtin_path(paths: dict, key: str) -> str:
    return str(paths.get(key) or BUILTIN_PATHS[key])


# ---------------------------------------------------------------------------
# 二、任务配置：定位、config_version、artifacts 展开
# ---------------------------------------------------------------------------

def _resolve_task_path(root: Path, tasks_dir: str, task_arg: str | None) -> tuple[Path, bool]:
    """返回 (任务配置文件, 是否是模板占位)。定位不到/有歧义 ⇒ `_ContractError`。"""
    base = root / tasks_dir
    if task_arg:
        given = Path(task_arg).expanduser()
        names = [given] if given.suffix == ".yaml" else [given, Path(str(given) + ".yaml")]
        search_dirs = [] if given.is_absolute() else [Path.cwd(), root, base]
        found = None
        for name in names:
            if name.is_absolute():
                if name.is_file():
                    found = name
                    break
                continue
            for d in search_dirs:
                cand = d / name
                if cand.is_file():
                    found = cand
                    break
            if found is not None:
                break
        if found is None:
            raise _ContractError(
                f"任务配置不存在：--task {task_arg!r}（找过 {base} 与当前目录；要指名路径请带 .yaml）"
            )
        found = found.resolve()
        return found, found.name == TEMPLATE_TASK_NAME

    if base.is_dir():
        real = sorted(
            p for p in base.glob("*.yaml")
            if p.name != TEMPLATE_TASK_NAME and not p.name.endswith(".local.yaml")
        )
        if len(real) == 1:
            return real[0].resolve(), False
        if len(real) > 1:
            names = "、".join(p.name for p in real)
            raise _ContractError(f"config/tasks/ 下有多份任务配置（{names}）⇒ 必须 --task 指名，本文件不猜")
    template = base / TEMPLATE_TASK_NAME
    if template.is_file():
        return template.resolve(), True
    raise _ContractError(f"config/tasks/ 下既没有真实任务配置，也没有 {TEMPLATE_TASK_NAME}")


def _config_version(task_path: Path, is_template: bool) -> str:
    if is_template:
        # 尚无真实任务配置 ⇒ 沿用本工程既有的占位值（见 ReleaseNotes.md 0.1.0–0.3.0 段）
        return PLACEHOLDER_CONFIG_VERSION
    digest = hashlib.sha256(_fingerprint_bytes(task_path)).hexdigest()
    return f"cfg-{digest[:8]}"


def _fingerprint_bytes(task_path: Path) -> bytes:
    """算指纹用的字节：**配置的规范化内容，且剔掉 `intents`**。

    ★ 为什么剔 `intents`：它是人不断 append 的"想法区"，不是本轮输入。它一旦参与指纹，
      人每追加一条想法都会让 `devtools/check_state.py` 判"状态与配置不一致"，而
      `state.py init` 会把 stage 重置回 architect —— 追加一条想法就毁掉进行中的一轮。
    ★ 为什么用规范化内容而不是文件字节：指纹要回答"**实验输入变了吗**"（模型/精度/口径/钉点），
      注释、键的书写顺序、行尾空格都不是输入。这样"补一句注释"不会凭空产生一次版本变更。
    ★ 解析不了 ⇒ 退回文件字节（严格一点，绝不静默放过坏配置；坏配置由 `config.py` 逐条报）。
    """
    raw = task_path.read_bytes()
    try:
        doc = _load_yaml(task_path)
    except Exception:  # noqa: BLE001 —— 解析失败不在这里判死，由 config.py 报
        return raw
    if not isinstance(doc, dict):
        return raw
    stripped = {k: v for k, v in doc.items() if k != "intents"}
    try:
        dumped = json.dumps(stripped, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return raw
    return ("lpta-cfg-fp\n" + dumped).encode("utf-8")


def _expand_artifacts_root(raw, task_id: str, experiments: str) -> str:
    """`artifacts.root` 缺失或写成 `default` ⇒ 展开为 `<paths.experiments>/<任务名>`（§0.1／§11 ①）。"""
    text = "" if raw is None else str(raw).strip()
    if text in ("", "default"):
        return f"{experiments}/{task_id}"
    return text


def _artifacts_root_source(raw, task_id: str, experiments: str) -> str:
    """展开来源（§14.2「含展开来源」／`runtime/config.py` 契约第 2 条）。

    §14.2 把 `artifacts.*` 钉成 `str`、附录 F 的示例也是纯路径 ⇒ 本文件**不新增字段**
    （新增字段＝自造规格）；来源在 `init` 的 stderr/stdout 打印一行，供人与上层编排当场核对。
    """
    text = "" if raw is None else str(raw).strip()
    if text in ("", "default"):
        return f"artifacts.root={text or '（缺失）'} ⇒ 展开为 {experiments}/{task_id}"
    return f"artifacts.root 显式给出：{text}"


def _round_dir(artifacts_root: str, round_id: str) -> str:
    return f"{artifacts_root.rstrip('/')}/rounds/{round_id}"


def _lp_work_dir(root: Path, task_dir: Path, runs_root, task_id: str, data_root) -> "str | None":
    """三段产物的**真实**根 —— 与 shell 侧同源：读 `<任务目录>/run.env` 的 `LP_WORK_DIR`。

    为什么必须读 run.env 而不是在 Python 里重写一份默认值：两处各写一份默认值，迟早分叉
    （0.18.14 之前正是如此：`data.runs` 记一个地方、东西在另一个地方，且**没有任何一步报错**）。
    读不到 run.env（或它没设这个变量）⇒ 退回 `<data.runs>/<任务名>` —— 与 `runtime/_common.sh`
    的默认规则**逐字一致**；两者不一致时以 run.env 为准（它才是真正被执行的那个）。

    解析靠 bash 而不是自己写展开器：`run.env` 是 shell 文件，`${LP_DATA_ROOT}` 这类引用只有
    shell 自己展开才是权威（自写一份等于第二份解析）。
    """
    fallback = f"{str(runs_root).rstrip('/')}/{task_id}" if runs_root else None
    env = task_dir / "run.env"
    if not env.is_file():
        return fallback
    script = (
        'set -u; set -a; '
        'export LP_ROOT="$1" LP_TASK_DIR="$2" LP_TASK_ID="$3" LP_DATA_ROOT="$4"; '
        '. "$2/run.env" >/dev/null 2>&1 || exit 3; '
        'printf %s "${LP_WORK_DIR:-}"'
    )
    try:
        out = subprocess.run(
            ["bash", "-c", script, "_", str(root), str(task_dir), task_id,
             "" if data_root is None else str(data_root)],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return fallback
    value = (out.stdout or "").strip()
    return value or fallback


# ---------------------------------------------------------------------------
# 三、current.json / STATUS.md 的构造与渲染
# ---------------------------------------------------------------------------

def _new_current(root: Path, task_path: Path, is_template: bool, round_id: str) -> tuple[dict, str]:
    project = _load_yaml(root / "config" / "project.yaml")
    paths = project.get("paths") if isinstance(project.get("paths"), dict) else {}
    task = _load_yaml(task_path)

    task_id = str(task.get("task_id") or "").strip()
    if not task_id:
        raise _ContractError(f"任务配置里没有 task_id：{task_path}")

    artifacts_block = task.get("artifacts") if isinstance(task.get("artifacts"), dict) else {}
    experiments_dir = _builtin_path(paths, "experiments")
    artifacts_root = _expand_artifacts_root(artifacts_block.get("root"), task_id, experiments_dir)
    root_source = _artifacts_root_source(artifacts_block.get("root"), task_id, experiments_dir)

    data = project.get("data") if isinstance(project.get("data"), dict) else {}
    runs_root = data.get("runs")
    # ★ 产物真实根 = `run.env` 的 `LP_WORK_DIR`（读不到才退回 `<data.runs>/<任务名>`），
    #   轮次产物在它下面的 `rounds/<轮次>/` —— 与三段脚本（`{train,convert,eval}_cmd.sh`）逐字同源。
    #   记的不是"盘位"，是**这一轮东西真正在的那个目录**。
    task_dir = Path(artifacts_root)
    if not task_dir.is_absolute():
        task_dir = root / task_dir
    work_root = _lp_work_dir(root, task_dir, runs_root, task_id, data.get("root"))
    runtime_root = f"{work_root}/rounds/{round_id}" if work_root else None

    train = task.get("train") if isinstance(task.get("train"), dict) else {}
    framework_head = train.get("framework_head")
    framework_head = str(framework_head) if framework_head not in (None, "") else None
    core_head = train.get("core_head")
    core_head = str(core_head) if core_head not in (None, "") else None

    loop_cfg = task.get("loop") if isinstance(task.get("loop"), dict) else {}
    loop = {
        # 真实值在 cmd_init／cmd_close 里用 rounds.jsonl 现算（0.18.29）；这里是"还没有历史"的默认
        "rounds_done": 0,
        "no_progress_streak": 0,
        "no_progress_rounds": loop_cfg.get("no_progress_rounds"),
    }

    blockers = []
    if is_template:
        blockers.append(
            f"尚无真实任务配置（config/tasks/ 下只有 {TEMPLATE_TASK_NAME}）"
            "⇒ task_id 与 artifacts.root 为模板占位值"
        )

    return {
        "schema": SCHEMA,
        "task_id": task_id,
        "round": round_id,
        "stage": "architect",
        "framework_version": _read_version(root),
        "config_version": _config_version(task_path, is_template),
        "artifacts": {
            "root": artifacts_root,
            "round_dir": _round_dir(artifacts_root, round_id),
            "runtime_root": runtime_root,
        },
        # 本文件不跑 git、不猜：`head` 取配置里的钉点，`clean` 未核验即 null（空输出 ≠ 干净）
        "framework_state": {"head": framework_head, "core_head": core_head, "clean": None},
        "last_handoff": None,
        "last_conclusion": None,
        "next_action": NEXT_ACTION_INIT,
        "loop": loop,
        "blockers": blockers,
    }, root_source


def _missing_note(runtime_root) -> str:
    """`STATUS.md` 里给产物路径加一句"现在在不在"—— 读到的人不会白跑一趟。"""
    if not runtime_root:
        return ""
    p = Path(str(runtime_root))
    if p.is_dir():
        return ""
    if not p.parent.parent.is_dir():
        return "（⚠ 产物根还不存在：`run.env` 的 `LP_WORK_DIR`／`project.yaml` 的 `data.runs` 指对了没）"
    return "（目录尚未创建：该轮还没起作业）"


def _render_status(current: dict) -> str:
    """六段摘要；**只**从 `current.json` 渲染，不引入第二个真相。"""
    art = current.get("artifacts") or {}
    fw = current.get("framework_state") or {}
    loop = current.get("loop") or {}
    blockers = current.get("blockers") or []
    lines = [
        "# `state/STATUS.md` —— 状态摘要（人读）",
        "",
        "> 由 `runtime/state.py` 从 `state/current.json` **渲染**；机器读 `current.json`，本文件不是第二个真相。",
        "> 手改无效：下一次 `init`／`advance`／`close` 会整体覆盖它。",
        "",
        "## 1. 当前阶段",
        "",
        f"- `stage`：`{current.get('stage')}`",
        f"- `last_handoff`：{('`' + str(current['last_handoff']) + '`') if current.get('last_handoff') else '（尚无交接）'}",
        "",
        "## 2. 当前轮次",
        "",
        f"- `round`：`{current.get('round')}`",
        f"- `task_id`：`{current.get('task_id')}`",
        "",
        "## 3. 版本（框架＋配置）",
        "",
        f"- 框架：`{current.get('framework_version')}`（读 `VERSION`）",
        f"- 配置：`{current.get('config_version')}`（任务配置内容哈希前 8 位；`{PLACEHOLDER_CONFIG_VERSION}` ＝ 尚无真实任务配置）",
        "",
        "## 4. 产物路径",
        "",
        f"- `artifacts.root`：`{art.get('root')}`",
        f"- `artifacts.round_dir`：`{art.get('round_dir')}`",
        f"- `artifacts.runtime_root`：{art.get('runtime_root') if art.get('runtime_root') else '（未配置）'}"
        + _missing_note(art.get("runtime_root")),
        f"- 框架检出：`head` ＝ {('`' + str(fw['head']) + '`') if fw.get('head') else '（未配置）'}；"
        f"`core_head` ＝ {('`' + str(fw['core_head']) + '`') if fw.get('core_head') else '（未配置）'}；"
        f"`clean` ＝ {('`' + str(fw['clean']).lower() + '`') if fw.get('clean') is not None else '`null`（未核验，本文件不跑 git）'}",
        "",
        "## 5. 上一步结论",
        "",
        f"- `last_conclusion`：{('`' + str(current['last_conclusion']) + '`') if current.get('last_conclusion') else '（尚无结论入库）'}",
        "",
        "## 6. 下一步与卡点",
        "",
        f"- `next_action`：{current.get('next_action')}",
        f"- `blockers`：{'（无）' if not blockers else ''}",
    ]
    lines += [f"  - {b}" for b in blockers]
    lines += [
        f"- `loop`：`rounds_done` ＝ `{loop.get('rounds_done')}`（**现算**自 `rounds.jsonl`）；"
        f"`no_progress_streak` ＝ `{loop.get('no_progress_streak')}`（末尾连续非 adopt 的轮数，派生视图）；"
        f"`no_progress_rounds` ＝ `{loop.get('no_progress_rounds')}`（任务配置给的上限）",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 四、读写 state/
# ---------------------------------------------------------------------------

def _state_dir(root: Path, explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    project = _load_yaml(root / "config" / "project.yaml")
    paths = project.get("paths") if isinstance(project.get("paths"), dict) else {}
    return (root / _builtin_path(paths, "state")).resolve()


def _write_json(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_status(state_dir: Path, current: dict) -> None:
    (state_dir / "STATUS.md").write_text(_render_status(current), encoding="utf-8")


def _ensure_rounds_file(state_dir: Path) -> bool:
    """rounds.jsonl 不存在则写一行 `_note` 骨架说明行；已存在则一字不动（append-only）。"""
    path = state_dir / "rounds.jsonl"
    if path.exists():
        return False
    seed = {"_note": ROUNDS_NOTE, "schema": SCHEMA}
    path.write_text(json.dumps(seed, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def _load_current(state_dir: Path) -> dict:
    path = state_dir / "current.json"
    if not path.is_file():
        raise _ContractError(f"{path} 不存在 ⇒ 先跑 `python3 runtime/state.py init`")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _ContractError(f"current.json 读不出来：{exc}") from exc
    if not isinstance(doc, dict) or not doc.get("stage"):
        raise _ContractError("current.json 结构不对（缺 stage）⇒ 拒绝在其上推进")
    return doc


def _persist(state_dir: Path, current: dict) -> None:
    _write_json(state_dir / "current.json", current)
    _write_status(state_dir, current)


def _bump_round(round_id: str) -> str:
    m = ROUND_RE.match(round_id)
    if not m:
        raise _ContractError(f"轮次号形状不对：{round_id!r}（要求形如 R-0001）")
    digits = m.group(1)
    width = max(4, len(digits))
    return f"R-{int(digits) + 1:0{width}d}"


# ---------------------------------------------------------------------------
# 五、子命令
# ---------------------------------------------------------------------------

def _warn_missing_work_root(current: dict) -> None:
    """产物根不存在就**说出来**（不是门、不改 rc）—— 静默记一个不存在的路径是本文件的老毛病。"""
    rt = (current.get("artifacts") or {}).get("runtime_root")
    if not rt:
        return
    work = Path(str(rt)).parent.parent  # <runtime_root> = <产物根>/rounds/<轮次>
    if not work.is_dir():
        print(
            f"  ⚠ 产物根还不存在：{work}\n"
            f"    传到这里的路径来自 run.env 的 LP_WORK_DIR（没写则用 project.yaml 的 data.runs）。\n"
            f"    起作业时三段入口会建它；如果这里指的是**错的盘**，现在改，别等跑完才发现。",
            file=sys.stderr,
        )


def cmd_init(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    project = _load_yaml(root / "config" / "project.yaml")
    paths = project.get("paths") if isinstance(project.get("paths"), dict) else {}
    task_path, is_template = _resolve_task_path(
        root, _builtin_path(paths, "tasks"), args.task
    )
    round_id = args.round or ROUND_DEFAULT
    if not ROUND_RE.match(round_id):
        raise _ContractError(f"轮次号形状不对：{round_id!r}（要求形如 R-0001）")

    state_dir = _state_dir(root, args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    seeded = _ensure_rounds_file(state_dir)
    current, root_source = _new_current(root, task_path, is_template, round_id)
    # ★ 已完成轮数**现算**（0.18.29 / R-07）：init 会覆盖 current.json，写死 0 会让每轮都从 1 开始。
    rows = _round_rows(state_dir / "rounds.jsonl")
    current["loop"]["rounds_done"] = len(rows)
    current["loop"]["no_progress_streak"] = _no_progress_streak(rows)
    _persist(state_dir, current)

    print(f"state/ 已就绪：{state_dir}")
    print(f"  轮次 {round_id}｜stage={current['stage']}｜框架 {current['framework_version']}｜配置 {current['config_version']}")
    print(f"  artifacts.root={current['artifacts']['root']}（来源：{root_source}）")
    _warn_missing_work_root(current)
    if is_template:
        print(f"  ⚠ 任务配置用的是模板占位：{task_path}（尚无真实任务配置）", file=sys.stderr)
    print(f"  rounds.jsonl：{'新建（含 _note 骨架说明行）' if seeded else '已存在 ⇒ 一字未改（append-only）'}")
    return EXIT_OK


def cmd_advance(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    state_dir = _state_dir(root, args.state_dir)
    current = _load_current(state_dir)

    token = args.handoff
    if token not in TOKENS:
        legal = "／".join(TOKENS)
        raise _ContractError(
            f"非法交接 token：{token!r} ⇒ 退出 2（fail-closed）。合法 token 只有十条：{legal}"
        )
    spec = TOKENS[token]
    stage = current.get("stage")
    if stage != spec["frm"]:
        raise _ContractError(
            f"token {token} 的生产者是 `{spec['frm']}`，但当前 stage=`{stage}` ⇒ 退出 2"
            "（不在那个阶段就不许替它交接；一个 token 只有一个生产者）"
        )

    rounds_path = state_dir / "rounds.jsonl"
    lines_before = _count_lines(rounds_path)

    current["stage"] = spec["to"]
    current["last_handoff"] = token
    current["next_action"] = spec["action"]
    if token == "NEXT_ROUND":
        current["round"] = _bump_round(str(current.get("round")))
        current["artifacts"]["round_dir"] = _round_dir(
            str(current["artifacts"].get("root")), current["round"]
        )
        runtime_root = current["artifacts"].get("runtime_root")
        if runtime_root:
            base = str(runtime_root).rsplit("/", 1)[0]
            current["artifacts"]["runtime_root"] = f"{base}/{current['round']}"
    current["blockers"] = [spec["blocker"]] if spec["blocker"] else []

    _persist(state_dir, current)

    lines_after = _count_lines(rounds_path)
    if lines_after != lines_before:
        # 不该发生：advance 永不追加轮次行。真发生就是本文件的 bug，按契约失败退出。
        raise _ContractError(
            f"advance 改动了 rounds.jsonl（{lines_before} → {lines_after} 行）—— 轮次行只由 close 追加"
        )
    print(f"{token}：stage {stage} → {current['stage']}；rounds.jsonl 行数不变（{lines_after}）")
    return EXIT_OK


def cmd_close(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    state_dir = _state_dir(root, args.state_dir)
    current = _load_current(state_dir)

    conclusion = args.conclusion
    if not CONCLUSION_RE.match(conclusion):
        raise _ContractError(f"结论 id 形状不对：{conclusion!r}（要求形如 C-0007）")
    if args.outcome not in OUTCOMES:
        raise _ContractError(f"outcome 只能是 {'／'.join(OUTCOMES)}，收到 {args.outcome!r}")

    round_id = str(current.get("round"))
    closed = _closed_rounds(state_dir / "rounds.jsonl")
    if round_id in closed:
        raise _ContractError(
            f"轮次 {round_id} 已经收口过（rounds.jsonl 里已有它的轮次行）⇒ 退出 2："
            "每轮结束**恰好追加一行**，不许重复收口"
        )
    artifacts = current.get("artifacts") or {}
    round_dir = str(artifacts.get("round_dir") or _round_dir(str(artifacts.get("root")), round_id))
    round_path = (root / round_dir).resolve() if not Path(round_dir).is_absolute() else Path(round_dir)

    metric = _read_metric(round_path)
    restored = None
    if args.framework_restored != "unknown":
        restored = args.framework_restored == "true"

    _ensure_rounds_file(state_dir)
    row = {
        "round": round_id,
        "task_id": current.get("task_id"),
        "stage_at_close": current.get("stage"),
        "framework_version": current.get("framework_version"),
        "config_version": current.get("config_version"),
        "conclusion": conclusion,
        "outcome": args.outcome,
        "metric": metric,
        "artifacts": {
            "root": artifacts.get("root"),
            "round_dir": round_dir,
            "metrics": f"{round_dir.rstrip('/')}/metrics.json",
        },
        "framework_restored": restored,
        "loop": {
            # ★ 与 `init` 同一份来源（rounds.jsonl 行数 ＋ 本轮这 1 行）——
            #   不读 `current.json` 的 rounds_done，那条值会被下一次 init 覆盖。
            "rounds_done": _rounds_done(state_dir) + 1,
        },
        "closed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with (state_dir / "rounds.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    current["loop"]["rounds_done"] = row["loop"]["rounds_done"]
    current["loop"]["no_progress_streak"] = _no_progress_streak(_round_rows(state_dir / "rounds.jsonl"))
    current["last_conclusion"] = f"{conclusion} {args.outcome}"
    current["next_action"] = NEXT_ACTION_CLOSED.format(conclusion=conclusion, outcome=args.outcome)
    if restored is not None:
        current["framework_state"]["clean"] = restored
    _persist(state_dir, current)

    print(
        f"close：{conclusion} {args.outcome}｜round={round_id}｜rounds.jsonl 追加 1 行"
        f"（rounds_done={row['loop']['rounds_done']}）"
    )
    return EXIT_OK


def _first_metric_name(success: dict) -> str:
    """主指标名 = `success.require` **第一条**里的 `<数据集>/<尺子>`（0.18.14 起没有 `success.metric`）。

    为什么取第一条：`rounds.jsonl` 的 `metric.name` 是一个字符串字段（附录 F 的契约），
    而 `require` 自 0.18.14 起是**列表**（多指标逐项对账）。清单的第一条即本轮主指标——
    这是口径，不是猜测：判据本身就是"按这个顺序逐项判的"。
    旧判据里的 `success.metric` 仍优先（向后兼容：已冻结的历史轮次收口时不能变）。
    """
    legacy = str(success.get("metric") or "").strip()
    if legacy:
        return legacy
    require = success.get("require")
    items = require if isinstance(require, list) else ([require] if require else [])
    for item in items:
        if not isinstance(item, str):
            continue
        # ★ 逗号是 lm-eval **原生指标名**的一部分（`<数据集>/exact_match,flexible-extract`）；
        #   0.18.28 前字符类里没有它 ⇒ 判据照原生键写会被截成 `<数据集>/exact_match`，
        #   于是 metrics.json 里明明有这个键却判"没有主指标"。
        for tok in re.findall(r"[A-Za-z0-9_.\-,]+/[A-Za-z0-9_.\-,]+", item):
            return tok
    return ""


def _resolve_metric_key(metrics: dict, name: str) -> "tuple[str, object]":
    """在 `metrics.json` 的指标字典里把判据写的主指标名**对上号**（不猜、不造）。

    三种情形：
      ① 判据写的就是字典里的键 ⇒ 原样取；
      ② 判据写**规范名**（`<数据集>/exact_match`），字典里却是带 filter 的原生键
         （`<数据集>/exact_match,flexible-extract`）⇒ **唯一**命中才取，并把**真实键名**记下来
         （`rounds.jsonl` 的 `metric.name` 必须能在 metrics.json 里原样查到）；
      ③ 命中多个 ⇒ 退出 2，让人在判据里写全（多个 filter 的指标不是同一个数，替人挑就是造假）。
    """
    if name in metrics:
        return name, metrics[name]
    cands = sorted(k for k in metrics if k.startswith(name + ","))
    if len(cands) == 1:
        return cands[0], metrics[cands[0]]
    if len(cands) > 1:
        raise _ContractError(
            f"主指标 {name!r} 在 metrics.json 里对上了多个带 filter 的键 {cands} ⇒ 退出 2："
            "判据里请写全（例如 `" + cands[0] + "`）—— 不同 filter 不是同一个数，这里不替你挑"
        )
    raise _ContractError(
        f"metrics.json 的 eval.target.metrics 里没有主指标 {name!r}（有的是 {sorted(metrics)}）⇒ 不许编，退出 2"
    )


def _read_metric(round_path: Path) -> dict:
    """**只引用** `<轮次>/metrics.json` 的数字；缺主指标 ⇒ 退出 2（不重算、不补 0）。"""
    criterion = _load_yaml(round_path / "criterion.yaml")
    success = criterion.get("success") if isinstance(criterion.get("success"), dict) else {}
    name = _first_metric_name(success)
    if not name:
        raise _ContractError(
            f"{round_path}/criterion.yaml 里 `success.require` 第一条没有 `<数据集>/<尺子>` ⇒ 收口时点不出主指标名"
            "（主指标名跑前冻结，不许现场造）"
        )

    metrics_path = round_path / "metrics.json"
    if not metrics_path.is_file():
        raise _ContractError(
            f"{metrics_path} 不存在 ⇒ 数字的唯一落点不在，不许收口（也不许在这里重算）"
        )
    try:
        doc = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _ContractError(f"{metrics_path} 读不出来：{exc}") from exc

    ev = doc.get("eval") if isinstance(doc.get("eval"), dict) else {}
    target = ((ev.get("target") or {}).get("metrics")) or {}
    baseline = ((ev.get("baseline") or {}).get("metrics")) or {}
    name, value = _resolve_metric_key(target, name)
    comparisons = ev.get("comparisons") if isinstance(ev.get("comparisons"), dict) else {}
    # ★ `runtime/metrics.py` 保证对照节点**只有一个**（键 `vs_<基线轮次>`；没有基线轮时键
    #   `vs_baseline`、值是 null）⇒ 按前缀取那一个；是 null／不是字典 ⇒ Δ 记 null（不重算）。
    vs_baseline = next(
        (v for k, v in comparisons.items() if k.startswith("vs_") and isinstance(v, dict)), {})
    cell = vs_baseline.get(name) if isinstance(vs_baseline.get(name), dict) else {}
    return {
        "name": name,
        "value": value,
        "baseline": baseline.get(name),
        "delta": cell.get("delta"),
    }


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def _round_rows(path: Path) -> "list[dict]":
    """`rounds.jsonl` 的轮次行（按文件顺序；跳过 `_note` 骨架说明行与坏行）。"""
    rows: list[dict] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("round") and "_note" not in row:
            rows.append(row)
    return rows


def _rounds_done(state_dir: Path) -> int:
    """已完成轮数 = `rounds.jsonl` 的行数（**现算**，不在 `current.json` 里累加）。

    为什么现算（0.18.29 / R-07）：`init` 每换轮都会**覆盖** `current.json`（`rounds_done` 因此归 0），
    `close` 再在它上面 +1 ⇒ 无论跑到第几轮，行里永远记 1。`rounds.jsonl` 是 append-only 的**事实**，
    以它为唯一来源就不会被"重建 current"这件事带偏（也顺手自愈：current 被删掉也不影响计数）。
    """
    return len(_round_rows(state_dir / "rounds.jsonl"))


def _no_progress_streak(rows: "list[dict]") -> int:
    """末尾连续"非 adopt"的轮数（视图，不是事实）：给编排器判"连续几轮没捞到东西"。"""
    n = 0
    for row in reversed(rows):
        if str(row.get("outcome") or "") == "adopt":
            break
        n += 1
    return n


def _closed_rounds(path: Path) -> set[str]:
    """rounds.jsonl 里已收口的轮次集合（跳过 `_note` 骨架说明行）。"""
    out: set[str] = set()
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("round") and "_note" not in row:
            out.add(str(row["round"]))
    return out


# ---------------------------------------------------------------------------
# 六、命令行
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="runtime/state.py",
        description="状态接口的唯一写者：state/{current.json,rounds.jsonl,STATUS.md}",
    )
    ap.add_argument("--root", help="配置根（等价于 LP_ROOT；指错即退出 2，不回退）")
    ap.add_argument("--state-dir", dest="state_dir", help="状态目录（默认读 config/project.yaml 的 paths.state）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="建/覆盖 current.json 与 STATUS.md；rounds.jsonl 只在不存在时建")
    p_init.add_argument("--task", help="任务配置名或路径（默认：config/tasks/ 下唯一一份非模板配置）")
    p_init.add_argument("--round", help=f"轮次号（默认 {ROUND_DEFAULT}）")
    p_init.set_defaults(func=cmd_init)

    p_adv = sub.add_parser("advance", help="推进一次交接（只改 current.json 与 STATUS.md）")
    p_adv.add_argument("--handoff", required=True, help="交接 token（§13.2 十条之一）")
    p_adv.set_defaults(func=cmd_advance)

    p_close = sub.add_parser("close", help="收口本轮：向 rounds.jsonl 恰好追加一行")
    p_close.add_argument("--conclusion", required=True, help="结论档案 id（形如 C-0007）")
    p_close.add_argument("--outcome", required=True, choices=OUTCOMES, help="判定")
    p_close.add_argument(
        "--framework-restored", dest="framework_restored",
        choices=("true", "false", "unknown"), default="unknown",
        help="框架检出是否已还原且校验一致（默认 unknown ⇒ 记 null；本文件不跑 git、不猜）",
    )
    p_close.set_defaults(func=cmd_close)
    return ap


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except _ContractError as exc:
        return _fail(str(exc))
    except OSError as exc:
        return _fail(f"文件操作失败：{exc}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
