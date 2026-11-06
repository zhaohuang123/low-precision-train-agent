#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# runtime/charts.py —— 从 `evidence/` 出趋势图（**纯标准库**，不引 matplotlib）
#
# 归属：抽数之外的**只读派生视图**。它不抽数字、不判定、不改 `metrics.json`；
#   只把 evidence 里已有的序列画成图，落在 `evidence/charts/`，供 `<轮次>/report.md` 引用。
#
# 为什么自己画：目标机没有 matplotlib / plotext（实测 ModuleNotFoundError）。
#   为出图去装绘图库，等于给「出一份报告」引入一个新的失败点；SVG 是纯文本，够用。
#
# 用法：
#   python3 runtime/charts.py --round R-0002                      # 画 loss / 量化噪声 / 耗时
#   python3 runtime/charts.py --round R-0002 --root <工程根>       # 同上，显式给根
#   python3 runtime/charts.py --round R-0002 --print-only          # 只打印会写哪些文件（不落盘）
#
# 退出码：0 画完（至少一张）｜2 证据不齐/参数不对（**不是**判定，也不归 5/6）
#
# ★ 纪律：图上出现的数值**只能来自 evidence/**（loss.txt|loss.jsonl、eval_clamp_qsnr.json、
#   <段>.exec.json）。图的标题里写明来源文件与点数，读图的人不必猜。
import argparse
import json
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import metrics  # noqa: E402  （复用唯一的 loss 解析器与 QSNR 读取器，不另写一套）

W, H = 960, 360
PAD_L, PAD_R, PAD_T, PAD_B = 64, 24, 44, 44
FONT = "font-family='ui-monospace,Menlo,Consolas,monospace'"


def _fmt(x: float, nd: int = 4) -> str:
    return f"{x:.{nd}g}" if abs(x) < 1e-4 else f"{x:.{nd}f}".rstrip("0").rstrip(".")


class Plot:
    """一张 SVG 折线图的极简画布：只做折线、网格、坐标刻度、标题、图例。"""

    def __init__(self, title: str, xlabel: str, ylabel: str):
        self.title = title
        self.xlabel = xlabel
        self.ylabel = ylabel
        self.series = []   # (名字, [(x, y)], 颜色, 线宽, 虚线)

    def add(self, name: str, points, color: str, width: float = 1.4, dash: bool = False):
        pts = [(float(x), float(y)) for x, y in points if x is not None and y is not None]
        if pts:
            self.series.append((name, pts, color, width, dash))

    def _bounds(self):
        xs = [x for _n, ps, *_ in self.series for x, _y in ps]
        ys = [y for _n, ps, *_ in self.series for _x, y in ps]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x0 == x1:
            x0, x1 = x0 - 1, x1 + 1
        if y0 == y1:
            y0, y1 = y0 - 1e-6, y1 + 1e-6
        pad = (y1 - y0) * 0.08
        return x0, x1, y0 - pad, y1 + pad

    def svg(self) -> str:
        x0, x1, y0, y1 = self._bounds()
        iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B

        def sx(x):
            return PAD_L + (x - x0) / (x1 - x0) * iw

        def sy(y):
            return PAD_T + ih - (y - y0) / (y1 - y0) * ih

        out = [
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' "
            f"viewBox='0 0 {W} {H}'>",
            f"<rect x='0' y='0' width='{W}' height='{H}' fill='#ffffff'/>",
            f"<text x='{PAD_L}' y='26' {FONT} font-size='15' fill='#111'>{_esc(self.title)}</text>",
            f"<text x='{PAD_L}' y='{H-10}' {FONT} font-size='12' fill='#555'>{_esc(self.xlabel)}</text>",
            f"<text x='12' y='{PAD_T+ih/2:.0f}' {FONT} font-size='12' fill='#555' "
            f"transform='rotate(-90 12 {PAD_T+ih/2:.0f})'>{_esc(self.ylabel)}</text>",
        ]
        # 网格 + y 刻度（5 条）
        for i in range(6):
            yv = y0 + (y1 - y0) * i / 5
            yy = sy(yv)
            out.append(f"<line x1='{PAD_L}' y1='{yy:.1f}' x2='{PAD_L+iw}' y2='{yy:.1f}' "
                       f"stroke='#e8e8e8' stroke-width='1'/>")
            out.append(f"<text x='{PAD_L-8}' y='{yy+4:.1f}' {FONT} font-size='11' "
                       f"fill='#666' text-anchor='end'>{_fmt(yv, 4)}</text>")
        # 边框
        out.append(f"<rect x='{PAD_L}' y='{PAD_T}' width='{iw}' height='{ih}' "
                   f"fill='none' stroke='#bbb'/>")
        # 折线
        for name, pts, color, wd, dash in self.series:
            d = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in pts)
            dash_attr = " stroke-dasharray='5,4'" if dash else ""
            out.append(f"<polyline points='{d}' fill='none' stroke='{color}' "
                       f"stroke-width='{wd}'{dash_attr} stroke-linejoin='round'/>")
        # x 刻度（首/中/末）
        for frac, xv in ((0, x0), (0.5, (x0 + x1) / 2), (1, x1)):
            out.append(f"<text x='{sx(xv):.1f}' y='{PAD_T+ih+16}' {FONT} font-size='11' "
                       f"fill='#666' text-anchor='{('start' if frac==0 else 'end' if frac==1 else 'middle')}'>"
                       f"{_fmt(xv, 6)}</text>")
        # 图例
        ly = 40
        for name, _ps, color, _wd, dash in self.series:
            out.append(f"<line x1='{PAD_L+iw-190}' y1='{ly}' x2='{PAD_L+iw-160}' y2='{ly}' "
                       f"stroke='{color}' stroke-width='2.4'{(' stroke-dasharray=\"5,4\"' if dash else '')}/>")
            out.append(f"<text x='{PAD_L+iw-152}' y='{ly+4}' {FONT} font-size='12' fill='#333'>"
                       f"{_esc(name)}</text>")
            ly += 18
        out.append("</svg>")
        return "\n".join(out) + "\n"


