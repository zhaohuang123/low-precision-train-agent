#!/usr/bin/env bash
# ── 骨架（无型号）────────────────────────────────────────────────────────────
# 照抄到 `<任务目录>/commands/` 后：① 把每个 `<...>` 换成真值 ② 把 `# <占位>` 的段落填上。
# 未替换的占位一律**当场拒绝**（fail-closed），不会带着占位去起作业。
# ─────────────────────────────────────────────────────────────────────────
# _taskcfg.sh —— 任务级**命令形状脚本**共用的「读任务配置」函数（被 `source`；唯一一份）
#
# 归属：任务目录 `commands/` 的共用前导（任务配置是场景的唯一落点）。
#
# 为什么住在这里：三段入口经 `<任务目录>/run.env` 调本目录的**命令形状脚本**，而那些脚本
# 是 `runtime/executor.py` 起的**独立 bash 进程** —— `runtime/_common.sh` 的 shell 函数不跨进程
# （没 export -f，也不该 export）。所以「在命令形状脚本里读任务配置」这件事要在任务目录里
# 有**一份**实现，三个脚本 source 它，不各抄一份。
#
# ★ 它不是第二套 YAML 解析器：只读 `config/tasks/<任务名>.yaml`（PyYAML），读不到就退出 2；
#   命令形状脚本**只读**配置（不写、不建目录、不改任何文件）。
# ★ 字段名只在任务配置里有一处；本文件不写默认值 —— 缺字段由调用方决定是「致命」还是「用环境变量」。

#: 读任务配置的点号路径；找到打印值，找不到退出 3（与 runtime/_common.sh 的 lp_task_cfg_get 同约定）。
taskcfg_get() {
  python3 - "$LP_ROOT/config/tasks/${LP_TASK_ID}.yaml" "$1" <<'PY'
import sys
try:
    import yaml
except Exception as exc:
    print(f"PyYAML 不可用（任务配置是 YAML）：{exc}", file=sys.stderr)
    sys.exit(2)
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print(f"任务配置读不出来 {sys.argv[1]}：{exc}", file=sys.stderr)
    sys.exit(2)
cur = doc
for k in sys.argv[2].split("."):
    if not isinstance(cur, dict) or k not in cur:
        sys.exit(3)
    cur = cur[k]
if cur is None or cur == "":
    sys.exit(3)
print(cur)
PY
}

#: 取一个**必须是具体值**（不许是 `<...>` 占位）的字段；占位/缺失 ⇒ 退出 2（fail-closed）。
#: `--print` 模式也走这里 —— 拼装出的命令要么是真命令，要么当场报错，**不印一条指着占位的命令**。
taskcfg_value() {  # <点号路径> <人话用途>
  local dotted="$1" why="${2:-}" val=""
  if ! val="$(taskcfg_get "$dotted")"; then
    echo "任务配置里取不到 ${dotted}（${why}）⇒ 退出 2：命令形状不许猜。" >&2
    exit 2
  fi
  case "$val" in
    *'<'*'>'*)
      echo "任务配置的 ${dotted} 仍是占位值 ${val}（${why}）⇒ 退出 2：" >&2
      echo "  「没配置」与「配了占位」必须区分开 —— 拿占位去拼命令，跑出来的是'看着正常'的实验。" >&2
      exit 2
      ;;
  esac
  printf '%s' "$val"
}

#: `train.extra_pythonpath[]` → `PYTHONPATH` 值（空＝没配，调用方**不许**造一个空 PYTHONPATH）。
#:
#: 为什么存在（0.18.30 / R-09）：训练侧要 import 的**另一半代码**（例如与 `train.framework_repo`
#: 配对的另一个检出）不在框架仓里，而任务里不许 `export` 环境（=活两处）。这个字段是它的唯一落点。
#:
#: ★ 两条纪律写进这里，别在调用方各写一遍：
#:   ① **只认绝对路径**：相对路径相对哪个 cwd 是不确定的（executor 用独立 bash 进程、cwd 随段而变）
#:      ⇒ 当场退 2，不猜；
#:   ② **顺序＝sys.path 顺序**：从左到右拼进 PYTHONPATH，先出现的先命中（重名模块靠它定优先级）；
#:   ③ 目录必须存在：打错一个字就静默 import 到别的版本，比退 2 贵得多。
#: ★ **eval 段不调用本函数**（口径不依赖训练侧那一半代码；理由见 docs/CONFIG.md 的字段说明）。
taskcfg_extra_pythonpath() {
  python3 - "$LP_ROOT/config/tasks/${LP_TASK_ID}.yaml" <<'PY'
import os, sys
import yaml

try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception as exc:
    print(f"读不了 {sys.argv[1]}：{exc}", file=sys.stderr); sys.exit(2)

train = doc.get("train") or {}
if not isinstance(train, dict):
    print("任务配置的 train 不是字典 ⇒ 退出 2", file=sys.stderr); sys.exit(2)

val = train.get("extra_pythonpath")
if val is None:
    sys.exit(0)                      # 没配 ⇒ 调用方一个字都不加（零行为变化）
if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
    print("train.extra_pythonpath 必须是**字符串列表**（例如 [\"/path/to/Megatron-LM\"]）⇒ 退出 2",
          file=sys.stderr)
    sys.exit(2)

seen, out = set(), []
for raw in val:
    entry = raw.strip()
    if not entry:
        print("train.extra_pythonpath 里有空项 ⇒ 退出 2（空项拼进 PYTHONPATH 会变成当前目录）",
              file=sys.stderr)
        sys.exit(2)
    if not entry.startswith("/"):
        print(f"train.extra_pythonpath 里的 {entry!r} 不是绝对路径 ⇒ 退出 2：", file=sys.stderr)
        print("  相对路径相对哪个 cwd 是不确定的（executor 起独立 bash 进程，cwd 随段而变）——"
              "写死绝对路径。", file=sys.stderr)
        sys.exit(2)
    if not os.path.isdir(entry):
        print(f"train.extra_pythonpath 里的 {entry} 不存在或不是目录 ⇒ 退出 2：", file=sys.stderr)
        print("  打错一个字会静默 import 到别的版本，比现在退 2 贵得多。", file=sys.stderr)
        sys.exit(2)
    if entry in seen:               # 同一个目录写两遍对 sys.path 是 no-op，静默去重
        continue
    seen.add(entry); out.append(entry)

print(":".join(out))
PY
}

#: 可见卡数：只读入口已经定好的可见集合，**不自己挑卡**（卡号只从 runtime/resources.py 来）。
taskcfg_visible_cards() {
  local vis="${ASCEND_RT_VISIBLE_DEVICES:-${LP_CARDS:-}}"
  [[ -n "$vis" ]] || {
    echo "ASCEND_RT_VISIBLE_DEVICES（或 LP_CARDS）没设 ⇒ 退出 2：" >&2
    echo "  起 torchrun 必须显式声明可见设备（旧工程真实事故：不声明时框架默认抢低号卡）。" >&2
    echo "  三段入口的 lp_guard_devices 会在起作业前定卡并把结果 export 进来；手工跑请自己 export。" >&2
    exit 2
  }
  local n=0
  local IFS=','
  for _ in $vis; do n=$((n + 1)); done
  printf '%s' "$n"
}
