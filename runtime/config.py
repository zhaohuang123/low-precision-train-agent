#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config.py —— 任务配置校验：`config/task.schema.json` 的**唯一**执行者。

归属：任务配置校验与三条语义规则（字段契约的唯一落点是 `config/task.schema.json`）。

================= 本文件现在实现了什么（P9 补件，逐条可复跑） =================

1. `python3 runtime/config.py <任务配置.yaml>`
   `python3 runtime/config.py validate <任务配置.yaml>`   ← 同上，两种写法等价
   —— 用 `config/task.schema.json`（draft-07 的一个**已声明子集**，见第 8 节）校验任务配置；
      不通过 ⇒ **逐条打印字段路径**并退出 `2`；通过 ⇒ 打印一行 OK 并退出 `0`。
   —— 退出码只有 `0`（通过）与 `2`（不通过／用法与根解析错误）；没有第三种。

2. 除 schema 之外，本文件还执行**三条 schema 表达不了的语义规则**（都打印字段路径）：
   (a) **占位值规则**：字段值里出现 `<...>` 形式、或为空串、或是 `default` ⇒ 视为**占位**，
       跳过下面的存在性检查。理由：本工程 P0 起的模板（`config/tasks/_TEMPLATE.yaml`）
       路径都是 `/data/models/<model-name>` 这种**带前缀的**占位写法，整串并不等于 `<...>`；
       若按「整串等于 `<...>`」判占位，模板自己就过不了（P9 实测：模板的 5 条路径全是这种形状）。
   (b) **路径类字段存在性**（只对**具体值**判；相对路径相对**配置根**，不相对当前目录）：
       `train.framework_repo`（必须是目录）、`model.source.path`、`eval.datasets[*].path`。
       这一集合是 §11 ①「路径类字段」的一个**子集** —— 没判哪些见第 6 节。
   (c) `task_id` 是**路径名**：不许含 `/`、空白，不许是 `.`／`..`（它决定 `<paths.experiments>/<任务名>`）。

3. `config/task.schema.json` 是**唯一**的字段契约；本文件是它在 `runtime/` 里的**唯一代码引用点**
   （`grep -rl 'task.schema.json' runtime/ --include='*.py' --include='*.sh'` 只命中本文件。
   ★ 早先的验收行写的是**不带 `--include`** 的 `grep -rl 'task.schema.json' runtime/`，
   它同时命中 `runtime/README.md` 的散文（逐脚本表第 4 行与落点判据表各一处）⇒ 那条断言
   **从 P0 起就恒假**（与本文件实现无关；P9 实测并已换等价有效命令）。）。校验对象只有 ① 任务配置；
   方案块的校验归 `runtime/validate_round.py`（§10 规则 7，**不重复**）。

3.5 `resolve-scheme <任务配置.yaml> [--out <文件>]`（P4d 落地；`TODO(P1)` 收口）
   —— 按 §11 ① 末行与 §16.1 P1 的验收：把**任务配置里可省略/写成 `default` 的路径类字段**
   展开成实际值＋来源，打印出来（`--out` 时另落一份 JSON，即 `<轮次>/scheme_resolved.json` 的生产者）。
   已展开：`artifacts.root`（缺失／`default`／占位 ⇒ `<paths.experiments>/<任务名>`）、
   `paths.*`（`config/project.yaml` 缺失该项 ⇒ 内建默认，并打印「内建默认」）、
   以及由它派生的 `<artifacts.root>/rounds`。字段级错误（缺键／类型错）⇒ 退出 `2` 并打印字段路径。
   —— 该子命令复用**同一份** schema 校验器与语义规则（不另写一套），唯一差别是
   `artifacts`／`artifacts.root` 的 `required` 被让开：**本文件就是这两个默认值的生产者**
   （schema 的 description 与 `required` 在此处互相打架，见文件头第 4 条）。

=================== 本文件**没有**实现什么（不夸张，逐条点名） ===================

4. `resolve-scheme` 只覆盖 **① 任务配置**（路径类默认值）。**§10 规则 5 的另一半**
   —— `design.md` 的 ② 方案自变量里写成 `value: default` 的项 ⇒ 按某处默认值展开
   —— **已无意义**（0.18.0 删掉了旋钮字典，没有"字典默认值"这个落点了；记 `TODO(P4f)` 已随字典删除关闭）：
   它要在**轮次目录**里读受控块、写 `<轮次>/scheme_resolved.json`，与「读任务配置」是两条契约。
   调用 `resolve-scheme <design.md>` 会**明确拒绝**（`2`，fail-closed），不会把 `.md` 当任务配置读。
   ★ 顺带记录一处**契约自相矛盾**（本步只报告、不改 schema）：`config/task.schema.json` 把
   `artifacts` 列进顶层 `required` 且 `artifacts.root` 也 `required`，但同一个 `artifacts` 的
   `description` 写的是「缺失或写成 `default` ⇒ 展开为 `<paths.experiments>/<任务名>`」，
   §16.1 P1 的验收也要求「删掉 `artifacts:` 之后 resolve-scheme 仍能展开」。
   本文件按 description／验收实现（展开时让开这两个 `required`），`validate` 一侧**一字未动**
   （裸 `validate` 仍按 `required` 判 ⇒ 缺 `artifacts` 退出 `2`）。两条路的差异见第 4.1 节。
