#!/usr/bin/env python3
"""validate_round.py —— **每轮必跑的门**（方案冻结、花卡之前）。

归属：轮次门的唯一实现（方案块规则 1–7、纪律规则 8–11）。

为什么它必须在 `runtime/` 而不是 `devtools/`：
    只放 `devtools/` 就只有开发期有人跑 —— 用户与 agent 每轮都不触发它，铁律会退化成文档里的一句话。
    它是**每轮流程（用户/agent 触发）**的一部分，由流水线在**方案冻结、花卡之前**调用。

用法（本工程的唯一入口）：
    python3 runtime/validate_round.py <轮次>/design.md
    退出 0 = 通过；退出 2 = 不通过（**拒绝开跑**）。
    不通过时：显式错误行**追加**进 `<轮次>/test.md`（不存在则 `report.md`；两个都不存在就建 `test.md`）；
    用户在对话里只看到一句人话，**不需要知道任何工具名**
    （例如「本轮不能开跑：③实现手段缺 patch（旋钮 X 标了 requires_code: true）」）。

`requires_code` 是**旋钮级、且与取值相关**的属性 —— 校验**逐条按 `value` 判**，不按旋钮名判（§9 开头）。

★ 0.18.0：`config/variables.yaml`（旋钮字典）**已删除**。它想用一张静态表同时回答三个不同的问题
（上游框架有没有这条轴／哪一轮实验把它改进来／本轮要不要再挂 patch），而答案是抄来的、必然过期
（实测：`rotation` 标 `framework_native: true`，实际是 R-0006 那轮提交进框架仓的）。
现在本文件只保留**不依赖任何外部知识**的一条自洽规则：
`requires_code: true` ⇒ 本轮 `implementation.patch` 必须非空。
旋钮名与取值**不再有白名单** —— 由 architect 自己读框架代码判定并在 design.md 正文写清依据；
写错的旋钮会在起训练时**响亮**失败，不静默。

**规则实现只此一份**：`devtools/validate_design.py`（P8）必须
`from validate_round import validate_design`，不另写一套。任务配置**本体**的字段校验仍只
`runtime/config.py` 一份（§10 规则 7）；本文件额外做两条**只读**交叉校验（0.18.14 起，
`_cross_checks`）：训练步数判据⇄任务配置一致、`success.require` 的指标名可解析 ——
它们只在"两处都写了"时比对，判据里没写即视为无冲突（不制造第二份权威）。

**YAML 解析原语只有一份**：受控块的保守子集解析住在 `runtime/config.py`，本文件
`from config import ...` 用**同一份**（两套解析必然静默分岔）。

本文件不含任何模型名／任务名／数据集名／阈值默认值（`devtools/check_decoupling.py` 会查）。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ★ 字典读取器与保守 YAML 子集**只有一份**，住在 `runtime/config.py`（`TODO(P4d)` 已收口）。
#   本文件 import 那**同一份**实现，不再自带第二份解析（两套解析必然静默分岔）。
#   显式把本文件所在目录放在 sys.path 首位：`python3 runtime/validate_round.py` 与
#   `devtools/validate_design.py` 的 `sys.path.insert(0, <root>/runtime)` 两条路都拿得到。
#: 配置根的标记文件：找到它算到了工程根（0.18.0 起不再用 `config/variables.yaml` 当标记 —— 那个文件已删）
ROOT_MARKER = Path("VERSION")

_RUNTIME_DIR = Path(__file__).resolve().parent
if str(_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_DIR))
from config import (  # noqa: E402  （上面必须先把 runtime/ 放进 sys.path）
    ContractError,
    GateError,
    _indent,
    _key_ok,
    _scalar,
    _split_top,
    _strip_comment,
    flow_value,
    has_comment,
    is_placeholder,
)

BLOCK_BEGIN = "<!-- LP-SCHEME-BEGIN -->"
BLOCK_END = "<!-- LP-SCHEME-END -->"

REQUIRED_KEYS = ("schema", "id", "axis", "question_ref", "strength_target",
                 "variables", "implementation")
AXES = ("precision", "scale_granularity", "rotation", "layer_policy", "clamp",
        "rounding", "qat_schedule", "master_weight", "train_hparam", "kernel_fix")
#: `strength_target` 是**自由文本**（也可写 `null`）：它是方案作者给自己写的一句"本臂想证明到什么程度"，
#: **没有机器判据**、不参与任何判定（判定只认 `outcome` ＋ 一句话理由 ＋ 证据指针）。
#: 本文件只做**类型**检查（字符串或 null），不认档位、不解释内容 —— 曾经那套 `L1|L2|L3` 枚举已按
#: 「减法」删掉（枚举会把"档位"变成一道必须过的机器闸，而它本来只是一句话）。
STRENGTH_TARGET_TYPE = (str, type(None))
#: 「键在、值明确写成 null」也算合法的必需键。只有 `strength_target`：
#: null 的语义＝「本轮不设强度目标」。其余必需键写成 null 一律仍按缺键处理
#: （它们的取值规则本来就表达不了「合法的 null」）。
NULLABLE_REQUIRED_KEYS = ("strength_target",)
FORBIDDEN_WORDS = ("依据", "假设", "阈值", "判据")
MAX_BLOCKS = 6

# ---------------------------------------------------------------------------
# design.md：块切分（§10 规则 1、2）
# ---------------------------------------------------------------------------

def _where(block: dict, bid=None) -> str:
    tag = bid if bid is not None else (block.get("id") or "未命名")
    return f"块 #{block['no']} (id={tag})"


def split_blocks(text: str) -> tuple:
    lines = text.split("\n")
    blocks, errors, cur = [], [], None
    for no, line in enumerate(lines, 1):
        s = line.strip()
        if s == BLOCK_BEGIN:
            if cur is not None:
                errors.append(f"ERROR {no} 行：{BLOCK_BEGIN} 出现时上一块还没 {BLOCK_END}"
                              f" —— 块**不许嵌套**（§10 规则 1）")
                cur = None
            cur = [no, []]
            continue
        if s == BLOCK_END:
            if cur is None:
                errors.append(f"ERROR {no} 行：{BLOCK_END} 没有配对的 {BLOCK_BEGIN}"
                              f"（§10 规则 1：标记必须成对）")
                continue
            blocks.append({"no": len(blocks) + 1, "start": cur[0],
                           "lines": cur[1], "line0": cur[0] + 1})
            cur = None
            continue
        if cur is not None:
            cur[1].append(line)
    if cur is not None:
        errors.append(f"ERROR {cur[0]} 行：{BLOCK_BEGIN} 到文件结束都没有 {BLOCK_END}"
                      f" —— 标记必须成对（§10 规则 1）")
    if not blocks and not errors:
        errors.append(f"ERROR 一个受控块都没有：候选方案必须用 {BLOCK_BEGIN} / "
                      f"{BLOCK_END} 包起来（§10 规则 1：1–{MAX_BLOCKS} 个块）")
    elif len(blocks) > MAX_BLOCKS:
        errors.append(f"ERROR 有 {len(blocks)} 个块，超过上限 {MAX_BLOCKS}（§10 规则 1）")
    return blocks, errors


def extract_yaml(block: dict) -> tuple:
    """取块内**恰好 1 个** ```yaml（§10 规则 2）。返回 (yaml_text, yaml_line0, errors)。"""
    errors, fences, keep, body = [], [], False, []
    for off, line in enumerate(block["lines"]):
        s = line.strip()
        if s.startswith("```"):
            fences.append((off, s[3:].strip()))
            if keep:
                keep = False
            elif s[3:].strip() in ("yaml", "yml"):
                keep, body = True, []
            continue
        if keep:
            body.append((line, block["line0"] + off))
    if len(fences) != 2:
        errors.append(f"ERROR {_where(block)} 块内有 {len(fences)} 个代码围栏，"
                      f"必须**恰好 2 个**（一对 ```yaml … ```；§10 规则 2）")
        return "", block["line0"], errors
    lang = fences[0][1]
    if lang not in ("yaml", "yml"):
        errors.append(f"ERROR {_where(block)} 唯一的代码块语言是 {lang or '(空)'}，"
                      f"必须是 ```yaml（§10 规则 2）")
        return "", block["line0"], errors
    if not body:
        errors.append(f"ERROR {_where(block)} 的 ```yaml 是空的（§10 规则 2/3）")
    return "\n".join(b[0] for b in body), (body[0][1] if body else block["line0"]), errors