class Bars:
    """耗时条形图：三段一根横条，标注秒数与占比。"""

    def __init__(self, title: str, rows):
        self.title = title
        self.rows = [(k, float(v)) for k, v in rows if isinstance(v, (int, float))]

    def svg(self) -> str:
        w, h = W, 60 + 46 * max(1, len(self.rows))
        total = sum(v for _k, v in self.rows) or 1.0
        out = [f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
               f"viewBox='0 0 {w} {h}'>",
               f"<rect x='0' y='0' width='{w}' height='{h}' fill='#ffffff'/>",
               f"<text x='24' y='26' {FONT} font-size='15' fill='#111'>{_esc(self.title)}</text>"]
        bw = w - 240
        for i, (k, v) in enumerate(self.rows):
            y = 50 + i * 46
            ln = max(2.0, bw * v / total)
            out.append(f"<text x='24' y='{y+15}' {FONT} font-size='13' fill='#333'>{_esc(k)}</text>")
            out.append(f"<rect x='110' y='{y}' width='{ln:.1f}' height='22' fill='#4b7bec' opacity='0.75'/>")
            out.append(f"<text x='{110+ln+10:.1f}' y='{y+16}' {FONT} font-size='12' fill='#333'>"
                       f"{v:.1f}s（{100*v/total:.0f}%）</text>")
        out.append("</svg>")
        return "\n".join(out) + "\n"


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&#39;"))


