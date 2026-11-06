#!/usr/bin/env python3
"""executor.py —— 起进程 ＋ 逐行落日志 ＋ 按观察在线早停 ＋ 杀进程组 ＋ 墙钟超时。

归属：三段执行器（`experimenter ──▶ runtime/{executor.py,resources.py,_common.sh,framework_patch.sh}`）。
实现步：**P4c**（P4 只交付了 `metrics.py` 与 `validate_round.py`；本文件当时是 `TODO(P4b)` 占位）。

## 四个机制（为什么是这四个，一条一条都是踩过的坑）

1. **行缓冲 ＋ 独立线程排空** —— 逐行落盘，不许因为管道缓冲区塞满而假死。
   * 日志文件用 `buffering=1`（行缓冲）打开：默认块缓冲会让磁盘上的 `train.log`
     任意滞后，"看不到进展"与"没有进展"就分不开。
   * `for line in proc.stdout` 在主循环里读会在进程不打印时**永久阻塞** ——
     而卡死的进程恰恰一行都不打印，等于放弃超时保护。故单独一个线程把输出灌进队列。
   * 子进程侧设 `PYTHONUNBUFFERED=1`（`LP_JOB_KEEP_BUFFERING=1` 可保留原行为）。
2. **按「观察」在线早停** —— 阈值**不进本文件**：全部来自调用方（**任务配置**
   `config/tasks/<任务名>.yaml` 的 `stop_conditions.loss.*`，由 `_common.sh` 取出后经
   `--jump-factor/--rel-to-best/--min-points`
   传入）。判定不是在这里比大小 —— 本文件把"到目前为止的 loss 序列"交给
   `metrics.training_observation()`（**全工程唯一一份**观察实现）回答；
   在线与离线看同一条轨迹必然用同一个答案。
   * 阈值缺失而早停开着 ⇒ **退出 2**（fail-closed）：本文件**没有**任何阈值默认值，
     悄悄用一个"看着合理"的数字，正是「阈值不进执行器」要防的事。
3. **杀整个进程组** —— `start_new_session=True` ＋ `os.killpg`。只杀父进程会留下孤儿继续吃卡。
4. **墙钟超时** —— `--timeout-s` / `--max-wall-hours`；到点同样杀整个进程组。

## 退出码（完整表在 `runtime/README.md` §2，唯一一份）

    0  成功
    1  命令自己失败（非零退出，未归类）
    2  约定/用法不过（缺命令、缺 --log、阈值缺失、参数非法）
    5  **训练侧无效**：发散早停 / 非有限值熔断 / **墙钟超时** ⇒ 杀整个进程组
       （0.18.26 起**平台早停不再归 5**：它记 `stop_kind=converged`、返回 0 —— 那是合法收工）
    6  **评测侧无效**（口径不全、驱动异常、结果不可比）

★ `6` 不由本文件产出，也**不该**由本文件产出：口径不全／驱动异常／结果不可比
  这三类**看不到**进程的退出码（进程可能以 0 退出而数字不可用），它们由评测入口
  （`eval.sh`）在读过产物与口径之后归类。本文件的 5／6 分工因此是：**5 是本文件判的**
  （阈值触发的主动终止，含墙钟超时 —— §2.1 的有意变更），**6 是评测侧判的**。
  写在这里，是为了让"本文件为什么不发 6"有个落点，而不是让它看起来漏了。

## 落点与纪律

* 逐行日志与进程元数据（`--log` / `--meta`）落 `<轮次>/evidence/`（原始证据，只读）。
* 本文件**不含**任何模型名／任务名／数据集名／阈值默认值（`devtools/check_decoupling.py` 会查）。
* 本文件**不判定**：不写 `metrics.json`（那是 `metrics.py` 的唯一职责）。`--quant-error-max`
  只是**历史透传参数**（0.18.14 起没有调用方喂它）：量化误差上限的唯一落点是任务配置的
  `stop_conditions.quant_error_max`，由 `train_cmd.sh` 换算成 `QAT_QSNR_FLOOR_DB` 注入探针看门狗；
  执行器不读判据、也不做比对（读了就是第二个事实来源）。

## 用法

    python3 runtime/executor.py --round R-0001 --stage train \\
        --log <证据目录>/train.log --loss-out <证据目录>/loss.txt \\
        --marker <证据目录>/early_stop.triggered --meta <证据目录>/train.exec.json \\
        --jump-factor 4.0 --rel-to-best 2.5 --min-points 2 --max-wall-hours 6 \\
        -- <命令...>

    python3 runtime/executor.py --selftest        # 不依赖真实训练；四机制各自真跑真看
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ★ 刻意**复用** metrics.py 的正则与观察实现，不在这里另写一份。
#   "两个来源决定同一个键"是本工程反复踩的坑：同一份日志两个过滤器，
#   迟早抽出的点数不一样，而两边都不报错。
MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))
import metrics  # noqa: E402

#: 退出码（与 runtime/README.md §2 的表述逐字对应；本文件只发其中 0/1/2/5）
EXIT_OK = 0
EXIT_CMD_FAILED = 1
EXIT_CONTRACT = 2
EXIT_TRAIN_INVALID = 5
EXIT_EVAL_INVALID = 6

#: 早停留痕里 `stop_kind` 的合法取值（唯一来源：`metrics.STOP_KINDS`，读者在那边）。
DEFAULT_STOP_KIND = "invalid"

#: 日志尾部保留行数（人看的诊断窗口，不是判定数据）
TAIL_LINES = 200


@dataclass
class JobResult:
    """一个作业跑完之后的**事实**。没有一个是判定。"""

    exit_code: int | None = None
    duration_s: float = 0.0
    early_stopped: bool = False
    timed_out: bool = False
    killed_reason: str = ""
    n_lines: int = 0
    last_iteration: int | None = None
    losses: list = field(default_factory=list)
    loss_lines: list = field(default_factory=list)
    #: 验证曲线（0.19.0）：**与训练曲线分开**。真机格式是
    #: ` validation loss at iteration N | lm loss value: 1.05E+00 |` —— `LOSS_RE` 要
    #: `loss` 后紧跟 `[:=]`，真格式匹配不上；但**老/别的变体**会打 `lm loss: …` 的验证行，
    #: 那种行会被 `LOSS_RE` 命中并混进训练曲线 ⇒ `jump_factor` 把"训练/验证交替"误判成跳变。
    #: 所以先按验证行分离，训练曲线只看剩下的行（与 `metrics.parse_loss_curves` 同口径）。
    valid: list = field(default_factory=list)
    valid_lines: list = field(default_factory=list)
    log_tail: list = field(default_factory=list)
    log_path: str = ""
    dry_run: bool = False
    #: 停下来的**种类**：`invalid`（发散/超时，这一轮作废）｜`converged`（平台，合法收工）
    stop_kind: "str | None" = None


def stage_exit_code(res: "JobResult") -> int:
    """**本段的判定码**（唯一决定点 —— 元数据与进程退出码都只从这里取）。

    ★ `res.exit_code` 是**子进程原始码**，不是判定码：早停时执行器杀整个进程组，
      torchrun 会在 worker 死掉后自己以 1 退出。把那个 1 当成本段结论，就把
      「平台早停（合法收工）」和「命令崩了」混成同一件事 —— 0.18.38 之前就是这样，
      于是任何按 `train.exec.json → exit_code` 判定的下游都把 converged 判死。
    """
    if res.timed_out:
        return EXIT_TRAIN_INVALID
    if res.early_stopped:
        kind = res.stop_kind or DEFAULT_STOP_KIND
        return EXIT_OK if kind == "converged" else EXIT_TRAIN_INVALID
    return EXIT_CMD_FAILED if res.exit_code != 0 else EXIT_OK


# ---------------------------------------------------------------------------
# 进程机制
# ---------------------------------------------------------------------------

def _kill_tree(proc: "subprocess.Popen") -> None:
    """杀掉整个进程组 —— torchrun 会派生 N 个 worker，只杀父进程会留下孤儿。"""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=20)
    except Exception:  # noqa: BLE001
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def _drain(pipe, q: "queue.Queue") -> None:
    """把子进程输出灌进队列。**必须单独一个线程**（见文件头 ①）。"""
    try:
        for line in pipe:
            q.put(line)
    except Exception:  # noqa: BLE001
        pass
    finally:
        q.put(None)  # 哨兵：告诉主循环没有更多输出了


def _read_best_round(best_dir: Path, cell: str) -> "tuple[str | None, str]":
    """`records/best/<cell>__*.yaml` 里的 `round:` ⇒ `(轮次 id, 说明)`。**找不到就说原因。**

    ★ 参照轮（0.19.0 定）：`records/best` 里那一轮天然"跑完 ＋ 通过判定 ＋ 证据齐全"，
      不用再从 `design.md` 认"哪个是框架原生轮"。
    ★ 多份就放弃：不同指标的 best 档案口径不同，合成一个参照就是拿两把尺子当一把。
    """
    d = Path(best_dir)
    if not d.is_dir():
        return None, f"还没有 {d}"
    hits = sorted(d.glob(f"{cell}__*.yaml"))
    if not hits:
        return None, f"{d} 里没有 {cell}__*.yaml"
    if len(hits) > 1:
        return None, f"{d} 里有 {len(hits)} 个本任务档案 ⇒ 参照有歧义，不猜"
    for line in hits[0].read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("#") or ":" not in s:
            continue
        k, _, v = s.partition(":")
        if k.strip() in ("round", "轮次"):
            return v.strip().strip('"'), f"参照轮来自 {hits[0].name}"
    return None, f"{hits[0].name} 没有 `round:` 字段"


def load_baseline_valid(rounds_dir: Path, round_id: str) -> "tuple[list, str]":
    """读参照轮的验证曲线（`<rounds_dir>/<轮次>/metrics.json` 的 `holdout.valid.curve`）。

    老轮次没有 `holdout` 段 ⇒ 退回它的 `evidence/valid.txt` / `train.log`。
    都没有 ⇒ 返回空曲线 ＋ 原因（racing 会自行判成"不判"）。
    """
    if not round_id:
        return [], "没有参照轮 id"
    bdir = Path(rounds_dir) / round_id
    mpath = bdir / "metrics.json"
    if mpath.is_file():
        try:
            doc = json.loads(mpath.read_text(encoding="utf-8"))
            curve = [((int(s), float(v)))
                     for s, v in ((doc.get("holdout") or {}).get("valid") or {}).get("curve") or []]
            if curve:
                return curve, f"{round_id}/metrics.json"
        except (OSError, ValueError, TypeError) as exc:
            return [], f"{round_id}/metrics.json 读不出验证曲线：{exc}"
    ev = bdir / "evidence"
    vp = ev / "valid.txt"
    if vp.is_file():
        curve, _ = metrics.parse_loss_curve(vp)
        if curve:
            return curve, f"{round_id}/evidence/valid.txt"
    lp = ev / "train.log"
    if lp.is_file():
        _tr, va, _n = metrics.parse_loss_curves(lp)
        if va:
            return va, f"{round_id}/evidence/train.log 的验证行"
    return [], f"{round_id} 没有验证曲线（历史轮次大多 --split 100,0,0，补不了）"


def _flag_value(argv: list, name: str) -> "str | None":
    """从 argv 里取 `--name value` 或 `--name=value` 的**值**；没给 ⇒ None。"""
    args = list(argv or [])
    for i, tok in enumerate(args):
        if tok == name and i + 1 < len(args):
            return args[i + 1]
        if tok.startswith(name + "="):
            return tok.split("=", 1)[1]
    return None


def make_gate(thresholds: dict, baseline_curve=None, holdout: dict = None):
    """造早停闸门：收"到目前为止的 loss 序列"，返回人话理由或 ``None``。

    ★ **阈值不进这个函数**（它们住在调用方，本文件一个默认值都没有）；
      判定**也不在这里** —— 交给 `metrics.training_observation`，全工程唯一一份。
    """
    tv = dict(thresholds or {})

    base = list(baseline_curve or [])
    hcfg = dict(holdout or {})

    def gate(curve: list, valid: list = None) -> "tuple[str, str] | None":
        """返回 `(人话理由, kind)`；kind 三选一：`invalid`（作废）／`holdout`（racing 淘汰）／
        `converged`（收工，结论有效）。

        ★ 优先级 invalid > holdout > converged：发散是"测的不是方案"；racing 是"没希望赢
          历史最好，腾卡"；平台是"不用再花算力，结论有效" —— 三件事处置不同，不许互相顶替。
        """
        obs = metrics.training_observation(curve, tv)
        if obs.get("early_stop_would_have_fired"):
            return (str(obs.get("early_stop_detail") or "在线早停条件满足"), "invalid")
        if hcfg:
            # ★ 判据只在 metrics.holdout_racing 一处；这里只决定"要不要问它"。
            r = metrics.holdout_racing(valid or [], base, hcfg)
            if r.get("fired"):
                return (str(r.get("reason") or "held-out racing 条件满足"), "holdout")
        if (obs.get("plateau") or {}).get("fired"):
            return (str(obs["plateau"].get("detail") or "平台早停条件满足"), "converged")
        return None

    return gate


# ---------------------------------------------------------------------------
# ckpt 刈草（0.18.26）
#
# 框架只有 `--save-interval`，**没有「保留几份」的开关**（参数表实查：save_interval /
# ckpt_fully_parallel_save / save_layer_by_layer / save_lora_to_hf，没有 save_retain）。
# 所以保留策略只能在进程**外面**做。六条安全规则写死在这里，别在调用方再写一套：
#   ① 只删 `<ckpt-dir>/iter_<数字>`；别的名字、别的层级一律不碰
#   ② **永不删最新一份**（无论 keep_last 配成什么）
#   ③ keep_last < 1 / 目录不存在 / 参数缺失 ⇒ 一个字节都不删
#   ④ mtime 在 120 s 内的目录不删（可能正在写）
#   ⑤ 删除失败只记日志，**不中断训练**
#   ⑥ 每次删除/保留都写一行到 retention log（人可审计）
# ---------------------------------------------------------------------------
ITER_DIR_RE = re.compile(r"^iter_(\d+)$")


def _iter_dirs(ckpt_dir: Path) -> list:
    out = []
    if not ckpt_dir.is_dir():
        return out
    for p in ckpt_dir.iterdir():
        if p.is_dir():
            m = ITER_DIR_RE.match(p.name)
            if m:
                out.append((int(m.group(1)), p))
    out.sort(key=lambda x: x[0])
    return out


def prune_checkpoints(ckpt_dir, keep_last, log_path=None, *, min_age_s: float = 120.0,
                      dry_run: bool = False, now: "float | None" = None) -> dict:
    """按 keep_last 删旧的 `iter_*`。返回 `{"kept":[...], "deleted":[...], "skipped":[...]}`。

    纯函数式：不 raise（除参数类型错），删不动就记 skipped。调它的地方可以放心不管它。
    """
    res = {"kept": [], "deleted": [], "skipped": []}
    if not ckpt_dir:
        return res
    d = Path(ckpt_dir)
    try:
        keep = int(keep_last)
    except (TypeError, ValueError):
        res["skipped"].append("keep_last 不是整数 ⇒ 不删")
        return res
    if keep < 1:
        res["skipped"].append(f"keep_last={keep} < 1 ⇒ 不删")
        return res
    iters = _iter_dirs(d)
    if len(iters) <= keep:
        res["kept"] = [p.name for _i, p in iters]
        return res
    newest = iters[-1][1]
    now = time.time() if now is None else now
    for _it, path in iters[:-keep]:
        if path == newest:                     # 规则②：理论上到不了，仍然挡一道
            res["kept"].append(path.name)
            continue
        try:
            age = now - path.stat().st_mtime
        except OSError:
            res["skipped"].append(f"{path.name}（stat 失败）")
            continue
        if age < min_age_s:                    # 规则④：可能正在写
            res["skipped"].append(f"{path.name}（{age:.0f}s 内刚动过，不删）")
            continue
        if dry_run:
            res["deleted"].append(path.name)
            continue
        try:
            shutil.rmtree(path)
        except OSError as e:                   # 规则⑤：不中断训练
            res["skipped"].append(f"{path.name}（删除失败：{e}）")
            continue
        res["deleted"].append(path.name)
    res["kept"] = [p.name for _i, p in _iter_dirs(d)]
    if log_path:
        try:
            lp = Path(log_path)
            lp.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(lp, "a", encoding="utf-8") as fh:
                if res["deleted"]:
                    fh.write(f"{stamp} 删除 {', '.join(res['deleted'])}"
                             f"（保留最近 {keep} 份：{', '.join(res['kept'])}）\n")
                for s in res["skipped"]:
                    fh.write(f"{stamp} 跳过 {s}\n")
        except OSError:
            pass
    return res


class _CkptKeeper(threading.Thread):
    """训练进程旁边的小扫帚：每 `interval` 秒清一次，退出前再清一次。"""

    def __init__(self, ckpt_dir, keep_last, log_path=None, *, interval: float = 60.0,
                 min_age_s: float = 120.0):
        super().__init__(name="ckpt-keeper", daemon=True)
        self.ckpt_dir = ckpt_dir
        self.keep_last = keep_last
        self.log_path = log_path
        self.interval = interval
        self.min_age_s = min_age_s
        self.total_deleted: list = []
        self._stop_evt = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.wait(self.interval):
            r = prune_checkpoints(self.ckpt_dir, self.keep_last, self.log_path,
                                  min_age_s=self.min_age_s)
            self.total_deleted.extend(r["deleted"])

    def stop(self) -> None:
        self._stop_evt.set()
        r = prune_checkpoints(self.ckpt_dir, self.keep_last, self.log_path,
                              min_age_s=self.min_age_s)
        self.total_deleted.extend(r["deleted"])


def run_process(
    cmd: list,
    log_path,
    *,
    cwd=None,
    env: dict = None,
    timeout_s: float = None,
    stop_gate=None,
    break_on_nonfinite: bool = True,
    dry_run: bool = False,
    echo: bool = True,
) -> JobResult:
    """起进程、逐行写日志、按需熔断。**同步阻塞到进程结束。**"""
    res = JobResult(log_path=str(log_path), dry_run=dry_run)
    log_p = Path(log_path)
    log_p.parent.mkdir(parents=True, exist_ok=True)

    if dry_run:
        # **buffering=1 = 行缓冲**（见文件头 ①）。
        with open(log_p, "a", encoding="utf-8", buffering=1) as fh:
            fh.write("[dry-run] " + " ".join(str(c) for c in cmd) + "\n")
        res.exit_code = 0
        res.log_tail = ["[dry-run]"]
        return res

    full_env = dict(os.environ)
    # ★ 让子进程**不缓冲**：我们自己行缓冲了，但子进程往管道写时默认也是块缓冲 8KB。
    if not full_env.get("LP_JOB_KEEP_BUFFERING"):
        full_env.setdefault("PYTHONUNBUFFERED", "1")
    if env:
        full_env.update(env)

    started = time.time()
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        cwd=str(cwd) if cwd else None,
        env=full_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        errors="replace",
        start_new_session=True,   # 自己的进程组，便于连同子进程一起杀（见文件头 ③）
    )

    tail: list = []
    q: "queue.Queue" = queue.Queue()
    reader = threading.Thread(target=_drain, args=(proc.stdout, q), daemon=True)
    reader.start()

    def _say(msg: str) -> None:
        if echo:
            print(msg, flush=True)

    def _check_stop() -> bool:
        """跑一次闸门；真停了返回 True（**判据在 metrics，这里只转发**）。

        ★ 闸门自己坏了不该让训练陪葬 —— 记一条并继续。（静默吞掉的话，
          "早停从没触发过"与"闸门一直在抛异常"看起来一模一样。）
        """
        if stop_gate is None:
            return False
        try:
            why = stop_gate(res.losses, res.valid)
        except Exception as e:  # noqa: BLE001
            tail.append(f"！在线早停闸门抛异常，本轮按不触发处理：{e}")
            _say(f"  ！在线早停闸门抛异常：{e}")
            return False
        if not why:
            return False
        thought = why
        if isinstance(thought, tuple):
            thought, kind = thought
            res.stop_kind = kind or DEFAULT_STOP_KIND
        else:
            res.stop_kind = DEFAULT_STOP_KIND
        res.early_stopped = True
        res.killed_reason = str(thought)
        _say(f"  ★ 在线早停：{res.killed_reason}")
        return True


    try:
        with open(log_p, "a", encoding="utf-8", buffering=1) as fh:
            while True:
                if timeout_s and (time.time() - started) > timeout_s:
                    res.timed_out = True
                    res.killed_reason = f"超过墙钟上限 {timeout_s:.0f}s"
                    break

                try:
                    line = q.get(timeout=0.5)
                except queue.Empty:
                    if not reader.is_alive() and q.empty():
                        break
                    continue

                if line is None:
                    break

                fh.write(line)
                res.n_lines += 1
                tail.append(line.rstrip("\n"))
                if len(tail) > TAIL_LINES:
                    del tail[:TAIL_LINES // 2]

                mi = metrics.ITER_RE.search(line)
                if mi:
                    res.last_iteration = int(mi.group(1))

                # ★ 0.19.0：**验证行先认**。顺序反了会把 `lm loss: …` 形态的验证行当训练点
                #   收进 losses（老 Megatron 变体就是这种），训练曲线里混进验证点 ⇒ jump_factor
                #   误判成跳变。认出来的验证行**不进** losses，只进 res.valid。
                mv = metrics.VALID_LINE_RE.search(line)
                if mv:
                    hit = metrics.LOSS_RE.search(line) or metrics.VALID_NUM_RE.search(line)
                    vval = metrics._to_float(hit.group(1)) if hit else None
                    if vval is not None:
                        res.valid_lines.append(line)
                        res.valid.append((int(mv.group(1)), vval))
                    if stop_gate is not None:
                        try:
                            why = stop_gate(res.losses, res.valid)
                        except Exception as e:  # noqa: BLE001
                            why = None
                            tail.append(f"！在线早停闸门抛异常，本轮按不触发处理：{e}")
                            _say(f"  ！在线早停闸门抛异常：{e}")
                        if why:
                            thought = why
                            if isinstance(thought, tuple):
                                thought, kind = thought
                                res.stop_kind = kind or DEFAULT_STOP_KIND
                            else:
                                res.stop_kind = DEFAULT_STOP_KIND
                            res.early_stopped = True
                            res.killed_reason = str(thought)
                            break
                    continue
                ml = metrics.LOSS_RE.search(line)
                if ml:
                    val = metrics._to_float(ml.group(1))
                    if val is not None:
                        # 记原始行：loss.txt 与内存里的序列必然一致
                        if mi:
                            res.loss_lines.append(line)
                        res.losses.append((res.last_iteration, val))
                        if break_on_nonfinite and not math.isfinite(val):
                            res.killed_reason = (
                                f"第 {res.last_iteration} 步 loss={val}（非有限值）"
                            )
                            break
                        if _check_stop():
                            break
    except KeyboardInterrupt:
        _kill_tree(proc)
        raise

    if res.timed_out or res.early_stopped:
        _kill_tree(proc)
    else:
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)

    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        proc.wait(timeout=30)
    except Exception:  # noqa: BLE001
        pass

    res.exit_code = proc.returncode
    res.duration_s = time.time() - started
    res.log_tail = tail
    return res


# ---------------------------------------------------------------------------
# 证据：loss.txt / 早停留痕 / 进程元数据
# ---------------------------------------------------------------------------

def write_loss_txt(path, loss_lines: list) -> int:
    """把命中的 loss **原始行**写出来（不是重新格式化）。

    写原始行是为了让 `metrics.py` 能原样再解析一遍 —— 两边看到的点必然一致。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [ln.rstrip("\n") for ln in loss_lines]
    p.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
    return len(lines)