# ---------------------------------------------------------------------------
# 块内 YAML（保守子集）
# ---------------------------------------------------------------------------

def _parse_implementation(lines, i, yline0):
    impl, errors = {}, []
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        body = _strip_comment(raw)
        if not body.strip():
            i += 1
            continue
        if _indent(body) <= 0:
            break
        if _indent(body) != 2:
            errors.append(f"ERROR {yline0 + i} 行：`implementation` 下的键必须缩进 2："
                          f"{raw.strip()!r}")
            i += 1
            continue
        key, _, rest = body.strip().partition(":")
        key, rest = key.strip(), rest.strip()
        if key == "patch" and not rest:
            items, i, errs = _parse_patch(lines, i + 1, yline0)
            impl["patch"] = items
            errors.extend(errs)
            continue
        try:
            impl[key] = flow_value(rest) if rest else None
        except GateError as e:
            errors.append(f"ERROR {yline0 + i} 行：{e}")
        i += 1
    return impl, i, errors


def _parse_patch(lines, i, yline0):
    items, errors, cur = [], [], None
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        body = _strip_comment(raw)
        if not body.strip():
            i += 1
            continue
        ind = _indent(body)
        if ind <= 2:
            break
        s = body.strip()
        if ind == 4 and s.startswith("-"):
            if cur is not None:
                items.append(cur)
            cur = {}
            s = s[1:].strip()
            if not s:
                i += 1
                continue
        elif ind < 4 or cur is None:
            errors.append(f"ERROR {yline0 + i} 行：`patch` 下的项必须缩进 4 且以 `-` 开头："
                          f"{raw.strip()!r}")
            i += 1
            continue
        key, _, rest = s.partition(":")
        try:
            cur[key.strip()] = flow_value(rest) if rest.strip() else None
        except GateError as e:
            errors.append(f"ERROR {yline0 + i} 行：{e}")
            cur[key.strip()] = None
        i += 1
    if cur is not None:
        items.append(cur)
    return items, i, errors


def parse_block_yaml(ytext: str, yline0: int, block: dict) -> tuple:
    errors = []
    doc = {"_line": {}, "_varlines": {}, "_var_has_comment": {}}
    lines = ytext.split("\n")

    # §10 规则 2：保守子集里不许出现锚点/别名/多文档
    for off, raw in enumerate(lines):
        b = _strip_comment(raw)
        if b.strip().startswith("---") or "<<" in b or b.strip().startswith("&"):
            errors.append(f"ERROR {yline0 + off} 行：保守子集不允许锚点/别名/多文档："
                          f"{raw.strip()!r}（§10 规则 2）")

    i = 0
    while i < len(lines):
        raw = lines[i]
        no = yline0 + i
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        body = _strip_comment(raw)
        if not body.strip():
            i += 1
            continue
        if _indent(body) != 0:
            errors.append(f"ERROR {no} 行：顶层键必须顶格（实际缩进 {_indent(body)}）："
                          f"{raw.strip()!r}")
            i += 1
            continue
        key, _, rest = body.strip().partition(":")
        key, rest = key.strip(), rest.strip()
        if not _key_ok(key):
            errors.append(f"ERROR {no} 行：键名不合规（必须小写加下划线）：{key!r}（§10 规则 2）")
            i += 1
            continue
        if key == "variables" and not rest:
            doc.setdefault("variables", {})
            i += 1
            while i < len(lines):
                r2 = lines[i]
                n2 = yline0 + i
                if not r2.strip() or r2.lstrip().startswith("#"):
                    i += 1
                    continue
                b2 = _strip_comment(r2)
                if not b2.strip():
                    i += 1
                    continue
                if _indent(b2) <= 0:
                    break
                if _indent(b2) != 2:
                    errors.append(f"ERROR {n2} 行：`variables` 下的变量名必须缩进 2："
                                  f"{r2.strip()!r}")
                    i += 1
                    continue
                k2, _, v2 = b2.strip().partition(":")
                k2 = k2.strip()
                if not _key_ok(k2):
                    errors.append(f"ERROR {n2} 行：变量名不合规（必须小写加下划线）：{k2!r}"
                                  f"（§10 规则 2）")
                try:
                    val = flow_value(v2) if v2.strip() else None
                except GateError as e:
                    errors.append(f"ERROR {n2} 行：{e}")
                    val = None
                doc["variables"][k2] = val
                doc["_varlines"][k2] = (r2, n2)
                doc["_var_has_comment"][k2] = has_comment(r2)
                i += 1
            continue
        if key == "implementation" and not rest:
            impl, i, errs = _parse_implementation(lines, i + 1, yline0)
            doc["implementation"] = impl
            errors.extend(errs)
            continue
        try:
            doc[key] = flow_value(rest) if rest else None
        except GateError as e:
            errors.append(f"ERROR {no} 行：{e}")
        doc["_line"][key] = no
        i += 1

    # §10 规则 6：块里不许出现依据/假设/阈值/判据（**报错带行号**）
    for w in FORBIDDEN_WORDS:
        for off, raw in enumerate(lines):
            if w in raw:
                errors.append(
                    f"ERROR {yline0 + off} 行：块里出现「{w}」：{raw.strip()!r}\n"
                    f"  ⇒ 依据与假设归 design.md **正文**，判定与口径归 **criterion.yaml**；"
                    f"受控块只放机器可读的选值与落地引用（§10 规则 6）")
                break
    return doc, errors


