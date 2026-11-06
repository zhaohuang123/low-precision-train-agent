#!/usr/bin/env python3
"""lm_eval_driver.py —— eval 驱动（**骨架**；照抄到 `<任务目录>/drivers/lm_eval_driver.py`）（**真 argv ＋ 旧件同一套产物**）。

归属：任务目录的 `drivers/`（评测驱动骨架）＋ `config/tasks/<任务名>.yaml` 的
      `eval.lm_eval.driver` ＋ 技能 `skills/eval-lm-eval`。

============================================================================
一、argv 形状：**逐项照抄**早先实测脚本（建设者侧只读材料，不随包）的 SHARD_ARGV，
    形状即 `build_shard_argv()`；文中 `[E]:行号` 指那份材料的内部位次，只作对照凭证
    （精确对照表只在建设者仓库的同一文件里，不随包）。
============================================================================

**本驱动与旧件的两处**有意**差异（都不改变 argv 与产物形状，逐条说清）**：

1. 旧的聚合 `python3 - <<PY` 内嵌在 shell 里，退出码用 `3`；本驱动是**独立进程**，
   按本工程的退出码表把「结果不完整 / 不是 flexible-extract / 一片没起」统一翻成
   **6（评测侧无效）** —— `6` 说的是「这一轮的分数根本不该被引用」，与旧 `3` 同义。
2. `entry_script` 在旧件里是 shell 入口（`[E]:49`）的路径与 sha；本工程**没有** shell 评测入口
   （三段入口 → `commands/eval_cmd.sh` → 本驱动），故该字段照实指向**本驱动**（`__file__`＋sha），
   键名与写法一字不改。

★ 口径（数据集名／few-shot／生成长度／批大小／shards）**不在本文件定义**：由
  `commands/eval_cmd.sh` 从任务配置 `eval.*` 与 `<轮次>/criterion.yaml` 的 `eval_protocol.*`
  读出后作为参数传进来；本文件不设默认值（缺一项就退出 2），也不读第二处配置。
★ `--print` 只打印拼装出的 argv，**不执行、不占卡** —— 与三段入口的 `--dry-run` 同一套纪律。
★ 本工程**从未真跑过**本文件：验过的是 `--print`（argv 形状）＋ `py_compile`（语法）。
  真跑要上真机（见 `skills/eval-lm-eval/references/lm-eval-driver-contract.md` §7）。
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_EVAL_INVALID = 6

#: 决策指标：旧 `[E]:391-395` 量过 —— strict-match 量的是**答案格式**，不是数学。
#: 缺它**不许兜底**取别的键（换指标 = 换量纲）。


# ---------------------------------------------------------------------------
# argv（形状唯一出处：旧 [E]:281-292）
# ---------------------------------------------------------------------------

def build_shard_argv(args, *, tasks, proto: dict, output_path: str,
                     samples_json: "str | None", limit: "int | None") -> "list[str]":
    """拼装**一片**的 lm_eval argv（形状见文件头 §一；与 `[E]:281-292` 同一形状）。

    `tasks`／`proto` 是**这一组**的：多数据集下不同集的 few-shot／生成长度可能不同 ⇒
    同口径的集一起跑，不同口径的集各起一次 lm_eval（组由 `_groups()` 算）。
    """
    mgt = proto.get("max_gen_toks")
    argv = [
        "--model", "hf",
        "--model_args", (f"pretrained={args.model},dtype={args.dtype},"
                         f"trust_remote_code=True,enable_thinking=False"),
        "--apply_chat_template",
        "--fewshot_as_multiturn",
        "--tasks", ",".join(tasks),
        "--num_fewshot", str(proto["num_fewshot"]),
        "--batch_size", str(proto["batch_size"]),
        "--device", args.device,
    ]
    # `max_gen_toks` 为 null ⇒ 这个集走 loglikelihood 口径（如多选类）⇒ **不传** `--gen_kwargs`。
    if mgt is not None:
        argv += ["--gen_kwargs", f"max_gen_toks={mgt}"]
    argv += ["--output_path", output_path, "--log_samples"]
    # `--limit` 与 `--samples` **不兼容**（旧 [E]:268-271）：给了 limit 就只起第 0 片、传 --limit。
    if limit is not None:
        argv += ["--limit", str(limit)]
    elif samples_json is not None:
        argv += ["--samples", samples_json]
    if args.extra_args:
        argv += str(args.extra_args).split()
    return argv


def _shard_plan(args, tasks) -> "tuple[int, dict]":
    """分片计划：`{分片号: samples_json | None}`。轮转发牌与旧 [E]:184-201 同一算式。

    * `--limit` 给了 ⇒ 只起第 0 片（旧 [E]:268-271：`--limit` 与 `--samples` 不兼容）；
    * `--shards 1` ⇒ 单片、不传 `--samples`；
    * `--shards >1` ⇒ **必须**显式给 `--num-samples`（旧 [E]:161-166 同纪律：不许按卡数兜底）。
    """
    nshards = int(args.shards)
    if nshards < 1:
        raise ValueError(f"--shards 必须 >=1，给的是 {nshards}")
    if args.limit is not None:
        return 1, {0: None}
    if nshards == 1:
        return 1, {0: None}
    if args.num_samples is None:
        raise ValueError("--shards>1 时必须显式给 --num-samples（轮转发牌的分母；不许猜）")
    n = int(args.num_samples)
    if n < 1:
        raise ValueError(f"--num-samples 必须 >=1，给的是 {n}")
    # ★ 缝②修：`--samples` 的 JSON 必须**每个任务一个键** —— 旧版只有 `{args.tasks: …}`
    #   （`--tasks a,b` 时键是字符串 "a,b"），而 lm-eval 是按**每个任务名**各找自己的键 ⇒
    #   多数据集下分片静默失效（每片都跑全量，不报错）。
    return nshards, {
        i: json.dumps({t: list(range(i, n, nshards)) for t in tasks},
                      separators=(",", ":"))
        for i in range(nshards)
    }


def _full_argv(args, job: dict, output_path: str) -> "list[str]":
    """一片的完整 argv：入口 = `<venv>/bin/lm_eval`（解释器旁边那一个）＋ 该片该组的参数。"""
    return [str(Path(sys.executable).parent / "lm_eval")] + build_shard_argv(
        args, tasks=job["tasks"], proto=job["proto"], output_path=output_path,
        samples_json=job["samples"], limit=job["limit"])


def _is_metric_key(k, v) -> bool:
    """结果字典里的这个键是不是**一个指标**（lm-eval 用 `acc`／`exact_match,flexible-extract` 这种名字）。

    0.17.0 起不再白名单 `exact_match*`：多选类数据集产出的是 `acc`，硬白名单会把它全跳过。
    这里改成**排除法**：非数字、`*_stderr`（标准差，不是指标）、以及几个已知的非指标键。
    """
    if not isinstance(k, str) or not k.strip():
        return False
    if k in ("alias", "samples", "n_samples", "effective", "original"):
        return False
    if k.endswith("_stderr"):
        return False
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _groups(args) -> "list[dict]":
    """按**生效口径**把数据集分组：同一组一次 lm_eval 调用。

    `--protocols-json` 缺省 ⇒ 全部任务共用命令行给的全局口径（一组）。
    给了就按 `{数据集名: {task_type,num_fewshot,max_gen_toks,batch_size,prompt_type}}`
    逐集取值（`eval_cmd.sh` 已经把「全局 protocol ⊕ 该集覆盖」算成生效值传进来）。
    """
    tasks = [x.strip() for x in str(args.tasks).split(",") if x.strip()]
    if not tasks:
        raise ValueError("--tasks 为空（至少一个数据集名）")
    protos: dict = {}
    raw = str(args.protocols_json or "").strip()
    if raw:
        try:
            protos = json.loads(raw)
        except ValueError as exc:
            raise ValueError(f"--protocols-json 不是合法 JSON：{exc}")
        if not isinstance(protos, dict):
            raise ValueError("--protocols-json 必须是对象 {数据集名: {口径…}}")
    buckets: "dict[str, dict]" = {}
    for name in tasks:
        over = protos.get(name) or {}
        if not isinstance(over, dict):
            raise ValueError(f"--protocols-json[{name!r}] 不是对象")
        nf = over.get("num_fewshot", args.num_fewshot)
        bs = over.get("batch_size", args.batch_size)
        mgt = over.get("max_gen_toks", args.max_gen_toks)
        for label, val in (("num_fewshot", nf), ("batch_size", bs)):
            if val is None:
                raise ValueError(
                    f"数据集 {name!r} 的**生效**口径里没有 {label} —— 口径项不许有默认值："
                    f"在 eval.protocol 或该集 eval.datasets[].protocol 里显式给")
        eff = {
            "task_type": str(over.get("task_type") or "generation"),
            "num_fewshot": int(nf),
            "max_gen_toks": None if mgt is None else int(mgt),
            "batch_size": int(bs),
            "prompt_type": over.get("prompt_type"),
        }
        key = json.dumps(eff, sort_keys=True, ensure_ascii=False)
        buckets.setdefault(key, {"tasks": [], "proto": eff})
        buckets[key]["tasks"].append(name)
    return list(buckets.values())


# ---------------------------------------------------------------------------
# 可用性 / 版本 / sha
# ---------------------------------------------------------------------------

def _sha16(path: "str | os.PathLike | None") -> "str | None":
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return None


def _lm_eval_version() -> "tuple[bool, str]":
    """`import lm_eval` 与版本回读 —— 与旧 [E]:90-91 同一件事。

    不可用 ⇒ **评测侧无效**（这一轮没有分数），绝不硬跑、绝不编版本号。
    """
    code = "import lm_eval; print(getattr(lm_eval, '__version__', '?'))"
    try:
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True)
    except OSError as exc:  # pragma: no cover
        return False, f"回读 lm_eval 版本失败：{exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return False, (f"这个解释器里没有 lm_eval 包：{sys.executable}"
                       + (f"\n  {tail[-1]}" if tail else ""))
    return True, (proc.stdout or "").strip() or "?"


# ---------------------------------------------------------------------------
# 聚合（旧 [E]:320-469 的同一组键、同一含义）
# ---------------------------------------------------------------------------

def _group_weight(doc: dict, gname: str):
    """组的样本数：递归求和 `group_subtasks` 里各子任务的 `n-samples`。

    lm-eval 只给**任务**写 `n-samples`，不给组写；而组指标是 `weight_by_size: True` 的
    micro 值（**组型数据集**的组定义：`aggregate_metric_list: {metric: acc, weight_by_size: True}`），
    跨分片合并时必须先乘上「这一片里这个组到底评了多少条」。子任务互斥 ⇒ 直接求和。
    取不到就返回 None（调用方据此退出，**不编数**）。
    """
    subs = (doc.get("group_subtasks") or {}).get(gname)
    if not subs:
        return None
    total = 0
    for sub in subs:
        ns = (doc.get("n-samples") or {}).get(sub) or {}
        one = ns.get("effective")
        if one is None:
            one = ns.get("original")
        if one is None:
            one = _group_weight(doc, sub)     # 嵌套组：继续往下拆
        if one is None:
            return None
        total += int(one)
    return total or None


def _aggregate(run_dir: Path, njobs: int, args, proto: dict) -> dict:
    sums: "dict[tuple, list]" = {}
    for k in range(njobs):
        cands = sorted(glob.glob(str(run_dir / f"shard_{k}" / "**" / "results*.json"),
                                 recursive=True))
        if not cands:
            raise RuntimeError(f"shard_{k} 没有 results json ⇒ 结果不完整，拒绝写结果文件")
        doc = json.loads(Path(cands[0]).read_text(encoding="utf-8"))
        res = doc.get("results") or {}
        if not res:
            raise RuntimeError(f"shard_{k} 的 results 为空")
        # ★ 组指标在 `groups`，**不在** `results`（`results` 只有 per-task）。
        #   不读它的后果不是「少一个键」，而是**声明了组型数据集却报没读到指标**——假失败。
        #   组 acc 是 weight_by_size 的 micro 值 ⇒ 与旧工程的 micro_acc 决策同一个数。
        for gname, gmetrics in (doc.get("groups") or {}).items():
            if isinstance(gmetrics, dict) and gname not in res:
                res[gname] = gmetrics
        for tname, metrics in res.items():
            for mkey, v in metrics.items():
                if not _is_metric_key(mkey, v):
                    continue
                # ★ 样本数**按存在性**取，不按真假取（旧 [E]:359-363 的真 bug 教训：
                #   合法的 0 会被 `or` 兜底成别的数 ⇒ n 静默放大）。
                ns = (doc.get("n-samples") or {}).get(tname) or {}
                cnt = None
                for key in ("effective", "original"):
                    if ns.get(key) is not None:
                        cnt = int(ns[key])
                        break
                if cnt is None:
                    for key in ("samples", "n_samples"):
                        if metrics.get(key) is not None:
                            cnt = int(metrics[key])
                            break
                if cnt is None:
                    # 组没有自己的 n-samples ⇒ 按子任务样本数求和（见 _group_weight 的说明）
                    cnt = _group_weight(doc, tname)
                if cnt is None:
                    raise RuntimeError(
                        f"shard_{k} 取不到样本数（n-samples 与结果字段都没有）⇒ 拒绝写结果文件（不编数）")
                acc = sums.setdefault((tname, mkey), [0.0, 0])
                acc[0] += float(v) * cnt
                acc[1] += cnt
    if not sums:
        raise RuntimeError("一个指标都没读到（results 里没有数值型指标键）")
    # ★ 每个**声明了的数据集**都必须至少产出一个指标：声明了却不评 = 静默不跑，不许放过。
    got: "dict[str, list]" = {}
    for (tname, _m) in sums:
        got.setdefault(tname, []).append(_m)
    expected = [x.strip() for x in str(args.tasks).split(",") if x.strip()]
    missing_ds = [x for x in expected if x not in got]
    if missing_ds:
        raise RuntimeError(
            f"这些数据集一个指标都没读到：{missing_ds}（有指标的是 {sorted(got)}）"
            f" ⇒ 不许兜底，也不许把它当「评过了」")
    order = sorted(sums)
    first = order[0]
    try:
        rel = Path(args.output_path).resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        rel = Path(args.output_path)
    first_name = f"{first[0]}/{first[1]}"
    metric_keys = {f"{a}/{b}": (sums[(a, b)][0] / sums[(a, b)][1]
                                if sums[(a, b)][1] else None) for (a, b) in order}
    return {
        "metric": first_name,
        "metrics": metric_keys,
        "accuracy": metric_keys[first_name],
        "n": sums[first][1],
        "correct": int(round(sums[first][0])),
        "agg": {
            "rule": "分片求和：Σ(每片 该指标 × 该片该集样本数) / Σ该集样本数（逐数据集分别算）",
            "per_filter": {f"{a}/{b}": {"acc": (sums[(a, b)][0] / sums[(a, b)][1]
                                                 if sums[(a, b)][1] else None),
                                        "n": sums[(a, b)][1]}
                           for (a, b) in order},
            "main_filter": first_name,
            "why": ("lm-eval 每个进程只算自己那片；这里按样本数加权求和 ⇒ 与单片跑全量等价。"
                    "键是 `<数据集>/<指标>`。`main_filter` 只是**按字典序**取的头一个（历史字段）；"
                    "本轮真正的决策指标由 criterion.yaml 的 `success.require`（列表，第一条为主指标）指定。"),
        },
        "protocol": proto,
        "ckpt": args.model,
        "eval_full": ({"flag": True,
                       "why": (f"eval_full=1：全量 {args.num_samples} 条（limit 未设）"
                               if args.limit is None else
                               f"eval_full=1，但 **limit={args.limit}** ⇒ 本次只评了前 "
                               f"{args.limit} 条，**不是全量**")}
                      if str(args.eval_full).lower() in ("1", "true", "yes") else
                      {"flag": False,
                       "why": f"eval_full={args.eval_full!r}（limit={args.limit}）⇒ subset"}),
        "evidence": {
            "run_dir": str(run_dir),
            "native_results": f"{run_dir}/lm_eval_native/（lm-eval 原生 results.json，原样）",
            "argv_files": [f"{run_dir}/argv_shard_{k}.txt" for k in range(njobs)],
            "shard_logs": [f"shard_{k}.log" for k in range(njobs)],
            "output_path_as_given": str(args.output_path),
            "output_path_relative_to_cwd": str(rel),
        },
    }


def _write_protocol(proto: dict, doc: dict, path: Path) -> None:
    """口径清单落盘 —— 写法逐字照旧 [E]:460-465（逐键 `k: v` ＋ 三行聚合说明）。"""
    with path.open("w", encoding="utf-8") as fh:
        for k, v in proto.items():
            fh.write(f"{k}: {v}\n")
        fh.write(f"aggregation: {doc['agg']['rule']}\n")
        fh.write(f"main_filter: {doc['agg']['main_filter']}\n")
        fh.write(f"per_filter: {json.dumps(doc['agg']['per_filter'], ensure_ascii=False)}\n")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="lm_eval_driver.py",
        description="lm_eval 评测驱动（真 argv ＋ 旧件同一套产物；口径由调用方传入）")
    # ── 契约必给项（缺一项 ⇒ 2；旧 [E]:55-58 同纪律：本驱动**不替你挑口径**）──
    ap.add_argument("--model", default="", help="模型产物路径（HF 格式目录）")
    ap.add_argument("--tasks", default="", help="数据集/任务名（口径项，必给）")
    ap.add_argument("--num_fewshot", type=int, default=None, help="few-shot 数（口径项，必给）")
    ap.add_argument("--max_gen_toks", type=int, default=None, help="生成长度上限（口径项，必给）")
    ap.add_argument("--batch_size", type=int, default=None, help="批大小（口径项，必给）")
    ap.add_argument("--output_path", default="", help="结果 JSON 落点（必给）")
    # ── 口径/环境事实（可缺；缺了按各自的旧默认，见文件头对照表）──
    ap.add_argument("--dtype", default="bfloat16")
    ap.add_argument("--device", default="npu")
    ap.add_argument("--dataset", default="",
                    help="本地数据文件，逗号分隔可多值（只记录并逐个查存在性）")
    ap.add_argument("--protocols-json", dest="protocols_json", default="",
                    help="逐数据集**生效**口径 JSON：{集名: {task_type,num_fewshot,"
                         "max_gen_toks,batch_size,prompt_type}}；缺省 ⇒ 全用命令行全局口径")
    ap.add_argument("--shards", type=int, default=1, help="分片数（旧 [E]:161-166）")
    ap.add_argument("--num-samples", dest="num_samples", type=int, default=None,
                    help="轮转发牌的分母（shards>1 时必给；旧 [E]:185 的 N）")
    ap.add_argument("--limit", type=int, default=None, help="子集上限（旧 MAX_EVAL_SAMPLES）")
    ap.add_argument("--cards", default="", help="本轮可见卡（只记录；卡号来自 runtime/resources.py）")
    ap.add_argument("--extra-args", dest="extra_args", default="", help="追加 lm_eval 参数")
    ap.add_argument("--eval-full", dest="eval_full", default="", help="是否全量（旧 LP_EVAL_FULL）")
    ap.add_argument("--harness-version", dest="harness_version", default="",
                    help="判据期望的 harness 版本（只记录；实测值从解释器回读）")
    ap.add_argument("--print", dest="print_only", action="store_true",
                    help="只打印拼装出的 lm_eval argv，不执行、不占卡")
    return ap


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    # ── ① 契约必给项（缺一项 ⇒ 2）────────────────────────────────────────────
    missing = [n for n, v in (("--model", args.model), ("--tasks", args.tasks),
                              ("--output_path", args.output_path)) if v in ("", None)]
    if missing:
        print(f"[driver] ✗ 调用参数不全：{'、'.join(missing)}", file=sys.stderr)
        print("[driver]   口径项没有默认值（缺一项就不许跑）⇒ 退出 2", file=sys.stderr)
        return EXIT_USAGE

    # ── ② 分组（同口径的集一起跑）＋ 分片计划（旧 [E]:161-166 / :184-201）──────
    try:
        groups = _groups(args)
        plans = [_shard_plan(args, g["tasks"]) for g in groups]
        nshards = plans[0][0]
        if any(pl[0] != nshards for pl in plans):
            raise ValueError("各分组的片数不一致（内部错）")
        jobs = []
        for gi, (g, (_n, plan)) in enumerate(zip(groups, plans)):
            for i in range(nshards):
                jobs.append({"group": gi, "shard": i, "tasks": g["tasks"],
                             "proto": g["proto"], "samples": plan.get(i),
                             "limit": args.limit})
    except ValueError as exc:
        print(f"[driver] ✗ 分片/分组计划不成立：{exc} ⇒ 退出 2", file=sys.stderr)
        return EXIT_USAGE

    # ── ③ `--print`：只打印，不执行（纪律同三段入口的 --dry-run）─────────────
    out = Path(args.output_path)
    run_dir = out.parent / "lm_eval_runs" / (
        "run_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    if args.eval_full:
        proto_note = f"eval_full={args.eval_full}"
    else:
        proto_note = "eval_full=（未给 ⇒ subset）"
    if args.print_only:
        print(f"[driver] lm_eval argv（**拼装结果**，未执行、未占卡）；"
              f"口径组 {len(groups)} 个 × 分片 {nshards} 片 = {len(jobs)} 次调用；{proto_note}")
        for k, job in enumerate(jobs):
            full = _full_argv(args, job, str(run_dir / f"shard_{k}"))
            print(f"[driver]   g{job['group']}[{','.join(job['tasks'])}] shard_{k}: "
                  + " ".join(full))
        print(f"[driver] 结果落点：{out}")
        print(f"[driver] 口径清单：{out.parent / 'lm_eval_protocol.txt'}"
              f"（同目录另落 lm_eval_native/）")
        print("[driver] ★ 口径（数据集/few-shot/生成长度/批大小）不在驱动里定义："
              "由 commands/eval_cmd.sh 从任务配置与判据读出后传进来。")
        return EXIT_OK

    # ── ⑤ 真跑前的存在性检查（旧 [E]:70/:83/:84）────────────────────────────
    if not (Path(args.model) / "config.json").is_file():
        print(f"[driver] ✗ 被评模型目录里没有 config.json：{args.model} ⇒ 拒绝启动（退出 2）",
              file=sys.stderr)
        return EXIT_USAGE
    for one_ds in [x.strip() for x in str(args.dataset).split(",") if x.strip()]:
        if not Path(one_ds).is_file():
            print(f"[driver] ✗ 数据文件不对：{one_ds} ⇒ 拒绝启动（退出 2）", file=sys.stderr)
            return EXIT_USAGE
    if not out.parent.is_dir():
        print(f"[driver] ✗ 结果落点的上级目录不存在：{out.parent} ⇒ 退出 2（不自己建目录）",
              file=sys.stderr)
        return EXIT_USAGE

    # ── ⑥ 解释器里必须有 lm_eval（没有 ⇒ 6：评测侧无效，不硬跑、不编数）──────
    ok, version = _lm_eval_version()
    if not ok:
        print(f"[driver] ✗ 评测驱动不可用：{version}", file=sys.stderr)
        print(f"[driver]   ⇒ 评测侧无效（退出 {EXIT_EVAL_INVALID}）：不产生指标，也不许编一个数出来。",
              file=sys.stderr)
        print("[driver]   先跑 scripts/install_env.sh 建评测 venv（落点由 eval.lm_eval.python 推出）。",
              file=sys.stderr)
        return EXIT_EVAL_INVALID

    # ── ⑦ 起分片（旧 [E]:260-302）＋ argv 原样留档（同一个数组，不抄一遍）────
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "lm_eval_native").mkdir(exist_ok=True)
    env = dict(os.environ)
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    procs, launched = [], []
    for k, job in enumerate(jobs):
        full = _full_argv(args, job, str(run_dir / f"shard_{k}"))
        (run_dir / f"argv_shard_{k}.txt").write_text(
            "\n".join(full) + "\n", encoding="utf-8")
        log = (run_dir / f"shard_{k}.log").open("w", encoding="utf-8")
        try:
            p = subprocess.Popen(full, stdout=log, stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            log.close()
            print(f"[driver] ✗ 起 shard_{k} 失败：{exc} ⇒ 评测侧无效（退出 {EXIT_EVAL_INVALID}）",
                  file=sys.stderr)
            return EXIT_EVAL_INVALID
        procs.append((k, p, log))
        launched.append(k)
        print(f"[driver]   g{job['group']} shard_{k} 已起（pid {p.pid}，{log.name}）",
              file=sys.stderr)
    (run_dir / "launched.txt").write_text(
        "".join(f"{i}\n" for i in launched), encoding="utf-8")

    failed = []
    for i, p, log in procs:
        rc = p.wait()
        log.close()
        if rc != 0:
            failed.append((i, rc))
    if failed:
        for i, rc in failed:
            print(f"[driver] ✗ shard_{i} **失败**（退出码 {rc}）—— 见 shard_{i}.log 尾部",
                  file=sys.stderr)
        print(f"[driver]   ⇒ 结果不完整 ⇒ 评测侧无效（退出 {EXIT_EVAL_INVALID}）", file=sys.stderr)
        return EXIT_EVAL_INVALID

    # ── ⑧ 原生件留档（旧 [E]:311-317）──────────────────────────────────────
    native = run_dir / "lm_eval_native"
    for k in range(len(jobs)):
        for f in glob.glob(str(run_dir / f"shard_{k}" / "**" / "results*.json"),
                           recursive=True):
            try:
                (native / Path(f).name).write_bytes(Path(f).read_bytes())
            except OSError:
                pass

    # ── ⑨ 聚合 + 写结果 + 写口径清单（旧 [E]:320-469）──────────────────────
    proto = {
        "harness": "lm-evaluation-harness",
        "harness_version": version,
        "harness_version_source": f"{sys.executable} -c 'import lm_eval;print(lm_eval.__version__)'",
        "harness_version_declared": args.harness_version or None,
        "interpreter": str(sys.executable),
        "interpreter_sha256": _sha16(sys.executable),
        # 旧 [E]:43-49：入口脚本自己的 sha（本工程没有 shell 评测入口 ⇒ 照实指向本驱动）
        "entry_script": str(Path(__file__).resolve()),
        "entry_script_sha256": _sha16(Path(__file__).resolve()),
        "task": args.tasks,
        "groups": [{"tasks": g["tasks"], **g["proto"]} for g in groups],
        "num_fewshot": int(args.num_fewshot),
        "max_gen_toks": (None if args.max_gen_toks is None else int(args.max_gen_toks)),
        "batch_size": int(args.batch_size),
        "device": args.device,
        "dtype": args.dtype,
        "model": args.model,
        "dataset": args.dataset or None,
        "limit": int(args.limit) if args.limit is not None else None,
        "shards": nshards,
        "cards": args.cards or None,
        "extra_args": args.extra_args or None,
    }
    try:
        doc = _aggregate(run_dir, len(jobs), args, proto)
    except RuntimeError as exc:
        print(f"[driver] ✗ {exc}", file=sys.stderr)
        print(f"[driver]   ⇒ 评测侧无效（退出 {EXIT_EVAL_INVALID}）：结果不可比、不出数字。",
              file=sys.stderr)
        return EXIT_EVAL_INVALID

    proto_out = run_dir / "lm_eval_protocol.txt"
    _write_protocol(doc["protocol"], doc, proto_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # ── ⑩ 原生件与口径清单**跟着结果文件走**（旧 [E]:471-495）──────────────
    if out.parent.resolve() != run_dir.resolve():
        dst = out.parent / "lm_eval_native"
        dst.mkdir(parents=True, exist_ok=True)
        for f in sorted(native.glob("*.json")):
            (dst / f.name).write_bytes(f.read_bytes())
        (out.parent / "lm_eval_protocol.txt").write_bytes(proto_out.read_bytes())
        if not (out.parent / "lm_eval_protocol.txt").is_file() \
                or (out.parent / "lm_eval_protocol.txt").stat().st_size == 0:
            print("[driver] ✗ 口径清单没复制成 ⇒ 退出 6（不静默放过）", file=sys.stderr)
            return EXIT_EVAL_INVALID

    print(f"[driver] ✓ 结果已落盘：{out}（{len(doc['metrics'])} 个指标键，"
          f"头一个 metric={doc['metric']}）", file=sys.stderr)
    print(f"[driver] ✓ 口径清单：{out.parent / 'lm_eval_protocol.txt'}"
          f"；原生件：{out.parent / 'lm_eval_native'}/", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