4.1 由此产生的**两个入口行为不同**（有意，且逐条说清）：
   `python3 runtime/config.py <任务配置>`（`validate`）：`artifacts` 缺失 ⇒ 退出 `2`
   （schema `required`）；`python3 runtime/config.py resolve-scheme <任务配置>`：`artifacts`
   缺失 ⇒ 展开成默认值并退出 `0`。两者都不算「静默」—— resolve-scheme 会在输出里逐行写明
   「缺失/`default` ⇒ 展开」这一事实与来源。
5. `artifacts.root` 的**目录创建**（文件头旧契约第 5 条：不存在则跑前创建）**不在本文件的任何子命令里做** ——
   `validate` 与 `resolve-scheme` 都是只读的（`--out` 只写调用方指名的那一个文件）。
   该动作已实现（P4f 补件），落点是**三段入口**：`runtime/_common.sh` 的 `lp_prepare_artifacts_root`
   在起作业前 `mkdir -p`（`--dry-run` 只预告、不落盘）。放在入口而不是本文件：本文件不认识「跑」这件事。
6. 没做存在性检查的路径类字段（有意，理由各自不同）：
   `eval.lm_eval.python`（评测 venv 由 `scripts/install_env.sh` 建；**配置先于 venv 存在**是常态，
   故缺它不是配置错 ⇒ 不判存在性。该脚本已在 **P10** 落地，见 `docs/CONFIG.md` §5）、
   `eval.lm_eval.driver`（驱动住在**任务目录**，且只在**评测段**被消费 ⇒ 本文件不判它的存在性：
    那是「跑起来之前」的事，本文件不认识「跑」）、
   `artifacts.root`（由第 5 节决定由跑前准备创建，缺它不是配置错）。
7. 由 `config/task.schema.json` 决定的字段集，**0.7.0 已按 §11 ① 与附录 B 收窄**（schema 是契约，本文件只执行它）：
   * `model.source.{url,path}` 的「至少一个非空」由 schema 的两支 `anyOf` 表达 ⇒
     `model.source: {url: "", path: ""}` 现在**退出 `2`**（P9 干跑实测：此前会通过）。
   * §11 ① 表的必填项进了 `required`：`model.{precision,source}`、`train.monitor_metrics`、
     顶层 `knowledge`／`loop` ⇒ **删掉它们现在都退出 `2` 并打印字段路径**
     （P9 干跑实测：此前逐行删掉均 rc=0）。★ 0.17.0 起 `eval.metrics` **已删**。
     它只是把驱动写出的键再声明一遍（全仓库只用在一行），留着就要再维护一条「配置与驱动必须一致」的检查；`comparisons` 现在直接取目标轮 `metrics.json` 里驱动写出的键 ⇒ 键名没有第二处声明。
     （0.15.0 起 `eval.compare_anchor.*` 已按决策者判定删除：「跟谁比」的唯一来源改为
     `<轮次>/criterion.yaml` 的 `success.baseline_ref`，它不住任务配置里）。
   * `additionalProperties: false` 已逐层打开（顶层与每个嵌套对象），拼错的键现在报「多余字段」；
     打开前逐份验过 `config/tasks/` 下的现有任务配置（模板 ＋ 演练夹具那两份）（都仍 rc=0）。
8. draft-07 的**已声明子集**（只实现用到的关键字，未用到的一律不假装支持）；
   schema 里出现本文件没实现的**校验用**关键字 ⇒ 退出 `2`（fail-closed，不许静默跳过一条校验）：
   `type`（含类型数组）／`required`／`properties`／`items`（对象形式）／`enum`／`const`／
   `minLength`／`pattern`／`minItems`／`minimum`／`maximum`／`additionalProperties`（布尔）／
   `anyOf`／`oneOf`。注解关键字（`title`／`description`／`default`／`examples`／`$schema`／`$id`／
   `$comment`／`$ref`）不参与校验。
9. schema 的 `additionalProperties` 是 `false`（0.7.0 起）：拼错的键会报「多余字段」并退出 `2`。
**代价明写**：以后要加一个新字段，必须**先**把它登记进 `config/task.schema.json`，否则合法配置
也会被拒 —— 这是契约文件的本意（字段集只有一个落点）。本文件仍**不**实现 draft-07 里那些
没声明的关键字（第 8 节，遇到即 fail-closed）。

================= 用法与退出码 =================

    python3 runtime/config.py [--root <配置根>] <任务配置.yaml>
    python3 runtime/config.py [--root <配置根>] validate <任务配置.yaml>
    python3 runtime/config.py [--root <配置根>] resolve-scheme <任务配置.yaml> [--out <文件>]

    0  通过
    2  不通过（字段级错误逐条打印）／用法错误／配置根解析不出来／schema 用了本文件没实现的关键字