def write_marker(path, *, reason: str, stage: str, round_id: str,
                 stop_kind: str, last_iter, n_points=None,
                 thresholds: dict = None) -> None:
    """写早停/超时留痕。格式是 `key: value` / `key=value`：**能机读**。

    ★ 读者是 `metrics.read_stop_marker()`：它只认 `stop_kind:` 这一行
      （取值必须在 `metrics.STOP_KINDS` 里）与顶格的 `stopped_at_step` / `reason`。
      `is_verdict=False` 是其中最重要的一行 —— 它明写"这是一条观察"。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    thr = thresholds or {}
    lines = [
        "在线早停/墙钟超时触发（**观察**，不是判定）",
        f"reason: {reason}",
        f"stop_kind: {stop_kind}",
        f"stopped_at_step: {last_iter if last_iter is not None else 0}",
        f"stage: {stage}",
        f"round: {round_id}",
        f"n_loss_points: {n_points}",
        "is_verdict=False",
        "thresholds:",
        f"  jump_factor={thr.get('jump_factor')}",
        f"  rel_to_best={thr.get('rel_to_best')}",
        f"  min_points={thr.get('min_points')}",
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_meta(path, *, args, res: JobResult, thresholds: dict,
               max_steps=None, quant_error_max=None, effective_cmd=None,
               holdout_info: dict = None) -> None:
    """进程元数据：全是事实，`is_verdict` 恒 `False`。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": 1,
        "produced_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "round": args.round_id,
        "stage": args.stage,
        "dry_run": bool(res.dry_run),
        "command": list(effective_cmd or []),
        "log_path": res.log_path,
        #: 本段**判定码**（= 进程退出码；见 `stage_exit_code()`）
        "exit_code": stage_exit_code(res),
        #: 训练命令（被杀掉的**子进程**）的原始码 —— 保留事实，别拿它当判定
        "child_exit_code": res.exit_code,
        "duration_s": round(res.duration_s, 3),
        "n_lines": res.n_lines,
        "last_iteration": res.last_iteration,
        "loss_points": len(res.losses),
        #: 验证点数（0.19.0）：与 loss_points 分开记。`0` 且配了 racing ⇒ 看 holdout.reason。
        "valid_points": len(res.valid),
        "early_stopped": res.early_stopped,
        "timed_out": res.timed_out,
        "killed_reason": res.killed_reason,
        "stop_kind": (res.stop_kind or DEFAULT_STOP_KIND
                      if (res.early_stopped or res.timed_out) else None),
        # 这一轮是不是**从 ckpt 续跑**的（由 _common.sh 的 --resume 传入；空 = 从基座开跑）
        "resume_from": (getattr(args, "resume_from", None) or None),
        # ★ held-out racing（0.19.0）：只登记事实 —— 参照了哪一轮、阈值多少、为什么没判。
        "holdout": {
            "enabled": bool((thresholds or {}).get("holdout")),
            "thresholds": (thresholds or {}).get("holdout"),
            "baseline": holdout_info,
            "valid_points": len(res.valid),
        },
        # 阈值原样记录（来源是调用方；本文件没有默认值）
        "thresholds": {
            "jump_factor": thresholds.get("jump_factor"),
            "rel_to_best": thresholds.get("rel_to_best"),
            "min_points": thresholds.get("min_points"),
            "plateau": thresholds.get("plateau"),
            "timeout_s": (args.timeout_s if args.timeout_s is not None
                          else (args.max_wall_hours * 3600.0 if args.max_wall_hours else None)),
        },
        # 这两条只**透传**：max_steps 到点收工是训练侧自己的事（train-iters），
        # quant_error_max 的比对要读 evidence/ 探针产物（metrics.py 的职责）。
        "stop_conditions_passthrough": {
            "max_steps": max_steps,
            "quant_error_max": quant_error_max,
            "steps_observed": res.last_iteration,
            "steps_reached_max": (None if max_steps is None or res.last_iteration is None
                                  else res.last_iteration >= int(max_steps)),
        },
        "is_verdict": False,
    }
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="executor.py",
        description="起一个作业、逐行落日志、按观察在线早停（只记事实，不判定）",
        add_help=True,
    )
    ap.add_argument("--round", dest="round_id", default="", help="轮次 id（只用于留痕）")
    ap.add_argument("--stage", default="job", help="阶段名：train / convert / eval / job")
    ap.add_argument("--log", default="", help="作业日志落点（追加写，行缓冲）")
    ap.add_argument("--loss-out", default="", help="把命中的 loss 原始行写到这里")
    ap.add_argument("--marker", default="", help="早停/超时时写这个留痕文件")
    ap.add_argument("--meta", default="", help="进程元数据（JSON）落点")
    ap.add_argument("--timeout-s", type=float, default=None, help="墙钟上限（秒）")
    ap.add_argument("--max-wall-hours", type=float, default=None,
                    help="墙钟上限（小时），等价于 --timeout-s")
    ap.add_argument("--no-early-stop", action="store_true",
                    help="关掉在线早停（非有限值熔断仍然生效）")
    # ★ 阈值：没有默认值 —— 全部由调用方从**任务配置** stop_conditions.* 读出后传入（见文件头 ②）
    ap.add_argument("--jump-factor", type=float, default=None,
                    help="相邻步 loss 上升比阈值（来自任务配置 stop_conditions.loss.jump_factor）")
    ap.add_argument("--rel-to-best", type=float, default=None,
                    help="相对当时最优的倍数阈值（来自任务配置 stop_conditions.loss.rel_to_best）")
    ap.add_argument("--min-points", type=int, default=None,
                    help="在线早停的点数门槛（来自任务配置 stop_conditions.loss.min_points）")
    ap.add_argument("--max-steps", type=int, default=None,
                    help="训练步数上限（来自任务配置，只记录事实，不据此杀进程）")
    ap.add_argument("--quant-error-max", type=float, default=None,
                    help="量化误差阈值：只原样记录（比对归 metrics.py）")
    ap.add_argument("--plateau-window", type=int, default=None,
                    help="平台早停：窗口宽度（步）")
    ap.add_argument("--plateau-min-gain-pct", type=float, default=None,
                    help="平台早停：改善阈值（百分数，1.0 = 1%%）")
    ap.add_argument("--plateau-patience", type=int, default=None,
                    help="平台早停：连续命中几次才停")
    ap.add_argument("--plateau-min-steps", type=int, default=None,
                    help="平台早停：最低步数（不足不谈平台）")
    # ★ held-out racing（0.19.0）：**参照是 `records/best` 里那一轮**（不是配置里点名的轮次）。
    #   三个阈值 + 两个路径 + 任务名；阈值缺一个 ⇒ 退出 2，路径缺 ⇒ racing 关闭并记原因。
    ap.add_argument("--holdout-min-step", type=int, default=None,
                    help="held-out racing：跳过 warmup 的最低步（不足不谈）")
    ap.add_argument("--holdout-max-gap-pct", type=float, default=None,
                    help="held-out racing：允许落后参照轮的最大比例（0.05 = 5%%）")
    ap.add_argument("--holdout-patience", type=int, default=None,
                    help="held-out racing：连续几个验证点超阈才停")
    ap.add_argument("--holdout-best-dir", default="",
                    help="records/best 目录（参照轮从这里找）")
    ap.add_argument("--holdout-rounds-dir", default="",
                    help="<实验根>/<任务>/rounds（参照轮的 metrics.json 从这里读）")
    ap.add_argument("--holdout-cell", default="",
                    help="任务名（records/best/<任务名>__*.yaml 的前缀）")
    ap.add_argument("--valid-out", default="",
                    help="把命中的**验证** loss 原始行写到这里（与 --loss-out 分开）")
    ap.add_argument("--ckpt-dir", default="",
                    help="ckpt 落点：训练期间在它下面按 keep-last 删旧 iter_*")
    ap.add_argument("--ckpt-keep-last", type=int, default=None,
                    help="ckpt 保留份数（<=0 或未给 ⇒ 一个字节都不删）")
    ap.add_argument("--retention-log", default="",
                    help="ckpt 刈草留痕（每删一份写一行）")
    ap.add_argument("--resume-from", default="",
                    help="从哪个 ckpt 续跑（只写进元数据，供报告引用）")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令，不真跑")
    ap.add_argument("--json", action="store_true", help="把结果打成 JSON")
    ap.add_argument("--selftest", action="store_true", help="四机制自检（不依赖真实训练）")
    ap.add_argument("cmd", nargs=argparse.REMAINDER, help="-- 之后是真正要跑的命令")
    return ap


