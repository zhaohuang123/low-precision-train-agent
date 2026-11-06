# MindSpeed —— MXFP4 内核的「≤ −127 硬清零」bug 与 `QAT_MASK_FIX`

> **这条笔记回答什么**：为什么一次 W4A4 QAT 的 MMLU **低于 4 选 1 的盲猜**却看起来像"方案效果差"；
> 以及怎么用一个**可迁移的公共 patch** 把它修掉（而不是靠某台机器上没随交接包走的本地改动）。
> 落点：`knowledge/frameworks/patches/mxfp4-mask-fix/`（按「仓 / 仓内相对路径」分目录）。
> 来历：这条 bug 是在历史实验里**撞上并测出来**的（W4A4 QAT 轮次里"mask fix 双开"是当时的一个自变量），
> 但那次修复只活在某台机器的检出里、没随交接包走 —— 所以 0.18.10 把它做成**公共 patch**。
> 性质：**公共 patch**（跨轮复用；在上游 `origin/master` 干净工作树 `git apply --check` 通过，
> 笔记 §3 那三条行为判据全过）。

---

## 1. 一句话

上游 MXFP4 假量化内核里有两行会把**所有 ≤ −127 的值硬清零**：

```python
mask = (tensor > -FP32_EXPONENT_BIAS).float()   # FP32_EXPONENT_BIAS = 127.0
tensor = tensor * mask
```

`−14016` 这样的**大负离群值**直接被乘成 `0` —— 而离群值恰恰是低精度量化最需要保护的东西。
后果不是"精度差一点"，是**模型根本没在正常工作**：4 选 1 的 MMLU 落在盲猜（0.25）以下。

## 2. 证据（这条不是推测）

| 量 | 值 | 说明 |
|---|---|---|
| 未修时的 MMLU | **0.2295** | < 0.25（4 选 1 盲猜）⇒ 数字无效，不是"方案弱" |
| 修掉后的 MMLU | **+0.0692** | 0.2987（base-init）／0.3372（SFT-init） |
| 行为对照（本机实测） | `−14016 → 0.0`（未修）／`→ −8192.0`（已修） | §3 自检打的就是这条 |

> 判据只能是**行为**：`grep` 到 `QAT_MASK_FIX` 字样不代表开关真的接管了那两行。
> 历史上踩过的坑正是"字在文件里、钩子不在、数字照出、还不报错"（那两行仍在 `else` 分支里）。

## 3. patch 怎么打、怎么验

```
patches/mxfp4-mask-fix/
  core/mindspeed/core/qat/w4a16_fake_quantization.patch   ← 目录树就是目标路径
```

打之前先看**上游原版长什么样**（`file:line` 是基线，不是本机改过的副本）：

| 位置（上游 `origin/master`） | 内容 |
|---|---|
| `mindspeed/core/qat/w4a16_fake_quantization.py:7-8` | `FP32_EXPONENT_BIAS = 127.0` ／ `FP32_MIN_NORMAL` |
| 同文件 `:11` | `def w4a16_fake_quant(tensor, ebits, mbits, qdim=-1)` |
| 同文件 **`:29-30`** | **bug 就在这两行**（`mask = (tensor > -FP32_EXPONENT_BIAS)…` ＋ `tensor = tensor * mask`） |

```bash
# 打（在**上游**检出上；已含开关的树会 apply 失败 —— 那就是"已经修好了"）
cd <MindSpeed 检出>
git apply <知识库>/knowledge/frameworks/patches/mxfp4-mask-fix/core/mindspeed/core/qat/w4a16_fake_quantization.patch
```

**验行为，不验字面**（`grep` 到 `QAT_MASK_FIX` 不代表开关接管了那两行 —— 它们仍在 `else` 分支里）：

