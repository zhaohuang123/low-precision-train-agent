---
name: bootstrap-eval-env
description: 当主 Agent 要在开跑前把评测用的 python venv 建出来、并把真实解释器路径回填进任务配置时加载——先定 venv 根与 lm_eval 的精确版本，再跑 scripts/install_env.sh 建/钉版本/回读自证，最后确认 preflight 第 ④ 项不再显示"将创建"。同时说清 eval.lm_eval.driver 在任务目录还没建时该填什么。
version: 1.0.0
applies_to: [main-agent]
---

# 评测环境一次性搭建（`bootstrap-eval-env`）

## 0. 谁用 / 什么时候用 / 不做什么

- **谁用**：**主 Agent**，开跑前跑一次。四个角色（architect／developer／tester／experimenter）**不加载**本 skill
  —— 它们不建环境。
- **什么时候用**：任务配置里 `eval.lm_eval.python` 还是占位值，或者 preflight 第 ④ 项一直显示"将创建"。
- **它解决什么**：鸡生蛋 —— 任务配置要求写一个**真实存在**的解释器，而那个环境还没建。
- **不做**：不重写 `scripts/install_env.sh`（引擎侧唯一实现就在那儿）；不建训练侧环境；不碰框架检出；
  不改 `eval.*` 的其它字段；**不替人决定 lm_eval 版本**。

> ⚠ 别拿 preflight ④ 当"环境好了"的证据：它跑的是 `install_env.sh --dry-run`，venv 不存在也 ✓（只打印"将创建"）。

## 1. 先定三件事（只有一件需要问人）

| 定什么 | 从哪来 |
|---|---|
| **venv 根** | 按约定：`<data.root>/venvs/lm-eval`（`data.root` 读 `config/project.yaml`，例：`/data` ⇒ `/data/venvs/lm-eval`）。人指定别的盘就按人说的 |
| **package** | 人给（本工程统一 `lm_eval`，写全包名） |
| **version** | **必须人给**，精确版本号。`install_env.sh` 会把它钉死并回读自证；不一致直接退出 `2` ⇒ 不许猜、不许写 `latest` |

拿不准版本时的唯一合法做法：问人，或照抄**你另一个已经跑通的工程**任务配置里那个 `version`。

## 2. 写进任务配置（唯一落点）

```yaml
eval:
  lm_eval:
    package: "<包名>"
    version: "<精确版本>"
    python: "<venv 根>/bin/python"      # 形状必须是 <venv 根>/bin/python（写系统 python 会被拒）
```

**不要**在别处再写一份 venv 路径：`install_env.sh` 由 `python` 反推 venv 根（`…/bin/python` 的上两级）。

## 3. 建（三条命令，第二条是预演）

```bash
python3 runtime/config.py validate config/tasks/<任务>.yaml        # 不过 ⇒ 逐条打印字段路径
bash scripts/install_env.sh --task <任务> --dry-run                # 只看它打算建到哪、装哪个版本
bash scripts/install_env.sh --task <任务>                          # 真建：建 venv → 装 → 回读自证
bash scripts/install_env.sh --task <任务>                          # 再跑一次：应打印"已是目标状态"（幂等）
```

★ **建法固定为"继承"**（0.18.13 起 `install_env.sh` 自己带 `--system-site-packages`）：
venv **不装** torch / torch_npu / transformers，而是**继承主环境的 Ascend 栈**，venv 里只装 `lm_eval`。

为什么不能隔离建：`lm-eval` 的 torch/transformers 在它的 `hf` extra 里，裸装**不拉**；
而 `lm_eval --model hf` 在 `lm_eval/models/huggingface.py:10` 就 `import torch` ⇒ 隔离建的 venv
"装上了但跑不了"，且会在**训练卡花完之后**才炸。评测必须用**与训练同一个** torch/torch_npu，
否则分数差异里会混进运行时差异。

所以：**不要**自己 `python3 -m venv` 建评测环境；只用 `install_env.sh`（它会算建法、判可运行性、记版本）。

## 4. 验收四条（缺一条就是没搭好）

```bash
<venv 根>/bin/python -V
<venv 根>/bin/python -c "import importlib.metadata as m; print(m.version('<包名>'))"   # 必须与配置逐字相同
<venv 根>/bin/python -c "import torch, torch_npu, transformers, lm_eval; print('OK')"  # 能 import 才算装好
bash scripts/preflight.sh <任务>                                   # 第 ④ 项 ✓ 且不再出现"将创建"
```

第 3 条是 0.18.13 补的：**只查 dist-info 版本不算装好**（C5 就是这么漏的 —— 三条全过、实跑没有 torch）。
第 4 条现在也是四条一起判：`preflight.sh` ④ 读 `install_env.sh --dry-run` 的退出码
（0 已就绪／3 需安装／4 需修），不再只看"命令跑完没"。

装完顺便看一眼记录：`<venv 根>/.lpta-env-install.json` 的 `inherited_versions` 里
就有这次实际生效的 `torch` / `torch_npu` —— 将来解释"分数为什么变了"先看它。

## 5. `eval.lm_eval.driver` 现在怎么填（**任务目录还没建也一样**）

- **填约定路径**：`experiments/<任务名>/drivers/lm_eval_driver.py`（相对配置根，或写绝对路径）。
- **现在填一个还不存在的文件不会让校验失败**：`runtime/config.py` 的存在性检查只覆盖
  `train.framework_repo`、`train.core_repo`、`model.source.path` 与 `eval.datasets[].path`。
- 那个文件在**任务目录初始化**时从 `templates/drivers/lm_eval_driver.py` 拷过去再按任务改
  （模板是骨架，接口契约在它文件头）。
- 只有**评测段**会消费它：`commands/eval_cmd.sh` 读 `eval.lm_eval.driver`，文件不在就退出 `2`。

## 6. 失败模式（一条一条对）

| 现象 | 原因 | 处置 |
|---|---|---|
| 退出 `2`「版本不一致」 | 那个 venv 里已经装了别的 `lm_eval` 版本 | 人工确认后重建 venv；**不许**静默换版本、也不许改配置里的 `version` 去迁就 |
| 退出 `2`「占位值」 | 配置里还是 `<...>` | 把 `package`／`version`／`python` 填成真值 |
| 退出 `2`「不是 `<venv 根>/bin/python` 形状」 | 写成了 `/usr/bin/python3` 之类 | 改成 venv 里的解释器 |
| 建 venv 失败 | 磁盘满／无 python3-venv | 按报错处理，别换路径绕过 |

## 7. 收尾：把这件事写进任务目录 README（一句话）

任务目录建好后，在 `experiments/<任务名>/README.md` 记一行：venv 根、`lm_eval` 版本、何时建的。
—— 目的：下一个接手的人不用重跑 `--dry-run` 猜。