# ---------------------------------------------------------------------------
# 规则 3–11
# ---------------------------------------------------------------------------

def _iron_law_msg(tags: str, var: str) -> str:
    return (f"ERROR {tags}\n"
            f"  variables.{var}.requires_code=true，但 implementation.patch 为空\n"
            f"  ⇒ 该方案不可执行：要么在 implementation.patch 给出改代码引用，"
            f"要么把 requires_code 改成 false")


def validate_block(block: dict, doc: dict, rdir: Path, seen_ids: set) -> tuple:
    errors, iron_var = [], None
    bid = doc.get("id")
    tags = _where(block, bid)

    # §10 规则 3：必需键一个都不能少。★ 「键不存在」与「键存在、值写成 null」是两回事 ——
    #   `strength_target: null` 是**明确允许**的取值（语义＝「本轮不设强度目标」），
    #   键在就是键在，不许被当成缺键（P9 实测：旧判法 ⇒ 该值永远过不了门，
    #   红 → 绿只能靠随手填一个档位，那是在改方案，不是在过门）。
    #   其余必需键写成 null 仍然算缺键：它们的取值规则里没有「合法的 null」这一档。
    for k in REQUIRED_KEYS:
        if k not in doc or (doc[k] is None and k not in NULLABLE_REQUIRED_KEYS):
            ln = doc["_line"].get(k)
            errors.append(f"ERROR {tags} 缺必需键 `{k}`"
                          + (f"（{ln} 行附近）" if ln else "")
                          + f"（§10 规则 3：{list(REQUIRED_KEYS)} 一个都不能少；"
                          + (f"{k} 允许写成 null 但键必须在）"
                             if k in NULLABLE_REQUIRED_KEYS else "键与值都不能空）"))
    if not isinstance(bid, str) or not bid.strip():
        errors.append(f"ERROR {tags} `id` 必须是非空字符串（§10 规则 3）")
    else:
        if bid in seen_ids:
            errors.append(f"ERROR {tags} `id` 在同一轮内重复：{bid!r}（§10 规则 3）")
        seen_ids.add(bid)
    if doc.get("schema") != 1:
        errors.append(f"ERROR {tags} `schema` 必须是 1（实际 {doc.get('schema')!r}）（§10 规则 3）")
    if doc.get("axis") not in AXES:
        errors.append(f"ERROR {tags} `axis`={doc.get('axis')!r} 不在枚举里（§10：{list(AXES)}）")
    # `strength_target`：只查**类型**（字符串或 null），不查档位 —— 它是自由文本，
    # 内容不参与任何判定（判定只认 outcome ＋ 一句话理由 ＋ 证据指针）。
    if "strength_target" in doc and not isinstance(doc["strength_target"], STRENGTH_TARGET_TYPE):
        errors.append(f"ERROR {tags} `strength_target`={doc['strength_target']!r} "
                      f"必须是**字符串或 null**（自由文本；没有档位枚举，内容不做机器判定）\n"
                      f"      ⇒ 写成 list/dict 这类结构化值多半是想表达别的东西，"
                      f"请改用一句话或 null")
    if not isinstance(doc.get("question_ref"), (str, int)) or doc.get("question_ref") in (None, ""):
        errors.append(f"ERROR {tags} `question_ref` 必须非空"
                      f"（§10 规则 3：填本份 criterion.yaml 的 id）")

    variables = doc.get("variables")
    if variables is None:
        variables = {}
    if not isinstance(variables, dict):
        errors.append(f"ERROR {tags} `variables` 必须是映射（§10 规则 3/4）")
        variables = {}
    # ★ 允许空映射（0.18.14）：基线轮这种"只评测、不训练"的轮次**没有自变量**，
    #   逼它编一个变量才是造假（`variables` 的形状仍然照 §9 规则 8 逐条校验；
    #   整个键缺失仍按 `REQUIRED_KEYS` 报错，这里只放宽"非空"）。
    for name, spec in variables.items():
        _vline, vno = doc["_varlines"].get(name, (None, None))
        at = f"{tags} 第 {vno} 行" if vno else tags
        if not isinstance(spec, dict):
            errors.append(
                f"ERROR {at}\n  variables.{name} 必须写成 {{value: …, requires_code: …}}；"
                f"实际是 {spec!r}\n"
                f"  ⇒ §9 规则 8：写出来的变量必须**同时**有 value 与 requires_code")
            continue
        if "value" not in spec:
            errors.append(f"ERROR {at}\n  variables.{name} 缺 `value`（§9 规则 8）")
        if "requires_code" not in spec:
            errors.append(f"ERROR {at}\n  variables.{name} 缺 `requires_code`（§9 规则 8）")
            continue
        rc = spec["requires_code"]
        if not isinstance(rc, bool):
            errors.append(f"ERROR {at}\n  variables.{name}.requires_code={rc!r} "
                          f"必须是 true/false（§9 规则 8）")
            continue
        if rc:
            iron_var = name

    impl = doc.get("implementation")
    if not isinstance(impl, dict):
        errors.append(f"ERROR {tags} `implementation` 必须是映射（§10 规则 3）")
        return errors, bid, iron_var
    patch = impl.get("patch")
    mode = impl.get("mode")
    if mode not in ("framework_native", "patch", "mixed"):
        errors.append(f"ERROR {tags} implementation.mode={mode!r} 只允许 "
                      f"framework_native|patch|mixed（§10 格式）")
    if iron_var is not None:
        if not (isinstance(patch, list) and patch):
            errors.append(_iron_law_msg(tags, iron_var))
        else:
            if mode == "framework_native":
                errors.append(
                    f"ERROR {tags}\n  variables.{iron_var}.requires_code=true，但 "
                    f"implementation.mode=framework_native\n"
                    f"  ⇒ 有 patch 就不能写成「纯配置」：mode 要是 patch 或 mixed（§9 表 2/3）")
            for n, item in enumerate(patch, 1):
                if not isinstance(item, dict):
                    errors.append(f"ERROR {tags}\n  implementation.patch 第 {n} 条不是映射"
                                  f"（§9 表 2）")
                    continue
                ref, why = item.get("ref"), item.get("why")
                if not isinstance(ref, str) or not ref.strip():
                    errors.append(f"ERROR {tags}\n  implementation.patch 第 {n} 条缺 `ref`"
                                  f"（§9 表 2）")
                    continue
                if not isinstance(why, str) or not why.strip():
                    errors.append(f"ERROR {tags}\n  implementation.patch 第 {n} 条缺 `why`"
                                  f"（§9 表 2：一句话说清为什么必须改代码）")
                target = Path(ref) if os.path.isabs(ref) else (rdir / ref)
                if not target.exists():
                    errors.append(
                        f"ERROR {tags}\n  implementation.patch 第 {n} 条的 ref 指向的文件不存在："
                        f"{ref}（相对本轮次目录 {rdir}）（§9 规则 11）")
    else:
        if isinstance(patch, list) and patch:
            errors.append(
                f"ERROR {tags}\n  variables 全部 requires_code=false（纯配置），但 implementation "
                f"非空：{{mode: {mode!r}, patch: ……}}\n"
                f"  ⇒ 零代码改动的方案，③ 只能是 {{mode: framework_native}}；"
                f"若确实要挂 patch，请把对应变量改成 requires_code: true（§9 表 1/3）")
        elif mode != "framework_native":
            errors.append(
                f"ERROR {tags}\n  variables 全部 requires_code=false ⇒ implementation.mode 必须是 "
                f"framework_native（实际 {mode!r}）（§9 表 1/3）")
    return errors, bid, iron_var


