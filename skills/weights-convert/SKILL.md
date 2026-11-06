---
name: weights-convert
description: 当训练起点（任务配置 model.start.path）还不存在、而模型只吃 mcore 时加载——用 scripts/convert_weights.sh 把 HF 原始权重一次性转成 mcore 起点：先判目标在不在（在就跳过，幂等），再转，最后验产物三条（iter=1／pt 非空／体积比 0.9–1.1）。不用于评测方向的 mcore→HF（那是三段里的 convert 段）。
version: 1.0.0
applies_to: [tester, experimenter]
---

# 训练起点权重转换（`weights-convert`）

## 0. 谁用 / 什么时候用 / 不做什么

- **谁用**：tester（冒烟之前）与 experimenter（跑三段之前）。**任何需要跑训练的角色都可能用到**。
- **什么时候用**：`model.start.format: mcore` 而 `model.start.path` 那个目录**还不存在**时。
- **不做什么**：
  - 不做**反方向**（mcore → HF 给评测用）—— 那是三段的 `convert.sh`，每轮一次；
  - 不猜 `model_type_hf`、不改任务配置、不替你决定"这一轮从哪起步"（那是 `intents[]` 与 `design.md` 的事）；
  - **从不删目录**。目标目录存在但不像检查点时它只会停下来报错。

## 1. 怎么调（一条命令）

```bash
bash scripts/convert_weights.sh --task <任务名> --dry-run   # 先看它打算转什么、转到哪
bash scripts/convert_weights.sh --task <任务名>             # 真转（目标已存在 ⇒ 直接跳过）
```

判定只有一条：**目标在就不重复转**（幂等，退出 0 并打印它是"转换产物"还是"训练产物"）。
所以要"重新转一次"，只能人工把目标目录删掉或改配置里的 `path` —— 脚本自己不删。

## 2. 它从哪读（**部署事实唯一落点＝任务配置**）

| 配置字段 | 用途 |
|---|---|
| `model.source.path` | HF 原始权重目录（"从哪来"） |
| `model.start.format` / `model.start.path` | 训练 `--load` 吃哪份、在哪 |
| `model.start.convert.{model_type_hf,tp,pp}` | 仅转换时用：框架的 `--model-type-hf`（**必填，不许猜**）与并行度 |
| `train.framework_repo` | 框架检出（`convert_ckpt_v2.py` 在它根下） |

★ 任务目录（`experiments/<任务>/**`）里**不许出现任何绝对路径** —— 那是可迁移的前提。路径只写在任务配置里。

## 3. 转完必须验三条（只看退出码不算数）

脚本自己验，任何一条不过就退出 2：

1. `latest_checkpointed_iteration.txt` 存在且值为 **`1`**（转换工具写死 1）；
2. `iter_*/mp_rank_*/*.pt` 至少一个、非空；
3. 产物总字节 vs HF `model*.safetensors` 总字节在 **0.90–1.10** 之间（本机实测：4B 是 1.0000，小模型 1.005）。

## 4. 四条实测底线（这四条是这道 skill 存在的理由）

1. **"转换产物"与"训练产物"长得一模一样**，唯一机械区别是两条：
   - `latest_checkpointed_iteration.txt`：转换恒为 `1`；训练产物 = 训到第几步；
   - 顶层键：转换产物只有 `args / checkpoint_version / iteration / model`；
     训练产物**多** `optimizer / opt_param_scheduler / rng_state / num_floating_point_operations_so_far / rerun_state_machine`。
   （小模型实测：转换产物 4 键、iter=1。要看键得 `torch.load(..., map_location="cpu")` —— 大模型的单个分片可能几 GB，吃内存。）
2. **tied embeddings 的模型**（如 `tie_word_embeddings: true`）转换产物里**没有** `output_layer.weight` —— 这是对的，**别补**。
3. 转换**不需要卡**，但要框架依赖（`torch`／框架包）；工具是 `python convert_ckpt_v2.py`，解释器可用 `--python` 指定。
4. 产物命名/并行度（tp/pp）决定 `mp_rank_XX` 的层数；**训练侧的 tp/pp 必须能整除它**，否则训练加载时才会炸。

## 5. 失败模式（一条一条对）

| 现象 | 原因 | 处置 |
|---|---|---|
| 退出 2「缺 `model_type_hf`」 | 配置里没写型号 | 在 `model.start.convert.model_type_hf` 填框架 `--model-type-hf` 认的值（与任务配置里那个一致）；**不许猜** |
| 退出 2「目标目录存在但不像 mcore 检查点」 | 半成品／别的格式／上次中断 | 人工确认后删掉或换 `path`；脚本不替你删 |
| 退出 2「产物验证失败：体积比」 | 型号写错／中途断 | 看 `${TARGET}.convert.log` 尾部；修完删掉目标重转 |
| 退出 2「框架检出里没有 `convert_ckpt_v2.py`」 | `train.framework_repo` 指错 | 改配置，别改脚本 |
| 转换命令本身非 0 | 依赖缺失/显存/磁盘 | 看日志尾部（脚本已打）；换 `--python` 指到框架那个解释器 |

## 6. 与三段的分工（别混）

| | 什么时候 | 方向 | 谁做 |
|---|---|---|---|
| 起点转换 | 每个 **HF 源**一次（不是每轮） | HF → mcore | 本 skill（`scripts/convert_weights.sh`） |
| 评测转换 | 每个**新检查点**一次 | mcore → HF | 三段的 `convert.sh`（`commands/convert_cmd.sh`） |

一句话：**起点转换次数 = 你用过的不同 HF 源的数量，不是轮数。**
