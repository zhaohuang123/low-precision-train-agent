#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================
# metrics.py —— 只抽数，不判定
# ============================================================================
#
# ## 这个文件做什么
#
# 把一轮实验的产物（loss 轨迹 + 两侧评测输出）变成一份**结构化数字**：
#
#     <artifacts.root>/rounds/<轮次>/metrics.json
#     <artifacts.root>/rounds/<轮次>/artifacts.json   ← 同一次抽取写出的**产物路径清单**
#
# `artifacts.json` 是**只增**的一份输出（`agents/experimenter/AGENT.md:46` 写「`runtime/metrics.py`
# 写 metrics.json ＋ artifacts.json」；此前它没有生产者 ⇒ 规格与实现不符）。它**不参与任何判定**，
# 也**不改** `metrics.json` 的一个字节。
# 它**不做**下面任何一件事：
#
#   * 不产出 PASS / FAIL / INCONCLUSIVE
#   * 不算置信区间、噪声底、δ 阈值
#   * 不给证据等级 L1–L3
#   * 不做**配对**（按 sample id 求交集、逐题对齐）
#
# 判据只有一种形态：跑前冻结的「成功条件／证伪条件」（§v0.1 简化原则 1）。
# 本文件把数摆出来，结论由 `experimenter`／人给。
#
# ## 为什么把判定拿掉了
#
# 本工程的前身（lpAgent）在这里放的是一个「严格单因子配对判定器」：跑
# ref(bf16) 与 tgt(量化) 两侧评测，按 sample id 求交集做配对，bootstrap
# 出 CI，再拿 CI 与 δ 比出结论，最后机械地贴一个证据等级。
#
# 工程主人明确否掉了这一套，原话是：
#
#   * 「配对的概念完全非必须」
#   * 「实验是针对已有的方案做实验实施」
#   * 「结论由 arbiter 给才合理」
#
# 三句话指向同一件事：这一轮实验的目的不是"A/B 两个模型在同一批题上做
# 因果推断"，而是**把一个已有方案真的跑出来、把它的数记下来**。在这种
# 目的下，逐题配对是多余的前提；而"这个数说明方案行不行"是一个**解读**，
# 解读属于下游 agent（arbiter），不属于一个正则脚本。
#
# 所以这里的边界划得很死：
#
#     本文件只负责「数是多少、数齐了没有」，从不回答「这说明了什么」。
#
# 判断在 arbiter 那一环 —— 它读这份 metrics.json，自己决定怎么说。
#
# ## 为什么训练侧的观察仍然留着
#
# 训练侧的三个事实（最大相邻跳变 / 最大相对最优比 / 非有限值位置）仍要算，
# 因为**在线早停要靠它省掉一次 46 分钟的白跑**：
#
#   某次训练 `iter1 loss 2.02 → iter2 18.4`（9.09 倍）但全是**有限值**，
#   只查 NaN/Inf 的发散检测完全没触发。流程照常往下走：转换、评测 46 分钟，
#   最后作为一条"精度 FAIL"进档案 —— 而它测的是一个从第 2 步起就没在正常
#   训练的模型，那条 FAIL 与方案毫无关系。
#
# 但它的输出是**观察**（`observation`）不是判定（`is_verdict: false`）：
# 它只说"这个 run 看着不对"，**不说方案精度好不好**。前者能省算力，
# 后者是 arbiter 的活。
#
# ## 为什么不用 pyyaml
#
# 只用标准库。这样在任何一个有 python3 的机器上都能跑，不需要先配环境 ——
# 一个需要装依赖才能跑的脚本，会在最需要它的那一刻跑不起来。
#
# ## 用法
#
#   python3 runtime/metrics.py --round <轮次>
#   python3 runtime/metrics.py --round <轮次> --task <任务名> \
#       --scheme <轮次>/design.md --criterion <轮次>/criterion.yaml
#   python3 runtime/metrics.py --selftest
#
# ## 名字与路径从哪来（**本文件唯一的可变部分**）
#
# 本文件是旧工程 `scaffold/metrics.py`（3188 行）的**等价移植**：**抽取规则一个字都没动**
# （loss 正则、去重规则、`distinct_steps>=2`、失败码、`null` ＋ 理由…）；
# 换掉的只有**名字与路径**，一律从 `config/` 读（§11「唯一落点规则」）：
#
#   config/project.yaml        → `paths.experiments` / `paths.records`（缺失 ⇒ 内建默认）
#   config/tasks/<任务名>.yaml  → `task_id` / `artifacts.root`
#   <轮次>/criterion.yaml       → `success.baseline_ref`（基线轮次 id；「跟谁比」的唯一来源）
#   轮次目录                    → `<artifacts.root>/rounds/<轮次>/`
#
# 工程根（= `config/` 与 `paths.*` 的起点）解析顺序：`--root` → 环境变量 `LP_ROOT`
#   → 本文件上一级。**指错不回退**：`LP_ROOT` 指到一个没有 `config/` 的树 ⇒ 退出 2。
#
# ⇒ 本文件**不含**任何具体模型名／任务名／数据集名／精度串。
#   任务名由 `--task`（或环境变量 `LP_TASK`）给出；读不到任务配置 ⇒ 退出 2（fail-closed）。
#
# 退出码（文档集：`0/1/2/5/6`）：
#   0  抽数成功（reference 侧缺失也算成功 —— 没有 ref 时 delta 就是 null）
#   2  配置参数错误（--round 缺失 / --scheme 指向的文件不存在 / 用了禁用开关 /
#      轮次目录不存在），或**证据缺失或不完整**（loss 轨迹读不出、目标侧评测读不出）
#      ★ 「数还没齐」**不是判定**，只是同一张表里的一种用法错误；没有任何结论被表达。
# ============================================================================

from __future__ import annotations

import argparse
import hashlib
import os
import json
import math
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 看起来很危险、但我们故意不提供的开关。
#:
#: 列在这里，是为了让"我们想过并且拒绝了"这件事留在代码里，也为了让误加
#: 这些开关的人立刻被拦下。判定不归本文件管，所以这些开关**永远不会存在**。
FORBIDDEN_FLAGS = (
    "--verdict", "--conclusion", "--force-pass", "--force-fail",
    "--pass", "--fail", "--assume-valid", "--skip-training-check",
)

#: 训练观察用的阈值。
#:
#: ## 这些数字从哪来：**真实序列实测**，不是估的
#:
#:   * 正常序列：相邻**上升**最大 1.2279；全程相对运行最优最大 1.257
#:   * 发散序列（那条假失败）：相邻上升 9.0911；相对最优 9.091
#:
#: jump_factor=4.0 留了约 3.26 倍余量，rel_to_best=2.5 留了约 2.0 倍余量。
#: 余量是刻意的：一个会误报的闸门会把好轮次也拦掉，而人被误拦几次之后
#: 就会绕过闸门 —— 那所有判据一起失效。
#:
#: ## 为什么在线与离线用**不同**的 min_points
#:
#: 在线判的价值**恰恰在第 2 步**（那时只有 2 个点）。共用一块只有两条路：
#: 在线永不触发（门槛太高），或者把离线门槛也拉到 2（正常 run 的早期波动
#: 会被误判成发散）。所以两块分开：在线 2、离线 10。
JUMP_FACTOR = 4.0
REL_TO_BEST = 2.5
MIN_POINTS = 10
EARLY_MIN_POINTS = 2

MODULE_DIR = Path(__file__).resolve().parent          # 本文件住 runtime/
DEFAULT_ROOT = MODULE_DIR.parent                      # 工程根（= LP_ROOT）


# ---------------------------------------------------------------------------
# 工具：读 loss 曲线
# ---------------------------------------------------------------------------

#: Megatron 风格: ` iteration       50/     300 | consumed samples: ... | lm loss: 1.234E+00 | ...`
#: 也兼容 `iter 50 loss 1.23` / `step=50 loss=1.23` 之类。
ITER_RE = re.compile(r"(?:iteration|iter|step)\s*[:=]?\s*(\d+)", re.I)
#: loss 值。**同时认 nan / inf**（见下）。
_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
LOSS_RE = re.compile(rf"(?:lm\s+)?loss\s*[:=]?\s*({_NUM}|[+-]?(?:nan|inf(?:inity)?))", re.I)

# ★ 为什么正文里的 `lm loss: nan` **必须**被抓住（这一条先前判错了）
#
#   先前的注释写着："非有限值来自框架写出的结构化行，而不是正文里的字"，
#   于是 LOSS_RE 只认数字。那个前提在本工程**不成立**：
#
#     真实框架（MindSpeed-LLM / Megatron）默认写的是**文本日志** `train.log`；
#     `evidence/loss.jsonl` 只有谁主动写它时才存在。也就是说文本是主路径。
#
#   后果：`lm loss: nan` 落在正文里 → 正则抓不到 → 轨迹里**看不出这一条**
#   → 「只查 NaN/Inf」的发散观察在这一路上完全失效。
#   而在线早停的全部价值就是**尽早**发现这种东西。
#
#   误伤风险：正则仍然要求出现 `loss` 这个词，不是全文本找 "nan"
#   （前身项目记过这个坑：全文本匹配 nan/inf 会误伤配置里本来就有 inf 的行）。
#   所以放宽到 nan/inf 是安全的。
#
#   `.jsonl` 那条路不变，仍然优先且更权威。
def _to_float(tok: str) -> float | None:
    """把正则抓到的 token 变成 float。nan / inf 也认（大小写、正负号都认）。"""
    low = tok.strip().lower()
    neg = low.startswith("-")
    body = low.lstrip("+-")
    if body.startswith("nan"):
        return float("nan")
    if body.startswith("inf"):
        return float("-inf") if neg else float("inf")
    try:
        return float(tok)
    except ValueError:
        return None