def human_hint(errors: list) -> str:
    """给用户看的**一句人话**（工具名不进对话）。"""
    for e in errors:
        if "implementation.patch 为空" in e:
            var = ""
            for line in e.split("\n"):
                line = line.strip()
                if line.startswith("variables.") and ".requires_code=true" in line:
                    var = line[len("variables."):].split(".")[0]
            return (f"本轮不能开跑：③实现手段缺 patch"
                    f"（旋钮 `{var}` 标了 `requires_code: true`）")
        if "零代码改动的方案" in e:
            return ("本轮不能开跑：方案声明零代码改动，却挂了 patch"
                    "（要么去掉 patch，要么把变量改成 requires_code: true）")
        if "缺必需键" in e:
            return "本轮不能开跑：方案块缺必需字段"
    return "本轮不能开跑：方案块不符合受控格式（详见本轮 test.md）"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def find_root(start: Path | None = None) -> Path | None:
    """`LP_ROOT` 优先（指错不回退，fail-closed）→ 从本文件向上找含 `VERSION` 的目录。"""
    env = os.environ.get("LP_ROOT")
    if env:
        p = Path(env)
        return p if (p / ROOT_MARKER).is_file() else None
    here = (start or Path(__file__).resolve().parent).resolve()
    for d in (here, *here.parents):
        if (d / ROOT_MARKER).is_file():
            return d
    return None


def validate_design(design_path: Path) -> list:
    """**唯一一份规则实现**：返回错误行列表（空 = 通过）。

    `devtools/validate_design.py`（P8）复用本函数，不另写一套（§9／§10 规则 7）。
    """
    rdir = design_path.parent
    try:
        text = design_path.read_text(encoding="utf-8")
    except OSError as e:
        return [f"ERROR design.md 读不出来（{e}）：{design_path}"]
    blocks, errors = split_blocks(text)
    seen_ids = set()
    for block in blocks:
        ytext, yline0, errs = extract_yaml(block)
        errors.extend(errs)
        if not ytext.strip():
            continue
        doc, errs = parse_block_yaml(ytext, yline0, block)
        errors.extend(errs)
        be, bid, _ = validate_block(block, doc, rdir, seen_ids)
        block["id"] = bid
        errors.extend(be)
    return errors


TEST_MD_MARK = "## 每轮门 `runtime/validate_round.py` 未通过"


def _record_target(rdir: Path) -> Path:
    """错误行落点：`test.md` 优先，其次 `report.md`，都不在就建 `test.md`（**只写一处**）。"""
    for name in ("test.md", "report.md"):
        if (rdir / name).is_file():
            return rdir / name
    return rdir / "test.md"


def record_to_md(design_path: Path, errors: list) -> Path | None:
    path = _record_target(design_path.parent)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    head = ""
    if not path.exists():
        head = ("# test.md\n\n"
                "> 归档：冒烟结果、候选配置、run 命令与预期耗时（tester 写）。\n"
                "> 本文件也被每轮门 `runtime/validate_round.py` 追加「未通过」记录。\n\n")
    body = [f"\n{TEST_MD_MARK}（{stamp}）\n",
            f"人话：{human_hint(errors)}\n",
            f"门：`python3 runtime/validate_round.py {design_path.name}` ⇒ 退出 `2`；"
            f"**拒绝开跑**（方案冻结、花卡之前）。\n",
            "```text"]
    body.extend(errors)
    body.append("```\n")
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(head + "\n".join(body))
    except OSError:
        return None
    return path


# ---------------------------------------------------------------------------
# 交叉校验：判据 ⇄ 任务配置（★ 不新增任何配置键，只用两边已有的字段对账）
# ---------------------------------------------------------------------------

#: `success.require` 里 `<数据集>/<尺子>` 的形状（驱动写出的键名就是这个形状）。
METRIC_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+")