def _median_smooth(vals, win):
    out = []
    for i in range(len(vals)):
        seg = vals[max(0, i - win + 1): i + 1]
        out.append(sorted(seg)[len(seg) // 2])
    return out


def _sparkline(vals, lo=None, hi=None, width=60):
    blocks = "▁▂▃▄▅▆▇█"
    if not vals:
        return ""
    lo = min(vals) if lo is None else lo
    hi = max(vals) if hi is None else hi
    span = (hi - lo) or 1.0
    step = max(1, len(vals) // width)
    pick = vals[::step]
    return "".join(blocks[min(7, int((v - lo) / span * 7.999))] for v in pick)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(add_help=True, description="从 evidence/ 出趋势图（纯标准库 SVG）")
    ap.add_argument("--root", default=None, help="工程根（默认：本文件上一级）")
    ap.add_argument("--round", required=True, help="轮次 id，例如 R-0002")
    ap.add_argument("--task", default=None,
                    help="任务名（默认读 config/project.yaml 的 task；读不到就必须给）")
    ap.add_argument("--out", default=None, help="输出目录（默认 <轮次>/evidence/charts）")
    ap.add_argument("--print-only", action="store_true", help="只打印将写的文件，不落盘")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else MODULE_DIR.parent
    try:
        rdir, cell = metrics._resolve_round_dir(
            root, args.round, None, metrics.load_names(root, args.task))
    except Exception as exc:  # noqa: BLE001
        print(f"charts.py：找不到轮次 {args.round}（{exc}）", file=sys.stderr)
        return 2
    ev = rdir / "evidence"
    if not ev.is_dir():
        print(f"charts.py：证据目录不存在：{ev}", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else (ev / "charts")
    notes = []
    wrote = []

    # ── loss ──
    curve, _ln = metrics.parse_loss_curve(ev / "loss.jsonl")
    src = "evidence/loss.jsonl"
    if not curve:
        curve, _ln = metrics.parse_loss_curve(ev / "loss.txt")
        src = "evidence/loss.txt"
    if curve:
        xs = [i for i, _v in curve]
        ys = [v for _i, v in curve]
        p = Plot(f"{args.round} · loss（来源 {src}，{len(ys)} 点）", "step", "loss")
        p.add("raw", list(zip(xs, ys)), "#9aa0a6", 1.0)
        p.add("median-10", list(zip(xs, _median_smooth(ys, 10))), "#d63031", 1.8)
        wrote.append((out_dir / "loss.svg", p.svg()))
        wrote.append((out_dir / "loss-sparkline.txt",
                      f"loss（{src}，{len(ys)} 点）\n"
                      f"  原始  : {_sparkline(ys)}\n"
                      f"  平滑10: {_sparkline(_median_smooth(ys, 10))}\n"
                      f"  首/中/末 = {ys[0]:.4f} / {ys[len(ys)//2]:.4f} / {ys[-1]:.4f}\n"))
    else:
        notes.append("没有 loss 轨迹（evidence/loss.txt|loss.jsonl）⇒ 不出 loss 图")

    # ── 量化噪声 ──
    q = metrics.load_qsnr(ev, [])
    series = q.get("series") or []
    if series:
        steps = q.get("sampled_at_steps") or [s.get("step") for s in series]
        wd = [(s.get("step", steps[i] if i < len(steps) else i + 1), s.get("weight_db"))
              for i, s in enumerate(series)]
        ad = [(s.get("step", steps[i] if i < len(steps) else i + 1), s.get("activation_db"))
              for i, s in enumerate(series)]
        p = Plot(f"{args.round} · 量化噪声 QSNR（来源 evidence/{metrics.QSNR_FILE}，"
                 f"{len(series)} 个采样步）", "step", "QSNR (dB)")
        p.add("weight", wd, "#0984e3", 1.8)
        p.add("activation", ad, "#e17055", 1.8)
        wrote.append((out_dir / "qsnr.svg", p.svg()))
    else:
        notes.append("没有量化噪声采样（evidence/eval_clamp_qsnr.json）⇒ 不出 qsnr 图")

    # ── 三段耗时 ──
    rows = []
    for stage in ("train", "convert", "eval"):
        fp = ev / f"{stage}.exec.json"
        if fp.is_file():
            try:
                d = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(d.get("duration_s"), (int, float)) and not d.get("dry_run"):
                    rows.append((stage, d["duration_s"]))
            except Exception:  # noqa: BLE001
                pass
    if rows:
        wrote.append((out_dir / "timing.svg",
                      Bars(f"{args.round} · 三段净耗时（来源 evidence/<段>.exec.json）", rows).svg()))
    else:
        notes.append("没有可用的 <段>.exec.json ⇒ 不出耗时图")

    if not wrote:
        print("charts.py：一张图都出不掉 —— " + "；".join(notes), file=sys.stderr)
        return 2
    for path, _content in wrote:
        print(f"  {'将写' if args.print_only else '写'} {path}")
    for n in notes:
        print(f"  ⚠ {n}", file=sys.stderr)
    if args.print_only:
        return 0
    for path, content in wrote:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"charts.py：出了 {len(wrote)} 个文件（纯标准库，无第三方依赖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