`resolve-scheme`：展开任务配置里可省略/写成 `default` 的路径类字段（`artifacts.root`、
`paths.*`，见第 3.5 节），打印实际值＋来源；`--out <文件>` 另落一份 JSON
（`<轮次>/scheme_resolved.json` 用它生成）。**只认任务配置**；给 `<轮次>/design.md`
（§10 规则 5 的 ② 方案自变量那一半）会明确拒绝并退出 `2`（见第 4 节）。

配置根解析：`--root` → 环境变量 `LP_ROOT` → 本文件上一级。**指错不回退**：那棵树里没有
`config/project.yaml` 或 `VERSION` ⇒ 退出 `2`（与 `runtime/state.py`／`runtime/metrics.py` 同规矩）。

纪律：本文件不含任何模型名／任务名／数据集名／阈值（`devtools/check_decoupling.py` 会查）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

try:  # 任务配置是 YAML；缺依赖即 fail-closed，不猜
    import yaml
except Exception:  # pragma: no cover
    yaml = None

EXIT_OK = 0
EXIT_CONTRACT = 2

MODULE_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = MODULE_DIR.parent
SCHEMA_REL = Path("config") / "task.schema.json"
PROJECT_REL = Path("config") / "project.yaml"

#: ① 由 `resolve-scheme` 负责展开的字段（§11 ① 末行／§16.1 P1 验收）。
#: `artifacts` 可**整体省略**；`artifacts.root` 可省略／写 `default`／是占位值。
#: ★ 这两个东西在 `config/task.schema.json` 里是 `required`，与它自己的 description
#:   （「缺失或写成 default ⇒ 展开」）打架 —— 本文件是它们的默认值生产者，故在
#:   `resolve-scheme` 一侧让开这两个 `required`，`validate` 一侧照 `required` 判（第 4.1 节）。
EXPANDABLE_OBJECTS = ("artifacts",)
EXPANDABLE_LEAVES = (("artifacts", "root"),)

#: `<paths.*>` 的内建默认（`config/project.yaml` 没有该项时用；用了就打印「内建默认」）。
#: 顺序即打印顺序（`tasks` 在最前，`experiments` 紧随 —— `artifacts.root` 要读它）。
BUILTIN_PATHS = (
    ("tasks", "config/tasks"),
    ("experiments", "experiments"),
    ("records", "records"),
    ("state", "state"),
    ("knowledge", "knowledge"),
    ("requests", "requests"),
)

#: 占位值：值里出现 `<...>`（`<` 与 `>` 成对）即视为占位（见文件头第 2(a) 条）
PLACEHOLDER_RE = re.compile(r"<[^<>]*>")
#: `task_id` 是路径名（决定 `<paths.experiments>/<任务名>`）
TASK_ID_RE = re.compile(r"^[^/\s]+$")

#: 具体值才做存在性检查的路径类字段：(点号路径, 期望形态)
#:   "dir" = 必须是目录；"any" = 存在即可（文件或目录）
#: ★ `eval.datasets[*].path` 是**多值**，不在这张表里 —— 由 `_eval_datasets_errors` 逐个查。
PATH_FIELDS = (
    ("train.framework_repo", "dir"),
    ("train.core_repo", "dir"),
    ("model.source.path", "any"),
)

#: 本文件实现的 draft-07 校验关键字；schema 里出现别的**校验用**关键字即退出 2
KNOWN_KEYWORDS = frozenset({
    "type", "required", "properties", "items", "enum", "const",
    "minLength", "pattern", "minItems", "minimum", "maximum",
    "additionalProperties", "anyOf", "oneOf",
})
#: 注解关键字（不参与校验；出现即忽略）
ANNOTATION_KEYWORDS = frozenset({
    "title", "description", "default", "examples", "$schema", "$id", "$comment", "$ref",
})


class ContractError(Exception):
    """契约层错误 ⇒ 退出 2（fail-closed）。"""


class GateError(ContractError):
    """每轮门／字典层的契约错误 ⇒ 退出 2（fail-closed）。

    本类住在 `config.py`（字典读取器的唯一一份实现所在），`runtime/validate_round.py`
    **import 它**而不是自己再定义一份 —— 「同一个错误类型两个定义」会让 `except` 静默漏接。
    """


# ---------------------------------------------------------------------------
# 保守 YAML 子集解析原语（**唯一一份**）
#
# 归属：字段取值解析器收口到一处（`TODO(P4d)` 已兑现）。
# 为什么住在这里：任务配置校验（本文件）与方案块校验（`validate_round.py`）都要解析
# 同一套保守 YAML；各带一份，两套解析迟早静默分岔。`validate_round.py` `from config import ...`
# 用**这一份**。（0.18.0 起不再有"旋钮字典"这个被解析对象。）
# 纪律：本节不依赖 PyYAML（保守子集自带解析），也**不做**任何具体名/阈值判断。
# ---------------------------------------------------------------------------

#: 0.18.0：旋钮字典 `config/variables.yaml` 已删除（它的三个问题挤在一个字段里，且必然过期）。
#: 下面这些解析原语仍被 `runtime/validate_round.py` 用来解析 design.md 的受控块。