def _key_line(path: Path, key: str) -> str:
    """`文件:行` —— 取该键在文本里第一次出现的行号（找不到就只给文件名，不猜）。"""
    try:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(rf"\s*{re.escape(key)}\s*:", line):
                return f"{path}:{i}"
    except OSError:
        pass
    return str(path)


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _cross_checks(design_path: Path, root: Path) -> "list[str]":
    """判据 ⇄ 任务配置 的两条对账（**花卡之前**拦下来；不引入新字段）。

    1. **训练步数只能有一个权威落点**：任务配置的 `stop_conditions.max_steps` 是真驱动
       （`train_cmd.sh` 拼进 `--train-iters`）。判据里若也写了一份，必须与它相等 ——
       否则"改判据那行不影响训练"会变成花卡事故。判据里**没写**则视为无冲突（不强制第二份）。
    2. **指标名必须能解析**：`success.require` 里出现的 `<数据集>/<尺子>` 必须在
       `eval_protocol.datasets[].name`（判据）或 `eval.datasets[].name`（任务配置）里存在 ——
       防 `"<数据集A>和<数据集B>"` 这种复合串静默通过、报告照写。
    """
    errors: list[str] = []
    round_dir = design_path.parent
    if round_dir.parent.name != "rounds":
        return errors  # 不是 <产物根>/rounds/<轮次>/ 布局 ⇒ 不猜，跳过（不是错误）
    task_id = round_dir.parent.parent.name
    crit_path = round_dir / "criterion.yaml"
    task_path = root / "config" / "tasks" / f"{task_id}.yaml"
    if not crit_path.is_file() or not task_path.is_file():
        return errors

    from config import _dig, _load_task_yaml  # noqa: E402  （与 config.py 同一份 YAML 读取）

    try:
        crit = _load_task_yaml(crit_path)
        task = _load_task_yaml(task_path)
    except ContractError as exc:
        return [f"ERROR 交叉校验读不了配置：{exc}"]

    # ---- ① 训练步数 ----
    cm = _dig(crit, "stop_conditions.max_steps")
    tm = _dig(task, "stop_conditions.max_steps")
    if cm is not None:
        if not isinstance(cm, int) or isinstance(cm, bool) or cm <= 0:
            errors.append(
                f"ERROR {_key_line(crit_path, 'max_steps')}\n"
                f"  criterion.yaml 的 `stop_conditions.max_steps` = {cm!r}：必须是**正整数**。\n"
                f"  （模板里的 0 表示「还没填」—— 它会让 `steps_reached_max` 恒真，等于一条假事实。）"
            )
        elif tm is None:
            errors.append(
                f"ERROR {_key_line(task_path, 'max_steps')}\n"
                f"  任务配置缺 `stop_conditions.max_steps` ⇒ 训练命令拼不出 `--train-iters`。"
            )
        elif int(cm) != int(tm):
            errors.append(
                f"ERROR 训练步数两处不一致（**只有一个权威落点**：任务配置）：\n"
                f"  任务配置 {_key_line(task_path, 'max_steps')} = {tm}（真生效，拼进 `--train-iters`）\n"
                f"  判据     {_key_line(crit_path, 'max_steps')} = {cm}（只透传记录）\n"
                f"  ⇒ 把判据那一处改成 {tm}，或删掉它（删掉即视为无冲突）。"
            )

    # ---- ② 指标名 ----
    known = {str(x.get("name")) for x in _as_list(_dig(crit, "eval_protocol.datasets"))
             if isinstance(x, dict) and x.get("name")}
    known |= {str(x.get("name")) for x in _as_list(_dig(task, "eval.datasets"))
              if isinstance(x, dict) and x.get("name")}
    #: 旧判据（0.18.13 及以前）用 `success.metric` ＋ 一句不带指标名的表达式 —— 兼容，不报错。
    legacy_metric = str(_dig(crit, "success.metric") or "").strip()
    for item in _as_list(_dig(crit, "success.require")):
        if not isinstance(item, str):
            errors.append(
                f"ERROR {_key_line(crit_path, 'require')}\n"
                f"  `success.require` 的每一项都必须是字符串表达式，实际是 {item!r}。"
            )
            continue
        tokens = METRIC_TOKEN_RE.findall(item)
        if not tokens:
            if legacy_metric:
                continue
            errors.append(
                f"ERROR {_key_line(crit_path, 'require')}\n"
                f"  `{item}` 里没有 `<数据集>/<尺子>`：不知道要比哪个指标 ⇒ 判定只能靠猜。\n"
                f"  正确形状：`<数据集>/<尺子> >= 基线 - <差值>`（例：`<数据集>/<尺子> >= 基线 - 0.03`）。"
            )
            continue
        for tok in tokens:
            if tok.split("/", 1)[0] not in known:
                errors.append(
                    f"ERROR {_key_line(crit_path, 'require')}\n"
                    f"  `{item}` 里的指标名 `{tok}` 解析不出来：字符串前面那一段必须是\n"
                    f"  `eval_protocol.datasets[].name` 之一（现有：{sorted(known) or '（一个都没有）'}）。\n"
                    f"  正确形状：`<数据集>/<尺子> >= 基线 - <差值>`（如 `<数据集>/<尺子> >= 基线 - 0.03`）。"
                )
    return errors