```bash
cd <MindSpeed 检出> && QAT_MASK_FIX_VERBOSE=0 python3 - <<'PY'
import importlib, os, torch
k = importlib.import_module("mindspeed.core.qat.w4a16_fake_quantization")
def q(env):
    os.environ.pop("QAT_MASK_FIX", None)
    if env: os.environ["QAT_MASK_FIX"] = env
    x = torch.tensor([[-14016.0, 1.0, -2.0, 3.0] + [0.5] * 28])
    with torch.no_grad(): return float(k.w4a16_fake_quant(x, 4, 2, qdim=-1)[0, 0])
assert hasattr(k, "mask_fix_enabled"), "补丁没打上（模块里没有 mask_fix_enabled）"
off, on1, on2 = q(None), q("1"), q("2")
print("  不设开关 ⇒", off, "｜=1 ⇒", on1, "｜=2 ⇒", on2)
assert off == 0.0,        "上游行为被改掉了（逃生阀失效）"
assert on1 != 0.0 and on1 == on1 and abs(on1) != float("inf"), "=1 没生效"
assert on2 == on1,        "=2 应与 =1 同义"
print("  ✓ 三条判据全过：开关真的接管了那两行")
PY
```

本机实测（0.18.10 验收，三条判据）：`不设开关 ⇒ 0.0｜=1 ⇒ −8192.0｜=2 ⇒ −8192.0`；
同一条判据在**未打补丁**的上游树上会先 `assert hasattr` 失败 —— 这正是"没装上就报错"。

## 4. ★ 两侧必须同开关（否则 Δ 里混进的是内核差异）

这个 bug 在**训练侧与评测侧各有一份内核**：

| 侧 | 开关 | 说明 |
|---|---|---|
| 训练 | `QAT_MASK_FIX=1` | 本 patch |
| 评测 | 与训练同值（**本工程未预置**：当轮在 `round.env` 里给，由该任务的评测驱动透传） | 不设 ⇒ 用的仍是**未修**内核；驱动里没有这条透传，就该按「评测侧还没接上」处理，不许当成同一内核 |

**规矩：一轮实验里两侧要么都开、要么都不开。** 只开一侧时，"训练 vs 评测"的差值里混进了
内核版本差异 —— 那正是"看着像方案问题、其实是脚手架问题"的一类。`run.env`／`criterion.yaml`
里应把开关写成**两侧同名同值**的显式项，并在报告里点名它们。

## 5. 为什么默认保留上游行为（不是漏改）

1. **逃生阀**："`QAT_MASK_FIX=0` 复现历史 bug 数字"这条路必须仍然真的能复现 bug ——
   否则闸门与逃生阀都成了死声明；
2. **共用安装**：本 patch 对不设变量的其它使用者是**严格 no-op**（行为与上游逐字相同）；
3. 因此**开不开是一轮实验的显式自变量**，不是补丁的默认值。

## 6. 与 `QAT_CLAMP_FIX` 是**两个**内核问题，别混

| | 触发 | 修法 | 由谁管 |
|---|---|---|---|
| **mask**（本文） | 值 ≤ −127 被硬清零 | 跳过那两行 | `QAT_MASK_FIX` |
| **clamp** | 共享指数溢出 ⇒ 写 `NaN` | 换成**值 clamp**（`[−127, +127]`，位置/先后有判据） | `QAT_CLAMP_FIX` |

`QAT_MASK_FIX` **管不了** clamp 那条：它们是同一条内核函数里两个不同的分支，
一个管"输入太负"，一个管"共享指数超出 E8M0 可表示范围"。

## 7. 写进报告时怎么表述

- 这一轮的 MMLU 若在 **0.25 以下**（4 选 1），先别下"方案弱"的结论 —— 先查本 patch 有没有打、
  `QAT_MASK_FIX` 有没有开、两侧是否同值；
- 报告里点名：`QAT_MASK_FIX` 的取值、patch 是否打上（§3 自检的 rc）、以及
  "本轮 Δ 是否跨过了内核版本变化"。