#: 键名允许的字符（小写＋数字＋下划线）；受控块的 `variables.<名>` 仍用它查键形
KEY_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789_"


def _strip_comment(s: str) -> str:
    quote = None
    for i, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i]
    return s


def has_comment(s: str) -> bool:
    """这一行有没有独立的 `#` 注释（用于「by_value 必须给依据」的机械检查）。"""
    return _strip_comment(s).rstrip() != s.rstrip()


def _split_top(s: str, sep: str) -> list:
    out, buf, depth, quote = [], [], 0, None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\" and i + 1 < len(s):
                buf.append(s[i:i + 2])
                i += 2
                continue
            if c == quote:
                quote = None
            buf.append(c)
        elif c in "\"'":
            quote = c
            buf.append(c)
        elif c in "[{":
            depth += 1
            buf.append(c)
        elif c in "]}":
            depth -= 1
            buf.append(c)
        elif c == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    out.append("".join(buf))
    return out


def _scalar(tok: str):
    s = tok.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    if s in ("null", "Null", "NULL", "~", ""):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def flow_value(tok: str):
    s = tok.strip()
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [] if not inner else [flow_value(x) for x in _split_top(inner, ",")]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        d = {}
        if inner:
            for part in _split_top(inner, ","):
                bits = _split_top(part, ":")
                if len(bits) < 2:
                    raise GateError(f"行内 map 的成员缺 ':'：{part!r}")
                d[_scalar(bits[0])] = flow_value(":".join(bits[1:]))
        return d
    return _scalar(s)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _key_ok(k) -> bool:
    return isinstance(k, str) and bool(k) and k[0].isalpha() and all(c in KEY_CHARS for c in k)


def is_placeholder(cand) -> bool:
    return isinstance(cand, str) and cand.startswith("<") and cand.endswith(">")


def _resolve_root(explicit: "str | None") -> Path:
    """`--root` → `LP_ROOT` → 本文件上一级；指错不回退（§0.1／§6.4）。"""
    cand = explicit or os.environ.get("LP_ROOT")
    if cand:
        root = Path(cand).expanduser().resolve()
        if not (root / "config" / "project.yaml").is_file() or not (root / "VERSION").is_file():
            raise ContractError(
                f"配置根指错、不回退：{root} 里没有 config/project.yaml 或 VERSION")
        return root
    root = DEFAULT_ROOT
    if not (root / "config" / "project.yaml").is_file() or not (root / "VERSION").is_file():
        raise ContractError(f"配置根解析不出来：{root} 里没有 config/project.yaml 或 VERSION")
    return root


def _load_schema(root: Path) -> dict:
    path = root / SCHEMA_REL
    if not path.is_file():
        raise ContractError(f"字段契约不在：{path}（配置没契约就不许校验通过）")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"字段契约读不出来：{path}（{exc}）") from exc
    if not isinstance(doc, dict):
        raise ContractError(f"字段契约顶层必须是对象：{path}")
    return doc


def _load_task_yaml(path: Path) -> dict:
    if yaml is None:
        raise ContractError("PyYAML 不可用（任务配置是 YAML）⇒ 拒绝执行")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"任务配置读不出来：{path}（{exc}）") from exc
    if not isinstance(doc, dict):
        raise ContractError(f"任务配置顶层必须是键值表：{path}")
    return doc


def _dig(doc, dotted: str):
    """点号路径取值；中间缺一层即返回 None（不猜）。"""
    cur = doc
    for key in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _is_placeholder(value) -> bool:
    """占位值 = 空／`default`／含 `<...>`（见文件头第 2(a) 条）。"""
    if value is None:
        return True
    text = str(value).strip()
    return text in ("", "default") or bool(PLACEHOLDER_RE.search(text))


def _type_name(value) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return type(value).__name__


def _type_ok(value, want) -> bool:
    if want == "boolean":
        return isinstance(value, bool)
    if want == "string":
        return isinstance(value, str)
    if want == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want == "object":
        return isinstance(value, dict)
    if want == "array":
        return isinstance(value, list)
    if want == "null":
        return value is None
    return False


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else str(key)


# ---------------------------------------------------------------------------
# schema 子集校验器（见文件头第 8 节）
# ---------------------------------------------------------------------------

def _check_schema_keywords(schema, where: str) -> None:
    """schema 里出现本文件没实现的**校验用**关键字 ⇒ 退出 2（不许静默跳过一条校验）。"""
    if not isinstance(schema, dict):
        return
    for key in schema:
        if key in KNOWN_KEYWORDS or key in ANNOTATION_KEYWORDS:
            continue
        raise ContractError(
            f"字段契约 {where} 用了本文件没实现的校验关键字 `{key}` ⇒ 退出 2（fail-closed：\n"
            f"  静默跳过它等于少校验一条，宁可拒绝执行。已实现的关键字见 runtime/config.py 文件头第 8 节。）")
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sub in props.items():
            _check_schema_keywords(sub, f"{where}.properties({key})")
    for sub_key in ("items", "additionalProperties"):
        sub = schema.get(sub_key)
        if isinstance(sub, dict):
            _check_schema_keywords(sub, f"{where}.{sub_key}")
    for comb in ("anyOf", "oneOf"):
        block = schema.get(comb)
        if isinstance(block, list):
            for i, sub in enumerate(block):
                _check_schema_keywords(sub, f"{where}.{comb}[{i}]")