def parse_loss_curve(path: Path) -> tuple[list[tuple[int, float]], list[str]]:
    """读 loss 轨迹。返回 ([(iter, loss)], notes)。

    支持两种格式：
      * `.jsonl` —— 每行 `{"iter": 1, "loss": 2.02}`（键名兼容 step/iteration/lm loss）
      * 纯文本 —— 从 Megatron 风格日志里正则抓 iter 与 loss
    """
    notes: list[str] = []
    pts: list[tuple[int, float]] = []

    if not path.exists():
        return [], [f"没有找到 loss 轨迹文件：{path}"]

    text = path.read_text(encoding="utf-8", errors="replace")

    if path.suffix == ".jsonl":
        for lineno, line in enumerate(text.split("\n"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            it = obj.get("iter", obj.get("iteration", obj.get("step")))
            lo = obj.get("loss", obj.get("lm loss", obj.get("lm_loss")))
            if it is None or lo is None:
                continue
            try:
                pts.append((int(it), float(lo)))
            except (TypeError, ValueError):
                notes.append(f"loss.jsonl 第 {lineno} 行无法解析为 (iter, loss)，已跳过")
    else:
        for line in text.split("\n"):
            mi = ITER_RE.search(line)
            if not mi:
                continue
            ml = LOSS_RE.search(line)
            if not ml:
                continue
            val = _to_float(ml.group(1))
            if val is None:
                continue
            pts.append((int(mi.group(1)), val))

    # 按 iter 排序；同 iter 保留先出现的（重试/续跑会重复写同一 iter）
    seen: dict[int, float] = {}
    for it, lo in pts:
        seen.setdefault(it, lo)
    curve = sorted(seen.items())

    if len(curve) != len(pts):
        notes.append(f"loss 轨迹里有 {len(pts) - len(curve)} 个重复 iter，保留首次出现值")

    return curve, notes


# ---------------------------------------------------------------------------
# 一、训练观察（不是判定）
# ---------------------------------------------------------------------------

def _ratios(losses: list[float]) -> tuple[list[float], list[float]]:
    """返回 (相邻上升比, 相对历史最好的比)。

    ## 为什么只算**上升**方向的相邻比

    loss 下降是正常的收敛，不该被 jump_factor 误伤。看真实数据就明白：
    正常的收敛早期可能从 10 掉到 2（比值 5），那远超 4.0 —— 如果对两个
    方向都算比值，每一个正常 run 都会在早期被误判成发散。

    工程里实测的参考数据：
        * 正常序列：相邻**上升**最大 1.2279；全程 相对历史最好 最大 1.257
        * 发散序列（假失败那条）：相邻上升 9.0911；相对历史最好 9.091
    阈值 jump_factor=4.0 / rel_to_best=2.5 分别留了约 3.26 倍 / 2.0 倍余量。

    ## 相对最好用「运行中的最小值」而不是「末步 / 全程最小」

    用运行最小能抓住**中途的尖峰**（spike 后恢复），用全程最小会漏掉它。
    实测的 1.257 与运行最小口径一致。
    """
    rises: list[float] = []
    rel: list[float] = []
    best = None
    for i, cur in enumerate(losses):
        if i == 0:
            rises.append(1.0)
        else:
            prev = losses[i - 1]
            rises.append(cur / prev if cur > prev else 1.0)
        best = cur if best is None else min(best, cur)
        # best 一定 > 0 才谈得上比值；loss 为 0 是不可能的，但别炸
        rel.append(cur / best if best and best > 0 else 1.0)
    return rises, rel


def _nonfinite(losses: list[float]) -> list[int]:
    return [i for i, v in enumerate(losses) if not math.isfinite(v)]


def _finite(v):
    """把非有限值收成 None —— metrics.json 里不能出现 NaN/Infinity。

    JSON 标准里没有 NaN/Infinity（Python 的 json 会宽容地写出来，
    但读它的下游（jq、其它语言的解析器）会当场炸）。数本身仍然记录，
    记在 `nonfinite_iters` 里 —— 丢掉的是"值"，不是"这件事发生过"。
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def training_observation(curve: list[tuple[int, float]], tv=None) -> dict:
    """观察这次 run 看着对不对 —— **不判定**。

    返回一个 dict，`is_verdict` 恒为 False，`observation` 取三值之一：

        "normal"               看着正常
        "suspected_divergence" 看着像发散（含 NaN/Inf）
        "insufficient_points"  点太少，连"看着对不对"都谈不上

    ★ 写进 `metrics.json` 时还有第四个值 `not_applicable`（0.18.14 起）：
      本轮**没有训练段**（基线轮只跑 convert/eval）—— 由 `_training_section` 判定，
      不是本函数的输出（本函数只看得见轨迹，不知道这一轮跑了几段）。

    ⚠️ 这三值描述的是**这个 run 的训练过程**，不是**方案精度好不好**。
       `observation="normal"` 完全不代表方案有效；`suspected_divergence`
       也不代表方案差 —— 它代表"这一轮测的不是方案，别往下花算力了"。

    ⚠️ 这个函数挡住的是一个真实事故，务必读一遍：

      某次训练 `iter 1 loss 2.02 → iter 2 loss 18.4`（9.09 倍），但它是
      **有限值** —— 所以"只查 NaN/Inf"的发散检测完全没触发。流程照常往下走：
      转换、评测 46 分钟，最后作为一条"精度 FAIL"进档案。
      **它测的是一个从第 2 步起就没在正常训练的模型。**
      那条 FAIL 与方案本身毫无关系，但它看起来和真结论一模一样。

    所以这里有两条独立的线：NaN/Inf（老的、必要条件）与**比值尖峰**
    （新的、真正挡住上面那条的）。只有前者是不够的。

    参数 `tv` 是阈值覆盖（`{"divergence": {...}, "early_stop": {...}}`），
    不传就用本模块实测校准过的常量。在线早停（`scaffold/run_job.py` 的
    stop_gate）调的就是**本函数** —— 不能用两套实现去看同一条轨迹。
    """
    tv = tv or {}
    div = tv.get("divergence") or {}
    es = tv.get("early_stop") or {}
    jump_factor = float(div.get("jump_factor", JUMP_FACTOR))
    rel_to_best = float(div.get("rel_to_best", REL_TO_BEST))
    min_points = int(div.get("min_points", MIN_POINTS))
    early_min = int(es.get("min_points", EARLY_MIN_POINTS))
    early_jump = float(es.get("jump_factor", jump_factor))
    early_rel = float(es.get("rel_to_best", rel_to_best))

    out: dict = {
        "is_verdict": False,
        "observation": "normal",
        "observation_reasons": [],
        "n_points": len(curve),
        "nonfinite_count": 0,
        "nonfinite_iters": [],
        "max_jump_ratio": None,
        "max_jump_at_iter": None,
        "max_rel_to_best": None,
        "max_rel_to_best_at_iter": None,
        "last_loss": None,
        "best_loss": None,
        "early_stop_would_have_fired": False,
        "early_stop_iter": None,
        "early_stop_detail": None,
        # 平台早停（0.18.26，可选）：`enabled=False` 时全部为 null，行为与 0.18.25 一致。
        "plateau": {"enabled": False, "window_steps": None, "min_gain_pct": None,
                    "patience": None, "min_steps": None, "fired": False,
                    "at_iter": None, "gain_pct": None, "detail": None},
        # 给 executor 的一个便利值：converged（平台）/ invalid（发散）/ None
        "stop_kind": None,
        "thresholds": {
            "jump_factor": jump_factor,
            "rel_to_best": rel_to_best,
            "min_points": min_points,
            "early_min_points": early_min,
        },
    }

    if not curve:
        out["observation"] = "insufficient_points"
        out["observation_reasons"].append("没有 loss 轨迹，连「这个 run 看着对不对」都谈不上")
        return out

    iters = [i for i, _ in curve]
    losses = [v for _, v in curve]
    fin = [v for v in losses if math.isfinite(v)]
    out["last_loss"] = _finite(losses[-1])
    out["best_loss"] = min(fin) if fin else None

    # --- 线 1：非有限值（NaN/Inf）---
    bad = _nonfinite(losses)
    out["nonfinite_count"] = len(bad)
    out["nonfinite_iters"] = [iters[i] for i in bad]
    if bad:
        out["observation"] = "suspected_divergence"
        out["observation_reasons"].append(
            f"loss 轨迹里有 {len(bad)} 个非有限值（NaN/Inf），"
            f"首次出现在 iter {out['nonfinite_iters'][0]}"
            + (f"，共 {len(bad)} 处：{out['nonfinite_iters'][:5]}"
               if len(bad) > 1 else "")
        )
        return out

    rises, rels = _ratios(losses)
    max_jump = max(rises)
    max_jump_i = rises.index(max_jump)
    max_rel = max(rels)
    max_rel_i = rels.index(max_rel)
    out["max_jump_ratio"] = max_jump
    out["max_jump_at_iter"] = iters[max_jump_i]
    out["max_rel_to_best"] = max_rel
    out["max_rel_to_best_at_iter"] = iters[max_rel_i]

    long_enough = len(curve) >= min_points

    # --- 线 2a：离线，看整条轨迹 ---
    if long_enough and max_jump > jump_factor:
        out["observation"] = "suspected_divergence"
        out["observation_reasons"].append(
            f"iter {iters[max_jump_i]} 相邻一步 loss 上升 {max_jump:.4f} 倍，"
            f"超过 jump_factor={jump_factor}"
            f"（前一步 {losses[max_jump_i - 1]!r} → 这一步 {losses[max_jump_i]!r}）"
        )
    elif long_enough and max_rel > rel_to_best:
        out["observation"] = "suspected_divergence"
        out["observation_reasons"].append(
            f"iter {iters[max_rel_i]} 的 loss 是历史最好的 {max_rel:.4f} 倍，"
            f"超过 rel_to_best={rel_to_best}"
        )

    # --- 线 2b：在线，只与"当时已经发生的事"有关 ---
    for k in range(len(curve)):
        pts_so_far = k + 1
        if pts_so_far < early_min:
            continue
        if rises[k] > early_jump:
            out["early_stop_would_have_fired"] = True
            out["early_stop_iter"] = iters[k]
            out["early_stop_detail"] = (
                f"在 iter {iters[k]}（第 {pts_so_far} 个点）相邻上升 "
                f"{rises[k]:.4f} 倍 > {early_jump}，在线早停本应杀掉这个 run"
            )
            break
        if rels[k] > early_rel:
            out["early_stop_would_have_fired"] = True
            out["early_stop_iter"] = iters[k]
            out["early_stop_detail"] = (
                f"在 iter {iters[k]}（第 {pts_so_far} 个点）loss 是当时最好的 "
                f"{rels[k]:.4f} 倍 > {early_rel}，在线早停本应杀掉这个 run"
            )
            break

    # --- 线 3：平台早停（0.18.26，**可选**；整块不配 ⇒ 关闭）---
    #
    # 为什么不能比单点：平台期 20 步窗的相对标准差中位 3.9%（实测 /mnt/share/train.log），
    # 单步"要不要停"必然被骗。所以比的是**窗口 vs 窗口的中位数**。
    # 为什么只在这里判：在线早停与离线观察必须同一个实现（0.18.15 的教训）。
    pl = (tv or {}).get("plateau") or {}
    if pl:
        pw = int(pl["window_steps"])
        pg = float(pl["min_gain_pct"])
        pp = int(pl["patience"])
        pm = int(pl["min_steps"])
        out["plateau"].update(window_steps=pw, min_gain_pct=pg, patience=pp,
                              min_steps=pm, enabled=True)
        streak = 0
        for k in range(len(losses)):
            if (k + 1) < pm or (k + 1) < 2 * pw:
                continue
            cur = losses[k - pw + 1: k + 1]
            prev = losses[k - 2 * pw + 1: k - pw + 1]
            if any(not math.isfinite(v) for v in cur + prev):
                continue
            mc = sorted(cur)[len(cur) // 2]
            mp = sorted(prev)[len(prev) // 2]
            if mp <= 0:
                continue
            gain = (mp - mc) / mp * 100.0
            if gain < pg:
                streak += 1
                if streak >= pp:
                    out["plateau"].update(
                        fired=True, at_iter=iters[k], gain_pct=round(gain, 4),
                        detail=(f"在 iter {iters[k]}：最近 {pw} 步中位 {mc:.4f} vs 再前 {pw} 步中位 "
                                f"{mp:.4f}，改善 {gain:.2f}% < {pg}%，连续 {streak} 次命中平台"
                                f"（min_steps={pm}）⇒ 收工"))
                    break
            else:
                streak = 0
        if out["plateau"]["fired"]:
            out["stop_kind"] = "converged"
    if out["stop_kind"] is None and out["early_stop_would_have_fired"]:
        out["stop_kind"] = "invalid"

    # 轨迹太短又被判"看着像发散"时，如果在线判会触发，仍然算 suspected ——
    # 因为那时"短"恰恰是早停起作用的结果，不是证据不足。
    if not long_enough and out["early_stop_would_have_fired"]:
        out["observation"] = "suspected_divergence"
        out["observation_reasons"].append(
            f"轨迹只有 {len(curve)} 个点（不足离线门槛 {min_points}），"
            f"但在线早停条件已满足：{out['early_stop_detail']}"
        )
    elif not long_enough and out["observation"] == "normal":
        # 拿 3 个点下结论比不判更糟 —— 一个会误报的观察会把好轮次也拦掉。
        out["observation"] = "insufficient_points"
        out["observation_reasons"].append(
            f"轨迹只有 {len(curve)} 个点，不足离线门槛 {min_points} —— "
            "点太少，看不出这个 run 是否正常（不是「正常」，也不是「发散」）"
        )

    return out


# ---------------------------------------------------------------------------
# 二、评测结果读取（json / jsonl / 简单文本）
# ---------------------------------------------------------------------------

def _sample_value(s: dict) -> float | None:
    """从一条 per-sample 记录里取 0/1（或连续分）。"""
    if "correct" in s:
        return 1.0 if s["correct"] else 0.0
    if "score" in s:
        try:
            return float(s["score"])
        except (TypeError, ValueError):
            return None
    return None


#: `load_eval` 只认标准 JSON。jsonl / 简单文本由 load_eval_any 兜底分派。
def load_eval(path: Path) -> tuple[dict, list[str]]:
    notes: list[str] = []
    if not path.exists():
        return {}, [f"没有找到评测结果文件：{path}"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {}, [f"{path.name} 不是合法 JSON：{e}"]
    if not isinstance(doc, dict):
        return {}, [f"{path.name} 顶层不是对象"]
    return doc, notes


def parse_eval_jsonl(path: Path) -> tuple[dict, list[str]]:
    """读逐行 JSON。带 id/correct/score 的行是样本，其余是元信息。"""
    notes: list[str] = []
    if not path.exists():
        return {}, [f"没有找到评测结果文件：{path}"]
    samples: list[dict] = []
    meta: dict = {}
    skipped = 0
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(obj, dict):
            skipped += 1
            continue
        if "id" in obj or "correct" in obj or "score" in obj:
            samples.append(obj)
        else:
            meta.update(obj)
    if skipped:
        notes.append(f"{path.name} 有 {skipped} 行不是合法 JSON 对象，已跳过")
    doc = dict(meta)
    doc["samples"] = samples
    return doc, notes


#: 简单文本格式：`<尺子名>: 0.4716` / `accuracy = 0.4716` / `n 1319`
SIMPLE_LINE_RE = re.compile(
    r"^\s*([A-Za-z0-9_.@/-]+)\s*[:=]?\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*$"
)


def parse_eval_simple(path: Path) -> tuple[dict, list[str]]:
    """读"一行一个键值"的简单文本格式（评测脚本顺手打的那种）。

    为什么留这条路：评测命令是**用户自己写在 run.env 里的**，它不一定写
    JSON。硬要求它写 JSON，就等于把"你评测脚本得配合我"变成前置条件 ——
    而这一步的价值是**尽量把已经跑出来的数收进来**，不是规范别人的输出。
    """
    notes: list[str] = []
    if not path.exists():
        return {}, [f"没有找到评测结果文件：{path}"]
    metrics: dict = {}
    n = None
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        m = SIMPLE_LINE_RE.match(line)
        if not m:
            continue
        key = m.group(1).lower()
        val = float(m.group(2))
        if key in ("n", "n_samples", "num_samples", "total", "count"):
            n = int(val)
        else:
            metrics[key] = val
    doc: dict = {"metrics": metrics}
    if n is not None:
        doc["n"] = n
    return doc, notes


def load_eval_any(path: Path) -> tuple[dict, list[str]]:
    """按扩展名分派；分派不动就依次兜底。

    兜底顺序是刻意的：先试标准 JSON（最想支持的形状），再试逐行 JSON，
    最后试简单文本。每一层失败都**不静默** —— 失败原因会累积进 notes，
    这样"为什么这一侧读出来是空的"永远答得出来。
    """
    if not path.exists():
        return {}, [f"没有找到评测结果文件：{path}"]

    if path.suffix == ".jsonl":
        return parse_eval_jsonl(path)

    doc, notes = load_eval(path)
    if doc:
        return doc, notes

    doc2, n2 = parse_eval_jsonl(path)
    if doc2.get("samples"):
        return doc2, notes + n2

    doc3, n3 = parse_eval_simple(path)
    if doc3.get("metrics") or doc3.get("n") is not None:
        return doc3, notes + n3

    return doc, notes


def _metric_name(doc: dict) -> str:
    """指标名。`<尺子名>_accuracy` → `<尺子名>`（去掉评测口径后缀，留下数据集/指标本体）。"""
    raw = str(doc.get("metric") or "").strip()
    for suf in ("_accuracy", "_acc", "_exact_match", "_em", "_score"):
        if raw.endswith(suf) and len(raw) > len(suf):
            return raw[: -len(suf)]
    return raw or "accuracy"


def summarize_eval(doc: dict, source: str) -> dict:
    """把一份评测 doc 收成 {metrics, n, source} —— **聚合值**，不是逐题结果。

    metrics 的取值优先级：
      1. doc 里已有 `metrics` 字典（评测脚本自己聚合好了）
      2. doc 里的标量字段（accuracy / acc / score / ...）
      3. 逐题 `samples` 求均值（有 samples 就一定能算出一个聚合值）
    """
    metrics: dict = {}
    md = doc.get("metrics")
    if isinstance(md, dict):
        for k, v in md.items():
            f = _finite(v)
            if f is not None:
                metrics[str(k)] = f

    name = _metric_name(doc)
    if name not in metrics:
        for key in ("accuracy", "acc", "score", "exact_match", "em", "pass@1", "avg"):
            if key in doc:
                f = _finite(doc.get(key))
                if f is not None:
                    metrics[name] = f
                    break

    samples = [s for s in (doc.get("samples") or []) if isinstance(s, dict)]
    if samples and not metrics:
        vals = [v for v in (_sample_value(s) for s in samples) if v is not None]
        if vals:
            metrics[name] = sum(vals) / len(vals)

    n = None
    if samples:
        n = len(samples)
    else:
        for key in ("n", "n_samples", "num_samples", "total"):
            if key in doc:
                f = _finite(doc.get(key))
                if f is not None:
                    n = int(f)
                    break

    return {"metrics": metrics, "n": n, "source": source}


def _eval_usable(summary: dict) -> bool:
    """有没有一个能拿来做减法的聚合值。"""
    return bool(summary) and bool(summary.get("metrics"))


def aggregate_delta(reference: dict, target: dict) -> tuple:
    """Δ = 目标聚合值 − 参考聚合值。**两个数相减，仅此而已。**

    ## 这里**没有**什么（都是被否掉的那套）
    * 没有按 sample id 求交集，没有逐题配对
    * 没有配对重合率、没有 bootstrap、没有置信区间
    * 没有"配对样本不足就不给 Δ"的门槛

    reference 为 None（这一轮没跑参考侧）时返回 (None, None) ——
    **这是正常情况，不是错误**：只跑目标侧、把这次的数记下来，
    本身就是一次合法的"方案实验实施"。
    """
    if reference is None or target is None:
        return None, None

    rm = reference.get("metrics") or {}
    tm = target.get("metrics") or {}
    if not rm or not tm:
        return None, "有一侧没有聚合值，不做相减"

    key = None
    for k in tm:
        if k in rm:
            key = k
            break
    if key is None:
        # 两侧各只有一个指标、但名字不同：仍然把两个数相减，但把这件事
        # 记进 notes。**不静默**——"减的是两个不同名指标"是必须留痕的取巧。
        if len(tm) == 1 and len(rm) == 1:
            tk = next(iter(tm))
            rk = next(iter(rm))
            return tm[tk] - rm[rk], (
                f"两侧指标名不同（target {tk} / reference {rk}），"
                "按各自唯一的聚合值相减 —— 这个 Δ 只作参考，不可当同名指标比"
            )
        return None, "两侧没有同名指标，不做相减（宁可为 null，也不要减出个假数）"

    return tm[key] - rm[key], None


# ---------------------------------------------------------------------------
# 三、方案指纹
# ---------------------------------------------------------------------------

def scheme_fingerprint(path: Path, root: Path) -> tuple:
    """返回 (相对工程根的路径, sha256 前 16 位)。

    记指纹不是为了"判定按哪份阈值算的"（判定已经不在本文件了），而是为了
    回答一个更朴素的问题：**这一轮 metrics.json 对应的是哪一份方案文件？**
    方案文件被就地改过的话，指纹会变，于是"这个数是不是当初那份方案跑出来的"
    还能对账。
    """
    try:
        rel = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(path)
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return rel, h


# ---------------------------------------------------------------------------
# 三之二、（本节已按 §v0.1 简化原则 1 删除：不设档位机器判据、不设档内噪声带）
# ---------------------------------------------------------------------------


def _yaml_flat_value(lines: list, prefix: tuple) -> tuple:
    """从**保守 YAML 子集**里取 `a.b.c` 这条路径上的标量值。

    返回 `(值, 是否找到)`；值可能是 `None`（YAML 的 `null`）。

    ## 为什么自己写这几行，而不是 import pyyaml
    见文件头"为什么不用 pyyaml"：一个需要装依赖才能跑的脚本，会在最需要它的
    那一刻跑不起来。本文件对 YAML 的需求**只有一个标量**，不需要通用解析器。

    ## 这个子集覆盖什么（`config/*.yaml` 的实际写法）
      * `key:` / `key: value`，缩进为空格、每深一层 +2
      * `#` 注释整行或行尾
      * `key: >` / `key: |` 折叠块 —— 只跳过它的**内容行**
      * 引号标量

    ## fail-closed 的三条
      1. 值后面跟 `#` 注释 → 只认注释之前的部分
      2. 本来就是引号包起来的 → **不切注释**（`#` 可能是值的一部分）
      3. 路径找不到 → 返回"没找到"，由调用方决定它是"缺字段"还是"文件坏了"

    ★ 已知边界（故意不覆盖，也不假装覆盖）：行内嵌套映射
    （`a: {b: c}`）与锚点/别名解析不出来。真遇到那种写法，结果是"没找到"，
    由调用方按缺字段处理（保守方向）。
    """
    # ★★ 这里踩过一个**静默降级**的坑，把形状原样记下来（它正是本项目最贵的
    #   那个错的一个实例）：
    #
    #   第一版把 `prefix` 当成"同一缩进层上的几个键"，于是
    #   `("eval", "protocol", "prompt_type")` 会去缩进 2 上找 `eval`
    #   （而它在缩进 0）⇒ **一个字段都读不出来 ⇒ 静默当成"没配置"**，
    #   而**没有任何一处报错**。
    #
    #   正确的语义：`prefix` 是**一条路径**，每深一层缩进 +2。
    #   顶层 `eval` 在缩进 0；它的子键在缩进 2。
    #   `--selftest` 的负向对照 F 段把这个语义钉住了。
    return _yaml_path_scan(list(lines), tuple(prefix), 0)


def _yaml_path_scan(lines: list, rest_path: tuple, depth: int) -> tuple:
    """在缩进 `2 * depth` 这一层里走完 `rest_path`，取最后一个键的标量。"""
    if not rest_path:
        return None, False
    key_want = rest_path[0]
    want_indent = 2 * depth
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s or s.startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        m = re.match(r"([A-Za-z_][\w\-]*)\s*:(.*)$", s)
        if not m:
            i += 1
            continue
        key, rest = m.group(1), m.group(2)

        if len(rest_path) == 1:
            # 叶子：**只认本层**（缩进不符就不是它）。
            if indent == want_indent and key == key_want:
                return _yaml_scalar(rest), True
            i += 1
            continue

        # 中间层：命中 `key:` 且它是**空值**（后面是子块）才往下走；
        # `key: value` 形状说明它是叶子，与路径不符 ⇒ 跳过。
        if indent == want_indent and key == key_want and not rest.strip():
            block: list = []
            j = i + 1
            while j < n:
                r2 = lines[j]
                if not r2.strip():
                    block.append(r2)
                    j += 1
                    continue
                if len(r2) - len(r2.lstrip(" ")) <= indent:
                    break
                block.append(r2)
                j += 1
            val, found = _yaml_path_scan(block, rest_path[1:], depth + 1)
            if found:
                return val, True
            # ★ 同一个 key 可能出现多次（起草过程里留了两处 `success:` 之类），
            #   这一段里没有目标子键就继续往下找 —— **不许在这里早退**。
            i = j
            continue
        i += 1
    return None, False


def _yaml_scalar(rest: str):
    """把 `: ` 之后的那一段变成标量。`null` / 空 → None。"""
    val = rest.strip()
    if not val or val in ("~", "null", "Null", "NULL"):
        return None
    if val[0] in "\"'":
        q = val[0]
        end = val.find(q, 1)
        if end != -1:
            return val[1:end]
        return val[1:]
    if val in (">", "|", ">-", "|-", ">+", "|+"):
        # 折叠块：标量值在后面的行里。本文件不解析它的内容。
        return None
    if " #" in val:
        val = val.split(" #", 1)[0].strip()
    return val

# ---------------------------------------------------------------------------
# 名字与路径层：**本文件唯一的可变部分**，全部读 `config/`（§11「唯一落点规则」）
# ---------------------------------------------------------------------------
#
# ★ 为什么要有这一层：旧工程把模型名/数据集名/精度串直接写死在本文件里（实测 66 处）。
#   本工程把它们移出 `runtime/` —— 名字只许活在 `config/` 与任务目录、轮次目录。
#   ★ 抽取规则**一个字都没动**：这一层只回答"叫什么、在哪"，不参与任何抽取。

#: 名字/路径的进程内缓存，由 `load_names()` 从 `config/` 填。
NAMES: dict = {}

#: `paths.*` 的内建默认（优先级最低一层，见 §0.1）。只在这里写一份。
DEFAULT_PATHS = {"experiments": "experiments", "records": "records"}


class NamesError(Exception):
    """名字/路径读不出来 —— fail-closed：调用方一律退出 2，不许猜。"""


def _cfg_scalar(root: Path, rel: str, dotted: str):
    """从配置根下的某个 YAML 里取一条点号路径的标量。文件不在/读不出 ⇒ None。"""
    p = root / rel
    if not p.is_file():
        return None
    try:
        body = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    val, found = _yaml_flat_value(body, tuple(dotted.split(".")))
    return val if found else None


def load_names(root: Path, task: str = None) -> dict:
    """从 `config/` 读入本文件需要的**全部名字与路径**。

    读什么（全是"换模型/换任务会变"的部分）：
      * `config/project.yaml`       → `paths.experiments` / `paths.records`
      * `config/tasks/<任务名>.yaml` → `task_id` / `artifacts.root`

    ★ 0.17.0 起**不读**「尺子名清单」（`eval.metrics` 已删）：尺子名由驱动写进
      `metrics.json`，`comparisons` 直接取那批键 ⇒ 名字只有一个落点。
    任务名：`task` 参数 → 环境变量 `LP_TASK`；都没有 ⇒ `NamesError`（不许猜）。

    ★ 这一层**不解析任何阈值/判据**：运行期阈值住任务配置 `stop_conditions.*`，
      评测口径住 `criterion.yaml` 的 `eval_protocol.*`；
      「跟谁比」的唯一来源 `success.baseline_ref` 也住 `criterion.yaml`，由 `run_extract` 读。
    """
    task = (task or os.environ.get("LP_TASK") or "").strip() or None
    if not task:
        raise NamesError(
            "读不到任务名 —— 本文件的名字/路径全部来自 config/tasks/<任务名>.yaml。\n"
            "  给 --task <任务名>，或设环境变量 LP_TASK；**不许猜**。")
    if "/" in task or task in (".", ".."):
        raise NamesError(f"任务名不是合法名（不能含 / 或为 . / ..）：{task}")

    rel_task = f"config/tasks/{task}.yaml"
    if not (root / rel_task).is_file():
        raise NamesError(
            f"任务配置不存在：{root / rel_task}\n"
            f"  （模型名/数据集名/精度串只许活在 config/tasks/ 下，不许写进 runtime/）")

    project = "config/project.yaml"
    paths = {
        "experiments": (_cfg_scalar(root, project, "paths.experiments")
                        or DEFAULT_PATHS["experiments"]),
        "records": (_cfg_scalar(root, project, "paths.records")
                    or DEFAULT_PATHS["records"]),
    }

    task_id = _cfg_scalar(root, rel_task, "task_id") or task
    artifacts_root = _cfg_scalar(root, rel_task, "artifacts.root")
    if not artifacts_root or artifacts_root == "default":
        artifacts_root = f"{paths['experiments']}/{task}"


    return {"task": task, "task_id": task_id, "artifacts_root": artifacts_root,
            "paths": paths}




# ---------------------------------------------------------------------------
# 三之三、早停/主动停的留痕
# ---------------------------------------------------------------------------
#
# 「这一轮是被停下来的」原先只活在**运行时**（`train.sh` 的 stderr、
# `run_job.py` 的那句提醒），抽数产物里**没有落点**。于是几天后看
# `metrics.json` 的人根本不知道这一轮是 80 步停的，会把它和 300 步的轮次
# 直接比 —— 而那不是同一个量尺。
#
# ★ 这里只**转发事实**：有没有留痕、停在哪一步、为什么停。**一个字都不判**
#   "该不该停""停得对不对"（那是 arbiter 的活）。

#: 早停/主动停留痕的文件名（在轮次的 `evidence/` 下）。
#: 谁生成它：`scaffold/train.sh` 把它写进 `--marker`
#: （`EARLY_MARK="$EV/early_stop.triggered"`，`EV="$ROUND_DIR/evidence"`），
#: 由 `run_job.py` 的 `write_marker()` 落盘 —— 与 `evidence/eval_full.flag`
#: 同一个模式：**文件在 ⇒ 事实成立**。
EARLY_STOP_MARKER_FILENAME = "early_stop.triggered"

#: `stop_kind` 的合法取值（`run_job.write_marker()` 只写这三种）。
STOP_KINDS = ("invalid", "holdout", "converged")

#: 兜底扫描时单个文件的大小上限。留痕是几十行文本；超过这个量级的一定是
#: 训练日志/别的产物，不可能是留痕。
_STOP_MARKER_SCAN_MAX_BYTES = 256 * 1024

#: 认留痕的判据：**只认 `stop_kind:` 这一行**（允许缩进 —— `train.sh` 会把
#: 留痕 `sed 's/^/    /'` 后打出来；`:` 或 `=` 都认）。
#: `run_job.write_marker()` 每次都写它；`metrics.json` / `status.md` 不会。
_STOP_KIND_RE = re.compile(r"^[ \t]*stop_kind[ \t]*[:=][ \t]*(\S.*)$", re.M)

#: 留痕的 `key: value` / `key=value` 行。**只认顶格的键** ——
#: `thresholds:` 下面那些缩进的子键（`  jump_factor=4.0`）不是留痕本身。
_MARKER_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]*[:=][ \t]*(.*)$")


def _find_stop_marker(rdir: Path, ev: Path):
    """定位早停留痕文件，找不到返回 None。

    1. ★ 真实路径：`evidence/early_stop.triggered`（来自 `train.sh` 的
       `EARLY_MARK`，出处见该文件第 53 行）。**先查它，查不到才兜底。**
    2. 兜底：`ev` / `rdir` 下**含 `stop_kind:` 行**的文件（按路径排序取第一个）。
       这样脚本改了 marker 名字/位置也不会让留痕凭空消失。
    """
    primary = ev / EARLY_STOP_MARKER_FILENAME
    if primary.is_file():
        return primary
    seen = set()
    for base in (ev, rdir):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            try:
                if p.stat().st_size > _STOP_MARKER_SCAN_MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if _STOP_KIND_RE.search(text):
                return p
    return None


def read_stop_marker(rdir: Path, ev: Path, notes: list = None,
                     marker_path: Path = None) -> dict:
    """读早停/主动停留痕，返回 `{"kind", "stopped_at_step", "reason"}`。

    ## 契约
      * **文件不存在 ⇒ 三个键全是 None** ✓（等价于"这一轮没发生早停"，
        老轮次都是这样）。此时**一条 notes 都不加** —— 没有留痕不是异常。
      * 文件在、但读不出来 / 没有 `stop_kind:` 行 / `stopped_at_step`
        不是整数 ⇒ 能读出的部分原样读出，读不出的记 None，并在 `notes`
        里留一条（**不静默**：坏留痕要被看见，不能被当成"没发生早停"）。
      * `kind` 只认 `STOP_KINDS` 里的值；枚举外的取值 ⇒ 记 None **并留痕**
        （把"留痕写坏了"和"没发生早停"分开）。

    `marker_path` 可传入已定位的留痕路径（省一次扫描）；不传就自己找。
    """
    if marker_path is None:
        marker_path = _find_stop_marker(rdir, ev)
    blank = {"kind": None, "stopped_at_step": None, "reason": None}
    if marker_path is None:
        return blank

    def note(msg: str) -> None:
        if notes is not None:
            notes.append(msg)

    try:
        rel = str(marker_path.relative_to(rdir))
    except ValueError:
        rel = str(marker_path)

    try:
        text = marker_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        note(f"early_stop 留痕文件在（{rel}）但读不出来（{e}）"
             " ⇒ early_stop 记 null。**这不是「没发生早停」**，是留痕坏了。")
        return blank

    kv: dict = {}
    for line in text.splitlines():
        m = _MARKER_KV_RE.match(line)
        if m and m.group(2).strip():
            kv.setdefault(m.group(1), m.group(2).strip())

    info = dict(blank)

    m = _STOP_KIND_RE.search(text)
    raw_kind = m.group(1).strip() if m else ""
    if not raw_kind:
        note(f"early_stop 留痕 {rel} 里没有 `stop_kind:` 行 ⇒ kind 记 null"
             "（留痕形状不对，**不静默**）。")
    elif raw_kind not in STOP_KINDS:
        note(f"early_stop 留痕 {rel} 的 stop_kind 取值不在合法集合 "
             f"{STOP_KINDS} 里：{raw_kind!r} ⇒ kind 记 null（**不静默**，"
             "也不当成「没发生早停」）。")
    else:
        info["kind"] = raw_kind

    raw_step = kv.get("stopped_at_step")
    if raw_step is not None:
        try:
            info["stopped_at_step"] = int(raw_step)
        except ValueError:
            note(f"early_stop 留痕 {rel} 的 stopped_at_step 不是整数："
                 f"{raw_step!r} ⇒ 记 null（**不静默**）。")

    if "reason" in kv:
        info["reason"] = kv["reason"]

    return info


# ---------------------------------------------------------------------------
# 三·b、在线量化误差（QSNR 探针）—— **读留痕，不判定**
# ---------------------------------------------------------------------------
#
# 来源：框架侧 `mindspeed/core/qat/qsnr_probe.py`（核心层）＋ LLM 层接线，由环境变量
# `QAT_QSNR_PROBE=1` 打开；落点 `$LP_EVIDENCE/eval_clamp_qsnr.json`（rank0 一份，
# 其余 rank 各一份 `…rank<r>.json`），同时每次采样打一行
# `[qat-qsnr] step=<k> aggregate_db=<v> (weight=… activation=…)`。
#
# ★ 本文件**只登记数**：`quant_error` 段里没有任何 "pass/fail"。
#   为什么：QSNR 量的是"假量化把张量弄坏了多少"，与"方案精度好不好"不是同一个量；
#   把前者当后者，会让一条 FAIL 看起来像真结论（同一类事故见 training_observation 的长注释）。
#   `quant_error_max`（任务配置）的**停跑判定也不在这里**：它在训练进程里由探针看门狗做
#   （`train_cmd.sh` 换算成 `QAT_QSNR_FLOOR_DB`）；本文件只登记 `watchdog_tripped` 这个事实。
#
# ★ 三种状态必须分得开（这是这类指标最容易脏的地方）：
#     measured       拿到 ≥1 个采样点
#     unmeasured     没开探针 / 文件不存在 —— **不是"达标"**，是"没测"
#     probe_invalid  探针自己报装配失败（取不到输入输出、形状不符…）—— 训练继续，QSNR 缺失
QSNR_FILE = "eval_clamp_qsnr.json"

def qsnr_db_to_rel_err(db):
    """QSNR(dB) → 相对误差 ε = 10 ** (-db/20)。`None` 原样返回（不是 0）。"""
    if db is None:
        return None
    try:
        return 10.0 ** (-float(db) / 20.0)
    except (TypeError, ValueError):
        return None


def load_qsnr(ev: Path, notes: list) -> dict:
    """读 `evidence/eval_clamp_qsnr.json` ⇒ 结构化量化误差；**一个字都不判**。

    键集合固定（下游依赖）：`status` / `source` / `enabled` / `installed` /
    `sampled_at_steps` / `n_points` / `series` / `min_db` / `last_db` /
    `min_rel_err` / `last_rel_err` / `watchdog_tripped` / `reason`。
    """
    blank = {
        "status": "unmeasured",
        "source": None,
        "enabled": None,
        "installed": None,
        "sampled_at_steps": None,
        "n_points": 0,
        "series": [],
        "min_db": None,
        "last_db": None,
        "min_rel_err": None,
        "last_rel_err": None,
        "watchdog_tripped": None,
        "reason": None,
    }
    path = ev / QSNR_FILE
    if not path.is_file():
        # 没开探针是最常见的情况（默认关）⇒ 一句话，不吵。
        blank["reason"] = (
            f"evidence/{QSNR_FILE} 不存在 ⇒ 本轮**没有**量化误差数据"
            "（探针默认关：起训练时给 QAT_QSNR_PROBE=1 才会有）"
        )
        notes.append(blank["reason"])
        # ★ 没有"旁证文件"这回事：探针的 probe_invalid 写在**主文件**里
        #   （`eval_clamp_qsnr.json` 的 `probe_invalid` 字段），所以主文件不在
        #   就只能是"没测"。曾经在这里加过一条猜出来的 `qsnr_probe_invalid.json`
        #   分支 —— 那个文件从来没有生产者，纯死代码，0.18.6 删掉。
        return blank

    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("顶层不是对象")
    except (OSError, ValueError) as exc:
        blank["source"] = f"evidence/{QSNR_FILE}"
        blank["status"] = "probe_invalid"
        blank["reason"] = (
            f"evidence/{QSNR_FILE} 读不出来（{type(exc).__name__}: {exc}）"
            " ⇒ QSNR 记「不可用」"
        )
        notes.append(blank["reason"])
        return blank

    out = dict(blank)
    out["source"] = f"evidence/{QSNR_FILE}"
    out["enabled"] = doc.get("probe_enabled")
    out["installed"] = doc.get("installed")
    out["sampled_at_steps"] = doc.get("sampled_at_steps")
    out["reason"] = doc.get("probe_invalid_reason")

    series = []
    for smp in (doc.get("samples") or []):
        if not isinstance(smp, dict):
            continue
        w = smp.get("weight") if isinstance(smp.get("weight"), dict) else {}
        a = smp.get("activation") if isinstance(smp.get("activation"), dict) else {}
        series.append({
            "step": smp.get("step"),
            "aggregate_db": _finite(smp.get("aggregate_db")),
            "weight_db": _finite(w.get("aggregate_db")),
            "activation_db": _finite(a.get("aggregate_db")),
            "n_layers": smp.get("n_layers"),
            "n_activation_recorded": smp.get("n_activation_recorded"),
        })
    series = [x for x in series
              if x["aggregate_db"] is not None or x["weight_db"] is not None]

    trip = doc.get("tripped")
    out["watchdog_tripped"] = trip if isinstance(trip, dict) else None
    out["series"] = series
    out["n_points"] = len(series)

    if not series:
        if doc.get("probe_invalid"):
            out["status"] = "probe_invalid"
            if not out["reason"]:
                out["reason"] = "探针自证 probe_invalid ⇒ QSNR 序列不可用"
        else:
            out["reason"] = (
                f"evidence/{QSNR_FILE} 在，但没有任何可用采样点（samples 为空或全 null）"
                " ⇒ QSNR 记「不可用」（**不是**「达标」）"
            )
        notes.append(out["reason"])
        return out

    out["status"] = "measured"
    dbs = [x["aggregate_db"] for x in series if x["aggregate_db"] is not None]
    if dbs:
        out["min_db"] = min(dbs)
        out["last_db"] = dbs[-1]
        out["min_rel_err"] = qsnr_db_to_rel_err(out["min_db"])
        out["last_rel_err"] = qsnr_db_to_rel_err(out["last_db"])
    if out["n_points"] < 2:
        notes.append(
            f"QSNR 只有 {out['n_points']} 个采样点 ⇒ 只能当**一个时点**看，"
            "不能判趋势（采样步由 QAT_QSNR_EVERY 决定）"
        )
    if out["watchdog_tripped"]:
        notes.append(
            f"★ 探针看门狗**已触发**（rule={out['watchdog_tripped'].get('rule_hit')!r}、"
            f"step={out['watchdog_tripped'].get('at_step')!r}）—— 这是工程护栏触发，"
            "说明本 run 的量化误差已越过护栏（不是方案精度结论）"
        )
    return out


# 四、主流程：抽数
# ---------------------------------------------------------------------------

#: `metrics.json` 的段形状 —— 下游 agent 与测试依赖它，改动等于改契约。
TRAINING_KEYS = (
    "points", "first_iter", "last_iter",
    "first_loss", "last_loss", "min_loss", "max_loss",
    "max_adjacent_rise", "max_rel_to_best",
    "nonfinite_iters", "observation", "observation_reasons",
    "thresholds_used", "is_verdict",
)
NOTE_TOP_KEYS = (
    "cell_key", "round", "generated_at", "scheme_path", "scheme_fingerprint",
    "criterion_path", "criterion_fingerprint", "baseline_path", "baseline_round",
    "training", "eval", "early_stop", "quant_error",
    # ★ 0.19.0：held-out racing（验证曲线 ＋ 参照轮 ＋ 判据留痕）。与 early_stop /
    #   quant_error / timing 同一类：**只登记事实**，`is_verdict` 恒 False。
    "holdout",
    # ★ 0.18.26：三段净耗时（读 `evidence/<段>.exec.json` 的 `duration_s`）。
    #   只登记**机器净耗时**；角色墙钟（含等人的时间）不在本文件里，也不许编。
    "timing",
    "notes",
)


def _list_cells(base: Path) -> str:
    """列出已有格子，供报错时说清"现在有哪些"。"""
    cells = sorted(p.name for p in base.glob("*") if p.is_dir())
    if not cells:
        return "    （还没有任何格子）"
    return "\n".join(f"    {c}" for c in cells)


def _resolve_round_dir(root: Path, round_id: str, cell: str, names: dict) -> tuple:
    """定位本轮目录 `<artifacts.root>/rounds/<轮次>/`，返回 (路径, cell_key)。

    ## ★ 规则只有一句：**唯一命中才继续；不唯一就报错，不猜**

    这一条与 `runtime/_common.sh` 的路径解析是**同一条规则的两份实现**（一边 shell、
    一边 Python），改一边必须改另一边。

    ## 名字从哪来
    `cell` = 任务名（`config/tasks/<任务名>.yaml` 的文件名），只在**跨任务撞号**时
    才需要给；记进产物的 `cell_key` 取任务配置的 `task_id`（跨轮档案的键，
    见 §3.1 的 `records/best/<任务名>__<指标>.yaml`）。
    """
    if "/" in round_id or round_id in (".", ".."):
        raise ValueError(f"轮次 id 不是合法名（不能含 / 或为 . / ..）：{round_id}")
    base = root / names["paths"]["experiments"]

    if cell:
        if "/" in cell or cell in (".", ".."):
            raise ValueError(f"--cell 不是合法的任务名（不能含 / 或为 . / ..）：{cell}")
        d = base / cell / "rounds" / round_id
        if not d.is_dir():
            raise ValueError(
                f"找不到这一轮：{d}\n\n"
                f"  --cell 给的是 {cell!r}，但那个任务下没有轮次 {round_id}。\n"
                f"  现有的任务：\n{_list_cells(base)}")
        return d, _cell_key(root, cell, names)

    hits = sorted(q for q in base.glob(f"*/rounds/{round_id}") if q.is_dir())
    if not hits:
        if (base / round_id).is_dir():
            raise ValueError(
                f"{round_id} 还是**旧布局**（轮次直接挂在任务根下，不在 `<任务名>/rounds/` 里）。\n\n"
                f"  现在：{base}/{round_id}/\n"
                f"  应该：{base}/<任务名>/rounds/{round_id}/\n\n"
                f"  挪一下即可（不动内容）：\n\n"
                f"    mkdir -p {base}/<任务名>/rounds\n"
                f"    mv {base}/{round_id} {base}/<任务名>/rounds/")
        raise ValueError(
            f"找不到轮次 {round_id}\n\n"
            f"  轮次目录由**你**建，位置决定它属于哪个任务：\n\n"
            f"    <paths.experiments>/<任务名>/rounds/{round_id}/\n\n"
            f"  现有的任务：\n{_list_cells(base)}")
    if len(hits) > 1:
        cand = "\n".join(f"    {h}" for h in hits)
        raise ValueError(
            f"轮次 id {round_id!r} 在**多个任务**里都存在，无法确定是哪一个：\n\n"
            f"{cand}\n\n"
            f"  轮次 id 只需要在**任务内**唯一，所以跨任务撞号是正常的。\n"
            f"  用 --cell 指定：\n\n"
            f"    --cell {hits[0].parent.parent.name}")
    return hits[0], _cell_key(root, hits[0].parent.parent.name, names)


def _cell_key(root: Path, task: str, names: dict) -> str:
    """跨轮档案的键 = 任务配置的 `task_id`（读不到就退回任务目录名，不猜别的）。"""
    if task == names.get("task"):
        return str(names.get("task_id") or task)
    return str(_cfg_scalar(root, f"config/tasks/{task}.yaml", "task_id") or task)


# ══════════════════════════════════════════════════════════════════════════════
# 参照对比 —— **「跟谁比」只有一个来源**：`<轮次>/criterion.yaml` 的
# `success.baseline_ref`（文档 §11 ④ 的字段表：`success.{metric, baseline_ref, require}`，
# 第一轮写 `null`）。
#
# ★ 三条纪律（与旧实现一致，一个字都没动）：
#   ① 两个尺子**成对**给；哪一侧没测 ⇒ 写 null + 理由，
#      **绝不填 0、绝不借用别的轮的同一个尺子**。
#   ② 基线**从档案里读**，不写死 —— 写死就是"凭空的对比"。
#   ③ `baseline_ref` 为 `null` ⇒ **本轮不比**：对照节点记 `null` ＋ 一句理由（不是错误）。
#
# 名字从哪来：
#   `success.baseline_ref` —— 基线**轮次 id**（可为 `null`）；抽数器按它在
#     `<artifacts.root>/rounds/<基线轮次>/metrics.json` 取**基线轮次**的指标。
#   **不再读配置**：尺子名 = 目标轮 `metrics.json` 的 `metrics` 字典的键（驱动写出）；
#     尺子**数量不设上限**，对照键逐个落（0.17.0 起；旧版只落 2 个）。
# ★ 键名是**中性**的：对照节点按基线轮次命名 `vs_<基线轮次>`；源码里没有一个具体轮次号/臂名。
# ══════════════════════════════════════════════════════════════════════════════


def _side_metric(side, name):
    if not isinstance(side, dict):
        return None
    v = (side.get("metrics") or {}).get(name)
    return v if isinstance(v, (int, float)) else None


def _delta_vs(side, cur, name):
    a, b = _side_metric(side, name), _side_metric(cur, name)
    if a is None or b is None:
        return None
    return b - a


def _criterion_baseline_ref(cpath: Path):
    """读 `<轮次>/criterion.yaml` 的 `success.baseline_ref` —— **只读这一条**。

    按文档 §11 ④ 的字段表：它是**基线轮次 id**（如 `R-0001`）；第一轮写 `null` ⇒ 本轮不比。
    读不出／不是标量 ⇒ `None`（＝不比，由调用方写 `null` ＋ 理由；**不猜**）。
    """
    try:
        lines = cpath.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    val, found = _yaml_flat_value(lines, ("success", "baseline_ref"))
    if not found or val is None:
        return None
    s = str(val).strip()
    return s or None


def _baseline_path_from_ref(root: Path, names: dict, baseline_ref: str) -> Path:
    """基线轮次 id ⇒ `<artifacts.root>/rounds/<基线轮次>/metrics.json`（存不存在由调用方判）。"""
    return root / names["artifacts_root"] / "rounds" / baseline_ref / "metrics.json"


def _comparisons(target, reference, baseline, delta_baseline, root, cell_key, notes,
                 baseline_ref=None):
    """**唯一一个**「跟谁比」节点：键 `vs_<基线轮次>`（基线轮次为 `null` ⇒ `vs_baseline: null`）。

    ★ 不再有第二个对照块：任务配置里那条自造的跨轮锚点（0.15.0 按决策者判定删除）原本产出一族
      **写死的键名**（带具体轮次号的对照块与其内部字段）—— 那些键名一并去掉 ⇒
      现在 `runtime/` 里没有一个具体轮次号/臂名，`devtools/check_decoupling.py` 的历史例外也随之取消。
      键名只由 `baseline_ref` 现算。
    """
    # ★ 尺子名 = **目标轮** `metrics.json` 里驱动写出的键（`eval.metrics` 已删 ⇒ 没有第二处声明）。
    #   0.17.0 起尺子**不设上限**：旧版只取 m0/m1 两槽，第 3 条起静默丢；
    #   多数据集改造后条目数**随数据集×尺子增长** ⇒ 必须全落。空名字不落键。
    names = [str(x) for x in ((target or {}).get("metrics") or {}) if str(x).strip()]
    # 基线轮次 id：优先吃**已读到的基线档**里的 `round`（权威），否则用 criterion 冻的那个。
    bl_round = (baseline or {}).get("round") or baseline_ref
    if not bl_round:
        notes.append(
            "criterion 的 success.baseline_ref 为 null（也没有给 --baseline）⇒ **本轮不比**："
            "comparisons.vs_baseline 记 null。第一轮实验就是这样，不是错误。"
        )
        return {"vs_baseline": None}
    bl = {
        "sources": [x for x in [(baseline or {}).get("source")] if x],
        "round": bl_round,
    }
    bl_notes: list = []
    if not names:
        bl_notes.append(
            "目标轮的 metrics 是空的 ⇒ 一个比较键都没有"
            "（驱动没写出任何指标 ⇒ 这一轮的数字不可用，不是「没测」）")
    missing: list = []
    for name in names:
        bl[name] = {"baseline": _side_metric(baseline, name),
                    "delta": _delta_vs(baseline, target, name)}
        if baseline is not None and _side_metric(baseline, name) is None:
            missing.append(name)
    if baseline is None:
        bl_notes.append("基线轮次的数读不到（文件不在／目标侧没有聚合值）⇒ 基线值与 Δ 都是 null")
    elif missing:
        bl_notes.append("基线轮没有这几把尺子的聚合值（那一轮没测）⇒ 它们的 Δ 为 null，"
                        "**不许**用别的轮补：" + "、".join(missing))
    bl["note"] = "；".join(bl_notes) if bl_notes else None
    return {f"vs_{bl_round}": bl}

def _collect_arms(ev, notes):
    """把臂级证据机读成一张表（键名避开判定词汇）.

    ★ 两条来源缺一不可：**主臂写 `eval_target.json`**（判据 (A) 的落点），
      其余臂写 `eval_arm_<id>.json` —— 只 glob 后者会**静默漏掉主臂** ✗。
    """
    arms = {}
    tf = ev / "eval_target.json"
    if tf.is_file():
        try:
            d = json.loads(tf.read_text(encoding="utf-8"))
            arms["target"] = {
                "source": "eval_target.json",
                "metric": d.get("metric"), "metrics": d.get("metrics"), "n": d.get("n"),
                "eval_full": d.get("eval_full"),
                "protocol_qat_env": (d.get("protocol") or {}).get("qat_env"),
                "evidence": d.get("evidence"),
            }
        except Exception as e:
            notes.append(f"主臂证据 eval_target.json 读不出（{e}）⇒ arms 里没有主臂")
    else:
        notes.append("没有 evidence/eval_target.json ⇒ arms 里没有主臂（不是'臂没跑'）")
    for f in sorted(ev.glob("eval_arm_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            notes.append(f"臂证据 {f.name} 读不出（{e}）⇒ 该臂不入 arms 表")
            continue
        arms[f.stem[len("eval_arm_"):]] = {
            "source": f.name,
            "metric": d.get("metric"), "metrics": d.get("metrics"), "n": d.get("n"),
            "eval_full": d.get("eval_full"),
            "protocol_qat_env": (d.get("protocol") or {}).get("qat_env"),
            "evidence": d.get("evidence"),
        }
    if not arms:
        notes.append("没有臂级证据 ⇒ eval.arms 是空表（不是'没有副作用'）")
    return arms


def _load_baseline(bpath: Path, root: Path, target: dict,
                   crit_hash: str, notes: list) -> tuple:
    """读**基线轮次**的 metrics.json，返回 (baseline 块, Δ, 是否可比)。

    ## 基线是**一个轮次**，不是判据里手抄的一个数字

    Δ = 本轮目标侧聚合值 − 基线轮次的目标侧聚合值 ——
    **两个机械产物相减**。这样差值可追溯到两份带指纹的文件；而
    "从历史记录里翻出个数来手减"得到的差值**没有指纹可对**，
    违反本工程"数字必须能追溯到机械产物"这条。

    ## 和 `eval.reference` 的区别（容易混）

      `eval.reference`   **本轮**重跑的参考侧。口径与目标侧**由构造保证相同**。
      `eval.baseline`    **历史**某一轮的目标侧。口径**不保证**相同 ——
                         所以要拿判据指纹对一下，不同就明说。

    两者都在，各自回答不同的问题：口径变了就必须重跑 reference；
    口径没变时 baseline 是免费的历史对照。

    ## 没有基线是正常情况

    第一轮实验没有基线（它自己就是基线）→ bpath 为 None → 两者都是 null。
    """
    if bpath is None:
        notes.append(
            "没有基线轮次 —— eval.baseline 与 delta_vs_baseline 都是 null。"
            "第一轮实验就是这样（它自己就是基线），不是错误。"
        )
        return None, None

    if not bpath.exists():
        notes.append(f"基线文件不存在：{bpath} —— 记为 null（不猜它的值）。")
        return None, None

    try:
        bdoc = json.loads(bpath.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        notes.append(f"基线文件读不出来（{e}）：{bpath} —— 记为 null。")
        return None, None

    try:
        rel = str(bpath.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(bpath)

    # 基线轮的**目标侧**就是它的"我这个方案值多少" —— 那正是我们要拿来当对照的数。
    # （不是它的 reference 侧：那是它当时的参考，不是它自己。）
    beval = bdoc.get("eval") or {}
    bmetrics = ((beval.get("target") or {}).get("metrics")) or {}

    block = {
        "source": rel,
        "round": bdoc.get("round"),
        "cell_key": bdoc.get("cell_key"),
        "criterion_fingerprint": bdoc.get("criterion_fingerprint"),
        "metrics": bmetrics,
    }

    if not bmetrics:
        notes.append(
            f"基线 {rel} 的目标侧没有任何聚合值 —— eval.baseline 记 null，Δ 不计算。"
        )
        return None, None

    # ★ 口径对账：判据指纹不同 = 两轮的成功条件/评测口径**至少有一处不同**。
    #   这是**事实**（两个文件不一样），不是判定 —— 所以它属于机械层。
    #   摆出来，让 arbiter 判；**不**替它决定"这两个数还能不能比"。
    bc = block.get("criterion_fingerprint")
    if crit_hash and bc and bc != crit_hash:
        notes.append(
            f"★ 口径可能不同：本轮判据指纹 {crit_hash} ≠ 基线轮 {bc}。"
            "两轮的 success / eval_protocol 至少有一处不一样，"
            "Δ 里可能混着口径差。★ 典型字段是 max_gen_toks / prompt_type / "
            "dataset / num_fewshot —— 但**差多少必须逐项实测，不许拿举例当数据**"
            "（本文件曾经在这里写死过一个举例数，2026-10-14 已删）。"
            "逐项比对的命令：\n"
            "      diff <(sed -n '/eval_protocol/,/^[a-z]/p' <基线轮判据>) "
            "<(sed -n '/eval_protocol/,/^[a-z]/p' <本轮判据>)\n"
            "    把**实际**不同的字段与各自的**实际**取值写进 report。"
            "要排除它，就把参考侧**重跑一遍**（那才是 eval.reference 的用途）。"
        )

    delta, why = aggregate_delta(block, target)
    if why:
        notes.append(why)
    return block, delta


def _eval_candidates(side: str) -> tuple:
    return (
        f"eval_{side}.json", f"eval_{side}.jsonl",
        f"eval_{side}.txt", f"eval_{side}.log",
    )


def _load_side(ev: Path, side: str) -> tuple:
    """在 evidence/ 里找某一侧的评测结果。返回 (doc, notes, path)。"""
    for name in _eval_candidates(side):
        p = ev / name
        if p.exists():
            doc, notes = load_eval_any(p)
            return doc, notes, p
    return {}, [
        f"evidence/ 下没有 {side} 侧的评测结果"
        f"（找过：{', '.join(_eval_candidates(side))}）"
    ], None


def _best_record(root: Path, cell_key: str) -> "tuple[Path | None, str | None]":
    """`records/best/<任务名>__<指标>.yaml` ⇒ `(路径, 原因)`。**找不到或有歧义都给原因，绝不猜。**

    ★ 为什么 racing 的参照是它（0.19.0 定）：`records/best` 里那一轮天然是**跑完 ＋
      通过判定 ＋ 证据齐全**的，不用再从 `design.md` 认"哪个是框架原生轮"。
    ★ 为什么多份就放弃：不同指标的 best 档案口径不同（`records/best` 的纪律是
      "不同口径的指标分文件放"），合成一个参照就是拿两把尺子当一把。
    """
    d = root / "records" / "best"
    if not d.is_dir():
        return None, f"还没有 {d} 目录（第一轮跑完、判定 adopt 之后才会写）"
    hits = sorted(d.glob(f"{cell_key}__*.yaml"))
    if not hits:
        return None, f"{d} 里没有 {cell_key}__*.yaml（本任务还没有通过判定的最优轮）"
    if len(hits) > 1:
        names = "、".join(h.name for h in hits)
        return None, (f"{d} 里有 {len(hits)} 个本任务的档案（{names}）⇒ 参照有歧义，不猜")
    return hits[0], None


def _curve_fingerprint(curve) -> str:
    """验证曲线的指纹（racing 参照漂移要看得见：参照换了，跨轮 gap 就不可比）。"""
    raw = json.dumps([[int(s), float(v)] for s, v in (curve or [])],
                     ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_valid_curve(ev: Path, notes: list) -> "tuple[list, str | None]":
    """读本轮的验证曲线。来源优先级：`evidence/valid.txt`（执行器写）→ `train.log` 的验证行。

    ★ 为什么要独立文件：`loss.txt` 里**只有训练 loss**（执行器按验证行先分离过），
      两者混在一起会被 `jump_factor` 误判成跳变 —— 这正是 `parse_loss_curves` 文档里
      记着的那个坑。没有 `valid.txt`（老轮次）就退回从完整日志里捞验证行。
    """
    vp = Path(ev) / "valid.txt"
    if vp.is_file():
        # ★ `valid.txt` 里是**纯验证行**（Megatron 形状 `validation loss at iteration N |
        #   lm loss value: X`）。`parse_loss_curve`（单数）只认训练行 ⇒ 这里必须走
        #   `parse_loss_curves`（复数）的验证那一支，否则文件明明有内容却被判成"没有验证点"。
        _vt, va, _vn = parse_loss_curves(vp)
        if va:
            return va, "evidence/valid.txt"
        curve, _notes = parse_loss_curve(vp)
        if curve:
            return curve, "evidence/valid.txt"
    lp = Path(ev) / "train.log"
    if lp.is_file():
        _tr, va, vnotes = parse_loss_curves(lp)
        notes.extend([f"验证曲线（从 train.log 捞）：{n}" for n in vnotes])
        if va:
            return va, "evidence/train.log 的验证行"
    return [], None


def load_valid_baseline(root: Path, experiments: Path, cell: str, notes: list) -> "tuple[list, dict]":
    """解析 racing 的参照轮（`records/best` → 该轮 `metrics.json` / `evidence`）⇒ `(曲线, 留痕)`。

    留痕里每条都要有：用的哪个档案、哪一轮、曲线指纹、以及**为什么没用上**（若有）。
    """
    info = {"kind": "best", "record": None, "round": None, "metrics": None,
            "fingerprint": None, "reason": None}
    rec, why = _best_record(root, cell)
    if rec is None:
        info["reason"] = why
        return [], info
    info["record"] = str(rec.relative_to(root)) if rec.is_relative_to(root) else str(rec)
    val, found = _yaml_flat_value(rec.read_text(encoding="utf-8", errors="replace").splitlines(),
                                  ("round",))
    if not found or not val:
        info["reason"] = (f"{info['record']} 没有 `round:` 字段（0.19.0 起 required："
                          f"它是 racing 的参照轮 id）⇒ 不判")
        return [], info
    rnd = str(val).strip()
    info["round"] = rnd
    if not re.fullmatch(r"R-\d{3,}", rnd):
        info["reason"] = f"`round:` 取值 {val!r} 不是轮次 id ⇒ 不判"
        return [], info
    bdir = experiments / cell / "rounds" / rnd
    mpath = bdir / "metrics.json"
    curve: list = []
    if mpath.is_file():
        info["metrics"] = str(mpath.relative_to(root)) if mpath.is_relative_to(root) else str(mpath)
        try:
            doc = json.loads(mpath.read_text(encoding="utf-8"))
            hold = doc.get("holdout") or {}
            for s, v in ((hold.get("valid") or {}).get("curve") or []):
                curve.append((int(s), float(v)))
        except (OSError, ValueError, TypeError) as exc:
            notes.append(f"基线轮 {rnd} 的 metrics.json 读不出验证曲线：{exc}")
    if not curve:
        curve, _src = load_valid_curve(bdir / "evidence", notes)
    if not curve:
        info["reason"] = (f"基线轮 {rnd}（{info['record']}）没有验证曲线 ⇒ 不判："
                          f"racing 需要两边在同一批 step 上都有验证点")
        return [], info
    info["fingerprint"] = _curve_fingerprint(curve)
    return curve, info


def _holdout_from_exec(ev: Path) -> "tuple[dict, str]":
    """从 `evidence/train.exec.json` 读**本轮实际生效**的 racing 阈值 ⇒ `(阈值, 说明)`。

    ★ 为什么以它为准：那是执行器真正拿在手里的数（`--holdout-*` 由 `_common.sh` 从任务
      配置解析后传入）。配置里那份可能写法不同（本文件的 YAML 读取器只认块风格），
      两边各算一次就会"在线在判、离线没在判" —— 这是最不该出现的错。
    """
    p = Path(ev) / "train.exec.json"
    if not p.is_file():
        return {}, ""
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, ""
    blk = doc.get("holdout") or {}
    th = blk.get("thresholds") or {}
    out = {}
    try:
        if th.get("min_step") is not None:
            out["min_step"] = int(th["min_step"])
        if th.get("max_gap_pct") is not None:
            out["max_gap_pct"] = float(th["max_gap_pct"])
        if th.get("patience") is not None:
            out["patience"] = int(th["patience"])
    except (TypeError, ValueError):
        return {}, ""
    return out, ("evidence/train.exec.json（本轮实际生效值）" if out else "")


def holdout_section(ev: Path, root: Path, experiments: Path, cell: str,
                    rdir: Path, tv: dict, notes: list) -> dict:
    """`metrics.json` 的 `holdout` 段：验证曲线 ＋ 参照轮留痕 ＋ racing 判据。

    ★ 只登记事实：`is_verdict` 恒 False。作废与否归 `criterion.yaml` 与判定环节。
    ★ 判据本身只在 `holdout_racing` 一处（执行器在线用的也是同一个函数）。
    """
    # ★ 阈值的**第一来源是本轮实际生效值**（`evidence/train.exec.json` 的 `holdout`，
    #   由 executor 的 write_meta 写下）。配置只是退路 —— 任务配置里那份可能没被读到
    #   （本文件的 YAML 读取器只认块风格），两边各算一次就会"训练侧在判、评测侧没在判"。
    eff, eff_src = _holdout_from_exec(ev)
    if eff:
        tv = eff
    src_note = eff_src or (f"config/tasks/{cell}.yaml（任务配置）" if tv else "")
    curve, src = load_valid_curve(ev, notes)
    base, info = load_valid_baseline(root, experiments, cell, notes)
    obs = holdout_racing(curve, base, tv)
    if src_note and isinstance(obs, dict):
        obs["thresholds_source"] = src_note
    vals = [v for _s, v in curve if isinstance(v, (int, float)) and math.isfinite(v)]
    stats = {
        "points": len(curve),
        "first_iter": curve[0][0] if curve else None,
        "last_iter": curve[-1][0] if curve else None,
        "first_loss": _finite(vals[0]) if vals else None,
        "last_loss": _finite(vals[-1]) if vals else None,
        "min_loss": _finite(min(vals)) if vals else None,
        "min_iter": (next(s for s, v in curve if v == min(vals)) if vals else None),
        "curve": [[int(s), _finite(v)] for s, v in curve],
        "source": src,
    }
    if not curve:
        notes.append("本轮没有验证点：`stop_conditions.holdout` 配了也不会生效 —— "
                     "检查 `<任务目录>/commands/train_argv.txt` 的 `--split`（valid 部分 > 0）"
                     "与 `--eval-iters`（> 0）。")
    return {"baseline": info, "valid": stats, "racing": obs, "is_verdict": False}


def _training_section(curve: list, tv: dict = None, no_train_segment: bool = False) -> dict:
    """把训练观察拼成 metrics.json 的 `training` 段（键**恰好**是契约里那 14 个）。

    这里刻意不把 training_observation 的整个 dict 倒出去：那个 dict 是给
    调用方（在线早停）看的，字段多了会随意长；写进文件的这一段是**契约**，
    多一个字段就多一个下游要维护的东西。

    `no_train_segment=True`：本轮**没有训练段**（基线轮／只评测的轮次）——
    `evidence/` 里连 `train.log`／`loss.txt` 都不存在，所以"没有 loss 轨迹"是**预期**，
    不是"点数不足"。两者混成一个 `insufficient_points` 会让人以为这一轮跑得不对。
    """
    obs = training_observation(curve, tv)
    if no_train_segment:
        obs["observation"] = "not_applicable"
        obs["observation_reasons"] = [
            "本轮没有训练段（只跑了 convert/eval）：没有 loss 轨迹是**预期**，"
            "不是「点数不足」——训练观察在基线轮不适用。"
        ]
    losses = [v for _, v in curve]
    fin = [v for v in losses if math.isfinite(v)]

    return {
        "points": len(curve),
        "first_iter": curve[0][0] if curve else None,
        "last_iter": curve[-1][0] if curve else None,
        "first_loss": _finite(losses[0]) if curve else None,
        "last_loss": _finite(losses[-1]) if curve else None,
        "min_loss": min(fin) if fin else None,
        "max_loss": max(fin) if fin else None,
        # 名字与老实现的 max_jump_ratio / max_rel_to_best 对齐：
        # "rise" 比 "jump" 准确 —— 只统计上升方向，下降不算跳变。
        "max_adjacent_rise": _finite(obs["max_jump_ratio"]),
        "max_rel_to_best": _finite(obs["max_rel_to_best"]),
        "nonfinite_iters": obs["nonfinite_iters"],
        "observation": obs["observation"],
        "observation_reasons": obs["observation_reasons"],
        # ★ 记下**实际用的全部阈值**，不是只记一个。
        #   理由：这四个数是"这个 run 是看着不对"的判据本身。只记 jump_factor
        #   的话，后来者看到 observation=suspected_divergence 无法复算 ——
        #   他不知道当时 rel_to_best / min_points 取的是多少。
        #   这几个数现在是 metrics.py 的模块常量（改动它们会改变历史结论的
        #   可比性，见文件头），所以把它们原样写进每一次的产物里。
        "thresholds_used": dict(obs["thresholds"]),
        "is_verdict": False,
    }


def load_stage_timing(ev: Path, notes: list) -> dict:
    """读三段进程元数据里的**净耗时** ⇒ `timing` 段。只登记事实，不判定。

    来源：`evidence/<段>.exec.json`（`runtime/executor.py` 的 `write_meta` 写出，
    由 `runtime/_common.sh` 传 `--meta`）。三份都可能缺：基线轮只跑 convert/eval，
    `dry-run` 不产证据 —— 缺就是 `null`，**不填 0**。
    """
    out = {"stages": {}, "engine_total_s": None, "sources": {}}
    total = 0.0
    counted = 0
    for stage in ("train", "convert", "eval"):
        p = ev / f"{stage}.exec.json"
        out["stages"][stage] = None
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            notes.append(f"evidence/{p.name} 解析失败（{exc}）—— 该段耗时记 null")
            continue
        if not isinstance(doc, dict):
            notes.append(f"evidence/{p.name} 顶层不是对象 —— 该段耗时记 null")
            continue
        dur = doc.get("duration_s")
        rec = {
            "duration_s": dur if isinstance(dur, (int, float)) else None,
            "exit_code": doc.get("exit_code"),
            "last_iteration": doc.get("last_iteration"),
            "early_stopped": doc.get("early_stopped"),
            "timed_out": doc.get("timed_out"),
            "dry_run": doc.get("dry_run"),
            "source": f"evidence/{p.name}",
        }
        out["stages"][stage] = rec
        out["sources"][stage] = rec["source"]
        if rec["dry_run"]:
            notes.append(
                f"{rec['source']} 是 **dry-run** 的元数据 ⇒ 它的耗时不是真跑耗时，不计入总数")
            continue
        if isinstance(rec["duration_s"], (int, float)):
            total += float(rec["duration_s"])
            counted += 1
    out["engine_total_s"] = round(total, 3) if counted else None
    if counted == 0:
        notes.append("evidence/ 下没有可用的 `<段>.exec.json` ⇒ 三段净耗时全为 null")
    return out


def _rel_to(root: Path, p) -> str:
    """把路径写成**相对配置根**的形式；实在折不了（例如根外路径）就原样给绝对/相对串。"""
    path = Path(p)
    try:
        return str(path.resolve().relative_to(Path(root).resolve()))
    except (ValueError, OSError):
        return str(path)


def write_artifacts_json(root: Path, rdir: Path, metrics: dict,
                         crit_rel, scheme_rel, baseline_path) -> Path:
    """写 `<轮次>/artifacts.json` —— 这一轮的**产物路径清单**（`skills/report-and-conclusion`
    对它的唯一定义就是这四个字）。

    三条纪律：
      * **只增输出**：不改 `metrics.json` 里已有的键、不改任何抽取规则（数字要能与历史轮次对账）。
      * **只登记真实存在的文件**：清单当场 `rglob` 本轮目录（含 `evidence/**`），不手写、不猜。
      * **清单不含 `artifacts.json` 自身**：否则同一份证据抽第二次时清单会多一项，
        产出就依赖"这个目录被抽过几次"（等价脚本的 hermetic 自检防的正是这一类）。
    """
    files = sorted(
        _rel_to(root, p) for p in rdir.rglob("*")
        if p.is_file() and p.name != "artifacts.json"
    )
    doc = {
        "schema": 1,
        "generated_at": metrics.get("generated_at"),
        "writer": "runtime/metrics.py",
        "cell_key": metrics.get("cell_key"),
        "round": metrics.get("round"),
        "round_dir": _rel_to(root, rdir),
        "metrics": _rel_to(root, rdir / "metrics.json"),
        "sources": {
            "scheme": scheme_rel,
            "criterion": crit_rel,
            "baseline": _rel_to(root, baseline_path) if baseline_path else None,
        },
        "artifacts": files,
    }
    out = rdir / "artifacts.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _summarize(round_id: str, out_path: Path, m: dict, incomplete: list) -> str:
    t = m["training"]
    e = m["eval"]

    def side(s):
        if s is None:
            return "null"
        return f"{s['metrics']} n={s['n']}"

    lines = [
        f"抽数完成（**没有**判定）：{out_path}",
        f"  round {round_id}  方案 {m['scheme_path'] or '(未给)'}  指纹 {m['scheme_fingerprint'] or '(未给)'}",
        f"  training  points={t['points']} observation={t['observation']}"
        f"  max_adjacent_rise={t['max_adjacent_rise']}  max_rel_to_best={t['max_rel_to_best']}",
        f"  eval      reference={side(e['reference'])}",
        f"            target={side(e['target'])}  delta_vs_reference={e['delta_vs_reference']}",
    ]
    if incomplete:
        lines.append("  数还没齐（**不是判定**）：缺 " + "、".join(incomplete))
    if m["notes"]:
        lines.append(f"  留痕 {len(m['notes'])} 条，见 metrics.json 的 notes")
    return "\n".join(lines)


def run_extract(root: Path, round_id: str, scheme_path: Path = None,
                cell: str = None, baseline_path: Path = None,
                criterion_path: Path = None, task: str = None) -> tuple:
    """抽一轮的数，写 `<artifacts.root>/rounds/<轮次>/{metrics.json,artifacts.json}`。返回 (退出码, 摘要)。

    `metrics.json` = 数字；`artifacts.json` = 产物路径清单（只增输出，见 `write_artifacts_json`）。

    退出码只有两种含义：0 抽完了 / 2 参数不对（"数还没齐"也归 2）。
    **没有任何一种表示"方案行不行"。**

    名字与路径全部由 `load_names()` 从 `config/` 读（见文件头）；读不到 ⇒ 退出 2。
    """
    global NAMES
    try:
        NAMES = load_names(root, task)
    except NamesError as e:
        return 2, f"ERROR {e}"
    try:
        rdir, cell_key = _resolve_round_dir(root, round_id, cell, NAMES)
    except ValueError as e:
        return 2, f"ERROR {e}"
    ev = rdir / "evidence"
    notes: list[str] = []

    # --- 判据指纹（只记录，不读它的内容）---
    #
    # 为什么要记：基线轮与本轮的口径是否一致，是 Δ 能不能解释的前提。
    # 判据里冻结着 `eval_protocol`（max_gen_toks / prompt_type / dataset…），
    # 所以**判据指纹相同 ⇒ 口径没有变**。这样不需要在 shell 里解析 YAML，
    # 也不需要往 metrics.json 里塞一堆协议字段。
    crit_rel = None
    crit_hash = None
    baseline_ref = None
    if criterion_path is not None:
        cp = criterion_path if criterion_path.is_absolute() else (root / criterion_path)
        if cp.exists():
            crit_rel, crit_hash = scheme_fingerprint(cp, root)
            # ★ 「跟谁比」的唯一来源（文档 §11 ④）：criterion 的 `success.baseline_ref`
            #   ＝ **基线轮次 id**，可为 `null`（⇒ 本轮不比）。抽数器按它去取基线轮的指标；
            #   显式 `--baseline <路径>` 仍然优先（它给的是路径，不是轮次 id）。
            baseline_ref = _criterion_baseline_ref(cp)
        else:
            notes.append(f"判据文件不在了：{cp} —— criterion_fingerprint 记 null。")

    if baseline_path is None and baseline_ref:
        baseline_path = _baseline_path_from_ref(root, NAMES, baseline_ref)
        notes.append(
            f"基线轮由 criterion 的 success.baseline_ref 指名：{baseline_ref} ⇒ 取 "
            f"{baseline_path}（只引用基线轮的 metrics.json，不猜、不填 0）。"
        )

    # --- 方案指纹（只记录，不读它的内容，更不拿它推阈值）---
    scheme_rel = None
    scheme_hash = None
    if scheme_path is not None:
        sp = scheme_path if scheme_path.is_absolute() else (root / scheme_path)
        if not sp.exists():
            return 2, f"ERROR 方案文件不存在：{sp}"
        scheme_rel, scheme_hash = scheme_fingerprint(sp, root)

    if not ev.is_dir():
        return 2, (
            f"ERROR 证据目录不存在：{ev}\n"
            "  这一轮还没跑出任何证据 —— 数还没齐（不是判定）。"
        )

    # --- loss 轨迹 ---
    curve, ln = parse_loss_curve(ev / "loss.jsonl")
    if not curve:
        c2, ln2 = parse_loss_curve(ev / "loss.txt")
        if c2:
            curve, ln = c2, ln2
        else:
            notes.extend(ln2)
    notes.extend(ln)
    if not curve:
        notes.append("evidence/ 下既没有 loss.jsonl 也没有 loss.txt（或轨迹为空）")

    # ★ 区分「没有训练段」与「训练了但点数不足」：**看证据文件在不在**，不看配置声明。
    #   基线轮只跑 convert/eval ⇒ evidence/ 里没有 train.log/loss.*，这是预期形状。
    no_train_segment = not curve and not any(
        (ev / name).is_file() for name in ("train.log", "loss.txt", "loss.jsonl")
    )
    training = _training_section(curve, no_train_segment=no_train_segment)

    # --- 评测（两侧独立读；参考侧缺失是正常情况）---
    ref_doc, ref_notes, ref_p = _load_side(ev, "reference")
    tgt_doc, tgt_notes, tgt_p = _load_side(ev, "target")
    notes.extend(ref_notes + tgt_notes)

    reference = summarize_eval(ref_doc, f"evidence/{ref_p.name}") if (ref_doc and ref_p) else None
    target = summarize_eval(tgt_doc, f"evidence/{tgt_p.name}") if (tgt_doc and tgt_p) else None

    # 文件在、但里面没有任何聚合值 → 对下游等于没有。**不假装它存在。**
    #
    # ★ 这条提示要说清"什么样的文件才算数"，否则它是个死胡同：
    #   读到"没有任何聚合值"的人下一步唯一想知道的就是"那我该写什么格式"。
    _SHAPES_HINT = (
        "可识别的形状有三种：(1) 顶层有 `metrics` 字典；"
        "(2) 顶层有 accuracy / acc / score / exact_match / em / pass@1 / avg 之一；"
        "(3) 顶层有 `samples` 数组（会按样本均值聚合）。"
    )
    if reference is not None and not _eval_usable(reference):
        notes.append(
            f"{reference['source']} 读出来没有任何聚合值（metrics 为空）—— 记为 null。"
            f" {_SHAPES_HINT}"
        )
        reference = None
    if target is not None and not _eval_usable(target):
        notes.append(
            f"{target['source']} 读出来没有任何聚合值（metrics 为空）—— 记为 null。"
            f" {_SHAPES_HINT}"
        )
        target = None

    baseline, delta_baseline = _load_baseline(
        baseline_path, root, target, crit_hash, notes)

    delta, delta_note = aggregate_delta(reference, target)
    if delta_note:
        notes.append(delta_note)
    if reference is None:
        notes.append(
            "没有参考侧评测结果 —— reference 与 delta_vs_reference 都是 null。"
            "这是正常情况（这一轮只跑目标侧），不是错误。"
        )
    if target is None:
        notes.append("没有目标侧评测结果 —— 这一轮的评测数还没齐。")

    # ── 早停/主动停的留痕：把「这一轮是被停下来的」变成读得出来的事实 ──────
    #
    # ★ 停止轮次的数字**不得**与 300 步轮次直接比（run_job.py:743 早停时的
    #   原话）。这句话原先只活在**运行时的 stderr** 里，抽数产物里没有落点 ——
    #   于是几天后读 metrics.json 的人不知道这一轮是 80 步停的。
    #   这里只**转发事实**（有没有停 / 停在哪一步 / 为什么），一个字都不判。
    #
    # ★ 这是**新增的顶层键**，不往任何既有段里加字段 ⇒ training 段仍是契约里
    #   那 14 个，eval 段原样。没有 marker 的老轮次 ⇒ 新键为 null（= 未发生早停）。
    marker_path = _find_stop_marker(rdir, ev)
    early_stop = read_stop_marker(rdir, ev, notes, marker_path=marker_path)
    if marker_path is not None:
        try:
            marker_rel = str(marker_path.relative_to(rdir))
        except ValueError:
            marker_rel = str(marker_path)
        notes.append(
            f"★ 本轮是**停止轮次**（留痕 {marker_rel}：kind={early_stop['kind']!r}、"
            f"stopped_at_step={early_stop['stopped_at_step']!r}、"
            f"reason={early_stop['reason']!r}）—— "
            "**停止轮次的数字不得与 300 步轮次直接比**（run_job.py 早停时的原话）："
            "training 段的 last_loss / last_iter 只覆盖到停止那一步，"
            "与跑满的轮次不是同一个量尺。要对照就按同一步数截齐，或只作趋势看。"
            "★ 口径分清：**训练侧 loss／步数类量不可跨轮直比**；**下游评测结果可比**，"
            "但那说的是「各自停止点上的模型质量」，不是「同预算下的方案优劣」。"
        )

    # ── 三段净耗时（0.18.26）────────────────────────────────────────────
    #   来源是 `evidence/<段>.exec.json`，由 executor 的 `write_meta` 写、`_common.sh` 传
    #   `--meta`。**只登记机器净耗时**：角色墙钟（含等人/思考）没有落点，不许编。
    timing = load_stage_timing(ev, notes)
    quant = load_qsnr(ev, notes)
    # ── held-out racing（0.19.0）─────────────────────────────────
    #   `tv_holdout` 与在线闸门用的是**同一块任务配置**（stop_conditions.holdout）；
    #   缺项就用 metrics.py 的工程护栏，并由 thresholds_source 说明来源。
    task_name = rdir.parent.parent.name
    tv_holdout = {}
    for k in ("min_step", "max_gap_pct", "patience"):
        v = _cfg_scalar(root, f"config/tasks/{task_name}.yaml",
                        f"stop_conditions.holdout.{k}")
        if v not in (None, ""):
            tv_holdout[k] = v
    if tv_holdout:
        for k in ("min_step", "patience"):
            if k in tv_holdout:
                tv_holdout[k] = int(float(tv_holdout[k]))
        tv_holdout["max_gap_pct"] = float(tv_holdout["max_gap_pct"])
    holdout = holdout_section(ev, root, root / NAMES["paths"]["experiments"],
                              task_name, rdir, tv_holdout, notes)

    metrics = {
        "cell_key": cell_key,
        "round": round_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scheme_path": scheme_rel,
        "scheme_fingerprint": scheme_hash,
        "criterion_path": crit_rel,
        "criterion_fingerprint": crit_hash,
        "baseline_path": (baseline or {}).get("source"),
        "baseline_round": (baseline or {}).get("round"),
        "training": training,
        "eval": {
            "reference": reference,
            "baseline": baseline,
            "target": target,
            "delta_vs_reference": delta,
            "delta_vs_baseline": delta_baseline,
            # ★ 只加在 eval 段内（顶层键一个不动 ⇒ [13] 形状契约不受影响）
            "comparisons": _comparisons(
                target, reference, baseline, delta_baseline, root, cell_key, notes,
                baseline_ref=baseline_ref),
            "arms": _collect_arms(ev, notes),
        },
        # ★ 新增的**顶层**键（唯一一处形状变化）：早停/主动停的留痕。
        #   null = 没有留痕 = 这一轮没发生早停（老轮次全是这样）。
        "early_stop": early_stop,
        # ★ 新增的**顶层**键（与 early_stop 同一类：只登记事实，不判定）。
        #   status ∈ measured/unmeasured/probe_invalid —— 「没测」与「达标」必须分得开。
        "quant_error": quant,
        # ★ 0.19.0：held-out racing 段（验证曲线 ＋ 参照轮 ＋ 判据留痕）。
        "holdout": holdout,
        # ★ 新增顶层键：三段净耗时。`engine_total_s` = 三段之和（dry-run 的不计入）。
        "timing": timing,
        "notes": notes,
    }

    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    # ★ 只增一份输出：`artifacts.json` = 产物路径清单。写在 `metrics.json` **之后**，
    #   这样清单里能列到 metrics.json 本身；清单里排除 artifacts.json 自身（见函数注释）。
    write_artifacts_json(root, rdir, metrics, crit_rel, scheme_rel, baseline_path)

    incomplete: list = []
    if not curve:
        incomplete.append("loss 轨迹")
    if target is None:
        incomplete.append("目标侧评测结果")
    code = 2 if incomplete else 0
    return code, _summarize(round_id, rdir / "metrics.json", metrics, incomplete)


# ---------------------------------------------------------------------------
# 五、自测
# ---------------------------------------------------------------------------

def _mk_curve(losses) -> list:
    return [(i + 1, float(v)) for i, v in enumerate(losses)]


def _converging(n=300, start=2.4, end=1.7) -> list:
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        base = start + (end - start) * t
        # 一点点确定性的抖动，制造真实的相邻跳变
        out.append(base + 0.02 * math.sin(i * 1.7))
    return out


def _real_normal_losses(n=300, start=2.4, end=1.7) -> list:
    """正常收敛 + 一次中途小尖峰，钉住工程**实测**的两个量级：

        相邻上升最大  1.2279
        相对运行最优  1.257

    构造方式：中段先探到 1.9（新的运行最优），再两步回升 —— 第二步相对
    前一步正好 1.2279 倍，相对运行最优正好 1.257 倍。之后继续下降。
    用运行最小值，所以"中途尖峰后恢复"这件事被算进了 max_rel_to_best。
    """
    out = [start + (end - start) * i / max(1, n - 1) for i in range(n)]
    k = n // 2
    dip = 1.9
    out[k] = dip
    out[k + 2] = dip * 1.257        # 相对运行最优正好 1.257
    out[k + 1] = out[k + 2] / 1.2279  # 相邻上升正好 1.2279
    for j in range(k + 3, n):
        t = (j - (k + 2)) / max(1, n - 1 - (k + 2))
        out[j] = out[k + 2] + (end - out[k + 2]) * t
    return out


def _walk_keys(obj) -> set:
    keys: set = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= _walk_keys(v)
    elif isinstance(obj, list):
        for it in obj:
            keys |= _walk_keys(it)
    return keys


#: 产物里绝不该出现的字段名 —— 它们是"判定"的词汇。
#: 这张表是给回归用的：哪天有人顺手把一个结论字段加回来，这里会先响。
BANNED_OUTPUT_KEYS = (
    "conclusion", "ci", "n_paired", "pairing_completeness",
    "criterion_hash", "noise_floor", "invalid_reason", "ok", "verdict",
)


#: 自测用的**合成**任务名与两个"尺子"名 —— 本文件不含任何真实模型名/数据集名/精度串；
#: 它们全部由 fixtures 的 `config/tasks/<任务名>.yaml` 提供（与生产路径同一条 load_names）。
SELFTEST_CELL = "st-cell"
SELFTEST_METRICS = ("st_m1", "st_m2")


def _selftest_timing_fixture() -> dict:
    """造一个只有 train/convert 的 evidence 目录（eval 缺、convert 是 dry-run）。"""
    import tempfile as _tf
    with _tf.TemporaryDirectory() as d:
        ev = Path(d)
        (ev / "train.exec.json").write_text(
            json.dumps({"duration_s": 120.5, "exit_code": 0, "dry_run": False}),
            encoding="utf-8")
        (ev / "convert.exec.json").write_text(
            json.dumps({"duration_s": 30.0, "exit_code": 0, "dry_run": True}),
            encoding="utf-8")
        return load_stage_timing(ev, [])


def selftest() -> int:
    print("=" * 70)
    print("metrics.py --selftest（只测抽数；本文件里没有判定可测）")
    print("=" * 70)

    passed = 0
    total = 0

    def case(label, ok, detail=""):
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
            print(f"  ok    {label}")
        else:
            print(f"  FAIL  {label}   {detail}")

    tmp = Path(tempfile.mkdtemp(prefix="metrics-selftest-"))
    # 与 `--task` 等价：自测里所有 run_extract 都按这个名字解析 config/
    os.environ["LP_TASK"] = SELFTEST_CELL

    def w(rel, text):
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # --- 1 loss 行解析（科学计数法）---
    print("\n[1] loss 文本行解析（Megatron 风格，含科学计数法）")
    p = w("loss_sci.txt",
          " iteration       50/     300 | consumed samples: 12800 | lm loss: 1.234E+00 |\n"
          " iteration      100/     300 | lm loss: 1.0E+00 |\n"
          " iteration      150/     300 | lm loss: 2.5e-01 |\n")
    curve1, notes1 = parse_loss_curve(p)
    print(f"        {curve1}")
    case("文本行抓到 3 个点", len(curve1) == 3, repr(curve1))
    case("科学计数法解析正确（1.234 / 1.0 / 0.25）",
         [v for _, v in curve1] == [1.234, 1.0, 0.25], repr(curve1))
    case("iter 解析正确 (50/100/150)",
         [i for i, _ in curve1] == [50, 100, 150], repr(curve1))

    # --- 1b ★ 正文里的 nan / inf 也必须抓到 ---
    #
    # 这条是被前身项目对照出来的一个**判断错误**：先前注释说"非有限值来自
    # 框架写出的结构化行，不是正文里的字"，于是 LOSS_RE 只认数字。
    # 但本工程真实框架写的是**文本日志**（train.log），loss.jsonl 只有谁主动
    # 写它时才存在 —— 文本是主路径。放宽前 `lm loss: nan` 完全落在雷达外，
    # 而"尽早发现 NaN"恰恰是在线早停的全部价值。
    print("\n[1b] 正文里的 lm loss: nan / inf（先前的漏网）")
    p = w("loss_text_nan.txt",
          " iteration 1/300 | lm loss: 2.0E+00 |\n"
          " iteration 2/300 | lm loss: nan |\n"
          " iteration 3/300 | lm loss: inf |\n"
          " iteration 4/300 | lm loss: -Infinity |\n"
          " iteration 5/300 | lm loss: 1.5E+00 |\n")
    curv_nan, _ = parse_loss_curve(p)
    print(f"        {curv_nan}")
    case("正文里的 nan/inf 全部读进来（5 个点）", len(curv_nan) == 5, repr(curv_nan))
    case("iter 2/3/4 是非有限值（nan / +inf / -inf）",
         [i for i, v in curv_nan if not math.isfinite(v)] == [2, 3, 4], repr(curv_nan))
    case("nan 的符号无意义但仍是非有限",
         math.isnan(curv_nan[1][1]), repr(curv_nan[1]))
    case("+inf / -inf 符号正确",
         curv_nan[2][1] == float("inf") and curv_nan[3][1] == float("-inf"),
         repr([curv_nan[2], curv_nan[3]]))
    # 反面：只有出现 `loss` 这个词才算 —— 全文本找 nan 会误伤
    #（前身项目记的坑：配置里本来就有 inf 这个词）
    p = w("loss_fake_nan.txt",
          " iteration 1/300 | lm loss: 2.0E+00 |\n"
          " iteration 2/300 | config: use_infinite_attention=false, nan_guard=on |\n")
    curv_fake, _ = parse_loss_curve(p)
    case("不含 loss 关键字的行不会被误抓（只有 1 个点）",
         len(curv_fake) == 1, repr(curv_fake))

    # --- 2 jsonl 里的 NaN / inf ---
    print("\n[2] jsonl 里的 NaN / Infinity / 字符串 nan / -inf")
    p = w("loss_bad.jsonl",
          '{"iter":1,"loss":2.0}\n'
          '{"iter":2,"loss":NaN}\n'
          '{"iter":3,"loss":Infinity}\n'
          '{"iter":4,"loss":"nan"}\n'
          '{"iter":5,"loss":"-inf"}\n')
    curve2, _ = parse_loss_curve(p)
    print(f"        {curve2}")
    case("5 行全部读进来（含非有限值）", len(curve2) == 5, repr(curve2))
    case("NaN/Inf 没有被当成解析失败丢掉",
         all(not math.isfinite(v) for _, v in curve2[1:]), repr(curve2))

    # --- 3 同 iter 去重 ---
    print("\n[3] 同 iter 重复（重试/续跑）→ 保留先出现者")
    p = w("loss_dup.txt", "iter 10 loss 1.0\niter 10 loss 9.0\niter 11 loss 0.5\n")
    curve3, notes3 = parse_loss_curve(p)
    print(f"        {curve3}   notes={notes3}")
    case("同 iter 保留先出现的值", curve3 == [(10, 1.0), (11, 0.5)], repr(curve3))
    case("重复被丢了这件事留在 notes 里", any("重复" in x for x in notes3), repr(notes3))

    # --- 4 非有限值定位 ---
    print("\n[4] 非有限值定位 → 观察（不是判定）")
    obs = training_observation(curve2)
    print(f"        nonfinite_iters={obs['nonfinite_iters']}  observation={obs['observation']}")
    case("非有限值定位到具体 iter", obs["nonfinite_iters"] == [2, 3, 4, 5],
         repr(obs["nonfinite_iters"]))
    case("非有限值 → suspected_divergence", obs["observation"] == "suspected_divergence",
         obs["observation"])
    case("观察自带 is_verdict=False（本文件不判定）", obs["is_verdict"] is False,
         repr(obs["is_verdict"]))
    case("观察理由是「这个 run 看着不对」而不是「方案不好」",
         any("非有限值" in r for r in obs["observation_reasons"]),
         repr(obs["observation_reasons"]))

    # --- 5 正常收敛（真实量级 1.2279 / 1.257）---
    print("\n[5] 正常收敛（实测量级：相邻上升 1.2279 / 相对最优 1.257）")
    obs_n = training_observation(_mk_curve(_real_normal_losses()))
    print(f"        max_jump={obs_n['max_jump_ratio']:.4f}  "
          f"max_rel={obs_n['max_rel_to_best']:.4f}  → {obs_n['observation']}")
    case("相邻上升峰值 = 实测 1.2279",
         abs((obs_n["max_jump_ratio"] or 0) - 1.2279) < 1e-9,
         repr(obs_n["max_jump_ratio"]))
    case("相对运行最优峰值 = 实测 1.257",
         abs((obs_n["max_rel_to_best"] or 0) - 1.257) < 1e-9,
         repr(obs_n["max_rel_to_best"]))
    case("正常 run 不被误伤（jump_factor=4.0 留了 3.26 倍余量）",
         obs_n["observation"] == "normal", obs_n["observation"])
    case("正常 run 的观察理由是空的", obs_n["observation_reasons"] == [],
         repr(obs_n["observation_reasons"]))

    # --- 6 发散观察（真实量级 9.0911）---
    print("\n[6] ★ 假失败回归：iter1=1.0 → iter2=9.0911（实测发散量级），随后 300 步正常")
    div = [1.0, 9.0911] + _converging(300, start=8.0, end=6.5)
    obs_d = training_observation(_mk_curve(div))
    print(f"        max_jump={obs_d['max_jump_ratio']:.4f} @iter {obs_d['max_jump_at_iter']}  "
          f"early_stop={obs_d['early_stop_would_have_fired']} @iter {obs_d['early_stop_iter']}")
    case("抓到了实测发散步的 9.0911 倍跳变",
         abs((obs_d["max_jump_ratio"] or 0) - 9.0911) < 1e-6,
         repr(obs_d["max_jump_ratio"]))
    case("→ suspected_divergence", obs_d["observation"] == "suspected_divergence",
         obs_d["observation"])
    case("全是有限值（证明不是靠 NaN/Inf 抓的）", obs_d["nonfinite_count"] == 0,
         repr(obs_d["nonfinite_count"]))
    case("在线早停会在第 2 个点触发（这一条省下 46 分钟白跑）",
         obs_d["early_stop_would_have_fired"] and obs_d["early_stop_iter"] == 2,
         f"{obs_d['early_stop_would_have_fired']} @ {obs_d['early_stop_iter']}")

    # --- 7 点数不足 ---
    print("\n[7] 点数不足 → insufficient_points（不是「正常」，也不是「发散」）")
    obs_s = training_observation(_mk_curve([1.0, 0.99, 1.0, 0.99, 1.0]))
    obs_empty = training_observation([])
    obs_sd = training_observation(_mk_curve([1.0, 1.0, 5.0, 4.0, 4.0]))
    case("5 个点、完全平稳 → insufficient_points",
         obs_s["observation"] == "insufficient_points", obs_s["observation"])
    case("空轨迹 → insufficient_points",
         obs_empty["observation"] == "insufficient_points", obs_empty["observation"])
    case("短轨迹但早停命中 → 仍算 suspected_divergence（短是早停的结果）",
         obs_sd["observation"] == "suspected_divergence"
         and obs_sd["early_stop_would_have_fired"],
         f"{obs_sd['observation']} / {obs_sd['early_stop_would_have_fired']}")
    # ★ 0.18.14：没有训练段的轮次（基线轮）不能记成"点数不足"
    _no_train = _training_section([], no_train_segment=True)
    case("无训练段 → observation=not_applicable（不是 insufficient_points）",
         _no_train["observation"] == "not_applicable"
         and _no_train["points"] == 0,
         repr(_no_train["observation"]))
    case("无训练段时键仍是那 14 个（契约不变）",
         set(_no_train.keys()) == set(TRAINING_KEYS), repr(sorted(_no_train.keys())))

    # --- 8 eval 解析：json ---
    print("\n[8] eval 解析：标准 json（逐题 samples）")
    p = w("ev.json", json.dumps({
        "metric": "st_m1_accuracy", "full_eval": True,
        "samples": [{"id": f"q{i}", "correct": i % 2 == 0} for i in range(100)],
    }))
    doc, _ = load_eval_any(p)
    s = summarize_eval(doc, "evidence/ev.json")
    print(f"        {s}")
    case("逐题 samples 聚合成一个值（50/100 = 0.5）",
         s["metrics"].get("st_m1") == 0.5, repr(s))
    case("n = 样本数", s["n"] == 100, repr(s["n"]))
    case("指标名去掉口径后缀（st_m1_accuracy → st_m1）",
         list(s["metrics"]) == ["st_m1"], repr(s["metrics"]))

    # --- 9 eval 解析：jsonl ---
    print("\n[9] eval 解析：jsonl（元信息行 + 逐行样本）")
    lines = ['{"metric":"st_m1_accuracy"}']
    lines += [json.dumps({"id": f"z{i}", "score": 1.0 if i < 30 else 0.0})
              for i in range(100)]
    p = w("ev.jsonl", "\n".join(lines) + "\n")
    doc, _ = load_eval_any(p)
    s = summarize_eval(doc, "evidence/ev.jsonl")
    print(f"        {s}")
    case("jsonl 逐行样本聚合（30/100 = 0.3）",
         abs(s["metrics"].get("st_m1", -1) - 0.3) < 1e-12, repr(s))
    case("jsonl 的元信息行也被读进来（n=100）", s["n"] == 100, repr(s["n"]))

    # --- 10 eval 解析：简单文本 ---
    print("\n[10] eval 解析：一行一个键值的简单文本")
    p = w("ev.txt", "st_m1: 0.4716\nn: 1319\n")
    doc, _ = load_eval_any(p)
    s = summarize_eval(doc, "evidence/ev.txt")
    print(f"        {s}")
    case("简单文本解析出指标值", s["metrics"] == {"st_m1": 0.4716}, repr(s))
    case("简单文本解析出样本数", s["n"] == 1319, repr(s["n"]))

    # --- 11 聚合 delta ---
    print("\n[11] delta_vs_reference：两个聚合值简单相减")
    ref = summarize_eval({"metrics": {"st_m1": 0.5}}, "evidence/eval_reference.json")
    tgt = summarize_eval({"metrics": {"st_m1": 0.4716}}, "evidence/eval_target.json")
    d, dnote = aggregate_delta(ref, tgt)
    print(f"        Δ = {d}")
    case("Δ = target − reference = 0.4716 − 0.5", abs(d - (-0.0284)) < 1e-12, repr(d))
    case("同名指标相减不需要额外留痕", dnote is None, repr(dnote))
    case("这里没有配对字段（交集/CI/重合率一概没有）",
         set(ref) == {"metrics", "n", "source"} and set(tgt) == {"metrics", "n", "source"},
         repr((ref, tgt)))

    # --- 12 端到端：reference 缺失 → null，退出码 0 ---
    print("\n[12] 端到端：只有目标侧 + loss 轨迹（**没有** reference）")
    root = tmp / "proj"
    # ★ 夹具里的名字全部是**合成名**：本文件不含任何真实模型名/数据集名/精度串。
    #   生产路径与自测路径共用同一条 load_names()。
    (root / "config" / "tasks").mkdir(parents=True, exist_ok=True)
    (root / "config" / "tasks" / f"{SELFTEST_CELL}.yaml").write_text(
        "schema: 1\n"
        f'task_id: "{SELFTEST_CELL}"\n'
        "model:\n  name: \"<模型名>\"\n  precision: \"<精度>\"\n"
        "eval:\n"
        f"  metrics: [{', '.join(SELFTEST_METRICS)}]\n"
        "artifacts:\n  root: \"default\"\n",
        encoding="utf-8")
    rdir = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0001"
    ev = rdir / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "loss.jsonl").write_text(
        "\n".join(json.dumps({"iter": i + 1, "loss": 2.4 - 0.7 * i / 299})
                  for i in range(300)) + "\n", encoding="utf-8")
    (ev / "eval_target.json").write_text(json.dumps({
        "metric": "st_m1_accuracy", "full_eval": True,
        "samples": [{"id": f"q{i}", "correct": i % 2 == 0} for i in range(100)],
    }), encoding="utf-8")

    code, text = run_extract(root, "R-0001")
    m = json.loads((rdir / "metrics.json").read_text(encoding="utf-8"))
    print(f"        exit={code}  reference={m['eval']['reference']}  "
          f"delta={m['eval']['delta_vs_reference']}")
    case("reference 缺失 → 退出码 0（正常情况，不是错误）", code == 0,
         f"code={code}\n{text}")
    case("reference 缺失 → reference 与 delta_vs_reference 都是 null",
         m["eval"]["reference"] is None and m["eval"]["delta_vs_reference"] is None,
         repr(m["eval"]))
    case("目标侧抽出了聚合值（0.5，n=100）",
         m["eval"]["target"] and m["eval"]["target"]["metrics"] == {"st_m1": 0.5}
         and m["eval"]["target"]["n"] == 100, repr(m["eval"]["target"]))
    case("source 记成相对轮次目录的路径",
         m["eval"]["target"]["source"] == "evidence/eval_target.json",
         repr(m["eval"]["target"]["source"]))
    case("训练段点数=300 / first_iter=1 / last_iter=300",
         (m["training"]["points"], m["training"]["first_iter"],
          m["training"]["last_iter"]) == (300, 1, 300), repr(m["training"]))
    case("训练段 observation=normal", m["training"]["observation"] == "normal",
         repr(m["training"]["observation"]))
    # ★ 四个阈值都必须在场。只记 jump_factor 的话，后来者看到
    #   observation=suspected_divergence 无法复算当时的标准。
    case("thresholds_used 记下实际用的全部四个阈值",
         m["training"]["thresholds_used"] == {
             "jump_factor": 4.0, "rel_to_best": 2.5,
             "min_points": 10, "early_min_points": 2,
         },
         repr(m["training"]["thresholds_used"]))
    case("training.is_verdict = False", m["training"]["is_verdict"] is False,
         repr(m["training"]["is_verdict"]))
    case("没有写 verdict.yaml（判定不在这里）",
         not (rdir / "verdict.yaml").exists(),
         str(rdir / "verdict.yaml"))

    # --- 13 形状契约 ---
    print("\n[13] metrics.json 形状契约（下游 agent 与测试依赖）")
    case("顶层键与契约一致", set(m.keys()) == set(NOTE_TOP_KEYS),
         repr(sorted(m.keys())))
    case("training 段键与契约一致", set(m["training"].keys()) == set(TRAINING_KEYS),
         repr(sorted(m["training"].keys())))
    case("eval 段键与契约一致",
         set(m["eval"].keys()) == {"reference", "baseline", "target",
                                   "comparisons", "arms",
                                   "delta_vs_reference", "delta_vs_baseline"},
         repr(sorted(m["eval"].keys())))
    # ★ 0.15.0：「跟谁比」**只有一个**节点（原来有两个：自造的跨轮锚点块已删）。
    #   没有基线轮 ⇒ 该节点是 `{"vs_baseline": null}` 一个键、值为 null。
    case("★ comparisons 只有一个「跟谁比」节点（两个已合成一个）",
         list(m["eval"]["comparisons"].keys()) == ["vs_baseline"],
         repr(list(m["eval"]["comparisons"].keys())))
    # ── [13b] timing（0.18.26）：只登记机器净耗时，dry-run 不计入 ──
    print("\n[13b] timing 段：读 <段>.exec.json，dry-run 不计入总数")
    _t = _selftest_timing_fixture()
    case("三段耗时都读出来", _t["stages"]["train"]["duration_s"] == 120.5
         and _t["stages"]["convert"]["duration_s"] == 30.0, repr(_t["stages"]))
    case("dry-run 段的耗时**不计入** engine_total_s（只算 train 的 120.5）",
         _t["engine_total_s"] == 120.5, repr(_t["engine_total_s"]))
    case("缺的段记 null，不填 0", _t["stages"]["eval"] is None, repr(_t["stages"]["eval"]))
    case("★ 没有基线轮 ⇒ 该节点的值是 null（不是 {}／不是 0）",
         m["eval"]["comparisons"]["vs_baseline"] is None,
         repr(m["eval"]["comparisons"]))
    case("generated_at 是 UTC ...Z 形状",
         re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
                      m["generated_at"]) is not None, repr(m["generated_at"]))
    case("产物里没有任何判定词汇的字段",
         not (_walk_keys(m) & set(BANNED_OUTPUT_KEYS)),
         repr(sorted(_walk_keys(m) & set(BANNED_OUTPUT_KEYS))))
    # ★ 新增的**顶层**键 early_stop：没有 marker 的老轮次 ⇒ 三个子键全 None。
    case("early_stop 顶层键形状正确（无 marker ⇒ 全 null）",
         m.get("early_stop") == {"kind": None, "stopped_at_step": None,
                                 "reason": None},
         repr(m.get("early_stop")))
    case("early_stop 在顶层键契约表里", "early_stop" in NOTE_TOP_KEYS)
    case("无 marker ⇒ notes 里不提早停（一个字符都不加）",
         not any("停止轮次" in n for n in m["notes"]),
         repr([n for n in m["notes"] if "停止" in n]))

    # --- 14 scheme 指纹 ---
    print("\n[14] --scheme：只记录路径与指纹")
    sp = w("proj/schemes/R-0001/s.yaml", "schema: 1\nid: demo\n")
    want = hashlib.sha256(sp.read_bytes()).hexdigest()[:16]
    code, _ = run_extract(root, "R-0001", scheme_path=sp)
    m2 = json.loads((rdir / "metrics.json").read_text(encoding="utf-8"))
    print(f"        scheme_path={m2['scheme_path']}  fingerprint={m2['scheme_fingerprint']}")
    case("scheme_fingerprint = 方案文件 sha256 前 16 位",
         m2["scheme_fingerprint"] == want, repr(m2["scheme_fingerprint"]))
    case("scheme_path 记成相对工程根的路径",
         m2["scheme_path"] == "schemes/R-0001/s.yaml", repr(m2["scheme_path"]))
    case("--scheme 指到不存在的文件 → 退出码 2",
         run_extract(root, "R-0001", scheme_path=Path("schemes/nope.yaml"))[0] == 2,
         "期望 2")

    # --- 15 数没齐 → 退出码 2（不是判定）---
    print("\n[15] 证据缺失或不完整 → 退出码 2（**不是判定**，只是数还没齐）")
    ev2 = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0002" / "evidence"
    ev2.mkdir(parents=True, exist_ok=True)
    (ev2 / "loss.jsonl").write_text('{"iter":1,"loss":2.0}\n', encoding="utf-8")
    code2, text2 = run_extract(root, "R-0002")
    case("目标侧评测缺失 → 2", code2 == 2, f"code={code2}\n{text2}")

    ev3 = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0003" / "evidence"
    ev3.mkdir(parents=True, exist_ok=True)
    (ev3 / "eval_target.json").write_text('{"metrics":{"st_m1":0.4}}', encoding="utf-8")
    code3, text3 = run_extract(root, "R-0003")
    m3 = json.loads((root / "experiments" / SELFTEST_CELL / "rounds" / "R-0003"
                     / "metrics.json").read_text(encoding="utf-8"))
    case("loss 轨迹缺失 → 2", code3 == 2, f"code={code3}\n{text3}")
    case("★ 连训练证据文件都没有 ⇒ observation=not_applicable（不是「点数不足」）",
         m3["training"]["points"] == 0
         and m3["training"]["observation"] == "not_applicable"
         and m3["training"]["first_iter"] is None, repr(m3["training"]))
    # 反面对照：**有** train.log 但解析不出点 ⇒ 仍是 insufficient_points（0.18.14 的分界线）
    (ev3 / "train.log").write_text("这不是 loss 行\n", encoding="utf-8")
    run_extract(root, "R-0003")
    m3b = json.loads((root / "experiments" / SELFTEST_CELL / "rounds" / "R-0003"
                      / "metrics.json").read_text(encoding="utf-8"))
    case("★ 有 train.log 但解析不出点 ⇒ observation=insufficient_points（证据文件定三态）",
         m3b["training"]["observation"] == "insufficient_points", repr(m3b["training"]))
    # ★ 语义，刻意锁住：
    #   「轮次目录不存在」= 你找错轮次了 → **2（配置错）**
    #   「目录在、证据不全」= 数还没跑出来 → 也是 **2**（文档集 0/1/2/5/6 里没有第 3 个码）
    #   判"数没齐"要靠 stdout 的 incomplete 清单与 metrics.json，不靠一个额外的退出码。
    case("轮次目录不存在 → 2（配置错，不是「数没齐」）",
         run_extract(root, "R-9999")[0] == 2, "期望 2")

    # --- 16 格子键 ---
    print("\n[16] 格子键：模型__精度，且**唯一命中才继续**")
    cell_m = json.loads((rdir / "metrics.json").read_text(encoding="utf-8"))
    case("产物里记下了 cell_key", cell_m.get("cell_key") == SELFTEST_CELL,
         repr(cell_m.get("cell_key")))
    case("cell_key 在顶层键表里", "cell_key" in NOTE_TOP_KEYS)
    case("--cell 指定正确 → 能抽",
         run_extract(root, "R-0003", cell=SELFTEST_CELL)[0] == 2, "期望 2（数没齐）")
    case("--cell 指定错误 → 2",
         run_extract(root, "R-0003", cell="no-such-task")[0] == 2, "期望 2")
    case("--cell 含 / → 2", run_extract(root, "R-0003", cell="a/b")[0] == 2, "期望 2")

    # 跨格子撞号：合法，但必须报错要求 --cell，不许猜
    other = root / "experiments" / "st-other" / "rounds" / "R-0003"
    (other / "evidence").mkdir(parents=True, exist_ok=True)
    code_amb, text_amb = run_extract(root, "R-0003")
    case("同 id 落在两个格子里 → 2（不猜是哪一个）", code_amb == 2, f"code={code_amb}")
    case("报错里要求用 --cell 消歧", "--cell" in text_amb, text_amb[:80])
    case("给了 --cell 就能抽", run_extract(root, "R-0003", cell=SELFTEST_CELL)[0] == 2)

    # 旧布局（扁平）→ 说清怎么挪，而不是"找不到"
    flat = root / "experiments" / "R-7777"
    (flat / "evidence").mkdir(parents=True, exist_ok=True)
    code_old, text_old = run_extract(root, "R-7777")
    case("旧布局（扁平）→ 2", code_old == 2, f"code={code_old}")
    case("报错点名「旧布局」并给出 mv 命令",
         "旧布局" in text_old and "mv " in text_old, text_old[:100])

    # --- 16 禁用开关 ---
    # --- 17 基线轮次：Δ 由两个 metrics.json 机械相减 ---
    print("\n[17] 基线是**一个轮次**：Δ = 本轮目标侧 − 基线轮次目标侧")
    #
    # 这是本文件唯一新增的"跨轮"能力。要守住两条：
    #   ① 它**只做减法**，绝不判断"这个差值算不算收益"；
    #   ② 基线不存在/读不出来时记 null，**绝不猜**。
    bcrit = root / "cfg" / "R-0001" / "criterion.yaml"
    bcrit.parent.mkdir(parents=True, exist_ok=True)
    bcrit.write_text("success:\n  metric: st_m1\n", encoding="utf-8")

    # 造一个基线轮的 metrics.json（目标侧 st_m1=0.44）
    broot = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0100"
    (broot).mkdir(parents=True, exist_ok=True)
    # 先用真实流程抽一遍，拿到它自己的判据指纹
    (broot / "evidence").mkdir(parents=True, exist_ok=True)
    (broot / "evidence" / "loss.jsonl").write_text(
        "".join(f'{{"iter":{i},"loss":{2.0 - i * 0.01}}}\n' for i in range(1, 21)),
        encoding="utf-8")
    (broot / "evidence" / "eval_target.json").write_text(
        '{"metric":"st_m1_accuracy","metrics":{"st_m1":0.44},"samples":[]}',
        encoding="utf-8")
    run_extract(root, "R-0100", cell=SELFTEST_CELL, criterion_path=bcrit)
    bmetrics = broot / "metrics.json"

    # 本轮：同一判据（口径相同），目标侧 0.47
    r2 = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0101"
    (r2 / "evidence").mkdir(parents=True, exist_ok=True)
    (r2 / "evidence" / "loss.jsonl").write_text(
        "".join(f'{{"iter":{i},"loss":{2.0 - i * 0.01}}}\n' for i in range(1, 21)),
        encoding="utf-8")
    (r2 / "evidence" / "eval_target.json").write_text(
        '{"metric":"st_m1_accuracy","metrics":{"st_m1":0.47},"samples":[]}',
        encoding="utf-8")

    code_b, _ = run_extract(root, "R-0101", cell=SELFTEST_CELL,
                            baseline_path=bmetrics, criterion_path=bcrit)
    mb = json.loads((r2 / "metrics.json").read_text(encoding="utf-8"))
    case("有基线 → 退出码 0", code_b == 0, f"code={code_b}")
    case("★ Δ 就是两个聚合值相减：0.47 − 0.44 = 0.03",
         abs((mb["eval"]["delta_vs_baseline"] or 0) - 0.03) < 1e-9,
         repr(mb["eval"]["delta_vs_baseline"]))
    case("记下了基线来自哪一轮", mb["baseline_round"] == "R-0100",
         repr(mb["baseline_round"]))
    case("基线块里照抄了它的数（不另算）",
         (mb["eval"]["baseline"] or {}).get("metrics") == {"st_m1": 0.44},
         repr(mb["eval"]["baseline"]))
    case("基线块的 source 是相对工程根的路径",
         (mb["eval"]["baseline"] or {}).get("source", "").endswith(
             f"experiments/{SELFTEST_CELL}/rounds/R-0100/metrics.json"),
         repr((mb["eval"]["baseline"] or {}).get("source")))
    case("判据指纹相同 → **不**报口径不同",
         not any("口径可能不同" in n for n in mb["notes"]),
         repr([n for n in mb["notes"] if "口径" in n]))

    # 判据变了（口径可能变）→ 必须**明说**，但不替 arbiter 判"能不能比"
    bcrit2 = root / "cfg" / "R-0101" / "criterion.yaml"
    bcrit2.parent.mkdir(parents=True, exist_ok=True)
    bcrit2.write_text("success:\n  metric: st_m1\n  eval_protocol:\n"
                      "    max_gen_toks: 512\n", encoding="utf-8")
    run_extract(root, "R-0101", cell=SELFTEST_CELL,
                baseline_path=bmetrics, criterion_path=bcrit2)
    md = json.loads((r2 / "metrics.json").read_text(encoding="utf-8"))
    case("★ 判据指纹不同 → 明说「口径可能不同」并给出重跑建议",
         any("口径可能不同" in n and "max_gen_toks" in n for n in md["notes"]),
         repr(md["notes"]))
    case("★ 但它**仍然算出** Δ —— 摆事实，不关房间",
         abs((md["eval"]["delta_vs_baseline"] or 0) - 0.03) < 1e-9,
         repr(md["eval"]["delta_vs_baseline"]))
    case("判据指纹记进了产物",
         md.get("criterion_fingerprint") and md.get("criterion_path"),
         f"{md.get('criterion_path')} / {md.get('criterion_fingerprint')}")

    # 第一轮：没有基线 —— 正常情况，不是错误
    r3 = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0102"
    (r3 / "evidence").mkdir(parents=True, exist_ok=True)
    (r3 / "evidence" / "loss.jsonl").write_text(
        "".join(f'{{"iter":{i},"loss":{2.0 - i * 0.01}}}\n' for i in range(1, 21)),
        encoding="utf-8")
    (r3 / "evidence" / "eval_target.json").write_text(
        '{"metric":"st_m1_accuracy","metrics":{"st_m1":0.5},"samples":[]}',
        encoding="utf-8")
    code_nb, _ = run_extract(root, "R-0102", cell=SELFTEST_CELL)
    mnb = json.loads((r3 / "metrics.json").read_text(encoding="utf-8"))
    case("★ 第一轮没有基线 → 退出码 0（正常，不是错误）", code_nb == 0, f"code={code_nb}")
    case("没有基线时两者都是 null",
         mnb["eval"]["baseline"] is None and mnb["eval"]["delta_vs_baseline"] is None,
         repr(mnb["eval"]))
    case("没有基线时说明「第一轮就是这样」",
         any("第一轮" in n for n in mnb["notes"]), repr(mnb["notes"]))

    # 基线文件不存在 → null，**不猜**
    code_miss, _ = run_extract(root, "R-0102", cell=SELFTEST_CELL,
                               baseline_path=root / "records" / "nope.json")
    mmiss = json.loads((r3 / "metrics.json").read_text(encoding="utf-8"))
    case("基线文件不存在 → 退出码 0，Δ 记 null（不猜）",
         code_miss == 0 and mmiss["eval"]["delta_vs_baseline"] is None,
         f"code={code_miss} delta={mmiss['eval']['delta_vs_baseline']}")
    case("并明说「基线文件不存在」",
         any("基线文件不存在" in n for n in mmiss["notes"]), repr(mmiss["notes"]))

    # ★★ 0.15.0：「跟谁比」的**唯一来源** = criterion 的 `success.baseline_ref`（基线轮次 id）。
    #    不给 `--baseline`，抽数器也要能按它自己把基线轮次的数取回来（文档 §11 ④）。
    bcrit3 = root / "cfg" / "R-0103" / "criterion.yaml"
    bcrit3.parent.mkdir(parents=True, exist_ok=True)
    bcrit3.write_text("success:\n  metric: st_m1\n  baseline_ref: R-0100\n",
                      encoding="utf-8")
    r4 = root / "experiments" / SELFTEST_CELL / "rounds" / "R-0103"
    (r4 / "evidence").mkdir(parents=True, exist_ok=True)
    (r4 / "evidence" / "loss.jsonl").write_text(
        "".join(f'{{"iter":{i},"loss":{2.0 - i * 0.01}}}\n' for i in range(1, 21)),
        encoding="utf-8")
    (r4 / "evidence" / "eval_target.json").write_text(
        '{"metric":"st_m1_accuracy","metrics":{"st_m1":0.50},"samples":[]}',
        encoding="utf-8")
    code_bref, _ = run_extract(root, "R-0103", cell=SELFTEST_CELL, criterion_path=bcrit3)
    mb3 = json.loads((r4 / "metrics.json").read_text(encoding="utf-8"))
    node = (list(mb3["eval"]["comparisons"].values()) or [None])[0]
    case("★ criterion.success.baseline_ref 自己把基线轮取回来（不给 --baseline）",
         code_bref == 0 and mb3["baseline_round"] == "R-0100",
         f"code={code_bref} baseline_round={mb3['baseline_round']!r}")
    case("★ 并据此算 Δ：0.50 − 0.44 = 0.06",
         abs((mb3["eval"]["delta_vs_baseline"] or 0) - 0.06) < 1e-9,
         repr(mb3["eval"]["delta_vs_baseline"]))
    case("★ 对照键名由它现算、中性：`vs_<基线轮次>`（源码里没有具体轮次号）",
         list(mb3["eval"]["comparisons"].keys()) == ["vs_R-0100"],
         repr(list(mb3["eval"]["comparisons"].keys())))
    case("对照节点里带基线轮次标识与两侧的数（基线 0.44 / Δ 0.06）",
         isinstance(node, dict) and node.get("round") == "R-0100"
         and abs(node["st_m1"]["baseline"] - 0.44) < 1e-9
         and abs(node["st_m1"]["delta"] - 0.06) < 1e-9,
         repr(node))
    case("★ baseline_ref 为 null ⇒ 对照节点记 null ＋ 一句理由（不是错误）",
         mnb["eval"]["comparisons"] == {"vs_baseline": None}
         and any("baseline_ref 为 null" in n for n in mnb["notes"]),
         f"{mnb['eval']['comparisons']!r} / "
         f"{[n for n in mnb['notes'] if 'baseline_ref' in n]!r}")
    # 反向：`baseline_ref` 指名了一轮、但那一轮的档不在 ⇒ 记 null ＋ 说清路径（不猜、不填 0）
    bcrit4 = root / "cfg" / "R-0104" / "criterion.yaml"
    bcrit4.parent.mkdir(parents=True, exist_ok=True)
    bcrit4.write_text("success:\n  metric: st_m1\n  baseline_ref: R-0199\n",
                      encoding="utf-8")
    code_bmiss, _ = run_extract(root, "R-0103", cell=SELFTEST_CELL, criterion_path=bcrit4)
    mb4 = json.loads((r4 / "metrics.json").read_text(encoding="utf-8"))
    case("★ baseline_ref 指名的轮次档不在 ⇒ 退出码 0、Δ 记 null（不猜、不填 0）",
         code_bmiss == 0 and mb4["eval"]["delta_vs_baseline"] is None,
         f"code={code_bmiss} delta={mb4['eval']['delta_vs_baseline']}")
    case("★ 键名仍跟着它指名的轮次走（`vs_R-0199`），并说清「基线文件不存在」",
         list(mb4["eval"]["comparisons"].keys()) == ["vs_R-0199"]
         and any("基线文件不存在" in n for n in mb4["notes"]),
         f"{list(mb4['eval']['comparisons'].keys())!r} / "
         f"{[n for n in mb4['notes'] if '基线' in n]!r}")

    print("\n[16] 禁用开关：本文件没有任何参数能指定结论")
    import contextlib
    import io
    gone = []
    for bad in FORBIDDEN_FLAGS:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = main([bad, "--round", "R-0001", "--root", str(root)])
        err = buf.getvalue()
        if rc != 2 or "判定不由本文件做" not in err:
            gone.append((bad, rc, err.strip()[:60]))
    case("8 个禁用开关全部退出 2，且文案说明「判定不由本文件做」",
         not gone, repr(gone))

    # ── 负向对照 F：解析器本身的方向性 ──────────────────────────────
    #
    # ★ 这一段是补的伤疤，不是补的功能。第一版 `_yaml_flat_value` 把 `prefix`
    #   当成"同一缩进层上的几个键"，于是 `eval`（缩进 0）跑去缩进 2 上找 ⇒
    #   **一个字段都读不出来 ⇒ 静默当成"没配置"**，且**不报错**。
    #   这里把解析器本身钉死，免得下一个人从别处改坏它。
    y_ok = (
        "eval:\n"
        "  engine: lm_eval\n"
        "  protocol: null\n"
        "  note: >\n"
        "     正文里写着 task_type: generation 这几个字\n"
        "  task_type: generation   # 生成式评测\n"
    )
    case("负向F 路径语义：eval 在缩进 0、子键在缩进 2 —— 取得到子键",
         _yaml_flat_value(y_ok.splitlines(),
                          ("eval", "task_type")) == ("generation", True),
         repr(_yaml_flat_value(y_ok.splitlines(), ("eval", "task_type"))))
    case("负向F 折叠块（note: >）正文里的同名文字**不许**被读成字段",
         _yaml_flat_value(
             "eval:\n  note: >\n     写着 task_type: generation 这几个字\n"
             "  engine: lm_eval\n".splitlines(),
             ("eval", "task_type")) == (None, False),
         "折叠块误读")
    case("负向F 整个文件缩进一层（键不在缩进 0）⇒ 读不出来（保守方向）",
         _yaml_flat_value(
             "  eval:\n    task_type: generation\n".splitlines(),
             ("eval", "task_type")) == (None, False),
         "缩进整体偏移")
    case("负向F 两个顶层 eval 中只有第二个带该字段 ⇒ 必须继续找"
         "（早退会让它读不出来）",
         _yaml_flat_value(
             "eval:\n  engine: lm_eval\neval:\n"
             "  task_type: generation\n".splitlines(),
             ("eval", "task_type")) == ("generation", True),
         "同键多段")
    case("负向F 显式 null ⇒ (None, True)，即「找到了但它是空」——"
         "与「根本没这个字段」区分得开",
         _yaml_flat_value("eval:\n  task_type: null\n".splitlines(),
                          ("eval", "task_type")) == (None, True),
         "null 与缺失混同")

    # --- 19 早停/主动停留痕（run_job.write_marker 写的 key=value 文本）---
    print("\n[19] 早停/主动停留痕 → 顶层键 early_stop（只转发事实，不判定）")

    def _mk_marker_round(rid, marker_text, rel="evidence/early_stop.triggered"):
        d = root / "experiments" / SELFTEST_CELL / "rounds" / rid
        e = d / "evidence"
        e.mkdir(parents=True, exist_ok=True)
        (e / "loss.jsonl").write_text(
            "\n".join(json.dumps({"iter": i + 1, "loss": 2.0 - 0.001 * i})
                      for i in range(80)) + "\n", encoding="utf-8")
        (e / "eval_target.json").write_text(
            '{"metrics": {"st_m1": 0.42}}', encoding="utf-8")
        if marker_text is not None:
            mp = d / rel
            mp.parent.mkdir(parents=True, exist_ok=True)
            mp.write_text(marker_text, encoding="utf-8")
        return d

    # ① converged（主动停：合法结果，不是实验作废）
    _mk_marker_round("R-STOP-CONV", (
        "主动停止（**合法结果**，不是实验作废）\n"
        "reason: 提前收敛：连续 10 步无改善且 qsnr 未掉\n"
        "stop_kind: converged\n"
        "stopped_at_step: 80\n"
        "stage: train\n"
        "round: R-STOP-CONV\n"
        "observation=converged\n"
        "is_verdict=False\n"
        "thresholds:\n"
        "  jump_factor=4.0\n"
        "  rel_to_best=2.5\n"))
    c_stop, _ = run_extract(root, "R-STOP-CONV")
    m_stop = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                         / "R-STOP-CONV" / "metrics.json").read_text(encoding="utf-8"))
    print(f"        [19] converged → early_stop={m_stop['early_stop']!r}")
    case("converged marker ⇒ early_stop.kind=converged / stopped_at_step=80",
         m_stop["early_stop"]["kind"] == "converged"
         and m_stop["early_stop"]["stopped_at_step"] == 80,
         repr(m_stop["early_stop"]))
    case("converged marker ⇒ reason 原样读出（不是 null）",
         m_stop["early_stop"]["reason"] == "提前收敛：连续 10 步无改善且 qsnr 未掉",
         repr(m_stop["early_stop"]["reason"]))
    case("有 marker ⇒ notes 里出现「停止轮次不得与 300 步轮次直接比」",
         any("不得与 300 步轮次直接比" in n for n in m_stop["notes"]),
         repr([n for n in m_stop["notes"] if "停止轮次" in n]))
    case("有 marker ⇒ 停止轮次口径说明里带上 kind 与步号",
         any("kind='converged'" in n and "stopped_at_step=80" in n
             for n in m_stop["notes"]),
         repr([n for n in m_stop["notes"] if "kind=" in n]))
    case("early_stop 新键不往既有段里塞字段"
         "（training 仍是契约里那 14 个）",
         set(m_stop["training"].keys()) == set(TRAINING_KEYS),
         repr(sorted(m_stop["training"].keys())))

    # ② invalid（在线早停触发 = 观察，不是判定）
    _mk_marker_round("R-STOP-INVALID", (
        "在线早停触发（**观察**，不是判定）\n"
        "reason: 相邻上升 9.09x 超过阈值\n"
        "stop_kind: invalid\n"
        "stopped_at_step: 2\n"
        "is_verdict=False\n"))
    run_extract(root, "R-STOP-INVALID")
    m_inv = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                        / "R-STOP-INVALID" / "metrics.json").read_text(encoding="utf-8"))
    print(f"        [19] invalid → early_stop={m_inv['early_stop']!r}")
    case("invalid marker ⇒ early_stop.kind=invalid / 步号=2",
         m_inv["early_stop"]["kind"] == "invalid"
         and m_inv["early_stop"]["stopped_at_step"] == 2,
         repr(m_inv["early_stop"]))

    # ③ 兜底：marker 名字换了，但文件里仍有 stop_kind: 行 ⇒ 仍读得到
    _mk_marker_round("R-STOP-FALLBACK", (
        "在线早停触发（**观察**，不是判定）\n"
        "stop_kind: invalid\n"
        "stopped_at_step: 3\n"),
        rel="evidence/some_other_marker.txt")
    run_extract(root, "R-STOP-FALLBACK")
    m_fb = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-STOP-FALLBACK" / "metrics.json").read_text(encoding="utf-8"))
    case("兜底：非约定文件名但含 stop_kind: 行 ⇒ 仍读出 kind=invalid / 步号=3",
         m_fb["early_stop"]["kind"] == "invalid"
         and m_fb["early_stop"]["stopped_at_step"] == 3,
         repr(m_fb["early_stop"]))

    # ④ 坏留痕：文件在但形状不对 ⇒ 不静默（notes 留痕，键记 null）
    _mk_marker_round("R-STOP-BROKEN", "这不是留痕，随便写点东西\n")
    run_extract(root, "R-STOP-BROKEN")
    m_bk = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-STOP-BROKEN" / "metrics.json").read_text(encoding="utf-8"))
    print(f"        [19] broken → early_stop={m_bk['early_stop']!r}")
    case("坏留痕（有 marker 文件但没有 stop_kind: 行）⇒ kind=null 且 notes 出声",
         m_bk["early_stop"]["kind"] is None
         and any("没有 `stop_kind:` 行" in n for n in m_bk["notes"]),
         repr((m_bk["early_stop"], m_bk["notes"])))

    # ⑤ 无 marker：early_stop 全 null 且 notes 里一个字都不提
    _mk_marker_round("R-STOP-NONE", None)
    run_extract(root, "R-STOP-NONE")
    m_no = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-STOP-NONE" / "metrics.json").read_text(encoding="utf-8"))
    case("无 marker ⇒ early_stop 全 null 且 notes 里一个字符都不加",
         m_no["early_stop"] == {"kind": None, "stopped_at_step": None,
                                "reason": None}
         and not any("停止轮次" in n or "early_stop 留痕" in n for n in m_no["notes"]),
         repr((m_no["early_stop"], [n for n in m_no["notes"] if "停" in n])))

    # ⑥ 纯函数层：文件不存在 ⇒ 全 None，且不写 notes
    empty_notes: list = []
    got = read_stop_marker(tmp / "nope", tmp / "nope" / "evidence", empty_notes)
    case("read_stop_marker：文件不存在 ⇒ 三个键全 None 且 notes 为空",
         got == {"kind": None, "stopped_at_step": None, "reason": None}
         and empty_notes == [],
         repr((got, empty_notes)))

    # --- 20 在线量化误差（QSNR 探针）的留痕 ---
    print("\n[20] quant_error：只登记探针留下的数，三种状态分得开")
    case("换算：QSNR 26.0206 dB ≈ 相对误差 5%",
         abs(qsnr_db_to_rel_err(26.0206) - 0.05) < 1e-4,
         repr(qsnr_db_to_rel_err(26.0206)))
    case("换算：20 dB ⇒ 10%、40 dB ⇒ 1%（单调，且不是线性）",
         abs(qsnr_db_to_rel_err(20) - 0.1) < 1e-9
         and abs(qsnr_db_to_rel_err(40) - 0.01) < 1e-9)
    case("换算：None 原样返回 None（不是 0、不是 1）",
         qsnr_db_to_rel_err(None) is None)

    # ① 没开探针（最常见）⇒ unmeasured，且 notes 说明为什么没数
    _mk_marker_round("R-QSNR-NONE", None)
    run_extract(root, "R-QSNR-NONE")
    m_q0 = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-QSNR-NONE" / "metrics.json").read_text(encoding="utf-8"))
    case("无 eval_clamp_qsnr.json ⇒ quant_error.status=unmeasured（**不是**达标）",
         m_q0["quant_error"]["status"] == "unmeasured"
         and m_q0["quant_error"]["n_points"] == 0,
         repr(m_q0["quant_error"]))
    case("unmeasured ⇒ notes 里说清「没有量化误差数据」及打开方式",
         any("没有**量化误差数据" in n or "没有" in n and "量化误差" in n
             for n in m_q0["notes"]),
         repr([n for n in m_q0["notes"] if "量化误差" in n]))

    # ② 正常采样 ⇒ measured，且 min/last 与换算都在
    d_q = _mk_marker_round("R-QSNR-OK", None)
    (d_q / "evidence" / QSNR_FILE).write_text(json.dumps({
        "probe_enabled": True, "installed": True, "probe_invalid": False,
        "sampled_at_steps": [1, 10], "qat_qsnr_every": 50, "tripped": None,
        "samples": [
            {"step": 1, "aggregate_db": 30.0, "n_layers": 144,
             "n_activation_recorded": 144,
             "weight": {"aggregate_db": 31.0}, "activation": {"aggregate_db": 29.0}},
            {"step": 10, "aggregate_db": 26.0206, "n_layers": 144,
             "n_activation_recorded": 144,
             "weight": {"aggregate_db": 27.0}, "activation": {"aggregate_db": 25.5}},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    run_extract(root, "R-QSNR-OK")
    m_q1 = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-QSNR-OK" / "metrics.json").read_text(encoding="utf-8"))
    q1 = m_q1["quant_error"]
    case("有 2 个采样点 ⇒ measured 且 series 两条（含 weight/activation 两路）",
         q1["status"] == "measured" and q1["n_points"] == 2
         and q1["series"][0]["weight_db"] == 31.0
         and q1["series"][1]["activation_db"] == 25.5,
         repr(q1["series"]))
    case("min_db 取最小（最差）那个，不是最后一个",
         q1["min_db"] == 26.0206 and q1["last_db"] == 26.0206
         and abs(q1["min_rel_err"] - 0.05) < 1e-4,
         repr((q1["min_db"], q1["last_db"], q1["min_rel_err"])))
    case("★ 只登记数：quant_error 里没有任何 pass/fail 字样",
         not any(k for k in q1 if "pass" in k.lower() or "verdict" in k.lower()),
         repr(sorted(q1)))
    case("quant_error 在顶层键契约表里", "quant_error" in NOTE_TOP_KEYS)

    # ③ 探针自证失败 ⇒ probe_invalid（训练继续，但序列不可用）
    d_bad = _mk_marker_round("R-QSNR-INVALID", None)
    (d_bad / "evidence" / QSNR_FILE).write_text(json.dumps({
        "probe_enabled": True, "installed": False, "probe_invalid": True,
        "probe_invalid_reason": "取不到第 1 个 micro-batch 的输入", "samples": [],
    }, ensure_ascii=False), encoding="utf-8")
    run_extract(root, "R-QSNR-INVALID")
    m_q2 = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-QSNR-INVALID" / "metrics.json").read_text(encoding="utf-8"))
    case("probe_invalid ⇒ status=probe_invalid 且原样带出原因",
         m_q2["quant_error"]["status"] == "probe_invalid"
         and "micro-batch" in (m_q2["quant_error"]["reason"] or ""),
         repr(m_q2["quant_error"]))

    # ④ 文件在但不是 JSON ⇒ 不静默成「没测」，而是「不可用」
    d_corrupt = _mk_marker_round("R-QSNR-CORRUPT", None)
    (d_corrupt / "evidence" / QSNR_FILE).write_text("这不是 JSON", encoding="utf-8")
    run_extract(root, "R-QSNR-CORRUPT")
    m_q3 = json.loads((root / "experiments" / SELFTEST_CELL / "rounds"
                       / "R-QSNR-CORRUPT" / "metrics.json").read_text(encoding="utf-8"))
    case("坏文件 ⇒ probe_invalid（不静默、也不当成 unmeasured）",
         m_q3["quant_error"]["status"] == "probe_invalid"
         and any("读不出来" in n for n in m_q3["notes"]),
         repr(m_q3["quant_error"]))

    # ── [20] held-out racing（0.19.0）：位置判据 ＋ 参照轮解析 ──────────
    print("\n[20] held-out racing：落后参照轮 ⇒ 淘汰；收窄/无参照/步点不齐 ⇒ 不判")
    base = [(10, 3.0), (20, 2.9), (30, 2.8), (40, 2.7)]
    cfg = {"min_step": 10, "max_gap_pct": 0.05, "patience": 2}

    r1 = holdout_racing([(10, 3.6), (20, 3.5), (30, 3.4), (40, 3.3)], base, cfg)
    case("连续两点落后 > 5% 且不收窄 ⇒ fired",
         r1["fired"] is True and r1["latest_gap"] > 0.05, repr(r1))
    case("fired 时给出人话理由（含步号与百分比）",
         "落后" in (r1["reason"] or "") and "%" in (r1["reason"] or ""), r1["reason"])

    # 全部 > 5% 但在收窄（20% -> 15% -> 12% -> 10%）
    r2 = holdout_racing([(10, 3.6), (20, 3.335), (30, 3.136), (40, 2.97)], base, cfg)
    case("落后幅度在收窄 ⇒ 不 fired（慢热追平不许误杀）",
         r2["fired"] is False and "收窄" in (r2["reason"] or ""), r2["reason"])

    r3 = holdout_racing([(10, 2.9), (20, 2.8), (30, 2.7), (40, 2.6)], base, cfg)
    case("比参照好 ⇒ 不 fired", r3["fired"] is False, r3["reason"])

    r4 = holdout_racing([(10, 9.0), (20, 9.0)], [], cfg)
    case("没有参照曲线 ⇒ 不判并说明原因",
         r4["fired"] is False and "没有基线验证曲线" in (r4["reason"] or ""), r4["reason"])

    r5 = holdout_racing([(15, 9.0), (25, 9.0), (35, 9.0)], base, cfg)
    case("步点对不上（没有共同 step）⇒ 不判（不插值）",
         r5["fired"] is False and "同一批 step" in (r5["reason"] or ""), r5["reason"])

    r6 = holdout_racing([(10, 3.6), (20, 3.5)], base, cfg)
    case("刚好两点且都不收窄 ⇒ fired（patience=2 的边界）", r6["fired"] is True, r6["reason"])
    case("判据自身永远 is_verdict=False", r6["is_verdict"] is False)

    # 参照轮解析：records/best → round: → 该轮 metrics.json 的验证曲线
    hb = root / "records" / "best"
    hb.mkdir(parents=True, exist_ok=True)
    rec = hb / f"{SELFTEST_CELL}__acc.yaml"
    rec.write_text("cell: %s\nmetric: acc\nvalue: 0.42\nround: R-9300\n"
                   % SELFTEST_CELL, encoding="utf-8")
    rounds = root / "experiments" / SELFTEST_CELL / "rounds"
    (rounds / "R-9300").mkdir(parents=True, exist_ok=True)
    (rounds / "R-9300" / "metrics.json").write_text(json.dumps({
        "holdout": {"valid": {"curve": [[10, 3.0], [20, 2.9]]}}}), encoding="utf-8")
    bcurve, binfo = load_valid_baseline(root, root / "experiments", SELFTEST_CELL, [])
    case("records/best 的 round: 被解析成参照轮",
         binfo["round"] == "R-9300" and len(bcurve) == 2, repr(binfo))
    case("参照留痕里带曲线指纹（参照漂移要看得见）",
         str(binfo.get("fingerprint") or "").startswith("sha256:"), repr(binfo.get("fingerprint")))

    # 多份档案 ⇒ 不猜
    (hb / f"{SELFTEST_CELL}__loss.yaml").write_text("round: R-9301\n", encoding="utf-8")
    _c2, i2 = load_valid_baseline(root, root / "experiments", SELFTEST_CELL, [])
    case("多个 best 档案 ⇒ 不猜（记原因、不判）",
         _c2 == [] and "歧义" in (i2["reason"] or ""), repr(i2))

    # holdout 段落盘：本轮没有验证点 ⇒ 记 note 指明该改哪个文件
    d_ho = rounds / "R-HO-EMPTY"
    (d_ho / "evidence").mkdir(parents=True, exist_ok=True)
    (d_ho / "evidence" / "train.log").write_text(
        " iteration 1/10 | lm loss: 3.0 |\n", encoding="utf-8")
    for n in (d_ho / "evidence").glob("*"):
        pass
    notes_ho: list = []
    sec = holdout_section(d_ho / "evidence", root, root / "experiments",
                          SELFTEST_CELL, d_ho, {}, notes_ho)
    case("没有验证点 ⇒ valid.points=0 且 racing 不判",
         sec["valid"]["points"] == 0 and sec["racing"]["fired"] is False, repr(sec["racing"]))
    case("没有验证点 ⇒ 提醒去改 train_argv.txt",
         any("train_argv.txt" in n for n in notes_ho), repr(notes_ho[:2]))
    case("holdout 段永远 is_verdict=False", sec["is_verdict"] is False)

    # valid.txt 是**纯验证行**（Megatron 形状）：必须读成曲线，不能是 0 点
    d_v = rounds / "R-9302"
    (d_v / "evidence").mkdir(parents=True, exist_ok=True)
    (d_v / "evidence" / "valid.txt").write_text(
        " validation loss at iteration 10 | lm loss value: 3.60E+00 |\n"
        " validation loss at iteration 20 | lm loss value: 3.50E+00 |\n"
        " validation loss at iteration 30 | lm loss value: 3.40E+00 |\n",
        encoding="utf-8")
    sec2 = holdout_section(d_v / "evidence", root, root / "experiments",
                           SELFTEST_CELL, d_v, {}, [])
    case("evidence/valid.txt（纯验证行）读成 3 点",
         sec2["valid"]["points"] == 3, repr(sec2["valid"]["curve"]))

    # **实际生效值优先**：任务配置读不到时，靠 train.exec.json 也不许两侧各算一次
    (hb / f"{SELFTEST_CELL}__loss.yaml").unlink()   # 去掉歧义档案，参照恢复可用
    (d_v / "evidence" / "train.exec.json").write_text(json.dumps({
        "holdout": {"enabled": True, "valid_points": 3,
                    "thresholds": {"min_step": 10, "max_gap_pct": 0.05, "patience": 2}}}),
        encoding="utf-8")
    sec3 = holdout_section(d_v / "evidence", root, root / "experiments",
                           SELFTEST_CELL, d_v, {}, [])
    case("阈值来源指向 train.exec.json（两侧同一份数）",
         "train.exec.json" in str(sec3["racing"]["thresholds_source"]),
         repr(sec3["racing"]["thresholds_source"]))
    case("带着实际生效值 ⇒ 落后参照轮即 fired",
         sec3["racing"]["fired"] is True, repr(sec3["racing"]["reason"]))

    print()
    print("=" * 70)
    if passed == total:
        print(f"PASSED: {passed}/{total}")
        return 0
    print(f"FAILED: {passed}/{total}")
    return 1


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # ★ 拦截那些"看起来很合理"的开关。
    for bad in FORBIDDEN_FLAGS:
        if bad in argv or any(a.startswith(bad + "=") for a in argv):
            print(
                f"拒绝：{bad}\n"
                "这些开关永远不会存在，因为判定不由本文件做。\n"
                "本文件只把评测输出与 loss 日志变成结构化数字"
                "（<artifacts.root>/rounds/<轮次>/metrics.json）；\n"
                "PASS / FAIL / INCONCLUSIVE 由下游 arbiter 读着这些数字去判断。",
                file=sys.stderr,
            )
            return 2

    ap = argparse.ArgumentParser(
        description="把一轮实验的评测输出与 loss 日志抽成结构化数字。**不判定**。",
        epilog="本工具没有任何参数可以指定结论 —— 这是刻意设计的。",
    )
    ap.add_argument("--root", default=None,
                    help="工程根（= LP_ROOT；默认取环境变量 LP_ROOT，没有就取本文件上一级）")
    ap.add_argument("--task", help="任务名（= config/tasks/<任务名>.yaml 的文件名），"
                                   "也可用环境变量 LP_TASK；名字/路径全部由它决定")
    ap.add_argument("--round", help="轮次 id，例如 R-0001")
    ap.add_argument("--baseline",
                    help="**基线轮次**的 metrics.json 路径（不是 best/*.yaml，"
                         "也不是一个数字）。**显式路径优先**；不给时由 --criterion 的 "
                         "success.baseline_ref（基线轮次 id）自动定位。第一轮没有基线，不给即可")
    ap.add_argument("--criterion",
                    help="这一轮的判据文件路径。取两样东西：① sha256 指纹（对账口径有没有变）；"
                         "② `success.baseline_ref`（**基线轮次 id**，「跟谁比」的唯一来源；"
                         "为 null ⇒ 本轮不比）")
    ap.add_argument("--cell", help="任务名（= config/tasks/<任务名>.yaml 的文件名），"
                                   "只在跨任务撞号时给、用来消歧。"
                                   "省略时按 --round 在 <paths.experiments>/*/rounds/ 里找；"
                                   "不唯一就报错，不猜")
    ap.add_argument("--scheme", help="这一轮用到的方案 yaml（只记录路径与指纹，不读它的内容）")
    ap.add_argument("--quiet", action="store_true", help="只写文件，不打摘要")
    ap.add_argument("--selftest", action="store_true", help="在临时目录里造一组假证据做自测")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.round:
        ap.error("--round 是必需的（或者用 --selftest）")

    if args.root:
        root = Path(args.root).resolve()
    elif os.environ.get("LP_ROOT"):
        root = Path(os.environ["LP_ROOT"]).resolve()
        if not (root / "config").is_dir():
            print(f"ERROR LP_ROOT 指到一个没有 config/ 的树：{root}\n"
                  f"  ⇒ 退出 2（fail-closed；指错不回退、不许按当前工作目录反推）",
                  file=sys.stderr)
            return 2
    else:
        root = DEFAULT_ROOT
    scheme = Path(args.scheme) if args.scheme else None
    code, summary = run_extract(
        root, args.round, scheme, args.cell,
        Path(args.baseline) if args.baseline else None,
        Path(args.criterion) if args.criterion else None,
        args.task)
    if not args.quiet:
        stream = sys.stdout if code == 0 else sys.stderr
        print(summary, file=stream)
    return code


# ── 早停门控（工程能力件：records/capabilities/early-stop-gate.md）──────────────
# ★★ 性质：以下阈值全部是**工程护栏**（沿用 R-0010 `observations.qsnr.watchdog`
#    的定性：宁可早停），**不是**科学判据、不进判定、也不得跨臂比较。
#    默认关（缺键 ⇒ 行为与本段引入前逐位不变）；阈值必须跑前冻结。
#: ① held-out loss：第 10 步之前不判（用户口径）；相对自身最小值涨幅超阈值 ⇒ 停
#: ★ 点数按**不同 step 数**算（不是原始验证行条数）：框架**同一 step 会打两条**
#:   valid —— in-loop validation 与收尾 validation 各跑一次，收尾那条 `prefix`
#:   多一个 ` on validation set`、值也不同；同 step 取最后出现的一条。
HOLDOUT_MIN_STEP = 10
HOLDOUT_RISE_PCT = 0.10

#: held-out **racing**（0.19.0）的工程默认。**只有任务配置整块缺失时**才用得上：
#: 正常路径由 `_common.sh` 把 `stop_conditions.holdout.*` 换算成 argv 传进来。
#: 与 `HOLDOUT_*`（上涨判据，默认关）是**两条不同的线**，别混：
#:   `holdout_deviation` = 相对**自身最小值**涨了 ⇒ 泛化退化（形状）
#:   `holdout_racing`    = 相对**历史最好那一轮**落后 ⇒ 没希望，腾卡（位置）
RACING_MIN_STEP = 50
RACING_MAX_GAP_PCT = 0.05
RACING_PATIENCE = 2
#: ③ 收敛停：三条**同时**成立（≥N 步没刷新最小 loss ∧ 尾部窗口上升 ∧ 量化未退化）
CONVERGE_NO_IMPROVE_STEPS = 50
CONVERGE_WINDOW = 10
CONVERGE_RISE_PCT = 0.02
#: 量化侧地板：**必须**与 MindSpeed/mindspeed/core/qat/qsnr_probe.py 的
#: `DROP_DB = 3.0`(:64) / `AGG_FLOOR_DB = 15.0`(:65) 一致 —— 由 `_selftest_earlystop`
#: 直接读那份源码断言，防止两处阈值悄悄漂移。
QSNR_DROP_DB = 3.0
QSNR_AGG_FLOOR_DB = 15.0
#: 验证行锚。出处：Megatron-LM/megatron/training/training.py:2279
#:   `string = f' validation loss at {prefix} | '`（prefix = `iteration N`）
VALID_LINE_RE = re.compile(
    r"validation\s+loss\s+at\s+(?:iteration|iter|step)\s*[:=]?\s*(\d+)", re.I)


#: ★ 验证行的 **loss 值**专属正则：真格式是 `lm loss value: {:.6E}`
#:   （Megatron-LM/megatron/training/training.py:2279 `f' validation loss at {prefix} | '`
#:    ＋ :2281 `'{} value: {:.6E} | '.format(key, …)`，key=`lm loss`）。
#:   共用 `LOSS_RE` 要求 `loss` 后紧跟 `[:=]` ⇒ 匹配不上 `loss value: 1.05E+00`
#:   ⇒ **绝不能改 LOSS_RE**（它决定历史轮次的数字），只给验证侧用这一份。
VALID_NUM_RE = re.compile(r"value\s*[:=]?\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")


def parse_loss_curves(path):
    """→ (train_curve, valid_curve, notes)

    ★ 为什么必须分离（真机口径）：框架实际打印的验证行是
      ` validation loss at iteration N | lm loss value: 1.05E+00 | lm loss PPL: … |`
      （training.py:2279＋:2281，`value:` 而不是 `lm loss:`）。`LOSS_RE`(:154) 要求
      `loss` 后紧跟 `[:=]` ⇒ **匹配不上**真格式验证行 ⇒ 它**不会**被
      `parse_loss_curve` 收进 train 曲线。分离仍然必须：① 老/别的 Megatron 变体
      确实会打 `lm loss: …` 的验证行，那种格式下 `LOSS_RE` 会命中，验证点混进
      train ⇒ `jump_factor=4.0`（相邻上升 > 4 倍）把"训练/验证交替"误判成跳变、
      **误触发既有早停**；② 验证点必须只走 valid 曲线，才能按"不同 step 数"做
      held-out 判据（见 `holdout_deviation`）。
    ★ train_curve **直接复用** `parse_loss_curve`，所以没有验证行的日志行为与本函数
      引入前**逐位一致**（`_selftest_earlystop` 对既有 300 步真轨迹做 `==` 断言）。
    """
    train, notes = parse_loss_curve(path)
    notes = list(notes)
    valid = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return train, valid, notes + [f"验证行扫描失败：{exc}"]
    for line in lines:
        m = VALID_LINE_RE.search(line)
        if m is None:
            continue
        hit = LOSS_RE.search(line)
        if hit is None:
            # ★ 真格式 `| lm loss value: 1.050000E+00 |`：LOSS_RE 匹配不上（它要求
            #   `loss` 后紧跟 [:=]）⇒ 用验证侧专属正则兜底；**不改共用 LOSS_RE**
            #   （那个正则决定历史轮次的数字，改了等于改历史）。
            hit = VALID_NUM_RE.search(line)
        if hit is None:
            # ★ 不静默跳过：认不出值要在 notes 里留一条（本项目最怕"悄悄没生效"）。
            notes.append(
                f"验证行 step={m.group(1)} 只认出步号、认不出 loss 值"
                f"（真格式应为 `lm loss value: 1.05E+00`）—— 该点未计入 valid")
            continue
        tok = hit.group(1)
        try:
            val = float(tok)
        except (TypeError, ValueError):
            notes.append(f"验证行 step={m.group(1)} 的值 {tok!r} 读不出，跳过")
            continue
        if val != val or val in (float("inf"), float("-inf")):
            notes.append(f"验证行 step={m.group(1)} 为非有限值 {tok!r}，跳过")
            continue
        valid.append((int(m.group(1)), val))
    valid.sort(key=lambda t: t[0])
    return train, valid, notes


def _series_stat(curve):
    """曲线摘要：n/first/last/min/max/min_step/since_min（since_min = 尾步 − 最小步）。"""
    if not curve:
        return {"n": 0, "since_min": None}
    vals = [v for _, v in curve]
    lo = min(vals)
    min_step = next(s for s, v in curve if v == lo)
    return {"n": len(curve), "first": vals[0], "last": vals[-1], "min": lo,
            "max": max(vals), "min_step": min_step,
            "since_min": curve[-1][0] - min_step}


def _dedup_last_per_step(curve):
    """同 step 多条 ⇒ 保留**最后出现**的一条。返回 (去重后升序曲线, 重复条数)。

    ★ 为什么同 step 会多条：框架**同一 step 会打两条** valid 行 —— in-loop
      validation 与收尾 validation 各跑一次，收尾那条的 `prefix` 多一个
      ` on validation set`，两次的值也不同（如 step 10 的 0.878 与 0.865）。
    ★ 为什么取**最后**一条（而不是默默取第一条）：收尾那次写在后面，读的是同一
      step 上更靠后的权重状态，更权威；且 `parse_loss_curves` 的 valid 是
      **稳定**排序（:2639），同 step 的条目保持文件出现顺序，所以"最后出现"
      与文件顺序一致，可复现。
    """
    last: dict[int, float] = {}
    dup = 0
    for s, v in curve:
        if s in last:
            dup += 1
        last[s] = v
    return sorted(last.items()), dup


def holdout_deviation(train_curve, valid_curve, tv=None):
    """① 测试集(held-out) loss 偏差门。**默认关**：验证曲线为空/点不足 ⇒ 不判。

    ★ 判据口径是"**跑完前 10 步之后**再判"，所以点数必须按**不同 step 数**算，
      不能按 `len(valid_curve)`：框架同一 step 会打两条 valid（in-loop ＋ 收尾
      各跑一次 validation，见 `_dedup_last_per_step` 的说明），于是同 step 的
      两条会被旧口径 `len(...) >= 2` 误当成两个点 ⇒ 第 10 步的单点数据就能
      开门 ✗。这里改用 `len({s for s, _ in valid_curve})` 作为点数，同 step 多余
      的条数记进 `dup_same_step`，去重策略记进 `dup_policy`。
    """
    sub = tv.get("holdout", {}) if isinstance(tv, dict) else {}
    min_step = int(sub.get("min_step", HOLDOUT_MIN_STEP))
    pct = float(sub.get("rise_pct", HOLDOUT_RISE_PCT))
    dedup, dup_same_step = _dedup_last_per_step(valid_curve)
    distinct_steps = len(dedup)
    out = {"fired": False, "reason": None, "min_step": min_step, "rise_pct": pct,
           "train": _series_stat(train_curve), "valid": _series_stat(dedup),
           "distinct_steps": distinct_steps, "dup_same_step": dup_same_step,
           "dup_policy": "同 step 取最后出现的一条",
           "thresholds_source": ("tv.holdout" if sub else "metrics.py 默认（工程护栏）")}
    # ★ 按**不同 step 数**判，不按原始点数：同 step 两条（in-loop＋收尾）不算两个点。
    if distinct_steps < 2:
        out["reason"] = (f"不同 step 只有 {distinct_steps} 个（< 2）⇒ 不判"
                         f"（用户口径：跑完前 {min_step} 步之后才判；"
                         f"原始验证点 {len(valid_curve)} 条、同 step 重复 {dup_same_step} 条，"
                         f"同 step 取最后出现的一条）")
        return out
    st = out["valid"]
    if dedup[-1][0] < min_step:
        out["reason"] = (f"最新验证步 {dedup[-1][0]} < {min_step} ⇒ 不判"
                         f"（用户口径：跑完前 {min_step} 步之后才判）")
        return out
    rise = (st["last"] / st["min"] - 1.0) if st["min"] > 0 else None
    out["rise_vs_min"] = rise
    if rise is not None and rise > pct:
        out["fired"] = True
        out["reason"] = (f"held-out loss 相对自身最小值 {st['min']:.6g}（step {st['min_step']}）"
                         f"上涨 {rise * 100:.2f}% > 阈值 {pct * 100:.2f}%")
    else:
        out["reason"] = "held-out loss 未超阈"
    return out

def holdout_racing(valid_curve, baseline_curve, tv=None) -> dict:
    """held-out **racing**：本轮验证 loss 相对**历史最好那一轮**落后多少 —— 提效用的主判据。

    为什么要它（0.19.0）：早停的目的不是"曲线难看就停"，而是**把算力从没希望的轮次
    里抽出来**（successive halving / Hyperband 的思路）。所以判据是**相对位置**，
    不是绝对形态：同一个 step 上，本轮验证 loss 比历史最好那一轮差多少。

    判据分三段（缺任一条都不判，宁可不判也不猜）：

      ① 只比**两边都评过**的 step。**不插值** —— 插出来的 gap 是假数。
      ② 只判 `>= min_step` 的点（跳过 warmup：低精度方案常"慢热"，早期落后不代表终局）。
      ③ 最近 `patience` 个点的 gap 都 `> max_gap_pct`，且**没有收窄**（最后一个 gap
         不小于倒数第二个 gap 减去 0.5 个百分点的噪声容差）⇒ `fired`。

    `fired=True` 只有一个含义：**这轮没有希望赢过历史最好，别再烧卡**。
    它不是"方案差"的判定 —— 判定归 `criterion.yaml`；本函数输出永远 `is_verdict: False`。

    ★ 为什么"没有收窄"是必须的：低精度方案常见"慢热后追平"，只看落后幅度会误杀。
    ★ 为什么参照是 `records/best` 而不是"框架原生轮"：best 天然是**跑完 ＋ 通过判定 ＋
      证据齐全**的那一轮，不用再从 `design.md` 认身份（0.19.0 定）。
    """
    sub = tv if isinstance(tv, dict) else {}
    min_step = int(sub.get("min_step", RACING_MIN_STEP))
    gap_pct = float(sub.get("max_gap_pct", RACING_MAX_GAP_PCT))
    patience = int(sub.get("patience", RACING_PATIENCE))
    out = {"fired": False, "reason": None, "min_step": min_step,
           "max_gap_pct": gap_pct, "patience": patience,
           "points": [], "latest_gap": None, "common_steps": 0,
           "valid_points": len(valid_curve or []),
           "baseline_points": len(baseline_curve or []),
           "thresholds_source": ("任务配置 stop_conditions.holdout"
                                 if isinstance(tv, dict) and tv else
                                 "metrics.py 默认（工程护栏）"),
           "is_verdict": False}
    if not valid_curve:
        out["reason"] = "本轮没有验证点 ⇒ 不判（任务 argv 里 `--eval-iters 0` 或没切验证集）"
        return out
    if not baseline_curve:
        out["reason"] = ("没有基线验证曲线 ⇒ 不判（records/best 里那一轮必须有验证点；"
                         "历史轮次大多 `--split 100,0,0`，补不了）")
        return out
    base = dict(_dedup_last_per_step(baseline_curve)[0])
    mine, _dup = _dedup_last_per_step(valid_curve)
    pairs = []
    for s, v in mine:
        bv = base.get(s)
        if bv is None or not isinstance(bv, (int, float)) or bv <= 0:
            continue
        if not isinstance(v, (int, float)) or not math.isfinite(v):
            continue
        pairs.append((s, v / bv - 1.0))
    out["common_steps"] = len(pairs)
    judged = [(s, g) for s, g in pairs if s >= min_step]
    out["points"] = [[s, round(g, 6)] for s, g in judged]
    if not judged:
        out["reason"] = (f"共同步点里没有 >= {min_step} 的（共同 {len(pairs)} 点、"
                         f"本轮 {len(mine)} 点、基线 {len(base)} 点）⇒ 不判："
                         f"两边验证点必须落在**同一批 step** 上才可比（不插值）")
        return out
    out["latest_gap"] = round(judged[-1][1], 6)
    window = judged[-patience:]
    if len(window) < patience:
        out["reason"] = (f">= {min_step} 的验证点只有 {len(judged)} 个（< patience={patience}）"
                         f"⇒ 不判")
        return out
    over = [g for _, g in window if g > gap_pct]
    if len(over) < patience:
        out["reason"] = (f"最近 {patience} 个 gap 里只有 {len(over)} 个 > "
                         f"{gap_pct * 100:.2f}%（{', '.join(f'{g * 100:.2f}%' for g in over) or '无'}）"
                         f"⇒ 未超阈")
        return out
    gaps = [g for _, g in window]
    tol = 0.005
    if gaps[-1] < gaps[-2] - tol:
        out["reason"] = (f"gap 在收窄（{gaps[-2] * 100:.2f}% → {gaps[-1] * 100:.2f}%，"
                         f"容差 {tol * 100:.1f} 个百分点）⇒ 还在追，不停")
        return out
    out["fired"] = True
    out["reason"] = (f"held-out racing：第 {judged[-1][0]} 步验证 loss 落后历史最好那一轮 "
                     f"{judged[-1][1] * 100:.2f}%（阈值 {gap_pct * 100:.2f}%），"
                     f"最近 {patience} 点 {gaps[-1] * 100:.2f}% 未见收窄 ⇒ 没希望，停")
    return out


def convergence_observation(train_curve, qsnr_db=None, qsnr_prev_db=None, tv=None):
    """③ 收敛停：≥N 步没刷新最小 loss ∧ 尾部窗口上升 ∧ 量化未退化（三条同时）。

    ★ 量化证据缺失（`qsnr_db is None`）⇒ **不触发**：没有证据就不停，停了也说不清。
    """
    sub = tv.get("converge", {}) if isinstance(tv, dict) else {}
    no_improve_th = int(sub.get("no_improve_steps", CONVERGE_NO_IMPROVE_STEPS))
    window = int(sub.get("window", CONVERGE_WINDOW))
    pct = float(sub.get("rise_pct", CONVERGE_RISE_PCT))
    floor_db = float(sub.get("qsnr_floor_db", QSNR_AGG_FLOOR_DB))
    drop_db = float(sub.get("qsnr_drop_db", QSNR_DROP_DB))
    st = _series_stat(train_curve)
    out = {"fired": False, "reason": None, "series": st,
           "no_improve_steps": no_improve_th, "window": window, "rise_pct": pct,
           "qsnr_db": qsnr_db, "qsnr_floor_db": floor_db, "qsnr_drop_db": drop_db,
           "thresholds_source": ("tv.converge" if sub else "metrics.py 默认（工程护栏）")}
    if len(train_curve) < max(window, 2):
        out["reason"] = f"训练点 {len(train_curve)} < 窗口 {window} ⇒ 不判"
        return out
    win = [v for _, v in train_curve[-window:]]
    rise = ((win[-1] - win[0]) / win[0]) if win[0] > 0 else None
    rise_vs_min = ((st["last"] / st["min"] - 1.0) if st["min"] > 0 else None)
    cond_a = st["since_min"] >= no_improve_th
    cond_b = bool(rise is not None and rise > 0
                  and rise_vs_min is not None and rise_vs_min >= pct)
    cond_c = None
    if qsnr_db is not None:
        cond_c = float(qsnr_db) >= floor_db
        if qsnr_prev_db is not None and float(qsnr_db) < float(qsnr_prev_db) - drop_db:
            cond_c = False
    out.update({"since_min": st["since_min"], "window_rise": rise,
                "rise_vs_min": rise_vs_min, "cond_no_improve": cond_a,
                "cond_rising": cond_b, "cond_qsnr_ok": cond_c})
    if qsnr_db is None:
        out["reason"] = "量化证据缺失 ⇒ 不判（fail-closed：没有证据就不停）"
        return out
    if cond_a and cond_b and cond_c:
        out["fired"] = True
        out["reason"] = (f"距最后一次刷新最小 loss(step {st['min_step']}) 已 {st['since_min']} 步"
                         f" ≥ {no_improve_th}；尾部 {window} 点自 {win[0]:.6g} 升至 "
                         f"{win[-1]:.6g}（相对最小值 +{rise_vs_min * 100:.2f}%）；"
                         f"量化聚合 {float(qsnr_db):.4f} dB ≥ 地板 {floor_db} dB")
    else:
        out["reason"] = (f"三条未同时成立：no_improve={cond_a} rising={cond_b} "
                         f"qsnr_ok={cond_c}")
    return out


def _selftest_earlystop():
    """早停门控自测（CPU、0 npu·h）：
    `python3 -c "import sys;sys.path.insert(0, 'runtime');import metrics;sys.exit(metrics._selftest_earlystop())"`"""
    import tempfile
    stats = {"n": 0, "fail": 0}

    def case(name, ok, extra=""):
        stats["n"] += 1
        if not ok:
            stats["fail"] += 1
        print(("  ok    " if ok else "  FAIL  ") + name
              + (f"  {extra!r}" if (extra and not ok) else ""))

    # 真实轨迹路径由环境变量给：本文件不含任何具体模型名/任务名/路径；
    # 不给就跳过这一段（不影响 --selftest 的 125 条）。
    _real = os.environ.get("LP_REAL_LOSS_LOG", "")
    real = Path(_real) if _real else Path("/nonexistent")
    if real.is_file():
        t0 = parse_loss_curve(real)[0]
        t1, v1, _ = parse_loss_curves(real)
        case("无验证行日志：train 曲线与既有解析器逐位一致", t0 == t1, (len(t0), len(t1)))
        case("无验证行日志：valid 曲线为空", v1 == [], v1[:3])
    else:
        case("真轨迹在场（不在则跳过）", True)

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "loss.txt"
        p.write_text(" iteration 1/300 | lm loss: 1.0E+00\n"
                     " validation loss at iteration 1 | lm loss value: 2.0E+00 |\n"
                     " iteration 2/300 | lm loss: 9.0E-01\n"
                     " validation loss at iteration 2 | lm loss value: 2.5E+00 |\n", encoding="utf-8")
        tr, va, _ = parse_loss_curves(p)
        case("训练行只进训练曲线", [v for _, v in tr] == [1.0, 0.9], tr)
        case("验证行只进验证曲线", [v for _, v in va] == [2.0, 2.5], va)
        case("既有解析器：同号时训练行先出现 ⇒ 去重(:249-253)保留训练值",
             [v for _, v in parse_loss_curve(p)[0]] == [1.0, 0.9], parse_loss_curve(p)[0])
        p3 = Path(d) / "eval_first.txt"
        p3.write_text(" validation loss at iteration 1 | lm loss value: 2.0E+00 |\n"
                      " iteration 1/300 | lm loss: 1.0E+00\n", encoding="utf-8")
        # ★ 真口径（旧断言已过时）：真格式验证行 `| lm loss value: 2.0E+00 |` 下
        #   `LOSS_RE` 要求 `loss` 后紧跟 [:=] ⇒ **匹配不上** ⇒ 验证行根本不会进
        #   train 曲线，"eval 行先出现就顶替训练点"在真机上**不存在**。
        #   （旧断言用的是框架不会打印的假格式 `| lm loss: 2.0E+00` ✗。）
        old3 = parse_loss_curve(p3)[0]
        case("★ 既有解析器：真格式 eval 行先出现 ⇒ **不**顶替训练点（训练点保持）",
             old3 == [(1, 1.0)], old3)
        tr3, va3, _ = parse_loss_curves(p3)
        case("★ 真格式下 train 与既有解析器逐位一致、valid 正常拿到该点",
             tr3 == old3 and va3 == [(1, 2.0)], (tr3, va3))
        p2 = Path(d) / "holdout.txt"
        p2.write_text(" validation loss at iteration 1 | lm loss value: 2.0E+00 |\n"
                      " validation loss at iteration 9 | lm loss value: 2.1E+00 |\n"
                      " validation loss at iteration 20 | lm loss value: 2.5E+00 |\n", encoding="utf-8")
        _, va2, _ = parse_loss_curves(p2)
        case("① 第 10 步前不判（step 9）",
             holdout_deviation([], va2[:2])["fired"] is False, holdout_deviation([], va2[:2]))
        case("① 第 10 步后偏差超阈 ⇒ 触发",
             holdout_deviation([], va2)["fired"] is True, holdout_deviation([], va2))

        # ★ 验收 3：真格式三行（train 1 → validation value → train 11）
        p6 = Path(d) / "real3.txt"
        p6.write_text(" iteration 1/300 | lm loss: 1.0E+00\n"
                      " validation loss at iteration 10 | lm loss value: 1.050000E+00 |\n"
                      " iteration 11/300 | lm loss: 9.0E-01\n", encoding="utf-8")
        tr6, va6, _ = parse_loss_curves(p6)
        case("★ 真格式三行：train[(1,1.0),(11,0.9)]、valid[(10,1.05)]、train≡parse_loss_curve",
             tr6 == [(1, 1.0), (11, 0.9)] and va6 == [(10, 1.05)]
             and tr6 == parse_loss_curve(p6)[0], (tr6, va6))

        # ★ 修 2：同一 step 的两条 valid（框架 in-loop ＋ 收尾各跑一次）**不算两个点**
        p4 = Path(d) / "dup_step.txt"
        p4.write_text(" validation loss at iteration 10 | lm loss value: 8.780000E-01 |\n"
                      " iteration 10/300 | lm loss: 7.0E-01\n"
                      " validation loss at iteration 10 | lm loss value: 8.650000E-01 |\n",
                      encoding="utf-8")
        _, va4, _ = parse_loss_curves(p4)
        obs4 = holdout_deviation([], va4)
        case("② 同 step 两条 ⇒ distinct_steps=1、dup_same_step=1、取最后一条、不判",
             obs4["distinct_steps"] == 1 and obs4["dup_same_step"] == 1
             and obs4["fired"] is False and va4[-1] == (10, 0.865), obs4)
        case("② 不判原因写明「不同 step 只有 1 个」",
             "不同 step 只有 1 个" in (obs4["reason"] or ""), obs4["reason"])
        p5 = Path(d) / "two_steps.txt"
        p5.write_text(" validation loss at iteration 10 | lm loss value: 8.780000E-01 |\n"
                      " validation loss at iteration 20 | lm loss value: 9.800000E-01 |\n",
                      encoding="utf-8")
        _, va5, _ = parse_loss_curves(p5)
        obs5 = holdout_deviation([], va5)
        case("② 不同 step 两个（10/20）⇒ distinct_steps=2、dup_same_step=0、可判",
             obs5["distinct_steps"] == 2 and obs5["dup_same_step"] == 0
             and obs5["fired"] is True, obs5)

    conv = [(s, 1.0 - 0.001 * s) for s in range(0, 31)] + \
           [(s, 0.970 + 0.003 * (s - 30)) for s in range(31, 100)]
    still = [(s, 1.0 - 0.001 * s) for s in range(0, 100)]
    case("③ 三条齐 ⇒ 触发", convergence_observation(conv, qsnr_db=17.0)["fired"] is True,
         convergence_observation(conv, qsnr_db=17.0))
    case("③ 量化证据缺失 ⇒ 不触发（fail-closed）",
         convergence_observation(conv, qsnr_db=None)["fired"] is False)
    case("③ 量化低于地板 ⇒ 不触发",
         convergence_observation(conv, qsnr_db=14.0)["fired"] is False)
    case("③ 仍在刷新低 ⇒ 不触发",
         convergence_observation(still, qsnr_db=17.0)["fired"] is False)
    case("③ 量化较上一点跌 > DROP_DB ⇒ 不触发",
         convergence_observation(conv, qsnr_db=17.0, qsnr_prev_db=21.5)["fired"] is False)
    if real.is_file():
        obs_real = convergence_observation(parse_loss_curve(real)[0], qsnr_db=17.2755)
        print("  ---- R-0010 真轨迹 ③ 观察（非断言，供人看）："
              f"fired={obs_real['fired']} since_min={obs_real.get('since_min')} "
              f"窗口涨幅={obs_real.get('window_rise')} 相对最小值={obs_real.get('rise_vs_min')}")
        case("③ 真轨迹冒烟：返回结构齐备",
             {"fired", "since_min", "window_rise", "rise_vs_min"} <= set(obs_real),
             sorted(obs_real))

    # 框架检出的落点由环境变量给（本文件不含任何工程外路径 —— §11 唯一落点规则）；
    # 不给就跳过这一段，不影响 `--selftest` 的 125 条。
    _probe = os.environ.get("LP_QSNR_PROBE", "")
    probe = Path(_probe) if _probe else Path("/nonexistent")
    if probe.is_file():
        txt = probe.read_text(encoding="utf-8")
        case("量化地板与 qsnr_probe.py 一致（防阈值漂移）",
             f"DROP_DB = {QSNR_DROP_DB}" in txt and f"AGG_FLOOR_DB = {QSNR_AGG_FLOOR_DB}" in txt,
             (QSNR_DROP_DB, QSNR_AGG_FLOOR_DB))
    else:
        case("qsnr_probe.py 在场（不在则跳过）", True)

    print("-" * 60)
    print(f"PASSED: {stats['n'] - stats['fail']}/{stats['n']}")
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