def _parse_cmd(rest: list) -> list:
    cmd = list(rest)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    return cmd


def main(argv=None) -> int:
    args = build_argparser().parse_args(argv)
    if args.selftest:
        return selftest()
    return _run(args)


def _run(args) -> int:
    cmd = _parse_cmd(args.cmd)
    if not cmd:
        print("ERROR: 没有给要跑的命令。用法：executor.py [选项] -- <命令...>", file=sys.stderr)
        return EXIT_CONTRACT
    if not args.log:
        print("ERROR: 必须给 --log（作业日志落点，逐行追加）", file=sys.stderr)
        return EXIT_CONTRACT

    # ── 墙钟闸：必须有上限且 > 0（0/负数曾被静默当成"没有上限"⇒ 无限等卡）─────
    for _name, _val in (("--max-wall-hours", args.max_wall_hours), ("--timeout-s", args.timeout_s)):
        if _val is not None and not float(_val) > 0:
            print(f"ERROR: {_name} = {_val}（必须 > 0）。\n"
                  "  0 或负数等于**关掉墙钟闸**：`if args.max_wall_hours` 这种写法会把它当成没给，\n"
                  "  于是 run_process(timeout_s=None) 无限等一张卡。\n"
                  "  ⇒ 退出 2（fail-closed）。", file=sys.stderr)
            return EXIT_CONTRACT
    if args.timeout_s is None and args.max_wall_hours is None:
        print("ERROR: 必须给墙钟上限（--timeout-s 或 --max-wall-hours）。\n"
              "  **不许无限等一张卡**：本文件不提供默认上限（默认值＝又一个阈值来源）。\n"
              "  唯一落点是任务配置 stop_conditions.wall_clock_hours，由 _common.sh 传入。\n"
              "  ⇒ 退出 2（fail-closed）。", file=sys.stderr)
        return EXIT_CONTRACT

    # ── 阈值闸：早停开着就必须拿到三个阈值，缺一个即退出 2（fail-closed）──────
    thresholds: dict = {}
    if not args.no_early_stop:
        missing = [n for n, v in (("--jump-factor", args.jump_factor),
                                  ("--rel-to-best", args.rel_to_best),
                                  ("--min-points", args.min_points)) if v is None]
        if missing:
            print("ERROR: 在线早停开着，但缺少阈值：" + "、".join(missing) + "\n"
                  "  ⇒ 退出 2（fail-closed）。**本文件不提供阈值默认值**：\n"
                  "     阈值只许来自**任务配置** stop_conditions.loss.*（由调用方传入）。\n"
                  "     要关掉在线早停请显式给 --no-early-stop（那也不许在本文件里写一行默认阈值）。",
                  file=sys.stderr)
            return EXIT_CONTRACT
        thresholds = {"early_stop": {"jump_factor": args.jump_factor,
                                     "rel_to_best": args.rel_to_best,
                                     "min_points": args.min_points},
                      "divergence": {"jump_factor": args.jump_factor,
                                     "rel_to_best": args.rel_to_best,
                                     "min_points": args.min_points}}
        # ★ 平台早停（可选）：四个参数**同进同出**。给一半 ⇒ 退出 2，不猜剩下的一半。
        pl_given = [args.plateau_window, args.plateau_min_gain_pct,
                    args.plateau_patience, args.plateau_min_steps]
        if any(v is not None for v in pl_given):
            if any(v is None for v in pl_given):
                print("ERROR: 平台早停参数必须四个齐全（--plateau-window / "
                      "--plateau-min-gain-pct / --plateau-patience / --plateau-min-steps）。\n"
                      "  ⇒ 退出 2（fail-closed）。唯一落点是任务配置 stop_conditions.plateau.*。",
                      file=sys.stderr)
                return EXIT_CONTRACT
            thresholds["plateau"] = {"window_steps": args.plateau_window,
                                     "min_gain_pct": args.plateau_min_gain_pct,
                                     "patience": args.plateau_patience,
                                     "min_steps": args.plateau_min_steps}

        # ★ held-out racing（可选）：三个阈值**同进同出**；给一半 ⇒ 退出 2，不猜。
        ho_given = [args.holdout_min_step, args.holdout_max_gap_pct, args.holdout_patience]
        if any(v is not None for v in ho_given):
            if any(v is None for v in ho_given):
                print("ERROR: held-out racing 参数必须三个齐全（--holdout-min-step / "
                      "--holdout-max-gap-pct / --holdout-patience）。\n"
                      "  ⇒ 退出 2（fail-closed）。唯一落点是任务配置 stop_conditions.holdout.*。",
                      file=sys.stderr)
                return EXIT_CONTRACT
            if args.holdout_max_gap_pct < 0:
                print(f"ERROR: --holdout-max-gap-pct = {args.holdout_max_gap_pct}（必须 >= 0）",
                      file=sys.stderr)
                return EXIT_CONTRACT
            thresholds["holdout"] = {"min_step": args.holdout_min_step,
                                     "max_gap_pct": args.holdout_max_gap_pct,
                                     "patience": args.holdout_patience}

    # ── held-out racing 启动闸（0.19.0）──────────────────────────────
    #   配了 racing 却没有验证点可流入 ⇒ 它永远不会触发。这种"配了等于没配"必须开跑前
    #   就炸掉，否则一整轮算力烧完才发现 `--eval-iters 0` 根本没打验证行。
    ho_base: list = []
    ho_info: dict = {"kind": "best", "round": None, "source": None, "reason": None}
    if thresholds.get("holdout"):
        iters = _flag_value(cmd, "--eval-iters")
        vpath = _flag_value(cmd, "--valid-data-path")
        split = _flag_value(cmd, "--split")
        valid_n = 0
        if split:
            parts = [x.strip() for x in str(split).split(",")]
            if len(parts) >= 2 and parts[1].isdigit():
                valid_n = int(parts[1])
        if vpath is None and valid_n <= 0:
            print("ERROR: 配了 stop_conditions.holdout（held-out racing），但训练 argv 里"
                  "没有验证集：\n"
                  f"  --split = {split!r}（第二段应为验证比例，> 0）／"
                  f" --valid-data-path = {vpath!r}\n"
                  "  ⇒ 退出 2（fail-closed）：没有验证点，racing 永远不会触发。\n"
                  "  唯一落点是 `<任务目录>/commands/train_argv.txt`（把 `--split 100,0,0`"
                  " 改成 `--split 98,2,0`，或给 `--valid-data-path`）。", file=sys.stderr)
            return EXIT_CONTRACT
        try:
            n_it = int(str(iters)) if iters is not None else 0
        except ValueError:
            n_it = 0
        if n_it <= 0:
            print("ERROR: 配了 stop_conditions.holdout，但训练 argv 的 --eval-iters 不大于 0"
                  f"（{iters!r}）⇒ 训练不会打验证行。\n"
                  "  ⇒ 退出 2（fail-closed）。唯一落点是 `<任务目录>/commands/train_argv.txt`。",
                  file=sys.stderr)
            return EXIT_CONTRACT
        rnd, why = _read_best_round(Path(args.holdout_best_dir), args.holdout_cell) \
            if args.holdout_best_dir and args.holdout_cell else (None, "没给 --holdout-best-dir/--holdout-cell")
        ho_info["round"] = rnd
        ho_info["reason"] = None if rnd else why
        if rnd:
            ho_base, src = load_baseline_valid(Path(args.holdout_rounds_dir), rnd)
            ho_info["source"] = src
            if not ho_base:
                ho_info["reason"] = src
        if not ho_base:
            print(f"  racing     参照不可用 ⇒ 本轮**不判**：{ho_info['reason']}", flush=True)

    limit = args.timeout_s
    if limit is None and args.max_wall_hours:
        limit = float(args.max_wall_hours) * 3600.0

    print(f"== executor.py [{args.stage}] {args.round_id} ==", flush=True)
    print(f"  日志      {args.log}", flush=True)
    print(f"  命令      {' '.join(cmd)}", flush=True)
    if args.no_early_stop:
        print("  在线早停  **关闭**（只保留非有限值熔断）", flush=True)
    else:
        print(f"  在线早停  开启：相邻上升 > {args.jump_factor} 倍 或 相对当时最优 > "
              f"{args.rel_to_best} 倍，且已积累 >= {args.min_points} 个点"
              f"（阈值来源：调用方传入；观察实现：metrics.training_observation）", flush=True)
    if limit:
        print(f"  墙钟上限  {limit:.0f}s（到点杀整个进程组，退出 {EXIT_TRAIN_INVALID}）", flush=True)

    gate = (None if args.no_early_stop else
            make_gate(thresholds, baseline_curve=ho_base, holdout=thresholds.get("holdout")))

    # ── ckpt 刈草（0.18.26）：训练进程旁边起一把小扫帚 ─────────────────────
    #   规则见 prune_checkpoints 文件头六条。keep_last 缺失/非法 ⇒ 不删（fail-closed），
    #   只打一行提示 —— 删文件这件事，宁可不做也不能猜着做。
    keeper = None
    if args.ckpt_dir:
        if not args.ckpt_keep_last or args.ckpt_keep_last < 1:
            print(f"  ckpt 保留  **不删**（--ckpt-keep-last={args.ckpt_keep_last!r} 非法或未给）"
                  f"：{args.ckpt_dir}", flush=True)
        elif args.dry_run:
            print(f"  ckpt 保留  dry-run 不删（keep_last={args.ckpt_keep_last}）", flush=True)
        else:
            keeper = _CkptKeeper(args.ckpt_dir, args.ckpt_keep_last,
                                 args.retention_log or None)
            keeper.start()
            print(f"  ckpt 保留  只留最近 {args.ckpt_keep_last} 份，每 60s 清一次"
                  f"（留痕 {args.retention_log or '（未给）'}）", flush=True)

    res = run_process(cmd, args.log, timeout_s=limit, stop_gate=gate,
                      dry_run=args.dry_run)
    if keeper is not None:
        keeper.stop()
        if keeper.total_deleted:
            print(f"  ckpt 刈草  删了 {len(keeper.total_deleted)} 份："
                  f"{', '.join(keeper.total_deleted)}", flush=True)

    if args.loss_out and not args.dry_run:
        n = write_loss_txt(args.loss_out, res.loss_lines)
        print(f"  loss 行   {n} 行 -> {args.loss_out}", flush=True)

    if args.valid_out and not args.dry_run:
        nv = write_loss_txt(args.valid_out, res.valid_lines)
        print(f"  valid 行  {nv} 行 -> {args.valid_out}", flush=True)

    n_points = len(res.losses)
    print(f"  结束      退出码={res.exit_code} 用时={res.duration_s:.1f}s "
          f"行数={res.n_lines} loss点={n_points} 末步={res.last_iteration}", flush=True)

    if args.meta:
        write_meta(args.meta, args=args, res=res, thresholds=thresholds,
                   max_steps=args.max_steps, quant_error_max=args.quant_error_max,
                   effective_cmd=cmd, holdout_info=ho_info)
        print(f"  元数据    {args.meta}", flush=True)

    if args.json:
        print(json.dumps({
            "round": args.round_id, "stage": args.stage,
            "exit_code": stage_exit_code(res), "child_exit_code": res.exit_code,
            "duration_s": round(res.duration_s, 1),
            "n_lines": res.n_lines, "early_stopped": res.early_stopped,
            "timed_out": res.timed_out, "killed_reason": res.killed_reason,
            "last_iteration": res.last_iteration, "loss_points": n_points,
            "valid_points": len(res.valid),
            "log_path": res.log_path,
            "is_verdict": False,   # 明确：这里没有任何判定
        }, ensure_ascii=False), flush=True)

    if res.early_stopped or res.timed_out:
        # ★ 0.18.26：区分**两种停止**，退出码不同（此前一律 5，等于把「收工」也当废品）：
        #   invalid    → 发散/超时：这一轮测的不是方案 ⇒ 5
        #   converged  → 平台：结论有效，只是没跑满 ⇒ 0
        kind = res.stop_kind or DEFAULT_STOP_KIND
        if res.timed_out:
            print(f"\n★ 墙钟超时被杀：{res.killed_reason}", file=sys.stderr, flush=True)
            print("  这是**观察**：这一轮没跑完，别往下花算力。不是精度结论。",
                  file=sys.stderr, flush=True)
            kind = DEFAULT_STOP_KIND
        elif kind == "converged":
            print(f"\n★ 平台早停触发（**合法收工**，不是实验作废）：{res.killed_reason}",
                  file=sys.stderr, flush=True)
            print("  这一轮的结论有效；但它是**停止轮次**：训练侧 loss 不得与跑满轮次直比，"
                  "下游评测可以比（那是「各自停止点上的模型」）。", file=sys.stderr, flush=True)
        else:
            print(f"\n★ 在线早停触发：{res.killed_reason}", file=sys.stderr, flush=True)
            print("  这是**观察**：这一轮测的不是方案，别往下花算力。不是精度结论。",
                  file=sys.stderr, flush=True)
        if args.marker:
            stop_thr = {"jump_factor": args.jump_factor,
                        "rel_to_best": args.rel_to_best,
                        "min_points": args.min_points}
            if args.plateau_window:
                stop_thr["plateau"] = {"window_steps": args.plateau_window,
                                       "min_gain_pct": args.plateau_min_gain_pct,
                                       "patience": args.plateau_patience,
                                       "min_steps": args.plateau_min_steps}
            write_marker(args.marker, reason=res.killed_reason, stage=args.stage,
                         round_id=args.round_id, stop_kind=kind,
                         last_iter=res.last_iteration, n_points=n_points,
                         thresholds=stop_thr)
            print(f"  留痕      {args.marker}", file=sys.stderr, flush=True)
        return stage_exit_code(res)

    if res.exit_code != 0:
        print(f"\n★ 命令以非零码退出：{res.exit_code}（日志尾部）", file=sys.stderr, flush=True)
        for ln in res.log_tail[-20:]:
            print("    " + ln, file=sys.stderr, flush=True)
        return EXIT_CMD_FAILED

    return EXIT_OK


