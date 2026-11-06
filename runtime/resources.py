#!/usr/bin/env python3
"""resources.py —— 起作业前扫占用 ＋ 定卡三层（策略／实测／决策 ＋ 打来源）；录制回放。

归属：设备守卫与资源预算（`config/project.yaml` 的 `devices.{usable,reserved,require_explicit}`）。
实现步：**P4c**（P4 只交付了 `metrics.py` 与 `validate_round.py`；本文件当时是 `TODO(P4)` 占位）。
旧对应物：`scaffold/resources.py`（**实测 1545 行**，只搬机制、不搬数据本体）。

## 它治的是什么

**写死的卡号会腐烂。** 旧工程写死"空闲卡＝4,5,6,7"，而实测某天 4-7 正被别的作业占满、
空闲的恰恰是 0-3。「腐烂的常量比没有常量更糟 —— 它看起来像经过考量的结论。」
所以卡号分三层，**每层都打来源**（缺一层即判失败）：

| 层 | 是什么 | 来源（脚本会打印） |
|---|---|---|
| **策略层** | 哪些卡**允许**用 | `config/project.yaml` 的 `devices.{usable,reserved,require_explicit}` |
| **实测层** | 本机此刻逐卡的 AICore% / HBM（`npu-smi info`） | `npu-smi`；**读不到就是读不到**，不等于空闲 |
| **决策层** | 最终卡号集合 ＋「为什么是这几张」 | `LP_CARDS` ＞ 已导出的 `ASCEND_RT_VISIBLE_DEVICES` ＞ 自动探测 |

**卡号从哪来只有这一个实现**：任何脚本／任务目录**不许**再写死卡号。

## 两类来源，判错方向不同（这条决定了所有 BLOCK/WARN 的取舍）

* **可靠来源 → BLOCK**：`/proc/<pid>/cmdline` 里**锚定**出来的作业入口、`ss` 上的 HCCL 端口。
* **不可靠来源 → 只 WARN**：`npu-smi` 的进程表（输出格式随版本变）。
  **误拦比漏拦更糟** —— 被拦多了，人就会绕过整个工具，那所有判据一起失效。

★ §6.3 要求「区分**没启用**与**搜了没搜到**」：`capture` 的快照里带一个 `sources` 段，
  逐条写明这次**问了谁**（`/proc` 在不在、`ss` 有没有、`npu-smi` 在不在）以及问出了什么；
  `check` 也会把"这一层没搜"写成 `NPU_SCAN_SKIPPED:` 行 —— 空输出与"扫了没命中"
  在证据上必须能分开。

## 录制回放

占用检查依赖 `/proc`，那是**机器状态**：直接读它的测试会随本机负载飘（今天过、明天挂，
而挂的原因与被测代码无关）。`capture` 把此刻的占用原样存下来，`LP_RESOURCES_STATE=<快照>`
（或 `--state`）之后对着**同一份**快照重放。回放时**大声说明"这是快照，不是现场"**。

## 退出码

    0  通过（可以开跑）
    2  用法／契约不过（策略读不到、卡号写不对、定卡定不下来、探测不了…）
       或 **资源冲突**（`check`：可靠来源发现冲突）⇒ 现在不能起作业
       ★ 它不是判定：说的是"现在不能起作业"，不是"方案不好"。

## 用法

    python3 runtime/resources.py cards                     # 逐卡 AICore% / HBM
    python3 runtime/resources.py pick --json                # 定卡（含三层来源）
    python3 runtime/resources.py check --cards 4,5,6,7      # 起作业前查冲突（2 = BLOCK）
    python3 runtime/resources.py capture --out /tmp/snap.json
    LP_RESOURCES_STATE=/tmp/snap.json python3 runtime/resources.py check --cards 4,5,6,7
    python3 runtime/resources.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

#: 本模块所在目录（`runtime/`）与默认配置根（工程根）。
MODULE_DIR = pathlib.Path(__file__).resolve().parent
DEFAULT_ROOT = MODULE_DIR.parent

#: 快照环境变量：设了就用它，**不读现场**（回放）。
STATE_ENV = "LP_RESOURCES_STATE"

#: 允许用**环境变量**临时覆盖策略层（一次性排障／演练用；常态值住在 `config/project.yaml`）。
ENV_RESERVED = "LP_CARDS_RESERVED"
ENV_USABLE = "LP_CARDS_USABLE"
ENV_REQUIRE_EXPLICIT = "LP_CARDS_REQUIRE_EXPLICIT"
ENV_EXPLICIT_CARDS = "LP_CARDS"
ENV_EXPORTED = "ASCEND_RT_VISIBLE_DEVICES"
ENV_HCCL_PORT = "LP_HCCL_PORT"

#: HCCL 默认绑的端口。实测 8 个 rank 在各自网卡 IP 上绑**同一个**端口；
#: 被占时 torchrun 会在 `hcclCommInitRank` 处失败（`Communication_Error_Bind_IP_Port` EI0020）。
HCCL_DEFAULT_PORT = 16666

#: 低于这个显存量、且 AICore 为 0，才视为空闲。
#:
#: ★ **这个数不能拍脑袋 —— 拍错的方向是"永远判不空闲"。**
#: 本机实测（本趟 `npu-smi info`，8 张 910B3，机器空闲、每张卡都报
#: "No running processes found"）：AICore 0%，HBM **3423–3425 MB / 65536**。
#: 那是驱动/上下文留下的**底噪，清不掉**。旧工程第一版把阈值写成 `2048`
#: （比底噪还低）⇒ 判定永远不空闲 ⇒ 卡确实空着 21 分钟而守卫一路报"仍被占用"。
#: 6144 落在底噪（≈3.4G）与最小真实作业（≈12G）之间，两边都有近 2× 余量。
_HBM_IDLE_MB = 6144

#: 编排进程只认真正的那几个入口 —— 用来排除**我们自己**的探测进程。
#: ★ 只登记**具体路径形态**，不许用裸子串：旧工程曾把本工程的数据根路径当标记，
#: 于是本工程自己的作业被全部排除，两个作业抢同一批卡时被放行（且不报错）。
SELF_MARKERS = ("runtime/resources.py",)

#: 入口名锚定：`argv[0]` 的 basename 必须像"能跑作业的东西"。
_LAUNCHER_RE = re.compile(
    r"^(python[0-9.]*|torchrun|torch\.distributed\.run|mpirun|mpiexec)$")
#: 入口名必须落在**独立 argv 元素**上。
_ENTRY_MARKERS = (
    "posttrain_gpt.py",      # 训练入口名（框架侧，不是模型名）
    "pretrain_gpt.py",
    "evaluation.py",
    "torchrun",
    "torch.distributed.run",
)
#: `npu-smi info` 的逐卡表与进程表。
_NPU_LINE_RE = re.compile(r"^\|(.*)\|\s*$", re.M)
#: 明细行里 `num/num` 可能出现两次（Hugepages、HBM）—— 取**最后一对**。
_PAIR_RE = re.compile(r"(\d+)\s*/\s*(\d+)")
#: Bus-Id 形状：`0000:01:00.0`。（进程表行的第二列是纯数字 pid，天然排除。）
_BUS_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-9a-fA-F]$")
#: `npu-smi info` 进程表行：`| <npu> <chip> | <pid> | <name> | <mem> |`。
#: ★ 名字列**可以是空的**（实测本机就是空）—— 旧版正则要求名字非空，
#: 于是把真进程全部丢掉，只剩一句 WARN，看起来像"扫过了、没问题"。
_NPU_PROC_RE = re.compile(
    r"^\|\s*(\d+)\s+(\d+)\s*\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(\d+)\s*\|\s*$", re.M)


# ---------------------------------------------------------------------------
# 配置根 / 工程级配置
# ---------------------------------------------------------------------------

def _find_root(explicit: str | None = None) -> pathlib.Path:
    """配置根：`--root` > `LP_ROOT` > 本文件上一级。**解析不出来就退出 2**。"""
    cand = explicit or os.environ.get("LP_ROOT") or str(DEFAULT_ROOT)
    root = pathlib.Path(cand).expanduser().resolve()
    if not (root / "config" / "project.yaml").is_file() or not (root / "VERSION").is_file():
        raise SystemExit(
            f"ERROR: 配置根指错或不是一个工程根：{root}\n"
            "  需要同时存在 config/project.yaml 与 VERSION（fail-closed，不回退、不猜）。")
    return root


def _read_devices(root: pathlib.Path) -> dict:
    """读 `config/project.yaml` 的 `devices` 段。**缺失即退出 2**（不猜卡策略）。"""
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - 本环境有 PyYAML
        raise SystemExit(f"ERROR: 需要 PyYAML 才能读 config/project.yaml：{exc}") from None
    path = root / "config" / "project.yaml"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"ERROR: 读不了 {path}：{exc}") from None
    dev = (doc or {}).get("devices") if isinstance(doc, dict) else None
    if not isinstance(dev, dict):
        raise SystemExit(
            f"ERROR: {path} 里没有 devices 段（usable / reserved / require_explicit）。\n"
            "  ⇒ 定卡策略没有落点，拒绝执行（fail-closed）。")
    for key in ("usable", "reserved", "require_explicit"):
        if key not in dev:
            raise SystemExit(f"ERROR: {path} 的 devices 段缺字段 `{key}`（fail-closed）。")
    return dev


# ---------------------------------------------------------------------------
# 工具：卡号
# ---------------------------------------------------------------------------

def parse_cards(spec) -> set:
    """`"0-3"` / `"4,5,6,7"` / `"0-2,5"` → `{0,1,2,3}`。

    非法 token 抛 `ValueError` —— **不静默忽略**：一个被悄悄丢掉的卡号
    会让"我要 4-7"变成"我要 7"，而两者都不报错。
    """
    out: set = set()
    if spec is None:
        return out
    for tok in str(spec).replace(" ", "").split(","):
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"卡号区间写不对：{tok!r}（形如 0-3）")
            lo, hi = int(a), int(b)
            if lo > hi:
                raise ValueError(f"卡号区间反了：{tok!r}")
            out |= set(range(lo, hi + 1))
        elif tok.isdigit():
            out.add(int(tok))
        else:
            raise ValueError(f"看不懂的卡号：{tok!r}（只认 4 / 4,5 / 4-7）")
    return out


def fmt_cards(cards: Iterable[int]) -> str:
    return ",".join(str(c) for c in sorted(set(int(c) for c in cards)))


@dataclass
class Policy:
    """哪些卡**允许**用，以及要不要人显式给卡。"""

    reserved: set
    usable: set
    require_explicit: bool
    source: str = "config/project.yaml devices.*"

    @classmethod
    def from_env(cls, env: dict = None, root: pathlib.Path | None = None):
        """策略层 = `config/project.yaml devices.*`，环境变量可临时覆盖（并留痕在 source 里）。"""
        e = env if env is not None else os.environ
        if root is None:
            raise SystemExit("ERROR: 内部错误：Policy.from_env 需要 root（策略没有落点）")
        dev = _read_devices(root)
        reserved_raw = str(dev.get("reserved", ""))
        usable_raw = str(dev.get("usable", ""))
        req_raw = dev.get("require_explicit")
        src = "config/project.yaml devices.*"
        over = [k for k in (ENV_RESERVED, ENV_USABLE, ENV_REQUIRE_EXPLICIT) if e.get(k)]
        if e.get(ENV_RESERVED):
            reserved_raw = e[ENV_RESERVED]
        if e.get(ENV_USABLE):
            usable_raw = e[ENV_USABLE]
        if e.get(ENV_REQUIRE_EXPLICIT):
            req_raw = e[ENV_REQUIRE_EXPLICIT]
        if over:
            src += " ＋ 环境变量覆盖(" + ",".join(over) + ")"
        try:
            reserved = parse_cards(reserved_raw)
            usable = parse_cards(usable_raw)
        except ValueError as exc:
            raise SystemExit(f"ERROR: 卡号策略配置不合法：{exc}") from None
        require = str(req_raw).strip().lower() not in ("0", "false", "no", "off", "")
        return cls(reserved=reserved, usable=usable, require_explicit=require, source=src)


# ---------------------------------------------------------------------------
# 录制 / 回放
# ---------------------------------------------------------------------------

_STATE_CACHE = {"loaded": False, "path": None, "doc": None}


def _load_state():
    """读快照（若 `LP_RESOURCES_STATE` 设了）。返回 dict 或 None。"""
    if _STATE_CACHE["loaded"]:
        return _STATE_CACHE["doc"]
    _STATE_CACHE["loaded"] = True
    path = os.environ.get(STATE_ENV, "").strip()
    if not path:
        return None
    _STATE_CACHE["path"] = path
    try:
        _STATE_CACHE["doc"] = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"ERROR: 读不了快照 {STATE_ENV}={path}：{exc}\n"
            "  （要么修好它，要么 unset —— **不会静默退回读现场**："
            "那样你以为是回放、其实是现场）") from None
    print(f"！ 使用**录制的快照**（不是现场）：{path}", file=sys.stderr)
    return _STATE_CACHE["doc"]


def _sources_now() -> dict:
    """这次**问了谁**：三个来源各自在不在。`没启用` 与 `搜了没搜到` 靠它分开。"""
    return {
        "proc": pathlib.Path("/proc").is_dir(),
        "ss": shutil.which("ss"),
        "npu_smi": shutil.which("npu-smi"),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "sources 写的是**这次问了谁**；某来源不在 ⇒ 那一层是「没搜」，"
                "不是「搜了没搜到」。",
    }


# ---------------------------------------------------------------------------
# 实测层：读现场
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NpuCard:
    """一张卡的瞬时状态（事实，不含判定）。"""

    npu: int
    aicore_pct: int
    hbm_used_mb: int
    hbm_total_mb: int

    @property
    def hbm_pct(self) -> float:
        return (100.0 * self.hbm_used_mb / self.hbm_total_mb
                if self.hbm_total_mb else 0.0)

    @property
    def looks_busy(self) -> bool:
        return self.aicore_pct > 0 or self.hbm_used_mb > _HBM_IDLE_MB


@dataclass(frozen=True)
class BusyProcess:
    pid: int
    cmdline: str
    source: str = "proc"
    device: str = "?"

    def short(self, n: int = 130) -> str:
        c = " ".join(self.cmdline.split())
        return c[:n] + ("…" if len(c) > n else "")

    def label(self) -> str:
        where = f"npu{self.device} " if self.device else ""
        return f"{where}pid {self.pid}: {self.short()}"


def parse_npu_cards(text: str) -> "list[NpuCard]":
    """把 `npu-smi info` 的文本解析成 `[NpuCard]`。**配不上就返回空**（不猜）。"""
    heads, details = [], []
    for m in _NPU_LINE_RE.finditer(text):
        cols = [c.strip() for c in m.group(1).split("|")]
        # 首尾竖线已被 `_NPU_LINE_RE` 吃掉 ⇒ 切开是 3 列，不是 4。
        if len(cols) < 3:
            continue
        c0, c1 = cols[0], cols[1]
        parts = c0.split()
        if (len(parts) >= 2 and parts[0].isdigit()
                and any(ch.isalpha() for ch in parts[1])):
            heads.append(int(parts[0]))          # 卡头：`| <npu> <Name> | …`
            continue
        if _BUS_RE.match(c1):                    # 卡明细：`| <chip> | <Bus-Id> | …`
            pairs = _PAIR_RE.findall(cols[2])
            ai = re.match(r"\s*(\d+)", cols[2])
            if pairs and ai:
                used, total = pairs[-1]          # ★ 最后一对才是 HBM
                details.append((int(ai.group(1)), int(used), int(total)))
    if not heads or len(heads) != len(details):
        return []   # 配不上就不猜：宁可"读不到"，也不要一份错位却看起来正常的显存表
    return [NpuCard(npu=n, aicore_pct=ai, hbm_used_mb=u, hbm_total_mb=tot)
            for n, (ai, u, tot) in zip(heads, details)]


def read_npu_cards() -> "list[NpuCard]":
    """逐卡读 AICore% / HBM。**读不到返回空列表**（调用方必须把"读不到"与"空闲"分开）。"""
    st = _load_state()
    if st is not None:
        if not st.get("cards_readable", True):
            return []
        return [NpuCard(int(c["npu"]), int(c["aicore_pct"]),
                        int(c["hbm_used_mb"]), int(c["hbm_total_mb"]))
                for c in st.get("cards", [])]
    if not shutil.which("npu-smi"):
        return []
    try:
        r = subprocess.run(["npu-smi", "info"], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return []
    return parse_npu_cards(r.stdout or "")


def find_npu_processes() -> "list[BusyProcess]":
    """`npu-smi` 进程表：**只 WARN**（解析不可靠）。空名字的行也算真进程。"""
    st = _load_state()
    if st is not None:
        return [BusyProcess(int(q.get("pid", 0)), str(q.get("cmdline", "")),
                            source="npu-smi", device=str(q.get("device", "?")))
                for q in st.get("busy_npu", [])]
    if not shutil.which("npu-smi"):
        return []
    try:
        r = subprocess.run(["npu-smi", "info"], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for m in _NPU_PROC_RE.finditer(r.stdout or ""):
        npu, _chip, pid, name, mem = m.groups()
        out.append(BusyProcess(int(pid), f"{name.strip() or '（进程名为空）'} mem={mem}MB",
                               source="npu-smi", device=str(npu)))
    return out


def _iter_proc_cmdlines():
    st = _load_state()
    if st is not None:
        for p in st.get("busy_proc", []):
            yield int(p.get("pid", 0)), str(p.get("cmdline", ""))
        return
    root = pathlib.Path("/proc")
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except Exception:  # noqa: BLE001 - 进程随时可能消失
            continue
        if not raw:
            continue
        yield int(entry.name), raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()


def _visible_cards(pid: int, total: int):
    """读某进程的 `ASCEND_RT_VISIBLE_DEVICES`，判断它占哪几张卡。

    三种情况**必须分开**（混起来就会得出错误的占用结论）：
      * 读到具体卡号   → 返回那个集合
      * 变量**没有设** → 返回 `set(range(total))`：昇腾默认吃**所有可见卡**
      * environ 读不到 → 返回 `None`（未知）。**未知不等于没占**。
    """
    st = _load_state()
    if st is not None:
        for p in st.get("busy_proc", []):
            if int(p.get("pid", 0)) == pid:
                dev = str(p.get("device", "?"))
                return None if dev == "?" else {int(x) for x in dev.split(",") if x.isdigit()}
        return None
    try:
        raw = (pathlib.Path("/proc") / str(pid) / "environ").read_bytes()
    except Exception:  # noqa: BLE001
        return None
    val = None
    for item in raw.split(b"\x00"):
        if item.startswith((ENV_EXPORTED + "=").encode()):
            val = item.split(b"=", 1)[1].decode("utf-8", "replace").strip()
            break
    if val is None:
        return set(range(total))
    try:
        return parse_cards(val)
    except ValueError:
        return None


def find_training_processes(exclude_pids: Iterable[int] = (), root=None,
                            total: int = 0) -> "list[BusyProcess]":
    """`/proc` 里**锚定**出来的作业进程（可靠来源）。"""
    excl = {int(p) for p in exclude_pids}
    out = []
    for pid, cmdline in _iter_proc_cmdlines():
        if pid in excl:
            continue
        if any(m in cmdline for m in SELF_MARKERS):
            continue
        if not is_training_entry(cmdline, root=root):
            continue
        got = _visible_cards(pid, total or 8)
        dev = "?" if got is None else (fmt_cards(got) if got else "—")
        out.append(BusyProcess(pid=pid, cmdline=cmdline, source="proc", device=dev))
    return out


def find_port_occupants(port: int) -> "list[BusyProcess]":
    """谁在监听 `port`。**只探测，不自动换端口**（换端口能让两个作业共存，
    但它们抢的是同一批卡 —— 那正是需要人决定的事）。"""
    st = _load_state()
    if st is not None:
        return [BusyProcess(int(q.get("pid", 0)), str(q.get("cmdline", "")), source="ss")
                for q in st.get("ports", [])]
    if not shutil.which("ss"):
        return []
    try:
        # **必须带 -p** —— 不带就没有 users:(...) 列，pid 会是空的。
        r = subprocess.run(["ss", "-tlnpH"], capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local = parts[3]
        _, _, p = local.rpartition(":")
        if p != str(port):
            continue
        pid, name = 0, "?"
        m = re.search(r'\("([^"]+)",pid=(\d+)', line)
        if m:
            name, pid = m.group(1), int(m.group(2))
        out.append(BusyProcess(pid=pid, cmdline=f"{name} @ {local}", source="ss"))
    return out


def hccl_port() -> int:
    raw = os.environ.get(ENV_HCCL_PORT, "").strip()
    if raw.isdigit():
        return int(raw)
    return HCCL_DEFAULT_PORT


# ---------------------------------------------------------------------------
# 触发判据：这条命令行是不是一条**吃卡作业的入口**（`/proc` 扫描用）
# ---------------------------------------------------------------------------

def is_training_entry(cmd: str, root=None) -> bool:
    """锚定地判"这是不是一条**吃卡作业的入口**"（`argv[0]` 像启动器 ＋ 入口名独立成 argv 元素）。

    ★ 为什么两道锚定缺一不可：只按"命令行里出现某个入口名"判，
      `grep -r posttrain_gpt .` 会被当成作业（实测踩过），而它没有
      `ASCEND_RT_VISIBLE_DEVICES` ⇒ 按"占全部卡"处理 ⇒ **误拦一切合法作业**。
    """
    parts = cmd.split()
    if not parts:
        return False
    if not _LAUNCHER_RE.match(os.path.basename(parts[0])):
        return False
    for tok in parts[1:]:
        if os.path.basename(tok) in _ENTRY_MARKERS:
            return True
    return False


# ---------------------------------------------------------------------------
# 录制：把此刻的占用原样存下来（含"这次问了谁"）
# ---------------------------------------------------------------------------

def capture() -> dict:
    cards = read_npu_cards()
    procs = find_training_processes()
    npu_procs = find_npu_processes()
    ports = find_port_occupants(hccl_port())
    return {
        "schema": 1,
        "captured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "resources.py capture 的快照。字段是事实，不含判定。",
        "sources": _sources_now(),
        "hccl_port": hccl_port(),
        "cards_readable": bool(cards),
        "cards": [{"npu": c.npu, "aicore_pct": c.aicore_pct,
                   "hbm_used_mb": c.hbm_used_mb,
                   "hbm_total_mb": c.hbm_total_mb} for c in cards],
        "busy_proc": [{"pid": p.pid, "cmdline": p.cmdline, "device": p.device}
                      for p in procs],
        "busy_npu": [{"pid": p.pid, "cmdline": p.cmdline, "device": p.device}
                     for p in npu_procs],
        "ports": [{"pid": p.pid, "cmdline": p.cmdline} for p in ports],
    }


# ---------------------------------------------------------------------------
# 占用检查（可靠来源 BLOCK；不可靠来源只 WARN）
# ---------------------------------------------------------------------------

#: 前缀 → 拦/告知 的分类**只有一个来源**（曾两边各写一份且不一致 ⇒ 把 WARN 当 BLOCK）。
CARD_WARN_PREFIXES = ("NPU_ELSEWHERE:", "NPU_BUSY_WARN:", "NPU_SCAN_SKIPPED:")


def check_devices_idle(exclude_pids: Iterable[int] = (), cards=None,
                       root=None) -> "list[str]":
    """返回问题描述列表；**空列表 = 可以开跑**。

    `cards` 给定时**只判这些卡**（卡 4-7 被占、而我要用 0-3 时，整机判据会拦下
    一个完全合法的请求 —— **误拦比漏拦更糟**）。
    """
    msgs: list = []
    st = _load_state()

    # ── 先说清"这一层搜了没有"（没启用 ≠ 搜了没搜到）──
    if st is None and not pathlib.Path("/proc").is_dir():
        msgs.append("NPU_SCAN_SKIPPED: /proc 不可用 ⇒ 训练进程这一层**没搜**"
                    "（不是「搜了没搜到」）。可靠来源缺失时不许把结论说成「空闲」。")

    procs = find_training_processes(exclude_pids, root=root)
    if cards is not None and procs:
        want = set(int(c) for c in cards)
        clash, other, unknown = [], [], []
        for p in procs:
            if p.device in ("?", "—", ""):
                unknown.append(p)       # 读不到用哪几张卡 ⇒ 不能假定它不占
                continue
            have = {int(x) for x in p.device.split(",") if x.strip().isdigit()}
            (clash if have & want else other).append(p)
        if clash or unknown:
            who = clash + unknown
            shown = "; ".join(p.label() for p in who[:3])
            more = f"（另有 {len(who) - 3} 个）" if len(who) > 3 else ""
            why = (f"其中 {len(unknown)} 个读不到它用哪几张卡 —— 未知不等于没占。"
                   if unknown else "")
            msgs.append(
                f"NPU_BUSY: 要用的卡 {sorted(want)} 上有 {len(who)} 个训练进程 → "
                f"{shown}{more}。{why}"
                "两个作业抢同一批卡会 Bind_IP_Port 失败；更糟的是可能各自拿到部分卡、"
                "都跑完，却都产出无效结论（这种失败不报错）")
            return msgs
        if other:
            msgs.append(f"NPU_ELSEWHERE: 卡 {sorted(want)} 空闲，但别的卡上有 "
                        f"{len(other)} 个训练作业在跑（本次不冲突，仅告知）")
        procs = []

    if procs:
        shown = "; ".join(p.label() for p in procs[:3])
        more = f"（另有 {len(procs) - 3} 个）" if len(procs) > 3 else ""
        msgs.append(f"NPU_BUSY: 机器上已有 {len(procs)} 个训练进程在跑 → {shown}{more}。"
                    "两个作业抢同一批卡会 Bind_IP_Port 失败；更糟的是可能各自拿到部分卡、"
                    "都跑完，却都产出无效结论（这种失败不报错）")
        return msgs

    npu = find_npu_processes()
    if st is None and not shutil.which("npu-smi"):
        msgs.append("NPU_SCAN_SKIPPED: npu-smi 不在 ⇒ 逐卡状态这一层**没搜**"
                    "（不是「搜了没搜到」）。")
    if npu:
        if cards is not None:
            want = set(int(c) for c in cards)
            on_ours, elsewhere = [], []
            for q in npu:
                have = {int(x) for x in str(q.device).split(",") if x.strip().isdigit()}
                if not have:
                    on_ours.append(q)
                    continue
                (on_ours if have & want else elsewhere).append(q)
            if not on_ours:
                msgs.append(f"NPU_ELSEWHERE: 卡 {sorted(want)} 空闲，但 npu-smi 在别的卡上"
                            f"显示 {len(elsewhere)} 个进程（本次不冲突，仅告知）")
                return msgs
            shown = "; ".join(p.label() for p in on_ours[:3])
            msgs.append(f"NPU_BUSY_WARN: 进程扫描未发现训练作业，但 npu-smi 显示卡 "
                        f"{sorted(want)} 上有 {len(on_ours)} 个进程 → {shown}。"
                        "npu-smi 输出解析不可靠，故只警告。")
            return msgs
        shown = "; ".join(p.label() for p in npu[:3])
        msgs.append(f"NPU_BUSY_WARN: 进程扫描未发现训练作业，但 npu-smi 显示 "
                    f"{len(npu)} 个进程占用 NPU → {shown}。npu-smi 输出解析不可靠，故只警告。")
        return msgs

    port = hccl_port()
    occupied = find_port_occupants(port)
    if occupied:
        shown = "; ".join(p.label() for p in occupied[:3])
        more = f"（另有 {len(occupied) - 3} 个）" if len(occupied) > 3 else ""
        msgs.append(
            f"NPU_PORT_BUSY: HCCL 端口 {port} 已被占用 → {shown}{more}。"
            f"torchrun 会在 hcclCommInitRank 处失败"
            f"（Communication_Error_Bind_IP_Port EI0020）。**不自动换端口** —— "
            f"换掉能让两个作业共存，但它们抢的是同一批卡，那正是需要人决定的事。")
    return msgs


def blocking(problems: Iterable[str]) -> "list[str]":
    """从问题列表里挑出**阻塞**的那些（分类跟着产生处放，见 `CARD_WARN_PREFIXES`）。"""
    return [p for p in problems if not p.startswith(CARD_WARN_PREFIXES)]


# ---------------------------------------------------------------------------
# 决策层：本轮用哪几张卡
# ---------------------------------------------------------------------------

@dataclass
class PickResult:
    cards: set
    source: str
    why: list
    ok: bool = True
    fatal: str = ""


def pick_cards(policy: Policy, *, explicit=None, exported=None,
               max_used_mb: int = _HBM_IDLE_MB, cards_state=None) -> PickResult:
    """算出本轮用哪几张卡。优先级：**显式指定 > 已导出的 `ASCEND_RT_VISIBLE_DEVICES` > 自动探测**。

    `cards_state`：`[(npu, aicore_pct, hbm_used_mb)]`。`None` 表示**探测不了** ——
    那时拒绝自动选卡（**这不是"全都空闲"**）。
    """
    why: list = []

    # ── ① 显式指定 ──
    if explicit:
        got = set(int(c) for c in explicit)
        bad = got & policy.reserved
        if bad:
            return PickResult(got, f"explicit({ENV_EXPLICIT_CARDS})", why, ok=False,
                              fatal=(f"卡 {sorted(bad)} 在策略层的 reserved（别人的卡）里。"
                                     f"**永不选 reserved 的卡** —— 显式点名也不行。"))
        return PickResult(got, f"explicit({ENV_EXPLICIT_CARDS})", why)

    # ── ② 已导出的 ASCEND_RT_VISIBLE_DEVICES ──
    if exported:
        got = set(int(c) for c in exported)
        bad = got & policy.reserved
        if bad:
            return PickResult(got, f"env:{ENV_EXPORTED}", why, ok=False,
                              fatal=(f"已导出的 {ENV_EXPORTED} 里含 reserved 卡 "
                                     f"{sorted(bad)}。**永不选 reserved 的卡** —— 改掉它。"))
        return PickResult(got, f"env:{ENV_EXPORTED}", why)

    # ── ③ 自动探测 ──
    if policy.require_explicit:
        return PickResult(set(), "none", why, ok=False,
                          fatal=(f"策略层 require_explicit=true：不允许隐式选卡。"
                                 f"请显式给出 {ENV_EXPLICIT_CARDS}（如 "
                                 f"{ENV_EXPLICIT_CARDS}=4,5,6,7）。"))
    if cards_state is None:
        return PickResult(set(), "auto", why, ok=False,
                          fatal=("读不到卡的状态（npu-smi 不可用 / 输出不认识）。"
                                 "**探测不了不等于空闲** —— 拒绝自动选卡，请显式给出 "
                                 f"{ENV_EXPLICIT_CARDS}。"))
    cand = sorted(policy.usable - policy.reserved)
    why.append(f"候选范围 = usable({fmt_cards(policy.usable)}) − "
               f"reserved({fmt_cards(policy.reserved)}) = {fmt_cards(cand)}")
    free, busy = [], []
    for npu, aicore, used in cards_state:
        if npu not in cand:
            why.append(f"卡 {npu}: 不在候选范围，跳过")
            continue
        (busy if (aicore > 0 or used > max_used_mb) else free).append((npu, aicore, used))
    for npu, aicore, used in busy:
        why.append(f"卡 {npu}: 忙（AICore {aicore}%, HBM {used}MB > {max_used_mb}MB）→ 排除")
    for npu, aicore, used in free:
        why.append(f"卡 {npu}: 空闲（AICore {aicore}%, HBM {used}MB <= {max_used_mb}MB）")
    if not free:
        return PickResult(set(), "auto", why, ok=False,
                          fatal=(f"候选范围 {fmt_cards(cand)} 内没有空闲卡"
                                 f"（读到的状态：{[(n, a, u) for n, a, u in cards_state]}）。"
                                 "等别的作业结束，或显式指定其它卡。"))
    return PickResult(set(n for n, _, _ in free), "auto", why)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _layers(root, policy, cards):
    snap = os.environ.get(STATE_ENV, "").strip()
    return {
        "policy": {"usable": fmt_cards(policy.usable),
                   "reserved": fmt_cards(policy.reserved),
                   "require_explicit": policy.require_explicit,
                   "source": policy.source},
        "measured": {"readable": bool(cards),
                     "cards": [{"npu": c.npu, "aicore_pct": c.aicore_pct,
                                "hbm_used_mb": c.hbm_used_mb,
                                "hbm_total_mb": c.hbm_total_mb,
                                "looks_busy": c.looks_busy} for c in (cards or [])],
                     "source": (f"{STATE_ENV}={snap}（快照，不是现场）" if snap
                                else "npu-smi info")},
    }


def _cmd_cards(args) -> int:
    cards = read_npu_cards()
    if not cards:
        msg = ("读不到卡的状态：npu-smi 不可用，或输出格式不认识。"
               "**这不代表卡是空闲的。**")
        if args.json:
            print(json.dumps({"ok": False, "reason": msg, "cards": [],
                              "sources": _sources_now()}, ensure_ascii=False))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"ok": True,
                          "cards": [{"npu": c.npu, "aicore_pct": c.aicore_pct,
                                     "hbm_used_mb": c.hbm_used_mb,
                                     "hbm_total_mb": c.hbm_total_mb,
                                     "hbm_pct": round(c.hbm_pct, 1),
                                     "looks_busy": c.looks_busy} for c in cards],
                          "sources": _sources_now()}, ensure_ascii=False, indent=2))
        return 0
    print(f"逐卡状态（空闲判据：AICore == 0 且 HBM <= {_HBM_IDLE_MB}MB）：")
    print(f"  {'卡':>3}  {'AICore%':>8}  {'HBM(MB)':>18}  {'占比':>6}  判断")
    for c in cards:
        print(f"  {c.npu:>3}  {c.aicore_pct:>8}  "
              f"{c.hbm_used_mb:>7} / {c.hbm_total_mb:<7}  "
              f"{c.hbm_pct:>5.1f}%  {'忙' if c.looks_busy else '空闲'}")
    free = fmt_cards([c.npu for c in cards if not c.looks_busy])
    print(f"\n  空闲卡：{free or '（无）'}")
    src = _sources_now()
    print(f"  这次问了谁：/proc={'在' if src['proc'] else '不在'}  "
          f"ss={src['ss'] or '不在'}  npu-smi={src['npu_smi'] or '不在'}")
    return 0


def _cmd_check(args) -> int:
    try:
        cards = parse_cards(args.cards) if args.cards else None
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    problems = check_devices_idle(cards=cards, root=args._root)
    blk = blocking(problems)
    if args.json:
        print(json.dumps({"ok": not blk,
                          "cards": sorted(cards) if cards else None,
                          "blocking": blk,
                          "warn": [p for p in problems if p not in blk],
                          "is_verdict": False}, ensure_ascii=False, indent=2))
    else:
        for p in problems:
            print(f"  [{'BLOCK' if p in blk else 'WARN '}] {p}")
        if not problems:
            print("  OK：可靠来源（/proc 训练进程、ss 端口）没发现冲突。"
                  "（这是**现在能不能起作业**，不是判定。）")
    return 2 if blk else 0


def _cmd_pick(args) -> int:
    root = args._root
    policy = Policy.from_env(root=root)
    try:
        explicit = (parse_cards(args.cards) if args.cards
                    else parse_cards(os.environ.get(ENV_EXPLICIT_CARDS, "")))
        exported = parse_cards(os.environ.get(ENV_EXPORTED, ""))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # 卡必须是本机存在的（拦住"要出不存在的卡"这种静默配置错误）
    cards_now = read_npu_cards()
    known = {c.npu for c in cards_now} or (policy.usable | policy.reserved)
    unknown_cards = sorted((set(explicit) | set(exported)) - known)
    if unknown_cards and known:
        print(f"ERROR: 指名了本机不存在的卡 {unknown_cards}（本机读到的卡号："
              f"{fmt_cards(known)}）⇒ 退出 2。", file=sys.stderr)
        return 2

    state = None
    if not explicit and not exported and not policy.require_explicit:
        state = ([(c.npu, c.aicore_pct, c.hbm_used_mb) for c in cards_now]
                 if cards_now else None)

    r = pick_cards(policy, explicit=explicit or None, exported=exported or None,
                   cards_state=state)

    # ★ `pick` 不只是"选"，还要**验**：选完把集合交给同一个占用检查。
    #   "选出一个会被静默干扰的集合"正是本模块存在的理由。
    if r.ok and r.cards:
        problems = check_devices_idle(cards=r.cards, root=root)
        blk = blocking(problems)
        if blk:
            r = PickResult(r.cards, r.source, list(r.why), ok=False,
                           fatal=("选出来的卡**过不了占用检查**（这不是判定，"
                                  "是「现在不能起作业」）：" + blk[0]))
        elif problems:
            r.why.extend(problems)

    layers = _layers(root, policy, cards_now)
    layers["decision"] = {"cards": fmt_cards(r.cards), "source": r.source,
                          "ok": r.ok, "why": r.why, "fatal": r.fatal}
    if args.json:
        print(json.dumps({"ok": r.ok, "cards": sorted(r.cards),
                          "export": fmt_cards(r.cards), "source": r.source,
                          "why": r.why, "fatal": r.fatal, "layers": layers,
                          "is_verdict": False}, ensure_ascii=False, indent=2))
    else:
        print("== 本轮用卡（定卡三层，每层都打来源）==")
        print(f"  策略层（{policy.source}）："
              f"usable={fmt_cards(policy.usable)} "
              f"reserved={fmt_cards(policy.reserved) or '（无）'} "
              f"require_explicit={policy.require_explicit}")
        m = layers["measured"]
        print(f"  实测层（{m['source']}）："
              + (f"读到了 {len(m['cards'])} 张（逐卡状态见 `cards`）" if m["readable"]
                 else "**读不到** ⇒ 探测不了 ≠ 空闲"))
        for w in r.why:
            print(f"    · {w}")
        if r.ok:
            print(f"  决策层（来源 {r.source}）：卡 {fmt_cards(r.cards)}")
            print(f"    export {ENV_EXPORTED}={fmt_cards(r.cards)}")
            print("    说明：这是**资源选择**，不是判定。")
        else:
            print(f"  决策层（来源 {r.source}）：**选不出来**：{r.fatal}")
    return 0 if r.ok else 2


def _cmd_capture(args) -> int:
    doc = capture()
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
        print(f"快照已写 {args.out}")
        print(f"  回放：{STATE_ENV}={args.out} python3 runtime/resources.py check --cards 4,5,6,7")
    else:
        print(text)
    return 0


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="resources.py",
        description="起作业前看机器空不空；并动态决定本轮用哪几张卡（只探测，不判定）")
    ap.add_argument("--root", default="", help="配置根（等价于 LP_ROOT；指错即退出 2）")
    ap.add_argument("--state", default="",
                    help=f"用录制的快照代替现场（等价于 {STATE_ENV}=<文件>）")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="sub")
    p1 = sub.add_parser("cards", help="逐卡读 AICore%% / HBM")
    p1.add_argument("--json", action="store_true")
    p1.set_defaults(fn=_cmd_cards)
    p2 = sub.add_parser("check", help="起作业前检查冲突（2 = BLOCK）")
    p2.add_argument("--cards", default="", help="只判这些卡，如 4,5,6,7")
    p2.add_argument("--json", action="store_true")
    p2.set_defaults(fn=_cmd_check)
    p3 = sub.add_parser("pick", help="动态选出本轮用卡")
    p3.add_argument("--cards", default="", help="显式指定（覆盖自动探测）")
    p3.add_argument("--json", action="store_true")
    p3.set_defaults(fn=_cmd_pick)
    p4 = sub.add_parser("capture", help="把此刻占用存成快照（可离线回放）")
    p4.add_argument("--out", default="", help="写到文件；不给则打到 stdout")
    p4.set_defaults(fn=_cmd_capture)
    return ap


def main(argv=None) -> int:
    ap = build_argparser()
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.state:
        os.environ[STATE_ENV] = args.state
    _STATE_CACHE["loaded"] = False
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    try:
        args._root = _find_root(args.root or None)
        return args.fn(args)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# 自测（全部用构造输入 ⇒ 不依赖本机真实占用，也不写盘）
# ---------------------------------------------------------------------------

#: `npu-smi info` 的**形状** fixture（不是本机实测输出）——
#: 只用来钉解析器对已知形状的行为，包括两个实测踩过的坑：
#:   * `58369/ 65536` 与 `12000 / 65536` 两种空格；
#:   * 进程表里**进程名为空**的行（旧版据此丢弃真进程）。
SAMPLE_SMI = """\
+------------------------------------------------------------------------------------------------+
| npu-smi 25.5.2                   Version: 25.5.2                                               |
+---------------------------+---------------+----------------------------------------------------+
| NPU   Name                | Health        | Power(W)    Temp(C)           Hugepages-Usage(page)|
| Chip                      | Bus-Id        | AICore(%)   Memory-Usage(MB)  HBM-Usage(MB)        |
+===========================+===============+====================================================+
| 0     910B3               | OK            | 101.0       51                0    / 0             |
| 0                         | 0000:C1:00.0  | 0           0    / 0          3423 / 65536         |
+===========================+===============+====================================================+
| 4     910B3               | OK            | 179.0       67                0    / 0             |
| 0                         | 0000:01:00.0  | 76          0    / 0          58369/ 65536         |
+===========================+===============+====================================================+
| 5     910B3               | OK            | 178.3       66                0    / 0             |
| 0                         | 0000:02:00.0  | 0           0    / 0          12000 / 65536         |
+===========================+===============+====================================================+
+---------------------------+---------------+----------------------------------------------------+
| NPU     Chip              | Process id    | Process name             | Process memory(MB)      |
+===========================+===============+====================================================+
| 4       0                 | 267310        |                          | 48935                  |
| 6       0                 | 267311        | python3                  | 12000                  |
+---------------------------+---------------+----------------------------------------------------+
"""


def selftest() -> int:
    checks, fails = [], []

    def case(name, cond, detail=""):
        checks.append(name)
        if cond:
            print(f"  ok    {name}")
        else:
            print(f"  FAIL  {name}    {detail}")
            fails.append(name)

    print("=" * 70)
    print("resources.py --selftest（全部用构造输入；不依赖本机真实占用）")
    print("=" * 70)

    # --- 1 卡号解析 ---
    print("\n[1] 卡号解析（非法输入必须报错，不许静默丢）")
    case("4,5,6,7", parse_cards("4,5,6,7") == {4, 5, 6, 7})
    case("0-3 → 0123", parse_cards("0-3") == {0, 1, 2, 3})
    case("混合 0-2,5", parse_cards("0-2,5") == {0, 1, 2, 5})
    case("带空格", parse_cards(" 4 , 5 ") == {4, 5})
    for bad in ("4-a", "3-1", "x", "4;;5"):
        try:
            parse_cards(bad)
            case(f"非法 {bad!r} 必须抛错", False, "没抛")
        except ValueError:
            case(f"非法 {bad!r} 抛错", True)

    # --- 2 逐卡解析 ---
    print("\n[2] npu-smi 逐卡解析（两行一卡；斜杠前后空格不固定）")
    cs = parse_npu_cards(SAMPLE_SMI)
    case("解析出 3 张卡", len(cs) == 3, repr([c.npu for c in cs]))
    case("卡号正确 0/4/5", [c.npu for c in cs] == [0, 4, 5], repr(cs))
    case("★ HBM 取最后一对（不是 Hugepages 那对）",
         [c.hbm_used_mb for c in cs] == [3423, 58369, 12000], repr(cs))
    case("★ `58369/ 65536` 与 `12000 / 65536` 两种空格都认",
         cs[1].hbm_used_mb == 58369 and cs[2].hbm_used_mb == 12000)
    case("AICore 正确 0/76/0", [c.aicore_pct for c in cs] == [0, 76, 0], repr(cs))
    case("★ 进程表行没被当成卡头", len(cs) == 3, f"解析出 {len(cs)} 张")
    case("空输入 → 空列表（读不到就是读不到）", parse_npu_cards("") == [])
    case("配不上时返回空，不猜", parse_npu_cards("| 0  910B3 | OK |\n") == [])

    # --- 3 looks_busy 边界（实测校准过的阈值）---
    print(f"\n[3] looks_busy 边界（_HBM_IDLE_MB={_HBM_IDLE_MB}；本机实测空闲底噪 3423–3425MB）")
    idle = NpuCard(0, 0, 3423, 65536)
    case("★ 3423MB/AICore0 判**空闲**（那是驱动底噪，不是进程）", idle.looks_busy is False)
    case("★ 旧阈值 2048 会把它误判成忙（记下这个坑）", idle.hbm_used_mb > 2048)
    case("12000MB 判忙（最小真实作业量级）",
         NpuCard(5, 0, 12000, 65536).looks_busy is True)
    case("AICore>0 即使 HBM 低也判忙", NpuCard(4, 1, 100, 65536).looks_busy is True)
    case("恰好 6144 判空闲（> 才是忙）", NpuCard(0, 0, 6144, 65536).looks_busy is False)
    case("6145 判忙", NpuCard(0, 0, 6145, 65536).looks_busy is True)

    # --- 4 npu-smi 进程行：空名字也算真进程 ---
    print("\n[4] npu-smi 进程行：**名字为空也是真进程**（旧版据此丢弃真进程）")
    hits = list(_NPU_PROC_RE.finditer(SAMPLE_SMI))
    case("★ 空名字行命中（旧代码会扔掉它）", len(hits) == 2, f"{len(hits)} 条")
    case("命中行带出内存 48935（人判断的唯一线索）",
         bool(hits) and hits[0].group(5) == "48935",
         repr(hits[0].groups() if hits else None))
    case("空名字被替换成一句人话（不是空串）",
         bool(hits) and (hits[0].group(4).strip() or "（进程名为空）") == "（进程名为空）")
    case("★ 表头 `| NPU Chip |` 匹配不上（防表头的那句不是死代码）",
         not any("NPU" in h.group(4) for h in hits))

    # --- 5 _visible_cards：三种情况必须分开 ---
    print("\n[5] _visible_cards：设了 / 没设 / 读不到 —— 三种必须分开")
    case("★ 读不到（不存在的 pid）→ None，而不是空集", _visible_cards(999999999, 8) is None)
    notset = _visible_cards(os.getpid(), 8)
    case("★ 「没设」等于占全部可见卡（昇腾默认）—— 本机实测未设该变量",
         notset == set(range(8)), repr(notset))
    if os.environ.get(ENV_EXPORTED) is None:
        case("（前提核对）本进程环境里确实没有 %s" % ENV_EXPORTED, True)
    else:
        case("（前提核对）本进程环境里没有 %s" % ENV_EXPORTED, False,
             f"{ENV_EXPORTED}={os.environ.get(ENV_EXPORTED)}（继承来的，测不成立）")

    # --- 6 pick 三档优先级 ---
    print("\n[6] pick 优先级：显式 > 已导出 > 自动")
    pol = Policy(reserved={0, 1, 2, 3}, usable=set(range(8)), require_explicit=False)
    r = pick_cards(pol, explicit={6, 7})
    case("显式指定直接采用", r.cards == {6, 7} and r.source.startswith("explicit"), repr(r))
    r = pick_cards(pol, explicit={6, 7}, exported={4})
    case("显式压过已导出", r.cards == {6, 7}, repr(r.cards))
    r = pick_cards(pol, exported={4, 5})
    case("没有显式时用已导出的", r.cards == {4, 5} and r.source.startswith("env:"), repr(r))
    state = [(0, 0, 3423), (4, 76, 58369), (5, 0, 12000), (6, 0, 3423), (7, 0, 3425)]
    r = pick_cards(pol, cards_state=state)
    case("★ 自动探测只选空闲的 6,7（4 忙、5 HBM 高）", r.cards == {6, 7}, repr(r.cards))
    case("★ 自动探测**永不**选 reserved 的 0（尽管它空闲）", 0 not in r.cards, repr(r.cards))
    case("把排除理由写清楚（谁忙、多少）",
         any("忙" in w and "卡 4" in w for w in r.why), repr(r.why))
    case("候选范围也打出来（可复算）",
         any("候选范围" in w for w in r.why), repr(r.why))

    # --- 7 pick 硬约束 ---
    print("\n[7] pick 硬约束：永不选 reserved / 探测不了不自动选")
    r = pick_cards(pol, explicit={2, 3})
    case("★ 显式点名 reserved 卡 → 不 ok（永不选 reserved）", r.ok is False, repr(r.fatal))
    r = pick_cards(pol, exported={1, 2})
    case("★ 已导出的卡里含 reserved → 不 ok", r.ok is False, repr(r.fatal))
    r = pick_cards(pol, cards_state=None)
    case("★ 探测不了（None）→ 拒绝自动选卡，而不是当成全空闲",
         r.ok is False and "不等于空闲" in r.fatal, r.fatal)
    pol_req = Policy(reserved={0, 1, 2, 3}, usable=set(range(8)), require_explicit=True)
    r = pick_cards(pol_req, cards_state=state)
    case("require_explicit=true → 拒绝隐式选卡",
         r.ok is False and "require_explicit" in r.fatal, r.fatal)
    r = pick_cards(pol, cards_state=[(4, 90, 60000), (5, 0, 60000)])
    case("候选全忙 → 不 ok 并说明", r.ok is False and "没有空闲卡" in r.fatal, r.fatal)

    # --- 8 策略层从 config/project.yaml 读（不写死卡号）---
    print("\n[8] 策略层：卡号从 config/project.yaml 读（工程里不写死卡号）")
    with tempfile.TemporaryDirectory() as td:
        tdp = pathlib.Path(td)
        (tdp / "config").mkdir()
        (tdp / "VERSION").write_text("0.0.0\n", encoding="utf-8")
        (tdp / "config" / "project.yaml").write_text(
            "schema: 1\npaths:\n  experiments: experiments\n"
            "devices:\n  usable: \"0-7\"\n  reserved: \"0-3\"\n"
            "  require_explicit: true\n", encoding="utf-8")
        root = _find_root(str(tdp))
        p = Policy.from_env(env={}, root=root)
        case("从配置读 reserved=0-3", p.reserved == {0, 1, 2, 3}, repr(p.reserved))
        case("从配置读 usable=0-7", p.usable == set(range(8)), repr(p.usable))
        case("从配置读 require_explicit=true", p.require_explicit is True)
        case("来源串里写明是配置文件", "config/project.yaml" in p.source, p.source)
        p2 = Policy.from_env(env={ENV_USABLE: "4,5,6,7"}, root=root)
        case("环境变量可临时覆盖，并在来源串里留痕",
             p2.usable == {4, 5, 6, 7} and ENV_USABLE in p2.source, p2.source)
        (tdp / "config" / "project.yaml").write_text(
            "schema: 1\ndevices:\n  usable: \"0-7\"\n", encoding="utf-8")
        try:
            Policy.from_env(env={}, root=root)
            case("devices 缺字段必须退出 2", False, "没退")
        except SystemExit:
            case("devices 缺字段 ⇒ 退出 2（不猜策略）", True)
        try:
            _find_root(str(tdp / "nope"))
            case("配置根指错必须退出 2", False, "没退")
        except SystemExit:
            case("配置根指错 ⇒ 退出 2", True)

    # --- 9 分类常量只有一个来源 ---
    print("\n[9] 拦/告知 的分类跟着产生处放（防两边各写一份）")
    case("NPU_ELSEWHERE 属于 WARN", "NPU_ELSEWHERE:" in CARD_WARN_PREFIXES)
    case("NPU_BUSY_WARN 属于 WARN", "NPU_BUSY_WARN:" in CARD_WARN_PREFIXES)
    case("NPU_SCAN_SKIPPED 属于 WARN（没搜 ≠ 搜了没搜到）",
         "NPU_SCAN_SKIPPED:" in CARD_WARN_PREFIXES)
    case("★ NPU_BUSY 不在 WARN 里（它要 BLOCK）", "NPU_BUSY:" not in CARD_WARN_PREFIXES)
    case("blocking() 只挑阻塞项",
         blocking(["NPU_BUSY: x", "NPU_ELSEWHERE: y", "NPU_BUSY_WARN: z"]) == ["NPU_BUSY: x"])
    case("HCCL 端口默认 16666", HCCL_DEFAULT_PORT == 16666)
    old_port = os.environ.get(ENV_HCCL_PORT)
    try:
        os.environ[ENV_HCCL_PORT] = "19999"
        case("端口可用 %s 覆盖" % ENV_HCCL_PORT, hccl_port() == 19999, repr(hccl_port()))
    finally:
        if old_port is None:
            os.environ.pop(ENV_HCCL_PORT, None)
        else:
            os.environ[ENV_HCCL_PORT] = old_port

    # --- 10 录制/回放 ---
    print("\n[10] 录制回放：快照替代现场（换卡就换结论）")
    snap = {
        "schema": 1, "captured_at": "2026-01-01T00:00:00Z",
        "note": "fixture", "cards_readable": True,
        "sources": {"proc": True, "ss": "/usr/sbin/ss", "npu_smi": "/usr/local/sbin/npu-smi",
                    "checked_at": "2026-01-01T00:00:00Z", "note": "fixture"},
        "hccl_port": 16666,
        "cards": [{"npu": 0, "aicore_pct": 0, "hbm_used_mb": 3423, "hbm_total_mb": 65536},
                  {"npu": 4, "aicore_pct": 88, "hbm_used_mb": 58369, "hbm_total_mb": 65536}],
        "busy_proc": [{"pid": 4242, "device": "4", "cmdline": "python3 posttrain_gpt.py"}],
        "busy_npu": [{"pid": 4242, "device": "4", "cmdline": "python3 mem=58369MB"}],
        "ports": [],
    }
    with tempfile.TemporaryDirectory() as td:
        sp = pathlib.Path(td) / "snap.json"
        sp.write_text(json.dumps(snap), encoding="utf-8")
        old = os.environ.get(STATE_ENV)
        os.environ[STATE_ENV] = str(sp)
        _STATE_CACHE["loaded"] = False
        try:
            got = read_npu_cards()
            case("快照回放：读到 2 张卡（不是现场 8 张）", len(got) == 2, repr(got))
            probs = check_devices_idle(cards={0, 1, 2, 3})
            case("★ 快照里 4 号卡上的进程只看 4 号：要 0-3 时不冲突（只 WARN）",
                 all(not p.startswith("NPU_BUSY:") for p in probs), repr(probs))
            probs = check_devices_idle(cards={4, 5})
            case("★ 要 4 号卡时 BLOCK（同一份快照，换卡就换结论）",
                 any(p.startswith("NPU_BUSY:") for p in probs), repr(probs))
        finally:
            if old is None:
                os.environ.pop(STATE_ENV, None)
            else:
                os.environ[STATE_ENV] = old
            _STATE_CACHE["loaded"] = False
        bad = pathlib.Path(td) / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        os.environ[STATE_ENV] = str(bad)
        _STATE_CACHE["loaded"] = False
        try:
            read_npu_cards()
            case("★ 坏快照必须报错退出，而不是静默退回读现场", False, "没报")
        except SystemExit:
            case("★ 坏快照 ⇒ 退出 2（不静默退回读现场）", True)
        finally:
            os.environ.pop(STATE_ENV, None)
            _STATE_CACHE["loaded"] = False

    # --- 11 capture 的 sources 段（没启用 ≠ 搜了没搜到）---
    print("\n[11] capture 的 sources 段：这次**问了谁**要能看见")
    src = _sources_now()
    case("sources 里有 proc/ss/npu_smi 三个来源", {"proc", "ss", "npu_smi"} <= set(src))
    case("sources 里写明了「不在 ⇒ 那一层是没搜」",
         "没搜" in src["note"], src["note"])

    print()
    print("=" * 70)
    if fails:
        print(f"FAILED: {len(checks) - len(fails)}/{len(checks)}")
        for f in fails:
            print(f"  - {f}")
        return 1
    print(f"PASSED: {len(checks)}/{len(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