def _boundary_note(design_path: Path, root: Path) -> "list[str]":
    """冻结时的**算术摘要**（0.18.38）：本轮最早能在第几步合法停下、训练结束时
    哪些 ckpt 还在盘上。

    两条都是纯算术：不出错、不改 rc —— 引擎不判断"该不该早停"（那是本轮判据的口径，
    由人在 `criterion.yaml` 里写死），只把"计划与配置可能打架"的地方在**花卡之前**
    摆到人眼前：

      ① 平台早停的 `min_steps < max_steps` ⇒ 本轮**不保证跑满**（可能提前收工）；
      ② `keep_last < 落盘次数` ⇒ 判据点名的早期 `ckpt/iter_*` 会被执行器的刈草删掉。

    没有这两条风险时**一个字都不说**（不制造恒红噪声，也不假装是检查器）。
    """
    round_dir = design_path.parent
    if round_dir.parent.name != "rounds":
        return []                      # 不是 <产物根>/rounds/<轮次>/ 布局 ⇒ 不猜
    task_path = root / "config" / "tasks" / f"{round_dir.parent.parent.name}.yaml"
    if not task_path.is_file():
        return []

    from config import _dig, _load_task_yaml  # noqa: E402
    try:
        task = _load_task_yaml(task_path)
    except ContractError:
        return []
    max_steps = _dig(task, "stop_conditions.max_steps")
    if not isinstance(max_steps, int) or isinstance(max_steps, bool) or max_steps <= 0:
        return []

    lines: "list[str]" = []
    plat = _dig(task, "stop_conditions.plateau")
    min_steps = plat.get("min_steps") if isinstance(plat, dict) else None
    if isinstance(min_steps, int) and not isinstance(min_steps, bool) \
            and 0 < min_steps < max_steps:
        lines.append(
            f"  平台早停 plateau.min_steps={min_steps} < max_steps={max_steps}"
            f" ⇒ 本轮**最早第 {min_steps} 步**就能合法收工（不保证跑满）")

    ck = _dig(task, "train.checkpoint")
    every = ck.get("save_interval_steps") if isinstance(ck, dict) else None
    keep = ck.get("keep_last") if isinstance(ck, dict) else None
    if isinstance(every, int) and not isinstance(every, bool) and every > 0 \
            and isinstance(keep, int) and not isinstance(keep, bool) and keep >= 1:
        saves = [i * every for i in range(1, max_steps // every + 1)]
        if len(saves) > keep:
            def _fmt(steps: "list[int]") -> str:
                return " / ".join(f"ckpt/iter_{s:07d}" for s in steps)
            lines.append(f"  ckpt：save_interval={every} ⇒ 落 {len(saves)} 份；"
                         f"keep_last={keep} ⇒ 结束时只剩 {_fmt(saves[-keep:])}")
            lines.append(f"        先被删掉的是 {_fmt(saves[:-keep])}")

    if not lines:
        return []
    return (["本轮边界（**信息，不是判定**）："] + lines
            + ["  ★ 若本轮判据要求「同预算对比／points == max_steps／点名早期 ckpt」，"
               "上面任一条与它矛盾 ⇒ 二选一：",
               "     关掉平台早停（`plateau.min_steps = max_steps`），"
               "或把 `keep_last` 抬到覆盖点名份数。"])


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(
        prog="validate_round.py",
        description="每轮必跑的门：design.md 受控 YAML 块的格式（§10 规则 1–7）"
                    "与铁律（§9 规则 8–11）")
    ap.add_argument("design", nargs="?", help="<轮次>/design.md")
    ap.add_argument("--root", help="配置根（等价于 LP_ROOT；指错即退出 2，不回退）")
    ap.add_argument("--selftest", action="store_true", help="正负对照自检（CPU、0 卡时）")
    args = ap.parse_args(argv)

    if args.root:
        os.environ["LP_ROOT"] = args.root
    if args.selftest:
        return _selftest()
    if not args.design:
        ap.error("必须给 <轮次>/design.md（或 --selftest）")
    root = find_root()
    if root is None:
        env = os.environ.get("LP_ROOT")
        print("ERROR 解析不出配置根"
              + (f"：LP_ROOT={env!r} 指向的树里没有 {ROOT_MARKER}" if env else
                 f"：从 {Path(__file__).resolve().parent} 逐级向上都没有 {ROOT_MARKER}")
              + "\n  ⇒ 退出 2（fail-closed；不许按当前工作目录反推）", file=sys.stderr)
        return 2
    design_path = Path(args.design)
    if not design_path.is_file():
        print(f"ERROR design.md 不存在：{design_path}\n  ⇒ 退出 2（fail-closed）", file=sys.stderr)
        return 2
    try:
        errors = validate_design(design_path)
    except GateError as e:
        errors = [f"ERROR {e}"]
    # 受控块过了才做交叉校验（块本身不合法时那边已经足够说清问题了，不叠噪声）。
    if not errors:
        errors = _cross_checks(design_path, root)
    if not errors:
        for _line in _boundary_note(design_path, root):
            print(_line)
        print(f"OK {design_path}：受控块格式与铁律都过（§9 规则 8–11、§10 规则 1–7；"
              f"判据⇄任务配置交叉校验也过）")
        return 0
    for e in errors:
        print(e, file=sys.stderr)
    landed = record_to_md(design_path, errors)
    print(f"  ⇒ 不通过（退出 2）：**拒绝开跑**。错误行已写入 "
          f"{landed if landed else '（test.md 写不进去！）'}", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# 自检：正负对照（每一条对应规则表里的一行）
# ---------------------------------------------------------------------------

GOOD_1 = """<!-- LP-SCHEME-BEGIN -->
```yaml
schema: 1
id: demo-native
axis: rotation
question_ref: Q-1
rank: 1
strength_target: 冒烟一臂
variables:
  rotation: {value: true, requires_code: false}
implementation:
  mode: framework_native
```
<!-- LP-SCHEME-END -->
"""

GOOD_2 = """<!-- LP-SCHEME-BEGIN -->
```yaml
schema: 1
id: demo-patch
axis: layer_policy
question_ref: Q-1
strength_target: 想做归因拆解
variables:
  exempt_layers: {value: {ref: sets/exempt.txt}, requires_code: true}   # 26 名原生，多要的 up_proj 要 patch
implementation:
  mode: patch
  patch:
    - ref: patches/0001-x.patch
      why: 融合层无法单独豁免，必须拆分支
```
<!-- LP-SCHEME-END -->
"""

def _fixture(tmp, body, tag, with_patch=False):
    d = tmp / tag
    (d / "config").mkdir(parents=True, exist_ok=True)
    (d / "VERSION").write_text("0.18.0\n", encoding="utf-8")
    rdir = d / "experiments" / "t" / "rounds" / "R-0001"
    (rdir / "patches").mkdir(parents=True, exist_ok=True)
    (rdir / "sets").mkdir(parents=True, exist_ok=True)
    if with_patch:
        (rdir / "patches" / "0001-x.patch").write_text("--- a\n+++ b\n", encoding="utf-8")
    (rdir / "sets" / "exempt.txt").write_text("model.layers.1.mlp.down_proj\n", encoding="utf-8")
    (rdir / "design.md").write_text(body, encoding="utf-8")
    return rdir / "design.md", d


def _selftest() -> int:
    import shutil
    import tempfile
    stats = {"n": 0, "fail": 0}

    def case(name, ok, extra=""):
        stats["n"] += 1
        if not ok:
            stats["fail"] += 1
        print(("  ok    " if ok else "  FAIL  ") + name
              + (f"  {extra!r}" if (extra and not ok) else ""))

    tmp = Path(tempfile.mkdtemp(prefix="lp-gate-"))
    try:
        d1, r1 = _fixture(tmp, GOOD_1, "g1")
        case("§9 表 1/3（正向）：纯配置块通过", validate_design(d1) == [],
             validate_design(d1))

        d2, r2 = _fixture(tmp, GOOD_2, "g2", with_patch=True)
        e2 = validate_design(d2)
        case("§9 规则 11（正向）：requires_code=true 且 ref 存在 ⇒ 通过", e2 == [], e2)

        d2b, r2b = _fixture(tmp, GOOD_2, "g2b")
        e2b = validate_design(d2b)
        case("§9 规则 11（负向）：ref 文件不存在 ⇒ 报错（这条不是空门）",
             any("不存在" in e for e in e2b), e2b[:1])

        bad_iron = GOOD_2.replace("""  mode: patch
  patch:
    - ref: patches/0001-x.patch
      why: 融合层无法单独豁免，必须拆分支
""", "  mode: patch\n")
        d3, r3 = _fixture(tmp, bad_iron, "g3")
        e3 = validate_design(d3)
        case("★ 铁律：requires_code=true 但 implementation.patch 为空 ⇒ 报错",
             any("implementation.patch 为空" in e for e in e3), e3[:1])
        case("★ 铁律报错带**块序号**与**变量名**",
             any("块 #1" in e and "exempt_layers.requires_code=true" in e for e in e3), e3[:1])
        case("★ 人话落到用户侧（含 requires_code: true，不含工具名/路径）",
             "本轮不能开跑" in human_hint(e3) and "requires_code: true" in human_hint(e3)
             and "python3" not in human_hint(e3) and "runtime/" not in human_hint(e3),
             human_hint(e3))

        bad_zero = GOOD_1.replace(
            "  mode: framework_native\n",
            "  mode: patch\n  patch:\n    - ref: patches/0001-x.patch\n"
            "      why: 想挂但变量说不用\n")
        d4, r4 = _fixture(tmp, bad_zero, "g4", with_patch=True)
        e4 = validate_design(d4)
        case("§9 表 1/3（负向）：全 false 却有 patch ⇒ 报错",
             any("零代码改动的方案" in e for e in e4), e4[:1])

        cases = [
            ("§9 规则 8：变量缺 requires_code",
             GOOD_1.replace("{value: true, requires_code: false}", "{value: true}"),
             "缺 `requires_code`"),
            ("§9 规则 8：变量缺 value",
             GOOD_1.replace("{value: true, requires_code: false}", "{requires_code: false}"),
             "缺 `value`"),
            ("§10 规则 3：缺必需键 strength_target",
             GOOD_1.replace("strength_target: 冒烟一臂\n", ""), "缺必需键"),
            ("§10 规则 3（负向）：strength_target 写成结构化值 ⇒ 报「必须是字符串或 null」",
             GOOD_1.replace("strength_target: 冒烟一臂", "strength_target: [L1, L2]"),
             "必须是**字符串或 null**"),
            ("§10 规则 3：axis 不在枚举里",
             GOOD_1.replace("axis: rotation", "axis: made_up"), "不在枚举里"),
            ("§10 规则 3：id 在同一轮内重复", GOOD_1 + GOOD_1, "在同一轮内重复"),
            ("§10 规则 6：块里出现「判据」",
             GOOD_1.replace("question_ref: Q-1", "question_ref: Q-1  # 照判据抄的"),
             "块里出现「判据」"),
            ("§10 规则 2：代码块语言不是 yaml",
             GOOD_1.replace("```yaml", "```json"), "必须是 ```yaml"),
            ("§10 规则 2：块内两个代码块",
             GOOD_1.replace("implementation:", "```text\nx\n```\nimplementation:"),
             "必须**恰好 2 个**"),
            ("§10 规则 1：BEGIN 没有配对的 END",
             GOOD_1.replace(BLOCK_END, ""), "标记必须成对"),
            ("§10 规则 1：END 没有配对的 BEGIN", BLOCK_END + "\n", "标记必须成对"),
            ("§10 规则 1：块不许嵌套", BLOCK_BEGIN + "\n" + GOOD_1, "不许嵌套"),
            ("§10 规则 1：0 个块 ⇒ 报错（不是空门）", "# 没有任何块\n", "一个受控块都没有"),
            ("§10 规则 1：超过 6 个块",
             GOOD_1.replace("id: demo-native", "id: a1") * 7, "超过上限"),
            ("§10 规则 2：块里没有代码围栏",
             BLOCK_BEGIN + "\nno fence\n" + BLOCK_END + "\n", "必须**恰好 2 个**"),
            ("§10 规则 2：锚点/别名不许用",
             GOOD_1.replace("implementation:", "&x\nimplementation:"), "锚点/别名"),
        ]
        for name, body, needle in cases:
            d, r = _fixture(tmp, body, "c%d" % stats["n"], with_patch=True)
            errs = validate_design(d)
            case(name, any(needle in e for e in errs), errs[:1])

        # ★ §10 规则 3 的 null 自相矛盾（P9 实测的真缺陷）：键在、值为 null 必须过；
        #   键整个没有才是缺键。三条都用 main() 实测**退出码**，不只比错误串。
        # ★ §10 规则 3 的自由文本（本轮"减法"）：曾经是 `L1|L2|L3` 枚举，任何别的写法都退出 2。
        #   现在 `strength_target` 是自由文本 —— 下面两条证明"枚举没了"：曾经非法的写法现在 rc=0，
        #   而 null（键在）仍然 rc=0。三条都用 main() 实测**退出码**，不只比错误串。
        freetext_body = GOOD_1.replace("strength_target: 冒烟一臂",
                                       "strength_target: L9 —— 曾经非法，现在只是自由文本")
        dfree, rfree = _fixture(tmp, freetext_body, "freetext")
        case("§10 规则 3（正向）：任意自由文本（含旧的非法档位 L9）⇒ 无错误",
             validate_design(dfree) == [], validate_design(dfree)[:1])
        case("★ 实测 rc：自由文本 `strength_target` ⇒ main() 退出 0",
             main([str(dfree), "--root", str(rfree)]) == 0)

        null_body = GOOD_1.replace("strength_target: 冒烟一臂", "strength_target: null")
        dnull, rnull = _fixture(tmp, null_body, "nullok")
        enull = validate_design(dnull)
        case("§10 规则 3（正向）：strength_target: null（键在）⇒ 无错误", enull == [], enull)
        case("★ 实测 rc：strength_target: null ⇒ main() 退出 0",
             main([str(dnull), "--root", str(rnull)]) == 0)

        gone_body = GOOD_1.replace("strength_target: 冒烟一臂\n", "")
        dgone, rgone = _fixture(tmp, gone_body, "nullgone")
        egone = validate_design(dgone)
        case("§10 规则 3（负向）：strength_target 键整个没有 ⇒ 报「缺必需键」",
             any("缺必需键 `strength_target`" in e for e in egone), egone[:1])
        case("★ 实测 rc：strength_target 键删掉 ⇒ main() 退出 2",
             main([str(dgone), "--root", str(rgone)]) == 2)

        both_body = null_body.replace("axis: rotation\n", "")
        dboth, rboth = _fixture(tmp, both_body, "nullplus")
        eboth = validate_design(dboth)
        case("§10 规则 3（负向）：strength_target 为 null 但其它必填（axis）缺 ⇒ 报错",
             any("缺必需键 `axis`" in e for e in eboth), eboth[:1])
        case("★ 实测 rc：null ＋ 其它必填缺 ⇒ main() 退出 2",
             main([str(dboth), "--root", str(rboth)]) == 2)

        d5, r5 = _fixture(tmp, bad_iron, "land")
        n = main([str(d5), "--root", str(r5)])
        tm = d5.parent / "test.md"
        case("★ 不通过时退出码 = 2", n == 2, n)
        case("★ 错误行进 <轮次>/test.md", tm.is_file() and "ERROR" in tm.read_text("utf-8"))
        case("★ test.md 里带人话与门名", tm.is_file()
             and "人话：" in tm.read_text("utf-8")
             and "validate_round.py" in tm.read_text("utf-8"))

        d6, r6 = _fixture(tmp, GOOD_1, "okpath")
        case("通过时退出码 = 0 且不写 test.md",
             main([str(d6), "--root", str(r6)]) == 0 and not (d6.parent / "test.md").exists())

        # ---- 交叉校验：判据 ⇄ 任务配置（0.18.14）----
        cross = tmp / "cross"
        tdir = cross / "rounds" / "R-0001"
        (cross / "config" / "tasks").mkdir(parents=True)
        tdir.mkdir(parents=True)
        (cross / "config" / "tasks" / "cross.yaml").write_text(
            "task_id: cross\nstop_conditions:\n  max_steps: 10\n"
            "eval:\n  datasets:\n    - name: ds1\n    - name: ds2\n", encoding="utf-8")
        cross_design = tdir / "design.md"
        cross_design.write_text("（只借它的父目录定位，不解析内容）\n", encoding="utf-8")
        cross_crit = tdir / "criterion.yaml"

        def _crit(ms, req) -> "list[str]":
            cross_crit.write_text(
                f"schema: 1\nid: c\nstop_conditions:\n  max_steps: {ms}\n"
                f"success:\n  baseline_ref: null\n  require:\n    - \"{req}\"\n"
                "eval_protocol:\n  datasets:\n    - name: ds1\n", encoding="utf-8")
            return _cross_checks(cross_design, cross)

        case("交叉校验（正向）：两处 max_steps 一致 ⇒ 无错误",
             _crit(10, "ds1/exact_match >= 基线 - 0.03") == [], _crit(10, "ds1/exact_match >= 基线 - 0.03")[:1])
        _e = _crit(300, "ds1/exact_match >= 基线 - 0.03")
        case("交叉校验（负向）：两处 max_steps 不一致 ⇒ 报错且两处的值都在报错里",
             len(_e) == 1 and "10" in _e[0] and "300" in _e[0], _e[:1])
        case("交叉校验（负向）：criterion 的 max_steps 留 0 ⇒ 报「必须是正整数」",
             any("正整数" in x for x in _crit(0, "ds1/exact_match >= 基线 - 0.03")))
        case("交叉校验（负向）：require 写成复合串「ds1和ds2」⇒ 报「没有 <数据集>/<尺子>」",
             any("没有 `<数据集>/<尺子>`" in x for x in _crit(10, "ds1和ds2 >= 基线 - 0.03")))
        case("交叉校验（负向）：指标名解析不出来 ⇒ 报错并列出现有数据集名",
             any("解析不出来" in x for x in _crit(10, "ds9/acc >= 基线 - 0.03")))
        case("交叉校验（正向）：多指标列表（两条都合法）⇒ 无错误",
             _crit(10, "ds1/exact_match >= 基线 - 0.03") == [])

        # ---- 边界摘要（0.18.38 / CR-0009 + CR-0011）：纯算术，不出错 ----
        case("边界摘要（无风险）：没开平台早停、也没配 checkpoint ⇒ 一个字都不说",
             _boundary_note(cross_design, cross) == [], _boundary_note(cross_design, cross)[:2])
        (cross / "config" / "tasks" / "cross.yaml").write_text(
            "task_id: cross\n"
            "stop_conditions:\n  max_steps: 300\n  plateau:\n"
            "    window_steps: 20\n    min_gain_pct: 1.0\n    patience: 2\n"
            "    min_steps: 150\n"
            "train:\n  checkpoint:\n    save_interval_steps: 50\n    keep_last: 2\n"
            "eval:\n  datasets:\n    - name: ds1\n", encoding="utf-8")
        _note = _boundary_note(cross_design, cross)
        case("边界摘要：plateau.min_steps=150 ⇒ 说出「最早第 150 步」",
             any("最早第 150 步" in x for x in _note), _note[:3])
        case("边界摘要：keep_last=2 ⇒ 说出只剩最后两份",
             any("iter_0000250 / ckpt/iter_0000300" in x for x in _note), _note)
        case("边界摘要：点明先被删的是 iter_0000050（判据点名的早期份）",
             any("iter_0000050" in x for x in _note), _note)
        case("边界摘要：加了这两块也不产生错误（判据与任务配置仍对得上）",
             _crit(300, "ds1/exact_match >= 基线 - 0.03") == [],
             _crit(300, "ds1/exact_match >= 基线 - 0.03")[:1])

        # ---- A4：基线轮没有自变量（variables 留空映射）----
        empty_vars = GOOD_1.replace(
            "variables:\n  rotation: {value: true, requires_code: false}\n",
            "variables: {}\n")
        dev, _rev = _fixture(tmp, empty_vars, "emptyvars")
        case("A4（正向）：variables 留空映射 ⇒ 通过（基线轮不编自变量）",
             validate_design(dev) == [], validate_design(dev)[:1])
        novars = GOOD_1.replace(
            "variables:\n  rotation: {value: true, requires_code: false}\n", "")
        dnv, _rnv = _fixture(tmp, novars, "novars")
        case("A4（负向）：variables 键整个没有 ⇒ 仍报缺必需键（放宽的只是「非空」）",
             any("缺必需键 `variables`" in x for x in validate_design(dnv)), validate_design(dnv)[:1])

        old = os.environ.get("LP_ROOT")
        os.environ["LP_ROOT"] = str(tmp / "no-such-tree")
        case("★ LP_ROOT 指向不存在的树 ⇒ 退出 2（fail-closed，不回退）", main([str(d1)]) == 2)
        if old is None:
            os.environ.pop("LP_ROOT", None)
        else:
            os.environ["LP_ROOT"] = old
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 60)
    print(f"PASSED: {stats['n'] - stats['fail']}/{stats['n']}")
    return 1 if stats["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