# ---------------------------------------------------------------------------
# 自测：不依赖真实训练 —— 四机制各自**真跑真看**
# ---------------------------------------------------------------------------

def selftest() -> int:
    checks: list = []
    fails: list = []

    def case(name, cond, detail=""):
        checks.append(name)
        if cond:
            print(f"  ok    {name}")
        else:
            print(f"  FAIL  {name}    {detail}")
            fails.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="lpta_executor_selftest_"))

    def script(body: str, name: str) -> Path:
        p = tmp / name
        p.write_text(textwrap.dedent(body), encoding="utf-8")
        return p

    THR = {"early_stop": {"jump_factor": 4.0, "rel_to_best": 2.5, "min_points": 2},
           "divergence": {"jump_factor": 4.0, "rel_to_best": 2.5, "min_points": 2}}

    print("=" * 70)
    print("executor.py --selftest（真子进程；不依赖真实训练）")
    print("=" * 70)

    # --- 1 正常跑完：逐行落日志、抽 loss、与 metrics 重新解析逐点一致 ---
    print("\n[1] 正常作业：逐行落日志、抽 loss、退出 0")
    s = script('''
        import time
        for i in range(1, 13):
            print(" iteration %7d/      300 | lm loss: %.6E |" % (i, 1.0 - i * 0.01), flush=True)
            time.sleep(0.01)
    ''', "ok.py")
    log = tmp / "ok.log"
    loss = tmp / "ok_loss.txt"
    r = run_process([sys.executable, str(s)], log, echo=False)
    n = write_loss_txt(loss, r.loss_lines)
    case("跑完退出 0", r.exit_code == EXIT_OK, repr(r.exit_code))
    case("没有早停/没有超时", (not r.early_stopped) and (not r.timed_out), r.killed_reason)
    case("抽到 12 个 loss 点", len(r.losses) == 12, repr(len(r.losses)))
    case("loss.txt 写了 12 行", n == 12, repr(n))
    case("日志文件 12 行逐行落盘", len(log.read_text(encoding="utf-8").splitlines()) == 12,
         repr(len(log.read_text(encoding="utf-8").splitlines())))
    re_curve, _ = metrics.parse_loss_curve(loss)
    case("loss.txt 被 metrics 重新解析得到同样的点", re_curve == r.losses,
         f"{re_curve[:3]}... vs {r.losses[:3]}...")

    # --- 2 行缓冲＋独立线程排空：进程还在跑时，日志就已经能看到第一行 ---
    print("\n[2] 行缓冲：子进程仍在 sleep 时，日志第一行已经落盘（不是等退出才写）")
    s = script('''
        import time
        print("FIRST-LINE-VISIBLE-BEFORE-EXIT", flush=True)
        time.sleep(1.5)
        print(" iteration 1/300 | lm loss: 1.0E+00 |", flush=True)
    ''', "buf.py")
    log = tmp / "buf.log"
    seen = {"v": False}

    def _runner():
        run_process([sys.executable, str(s)], log, echo=False)

    th = threading.Thread(target=_runner)
    t0 = time.time()
    th.start()
    while time.time() - t0 < 1.2:
        try:
            if "FIRST-LINE-VISIBLE-BEFORE-EXIT" in log.read_text(encoding="utf-8"):
                seen["v"] = True
                break
        except OSError:
            pass
        time.sleep(0.05)
    case("退出前就能读到第一行（行缓冲＋独立线程排空）", seen["v"], f"{time.time() - t0:.2f}s")
    th.join(timeout=30)

    # --- 3 在线早停：实测那条假失败（第 2 步跳 9.09 倍）---
    print("\n[3] 在线早停：iter1 2.022781E+00 → iter2 1.838940E+01（9.09 倍，有限值）")
    s = script('''
        print(" iteration       1/     300 | lm loss: 2.022781E+00 |", flush=True)
        print(" iteration       2/     300 | lm loss: 1.838940E+01 |", flush=True)
        import time; time.sleep(30)          # 若没被杀掉，会明显变慢
    ''', "boom.py")
    log = tmp / "boom.log"
    marker = tmp / "boom.triggered"
    t0 = time.time()
    r = run_process([sys.executable, str(s)], log, stop_gate=make_gate(THR), echo=False)
    dt = time.time() - t0
    case("早停触发", r.early_stopped is True, repr(r.early_stopped))
    case("进程被杀（没有等满 30s）", dt < 20, f"{dt:.1f}s")
    case("原因里带出 9.09 倍这个事实", "9.09" in r.killed_reason, r.killed_reason)
    case("原因说的是「观察」不是「精度」", "精度" not in r.killed_reason, r.killed_reason)
    write_marker(marker, reason=r.killed_reason, stage="train", round_id="R-9000",
                 stop_kind=DEFAULT_STOP_KIND, last_iter=r.last_iteration,
                 n_points=len(r.losses), thresholds=THR["early_stop"])
    mk = metrics.read_stop_marker(tmp, tmp, marker_path=marker)
    case("留痕能被 metrics.read_stop_marker 读回（kind=invalid）",
         mk.get("kind") == "invalid", repr(mk))
    case("留痕里的步数被读回（第 2 步）", mk.get("stopped_at_step") == 2, repr(mk))
    case("观察实现是 metrics.training_observation（同一条轨迹同一结论）",
         metrics.training_observation([(1, 2.022781), (2, 18.38940)],
                                      THR)["early_stop_would_have_fired"] is True)

    # --- 4 非有限值熔断（与早停是两条独立的线）---
    print("\n[4] 非有限值熔断：正文里的 lm loss: nan 也必须抓到")
    s = script('''
        print(" iteration 1/300 | lm loss: 2.0E+00 |", flush=True)
        print(" iteration 2/300 | lm loss: nan |", flush=True)
        import time; time.sleep(30)
    ''', "nan.py")
    r = run_process([sys.executable, str(s)], tmp / "nan.log",
                    stop_gate=make_gate(THR), echo=False)
    case("非有限值触发熔断", "非有限值" in r.killed_reason, r.killed_reason)
    case("非有限值不等于 early_stopped（两条线分开）",
         r.early_stopped is False, repr(r.early_stopped))

    # --- 5 不误伤：实测正常波动必须跑完 ---
    print("\n[5] 不误伤：实测正常序列（相邻最大 1.2279）必须跑完")
    s = script('''
        vals = [2.0, 2.4, 2.1, 1.9, 1.85, 1.8, 1.82, 1.75, 1.7, 1.65, 1.6, 1.55]
        for i, v in enumerate(vals, 1):
            print(" iteration %d/      300 | lm loss: %.4f |" % (i, v), flush=True)
    ''', "normal.py")
    r = run_process([sys.executable, str(s)], tmp / "normal.log",
                    stop_gate=make_gate(THR), echo=False)
    case("正常序列没被早停", r.early_stopped is False, r.killed_reason)
    case("正常序列退出 0", r.exit_code == EXIT_OK, repr(r.exit_code))

    # --- 6 命令自己失败 → 退出码透传 ---
    print("\n[6] 命令自己失败 → 退出码透传")
    s = script('import sys; sys.exit(7)', "fail.py")
    r = run_process([sys.executable, str(s)], tmp / "fail.log", echo=False)
    case("退出码透传 7", r.exit_code == 7, repr(r.exit_code))
    case("不是早停", r.early_stopped is False, repr(r.early_stopped))

    # --- 7 墙钟超时 ---
    print("\n[7] 墙钟超时：超时被杀")
    s = script('import time; time.sleep(30)', "slow.py")
    t0 = time.time()
    r = run_process([sys.executable, str(s)], tmp / "slow.log", timeout_s=2, echo=False)
    dt = time.time() - t0
    case("超时被标记", r.timed_out is True, repr(r.timed_out))
    case("没有等满 30s", dt < 20, f"{dt:.1f}s")

    # --- 8 杀**整个进程组**：孙进程也必须死 ---
    print("\n[8] 进程组：孙进程（独立 pid）也必须一起被杀")
    tag = f"LPTA_SELFTEST_GRP_{os.getpid()}"
    s = script(f'''
        import subprocess, time
        subprocess.Popen(["sh", "-c", "sleep 300  # {tag}"])
        print(" iteration       1/     300 | lm loss: 2.022781E+00 |", flush=True)
        print(" iteration       2/     300 | lm loss: 1.838940E+01 |", flush=True)
        time.sleep(60)
    ''', "grp.py")
    r = run_process([sys.executable, str(s)], tmp / "grp.log",
                    stop_gate=make_gate(THR), echo=False)
    time.sleep(0.6)

    def _alive_others(pattern: str) -> list:
        # 用方括号技巧：pgrep 自己的命令行**不匹配**这个模式（不是靠"排除自己"）
        rx = pattern[:6] + "[" + pattern[6] + "]" + pattern[7:]
        out = subprocess.run(["pgrep", "-f", rx], capture_output=True, text=True)
        return [ln for ln in (out.stdout or "").split() if ln.strip()]

    alive = _alive_others(tag)
    case("早停触发（进程组用例）", r.early_stopped is True, repr(r.early_stopped))
    case("孙进程已被杀（pgrep 空）", alive == [], repr(alive))

    # --- 9 阈值缺失 ⇒ 退出 2（本文件没有阈值默认值）---
    print("\n[9] 阈值缺失 ⇒ 退出 2（fail-closed；本文件不提供默认阈值）")
    import contextlib
    with open(os.devnull, "w") as null, contextlib.redirect_stderr(null):
        rc_missing = main(["--log", str(tmp / "x.log"), "--", "true"])
        rc_nocmd = main(["--log", str(tmp / "x.log")])
        rc_nolog = main(["--", "true"])
        rc_ok = main(["--no-early-stop", "--dry-run", "--log", str(tmp / "dry.log"),
                      "--max-wall-hours", "1", "--", "true"])
        rc_nowall = main(["--no-early-stop", "--dry-run", "--log", str(tmp / "w0.log"),
                          "--", "true"])
        rc_zero = main(["--no-early-stop", "--dry-run", "--log", str(tmp / "w1.log"),
                        "--max-wall-hours", "0", "--", "true"])
    case("早停开着但没给阈值 → 2", rc_missing == EXIT_CONTRACT, repr(rc_missing))
    case("没给命令 → 2", rc_nocmd == EXIT_CONTRACT, repr(rc_nocmd))
    case("没给 --log → 2", rc_nolog == EXIT_CONTRACT, repr(rc_nolog))
    case("--no-early-stop --dry-run 正常 → 0", rc_ok == EXIT_OK, repr(rc_ok))
    case("没给墙钟上限 → 2（不许无限等一张卡）", rc_nowall == EXIT_CONTRACT, repr(rc_nowall))
    case("--max-wall-hours 0 → 2（0 不等于「没有上限」）", rc_zero == EXIT_CONTRACT, repr(rc_zero))

    # --- 10 退出码语义 ---
    print("\n[10] 退出码语义（本文件只发 0/1/2/5；6 归评测入口，见文件头）")
    case("5 = 训练侧无效（早停/NaN/超时）", EXIT_TRAIN_INVALID == 5, repr(EXIT_TRAIN_INVALID))
    case("6 = 评测侧无效（不由本文件产出）", EXIT_EVAL_INVALID == 6, repr(EXIT_EVAL_INVALID))
    case("1 = 未归类运行期失败", EXIT_CMD_FAILED == 1, repr(EXIT_CMD_FAILED))
    case("2 = 约定/用法不过", EXIT_CONTRACT == 2, repr(EXIT_CONTRACT))

    # --- 11 与 metrics.py 共用同一份正则与观察实现 ---
    print("\n[11] 与 metrics.py 共用同一份正则与观察实现")
    case("用的是 metrics.ITER_RE", hasattr(metrics, "ITER_RE"))
    case("用的是 metrics.LOSS_RE", hasattr(metrics, "LOSS_RE"))
    gate_fn = make_gate(THR)
    # 闸门里调的是 `metrics.training_observation`：metrics 是模块级全局（闭包只捕获 tv），
    # 函数体里按属性取用（`co_names` 里有它的名字）。这样 make_gate 不是第二个观察实现。
    case("闸门就是 metrics.training_observation（不另写一份判定）",
         ("training_observation" in gate_fn.__code__.co_names)
         and gate_fn.__globals__.get("metrics") is metrics,
         f"names={gate_fn.__code__.co_names}")

    # --- 12 meta 落盘 ---
    print("\n[12] 进程元数据落盘（is_verdict=false）")
    ns = build_argparser().parse_args(
        ["--round", "R-9000", "--stage", "train", "--log", str(tmp / "m.log"),
         "--jump-factor", "4.0", "--rel-to-best", "2.5", "--min-points", "2",
         "--max-steps", "20", "--quant-error-max", "0.05", "--", "true"])
    mres = run_process(["true"], tmp / "m.log", echo=False)
    meta = tmp / "m.meta.json"
    write_meta(meta, args=ns, res=mres, thresholds=THR["early_stop"],
               max_steps=ns.max_steps, quant_error_max=ns.quant_error_max,
               effective_cmd=["true"])
    doc = json.loads(meta.read_text(encoding="utf-8"))
    case("meta 里 is_verdict=false", doc.get("is_verdict") is False, repr(doc.get("is_verdict")))
    case("meta 里记下 max_steps 透传值与 steps_reached_max",
         doc["stop_conditions_passthrough"]["max_steps"] == 20
         and doc["stop_conditions_passthrough"]["steps_reached_max"] is None,
         repr(doc["stop_conditions_passthrough"]))

    # ── [13] 平台早停 = 合法收工（退出 0，不是 5）────────────────────────
    print("\n[13] 平台早停：kind=converged ⇒ 退出 0（**不是**作业作废）")
    import random as _random
    _random.seed(11)
    plat_curve = []
    _v = 1.32
    for _i in range(1, 301):
        if _i <= 60:
            _v -= 0.0022
        _v += _random.gauss(0, 0.012 * _v)
        plat_curve.append((_i, _v))
    PLT = {"early_stop": {"jump_factor": 9.0, "rel_to_best": 9.0, "min_points": 5},
           "divergence": {"jump_factor": 9.0, "rel_to_best": 9.0, "min_points": 5},
           "plateau": {"window_steps": 30, "min_gain_pct": 2.0,
                       "patience": 2, "min_steps": 40}}
    gate_p = make_gate(PLT)
    hit = None
    for k in range(1, len(plat_curve) + 1):
        hit = gate_p(plat_curve[:k])
        if hit:
            break
    case("平台闸门在轨迹后段命中", hit is not None, repr(hit))
    case("平台命中给出 kind=converged", bool(hit) and hit[1] == "converged", repr(hit))

    # 真跑一个「每行一个 loss、中途走平」的假训练，看退出码
    fake = tmp / "fake_plateau.py"
    fake.write_text(
        "import sys\n"
        "seq = " + repr([round(v, 6) for _i, v in plat_curve]) + "\n"
        "for i, v in enumerate(seq, 1):\n"
        "    print(f'iteration {i}/300 | loss: {v}', flush=True)\n",
        encoding="utf-8")
    pmark = tmp / "platform.marker"
    pr = build_argparser().parse_args(
        ["--round", "R-9100", "--stage", "train", "--log", str(tmp / "p.log"),
         "--marker", str(pmark), "--jump-factor", "9.0", "--rel-to-best", "9.0",
         "--min-points", "5", "--plateau-window", "30", "--plateau-min-gain-pct", "2.0",
         "--plateau-patience", "2", "--plateau-min-steps", "40",
         "--timeout-s", "120", "--", sys.executable, str(fake)])
    rc_p = _run(pr)
    case("平台早停 ⇒ 退出 0", rc_p == 0, f"rc={rc_p}")
    case("平台早停留痕 kind=converged",
         pmark.is_file() and "stop_kind: converged" in pmark.read_text(encoding="utf-8"),
         pmark.read_text(encoding="utf-8")[:120] if pmark.is_file() else "无留痕")

    # --- [13b] 元数据里的 exit_code 是**判定码**，不是被杀子进程的码（0.18.38）---
    print("\n[13b] 元数据：converged ⇒ exit_code=0；子进程原始码另存 child_exit_code")
    cstop = JobResult(exit_code=1, early_stopped=True, stop_kind="converged",
                      killed_reason="平台早停", last_iteration=151)
    case("stage_exit_code(converged，子进程被杀) == 0",
         stage_exit_code(cstop) == 0, repr(stage_exit_code(cstop)))
    case("stage_exit_code(invalid) == 5",
         stage_exit_code(JobResult(exit_code=1, early_stopped=True,
                                   stop_kind="invalid")) == EXIT_TRAIN_INVALID)
    case("stage_exit_code(墙钟超时) == 5",
         stage_exit_code(JobResult(timed_out=True, early_stopped=True,
                                   stop_kind="invalid")) == EXIT_TRAIN_INVALID)
    case("stage_exit_code(正常跑完) == 0", stage_exit_code(JobResult(exit_code=0)) == 0)
    case("stage_exit_code(命令崩了) == 1",
         stage_exit_code(JobResult(exit_code=7)) == EXIT_CMD_FAILED)
    ns_c = build_argparser().parse_args(
        ["--round", "R-9102", "--stage", "train", "--log", str(tmp / "c.log"),
         "--jump-factor", "4.0", "--rel-to-best", "2.5", "--min-points", "2", "--", "true"])
    cmeta = tmp / "c.meta.json"
    write_meta(cmeta, args=ns_c, res=cstop, thresholds=THR["early_stop"],
               effective_cmd=["true"])
    cdoc = json.loads(cmeta.read_text(encoding="utf-8"))
    case("meta: converged 的 exit_code = 0（判定码）",
         cdoc.get("exit_code") == 0, repr(cdoc.get("exit_code")))
    case("meta: 子进程原始码保留在 child_exit_code",
         cdoc.get("child_exit_code") == 1, repr(cdoc.get("child_exit_code")))

    # 同一个假训练，但**不配 plateau** ⇒ 必须跑满（行为与 0.18.25 一致）
    pmark2 = tmp / "platform2.marker"
    pr2 = build_argparser().parse_args(
        ["--round", "R-9101", "--stage", "train", "--log", str(tmp / "p2.log"),
         "--marker", str(pmark2), "--jump-factor", "9.0", "--rel-to-best", "9.0",
         "--min-points", "5", "--timeout-s", "120", "--", sys.executable, str(fake)])
    rc_p2 = _run(pr2)
    case("不配 plateau ⇒ 跑满、不产生留痕", rc_p2 == 0 and not pmark2.exists(),
         f"rc={rc_p2} marker={pmark2.exists()}")

    # ── [14] ckpt 刈草：只删 iter_*、永不删最新、别的不碰 ────────────────
    print("\n[14] ckpt 保留策略（六条安全规则）")
    cd = tmp / "ckpt"
    for n in (10, 20, 30, 40, 50):
        (cd / f"iter_{n:07d}").mkdir(parents=True)
    (cd / "latest_checkpointed_iteration.txt").write_text("50\n", encoding="utf-8")
    (cd / "notes").mkdir()
    (cd / "iter_0000030" / "keepme").write_text("x", encoding="utf-8")
    import os as _os
    old = time.time() - 3600
    for p_ in cd.iterdir():
        _os.utime(p_, (old, old))
    r1 = prune_checkpoints(cd, 2, log_path=tmp / "retention.log")
    left = sorted(x.name for x in cd.glob("iter_*"))
    case("留 2 份且是最新两份",
         left == ["iter_0000040", "iter_0000050"], repr(left))
    case("tracker 与别的目录没被动",
         (cd / "latest_checkpointed_iteration.txt").is_file() and (cd / "notes").is_dir())
    case("刈草留痕写了删除记录",
         (tmp / "retention.log").is_file()
         and "删除" in (tmp / "retention.log").read_text(encoding="utf-8"))
    r2 = prune_checkpoints(cd, 0)
    case("keep_last<1 ⇒ 一个字节都不删",
         r2["deleted"] == [] and len(list(cd.glob("iter_*"))) == 2, repr(r2["deleted"]))
    r3 = prune_checkpoints(cd, 1, min_age_s=10 ** 9)
    case("刚动过的目录不删（可能正在写）",
         r3["deleted"] == [] and len(list(cd.glob("iter_*"))) == 2, repr(r3["skipped"]))

    # ── [15] held-out racing（0.19.0）：验证行分离 ＋ 参照轮 ＋ 淘汰判据 ──────
    print("\n[15] held-out racing：验证行与训练曲线分离、落后参照轮则淘汰")
    # 参照轮：records/best 指向 R-9200，它的 metrics.json 里有验证曲线
    bdir = tmp / "records" / "best"
    bdir.mkdir(parents=True)
    (bdir / "selftest__acc.yaml").write_text(
        "cell: selftest\nmetric: acc\nvalue: 0.5\nround: R-9200\n", encoding="utf-8")
    rroot = tmp / "exp" / "selftest" / "rounds"
    (rroot / "R-9200").mkdir(parents=True)
    (rroot / "R-9200" / "metrics.json").write_text(json.dumps({
        "holdout": {"valid": {"curve": [[10, 3.0], [20, 2.9], [30, 2.8], [40, 2.7]]}}
    }), encoding="utf-8")
    rnd, why = _read_best_round(bdir, "selftest")
    case("records/best 里读出参照轮", rnd == "R-9200", f"{rnd!r} {why}")
    bcurve, bsrc = load_baseline_valid(rroot, rnd)
    case("参照轮验证曲线被读出", len(bcurve) == 4, f"{bsrc}")

    # 假训练：训练行 + **老格式**验证行（`lm loss:` ⇒ LOSS_RE 会命中）必须分开
    mixed = script('''
        for i in range(1, 41):
            print(" iteration %7d/       40 | lm loss: %.6E |" % (i, 5.0 - i * 0.01))
            if i % 10 == 0:
                print(" validation loss at iteration %d | lm loss: %.6E |" % (i, 9.0), flush=True)
    ''', "mixed.py")
    HT = {"early_stop": {"jump_factor": 99.0, "rel_to_best": 99.0, "min_points": 99},
          "divergence": {"jump_factor": 99.0, "rel_to_best": 99.0, "min_points": 99},
          "holdout": {"min_step": 10, "max_gap_pct": 0.05, "patience": 2}}
    # ① 分离本身：把 racing 阈值放到不可能触发，跑到终点看两条曲线各自的点数
    HT_off = {"early_stop": HT["early_stop"], "divergence": HT["divergence"],
              "holdout": {"min_step": 10, "max_gap_pct": 9.9, "patience": 2}}
    rr = run_process([sys.executable, str(mixed)], tmp / "mixed.log",
                     stop_gate=make_gate(HT_off, baseline_curve=bcurve,
                                         holdout=HT_off["holdout"]), echo=False)
    case("训练曲线 40 点：验证行没有混进去", len(rr.losses) == 40, repr(len(rr.losses)))
    case("验证曲线单独 4 点", len(rr.valid) == 4, repr(len(rr.valid)))
    case("训练曲线里没有 9.0 那个验证值（分离成功）",
         all(abs(v - 9.0) > 1e-9 for _s, v in rr.losses),
         repr([v for _s, v in rr.losses][-6:]))
    # ② 判据：同样的日志，阈值收紧 ⇒ 在第 2 个验证点（step 20）淘汰
    rr2 = run_process([sys.executable, str(mixed)], tmp / "mixed2.log",
                      stop_gate=make_gate(HT, baseline_curve=bcurve,
                                          holdout=HT["holdout"]), echo=False)
    case("racing 命中 ⇒ 早停且 kind=holdout",
         rr2.early_stopped and rr2.stop_kind == "holdout",
         f"{rr2.early_stopped} {rr2.stop_kind} {rr2.killed_reason[:60]}")
    case("淘汰发生在第 2 个验证点（step 20）", rr2.last_iteration == 20, repr(rr2.last_iteration))
    case("holdout 是**淘汰**（判定码 5，不是收工的 0）",
         stage_exit_code(rr2) == EXIT_TRAIN_INVALID, repr(stage_exit_code(rr2)))

    # 落后但仍在收窄 ⇒ 不停（低精度"慢热后追平"不许误杀）
    vy = script('''
        import sys
        base = [3.0, 2.9, 2.8, 2.7]
        gaps = [0.20, 0.15, 0.10, 0.05]
        for i, (b, g) in enumerate(zip(base, gaps), 1):
            print(" iteration %7d/       40 | lm loss: 4.0 |" % (i * 10), flush=True)
            print(" validation loss at iteration %d | lm loss value: %.6E |"
                  % (i * 10, b * (1 + g)), flush=True)
    ''', "narrow.py")
    nr = run_process([sys.executable, str(vy)], tmp / "narrow.log",
                     stop_gate=make_gate(HT, baseline_curve=bcurve,
                                         holdout=HT["holdout"]), echo=False)
    case("gap 在收窄 ⇒ **不**淘汰", not nr.early_stopped,
         f"{nr.stop_kind} {nr.killed_reason[:60]}")

    # 启动闸：配了 racing 但 --eval-iters 0 ⇒ 退出 2（不许"配了等于没配"）
    bad = build_argparser().parse_args(
        ["--round", "R-9201", "--stage", "train", "--log", str(tmp / "g.log"),
         "--jump-factor", "4.0", "--rel-to-best", "2.5", "--min-points", "2",
         "--holdout-min-step", "10", "--holdout-max-gap-pct", "0.05",
         "--holdout-patience", "2", "--timeout-s", "60", "--",
         "echo", "--split", "100,0,0", "--eval-iters", "0"])
    case("配了 racing 却没有验证集 ⇒ 退出 2", _run(bad) == EXIT_CONTRACT)
    ok_ns = build_argparser().parse_args(
        ["--round", "R-9202", "--stage", "train", "--log", str(tmp / "g2.log"),
         "--jump-factor", "4.0", "--rel-to-best", "2.5", "--min-points", "2",
         "--holdout-min-step", "10", "--holdout-max-gap-pct", "0.05",
         "--holdout-patience", "2", "--timeout-s", "60", "--",
         "echo", "--split", "98,2,0", "--eval-iters", "10"])
    case("验证集与 --eval-iters 都在 ⇒ 放行",
         _run(ok_ns) == 0, "启动闸误杀")

    shutil.rmtree(tmp, ignore_errors=True)

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
    raise SystemExit(main(sys.argv[1:]))