def _validate(node, schema, path: str, errors: "list[str]") -> None:
    """把 `node` 对着 `schema` 校验；错误逐条 append 进 `errors`（每条带字段路径）。"""
    if not isinstance(schema, dict) or not schema:
        return
    label = path or "(根)"

    want = schema.get("type")
    if want is not None:
        wants = want if isinstance(want, list) else [want]
        if not any(_type_ok(node, w) for w in wants):
            errors.append(f"{label}: 类型应为 {'/'.join(str(w) for w in wants)}，实得 {_type_name(node)}")
            return  # 类型都不对，后面的值级规则不再叠报

    if "enum" in schema and node not in schema["enum"]:
        allowed = "／".join(repr(v) for v in schema["enum"])
        errors.append(f"{label}: 取值不在枚举内（允许 {allowed}），实得 {node!r}")
    if "const" in schema and node != schema["const"]:
        errors.append(f"{label}: 取值必须是 {schema['const']!r}，实得 {node!r}")
    if isinstance(node, str):
        if "minLength" in schema and len(node) < int(schema["minLength"]):
            errors.append(f"{label}: 字符串长度必须 ≥ {schema['minLength']}，实得长度 {len(node)}")
        if "pattern" in schema and not re.search(str(schema["pattern"]), node):
            errors.append(f"{label}: 不匹配 pattern {schema['pattern']!r}，实得 {node!r}")
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            errors.append(f"{label}: 必须 ≥ {schema['minimum']}，实得 {node!r}")
        if "maximum" in schema and node > schema["maximum"]:
            errors.append(f"{label}: 必须 ≤ {schema['maximum']}，实得 {node!r}")
    if isinstance(node, list) and "minItems" in schema and len(node) < int(schema["minItems"]):
        errors.append(f"{label}: 元素个数必须 ≥ {schema['minItems']}，实得 {len(node)}")

    for comb in ("anyOf", "oneOf"):
        branches = schema.get(comb)
        if not isinstance(branches, list):
            continue
        passed = 0
        for br in branches:
            tmp: "list[str]" = []
            _validate(node, br, path, tmp)
            if not tmp:
                passed += 1
        if comb == "anyOf" and passed == 0:
            errors.append(f"{label}: 没有任何一支满足 anyOf（{len(branches)} 支全不通过）")
        if comb == "oneOf" and passed != 1:
            errors.append(f"{label}: oneOf 要求恰好一支通过，实得 {passed} 支通过")

    if isinstance(node, dict):
        for key in schema.get("required", []) or []:
            if key not in node:
                errors.append(f"{_join(path, key)}: 缺必填字段（schema.required）")
        props = schema.get("properties")
        if isinstance(props, dict):
            for key, sub in props.items():
                if key in node:
                    _validate(node[key], sub, _join(path, key), errors)
        if schema.get("additionalProperties") is False and isinstance(props, dict):
            for key in node:
                if key not in props:
                    errors.append(f"{_join(path, key)}: 多余字段（schema.additionalProperties=false）")
    if isinstance(node, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, elem in enumerate(node):
                _validate(elem, items, f"{path}[{i}]", errors)


# ---------------------------------------------------------------------------
# schema 之外的语义规则（见文件头第 2 节的 (a)(b)(c)）
# ---------------------------------------------------------------------------

def _path_error(root: Path, label: str, value, kind: str) -> "str | None":
    """具体值才查存在性；缺省与占位值（含 `<...>`）跳过（文件头第 2(a) 条）。"""
    if value is None or _is_placeholder(value):
        return None
    path = Path(str(value).strip())
    if not path.is_absolute():
        path = root / path
    if kind == "dir":
        return None if path.is_dir() else f"{label}: 路径不存在或不是目录（{path}）"
    return None if path.exists() else f"{label}: 路径不存在（{path}）"


def _eval_datasets_errors(root: Path, doc: dict) -> "list[str]":
    """`eval.datasets[]` 的跨字段语义（schema 表达不了的：schema 没有交叉引用能力）。

    ① 名字**不许重复** —— 指标的键是 `<数据集>/<尺子>`，重名 ⇒ 两个集静默并成一组键。
    ② 每集的 `path` 逐个查存在性（占位值跳过）。

    纪律：这里只做**结构**判断，不认识任何具体数据集名/尺子名（`check_decoupling.py` 查这个）。
    """
    errors: "list[str]" = []
    ev = doc.get("eval")
    if not isinstance(ev, dict):
        return errors
    datasets = ev.get("datasets")
    if not isinstance(datasets, list):
        return errors  # 缺省/类型错由 schema 判

    names: "list[str]" = []
    for i, one in enumerate(datasets):
        if not isinstance(one, dict):
            continue
        name = one.get("name")
        if isinstance(name, str) and name.strip():
            name = name.strip()
            if name in names:
                errors.append(
                    f"eval.datasets[{i}].name: {name!r} 与前一个重名 —— 指标的键是"
                    f"`<数据集>/<尺子>`，重名会让两个集静默并成一组键")
            else:
                names.append(name)
        err = _path_error(root, f"eval.datasets[{i}].path", one.get("path"), "any")
        if err:
            errors.append(err)

    return errors


def _semantic_errors(root: Path, doc: dict) -> "list[str]":
    errors: "list[str]" = []

    task_id = doc.get("task_id")
    if isinstance(task_id, str) and not _is_placeholder(task_id):
        if not TASK_ID_RE.match(task_id) or task_id in (".", ".."):
            errors.append(
                f"task_id: {task_id!r} 不能当路径名（不许含 `/`、空白或为 `.`／`..`）—— "
                f"它决定 `<paths.experiments>/<任务名>`")

    for dotted, kind in PATH_FIELDS:
        err = _path_error(root, dotted, _dig(doc, dotted), kind)
        if err:
            errors.append(err)

    errors.extend(_eval_datasets_errors(root, doc))
    return errors


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------

def _find_task_config(root: Path, given: str) -> Path:
    """定位任务配置：绝对路径 → 当前目录 → 配置根 → `<paths.tasks>`（默认 config/tasks）。不猜。"""
    cand = Path(given).expanduser()
    names = [cand] if cand.suffix else [cand, Path(str(cand) + ".yaml")]
    search = [] if cand.is_absolute() else [Path.cwd(), root, root / "config" / "tasks"]
    for name in names:
        if name.is_absolute():
            if name.is_file():
                return name
            continue
        for base in search:
            p = base / name
            if p.is_file():
                return p
    raise ContractError(
        f"任务配置不存在：{given}（找过当前目录、配置根 {root} 与 {root / 'config' / 'tasks'}；"
        f"要指名路径请带 .yaml）")


def _shown(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def cmd_validate(root: Path, given: str) -> int:
    schema = _load_schema(root)
    _check_schema_keywords(schema, SCHEMA_REL.as_posix())
    path = _find_task_config(root, given)
    doc = _load_task_yaml(path)

    errors: "list[str]" = []
    _validate(doc, schema, "", errors)
    errors.extend(_semantic_errors(root, doc))
    if errors:
        print(f"runtime/config.py：{_shown(root, path)} **不通过**（退出 2，共 {len(errors)} 处）：",
              file=sys.stderr)
        for e in errors:
            print(f"  ERROR {e}", file=sys.stderr)
        print("  ⇒ 校验契约：config/task.schema.json（唯一执行者就是本文件）", file=sys.stderr)
        return EXIT_CONTRACT

    print(f"OK {_shown(root, path)}：通过 config/task.schema.json 的字段校验"
          f"（＋占位规则／路径类存在性 {len(PATH_FIELDS)} 项／task_id 路径名／"
          f"eval.datasets 交叉引用，共 4 条语义规则）")
    return EXIT_OK


def cmd_resolve_scheme(root: Path, given: str, out_path: "str | None" = None) -> int:
    """展开 ① 任务配置里可省略/写 `default` 的路径类字段（§11 ① 末行；见文件头第 3.5/4 节）。

    `given` **必须是任务配置**（`.yaml`）。给 `<轮次>/design.md`（§10 规则 5 的 ② 那一半）
    ⇒ 明确拒绝并退出 `2`（fail-closed，见文件头第 4 节）。
    """
    if given.lower().endswith((".md", ".markdown")):
        raise ContractError(
            f"resolve-scheme 只展开 **① 任务配置**，收到的是 {given!r}（`.md`）。\n"
            "  §10 规则 5 的 ② 方案自变量那一半（`design.md` 的 `variables.<名>.value: default`／\n"
            "  旋钮字典已删（0.18.0）⇒ 没有可展开的默认值来源 ⇒ 拒绝执行（退出 2, fail-closed），\n"
            "  不把 .md 当任务配置读。\n"
            "  今日可用的是：python3 runtime/config.py resolve-scheme <任务配置.yaml> [--out <文件>]")

    schema = _load_schema(root)
    _check_schema_keywords(schema, SCHEMA_REL.as_posix())
    path = _find_task_config(root, given)
    doc = _load_task_yaml(path)

    # ★ 让开 `artifacts`／`artifacts.root` 的 required：本子命令**就是**它们的默认值生产者。
    errors: "list[str]" = []
    _validate(doc, _relax_expandable_required(schema), "", errors)
    errors.extend(_semantic_errors(root, doc))
    if errors:
        print(f"runtime/config.py resolve-scheme：{_shown(root, path)} **不通过**"
              f"（退出 2，共 {len(errors)} 处）：", file=sys.stderr)
        for e in errors:
            print(f"  ERROR {e}", file=sys.stderr)
        print("  ⇒ 展开之前先过同一份 schema／语义规则（config/task.schema.json 的唯一执行者）",
              file=sys.stderr)
        return EXIT_CONTRACT

    try:
        rows = _resolved_rows(root, path, doc)
    except ContractError as exc:
        print(f"runtime/config.py resolve-scheme：{exc}", file=sys.stderr)
        return EXIT_CONTRACT

    print(f"runtime/config.py resolve-scheme：{_shown(root, path)} 通过校验；展开结果（实际值 ＋ 来源）：")
    for dotted, value, source in rows:
        print(f"  {dotted:<28} = {value}")
        print(f"  {'':<28}   ← {source}")

    if out_path:
        out = Path(out_path).expanduser()
        parent = out.parent if str(out.parent) else Path(".")
        if not parent.is_dir():
            # ★ 不建目录：轮次目录由人/流水线在方案冻结时建好（与 runtime/_common.sh 同一条纪律）。
            print(f"runtime/config.py resolve-scheme：--out 的上级目录不存在：{parent}"
                  f"（轮次目录由人/流水线建好，本文件**从不自己建** —— 建了就等于轮次可以凭空出现）",
                  file=sys.stderr)
            return EXIT_CONTRACT
        payload = {
            "schema": 1,
            "generated_by": "runtime/config.py resolve-scheme",
            "task_config": _shown(root, path),
            "resolved": {d: {"value": v, "from": s} for d, v, s in rows},
        }
        try:
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"runtime/config.py resolve-scheme：--out 写不进去：{out}（{exc}）", file=sys.stderr)
            return EXIT_CONTRACT
        print(f"  已落盘（--out）：{out}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# `resolve-scheme` 的展开规则（§11 ① 末行）
# ---------------------------------------------------------------------------

def _load_project_yaml(root: Path) -> dict:
    """读 `config/project.yaml`（`_resolve_root` 已经保证它存在）。"""
    path = root / PROJECT_REL
    if yaml is None:
        raise ContractError("PyYAML 不可用（config/project.yaml 是 YAML）⇒ 拒绝展开")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"config/project.yaml 读不出来：{path}（{exc}）") from exc
    if not isinstance(doc, dict):
        raise ContractError(f"config/project.yaml 顶层必须是键值表：{path}")
    return doc


def _relax_expandable_required(schema: dict) -> dict:
    """复制一份 schema，把**由展开负责**的字段从 `required` 里拿掉（不改原对象）。

    只动 `EXPANDABLE_OBJECTS`（顶层对象）与 `EXPANDABLE_LEAVES`（对象里的叶子）；
    别的 `required` 一条不少 —— 校验仍是同一份实现，不是「放松校验」。
    """
    relaxed = dict(schema)
    relaxed["required"] = [k for k in (schema.get("required") or []) if k not in EXPANDABLE_OBJECTS]
    props = schema.get("properties")
    if isinstance(props, dict):
        new_props = dict(props)
        for obj in EXPANDABLE_OBJECTS:
            sub = props.get(obj)
            if isinstance(sub, dict):
                sub_copy = dict(sub)
                leaves = {leaf for parent, leaf in EXPANDABLE_LEAVES if parent == obj}
                sub_copy["required"] = [k for k in (sub.get("required") or []) if k not in leaves]
                new_props[obj] = sub_copy
        relaxed["properties"] = new_props
    return relaxed


def _resolved_rows(root: Path, task_path: Path, doc: dict) -> "list[tuple[str, str, str]]":
    """算出「实际值 ＋ 来源」的行；字段级问题 ⇒ `ContractError`（调用方翻成退出 2）。"""
    shown = _shown(root, task_path)
    task_id = doc.get("task_id")
    if not isinstance(task_id, str) or _is_placeholder(task_id):
        raise ContractError(
            f"task_id：展开 `artifacts.root` 需要它（`<paths.experiments>/<任务名>`），"
            f"但它缺失或仍是占位值 {task_id!r} ⇒ 字段路径 task_id")

    project = _load_project_yaml(root)
    proj_paths = project.get("paths")
    if proj_paths is None:
        proj_paths = {}
    elif not isinstance(proj_paths, dict):
        raise ContractError(
            f"paths：类型应为 object，实得 {_type_name(proj_paths)}"
            f"（字段路径 paths，落点 {PROJECT_REL.as_posix()}）")

    rows: "list[tuple[str, str, str]]" = [("task_id", task_id, f"{shown}#task_id")]
    resolved_paths: "dict[str, str]" = {}
    for key, default in BUILTIN_PATHS:
        given = proj_paths.get(key)
        if given is None or _is_placeholder(given) or not str(given).strip():
            resolved_paths[key] = default
            rows.append((f"paths.{key}", default,
                         f"内建默认（{PROJECT_REL.as_posix()} 里没有 paths.{key}）"))
            continue
        if not isinstance(given, str):
            raise ContractError(
                f"paths.{key}：类型应为 string，实得 {_type_name(given)}"
                f"（字段路径 paths.{key}，落点 {PROJECT_REL.as_posix()}）")
        resolved_paths[key] = given.strip()
        rows.append((f"paths.{key}", given.strip(), f"{PROJECT_REL.as_posix()}#paths.{key}"))

    # ── artifacts.root：缺失／`default`／占位 ⇒ <paths.experiments>/<任务名> ──────────
    artifacts = doc.get("artifacts")
    if artifacts is None:
        root_raw, origin = None, "缺失"
    elif not isinstance(artifacts, dict):
        raise ContractError(
            f"artifacts：类型应为 object，实得 {_type_name(artifacts)}"
            f"（字段路径 artifacts，落点 {shown}）")
    else:
        root_raw = artifacts.get("root")
        origin = "缺失" if root_raw is None else "`default`" if str(root_raw).strip() == "default" else "给定值"

    if root_raw is None or _is_placeholder(root_raw) or str(root_raw).strip() in ("", "default"):
        base = resolved_paths["experiments"].rstrip("/")
        value = f"{base}/{task_id}"
        source = (f"{origin} ⇒ <paths.experiments>/<任务名>"
                  f"（paths.experiments 见上一行；任务名取 {shown}#task_id）")
    elif not isinstance(root_raw, str):
        raise ContractError(
            f"artifacts.root：类型应为 string，实得 {_type_name(root_raw)}"
            f"（字段路径 artifacts.root，落点 {shown}）")
    else:
        value = root_raw.strip()
        source = f"{shown}#artifacts.root（给定值，原样采用；相对路径相对配置根）"

    rows.append(("artifacts.root", value, source))
    rows.append((f"{value.rstrip('/')}/rounds", f"{value.rstrip('/')}/rounds",
                 "派生：<artifacts.root>/rounds（轮次目录的父目录）"))
    return rows


USAGE = """用法：
  python3 runtime/config.py [--root <配置根>] <任务配置.yaml>
  python3 runtime/config.py [--root <配置根>] validate <任务配置.yaml>
  python3 runtime/config.py [--root <配置根>] resolve-scheme <任务配置.yaml> [--out <文件>]

退出码：0 通过｜2 不通过（逐条打印字段路径）／用法或配置根错误

resolve-scheme：展开 ① 任务配置里可省略/写 `default` 的路径类字段（artifacts.root、paths.*），
                打印实际值＋来源；`--out <文件>` 另落一份 JSON。给 `.md` ⇒ 拒绝（见文件头第 4 节）。"""


def main(argv: "list[str] | None" = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root_arg = None
    out_arg = None
    positional: "list[str]" = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-h", "--help"):
            print(USAGE)
            return EXIT_OK
        if a == "--root":
            if i + 1 >= len(args):
                print("runtime/config.py：--root 后面缺参数\n" + USAGE, file=sys.stderr)
                return EXIT_CONTRACT
            root_arg = args[i + 1]
            i += 2
            continue
        if a.startswith("--root="):
            root_arg = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--out":
            if i + 1 >= len(args):
                print("runtime/config.py：--out 后面缺文件路径\n" + USAGE, file=sys.stderr)
                return EXIT_CONTRACT
            out_arg = args[i + 1]
            i += 2
            continue
        if a.startswith("--out="):
            out_arg = a.split("=", 1)[1]
            i += 1
            continue
        if a.startswith("-"):
            print(f"runtime/config.py：不认的参数 {a}\n{USAGE}", file=sys.stderr)
            return EXIT_CONTRACT
        positional.append(a)
        i += 1

    if not positional:
        print("runtime/config.py：缺任务配置路径\n" + USAGE, file=sys.stderr)
        return EXIT_CONTRACT

    try:
        root = _resolve_root(root_arg)
        if positional[0] == "validate":
            if len(positional) != 2:
                print("runtime/config.py：`validate` 后面要跟**恰好一个**任务配置路径\n" + USAGE,
                      file=sys.stderr)
                return EXIT_CONTRACT
            if out_arg:
                print("runtime/config.py：`validate` 不认 --out（它只读；--out 属 `resolve-scheme`）\n"
                      + USAGE, file=sys.stderr)
                return EXIT_CONTRACT
            return cmd_validate(root, positional[1])
        if positional[0] == "resolve-scheme":
            if len(positional) != 2:
                print("runtime/config.py：`resolve-scheme` 后面要跟**恰好一个**任务配置路径"
                      "（.yaml）\n" + USAGE, file=sys.stderr)
                return EXIT_CONTRACT
            return cmd_resolve_scheme(root, positional[1], out_arg)
        if len(positional) != 1 or out_arg:
            print(f"runtime/config.py：不认的子命令或参数：{positional + ([f'--out {out_arg}'] if out_arg else [])}\n"
                  + USAGE, file=sys.stderr)
            return EXIT_CONTRACT
        return cmd_validate(root, positional[0])
    except ContractError as exc:
        print(f"runtime/config.py：{exc}", file=sys.stderr)
        return EXIT_CONTRACT
    except OSError as exc:
        print(f"runtime/config.py：文件操作失败：{exc}", file=sys.stderr)
        return EXIT_CONTRACT



if __name__ == "__main__":
    raise SystemExit(main())
