---
name: code-change
description: 当 developer 要把 architect 的方案落成 MindSpeed-LLM / Megatron-LM 侧代码改动时加载——先在框架里定位量化实现并判断「框架能否表达这个方案」，能则最小改动＋写改动清单，不能则当场 CODE_FAILED 并指名缺哪个分支，绝不静默降级成训练侧与评测侧不一致。不用于扫参、不用于跑实验、不用于出结论。
version: 1.0.0
applies_to: [developer]
---

# 代码改动（`code-change`）

## 0. 什么时候用 / 什么时候不用

- **用**：拿到 `<轮次>/design.md` 的受控块，要把它变成框架侧的真实改动（或判定改不动）。
- **不用**：扫参/寻优（`autotune`）；跑三段与抽数（`run-observation`）；写报告与结论（`report-and-conclusion`）。
- **红线**：**训练侧与评测侧必须是同一个东西**；任何「看起来装上了」而实际没生效的改动，都算未完成。

## 1. 开工前要读的文件（路径 + 字段名）

| 读什么 | 取哪些字段 | 为什么 |
|---|---|---|
| `<轮次>/design.md`（只读） | 块内 `variables.<名>.{value,requires_code}`、`implementation.{mode,patch[]}` | 你要落地的东西；键名与取值来自字典 |
| **框架代码**（只读） | 旋钮的生效点（`file:line`）与取值域 | 判「框架有没有这条轴」只认代码；同一旋钮不同取值可能一个原生、一个要 patch |
| `config/tasks/<任务名>.yaml`（只读） | `train.{framework_repo,framework_head,core_repo,core_head}`、`model.{name,source}`、`eval.lm_eval.driver`；训练 argv 在 `<任务目录>/commands/train_argv.txt` | 框架检出、钉点、评测侧驱动 |
| `knowledge/frameworks/*.md` | 能力、限制、关键 `file:line`、「改哪里能达成什么」 | 先查已有扫描结论，别从零翻代码 |
| `knowledge/frameworks/patches/*.patch` | 已证明稳定、可跨轮复用的公共 patch | 能复用就不重写 |
| `records/conclusions/*.yaml`、`knowledge/techniques/*.yaml` | 同类改动的既往结果与 `why_failed` | 别重试同一个坑 |

## 2. 步骤（每步带判据）

1. **定位量化实现**：在 `train.framework_repo` 里找到该旋钮对应的参数/开关/量化往返函数/融合结构。
   *判据*：**读到 `file:line` 才算核过**；只说「框架应该支持」不算。
2. **判能否表达**：
   - 能（含纯配置、零代码）⇒ 进第 3 步；
   - 不能 ⇒ **当场报 `CODE_FAILED`**，指名缺哪个分支/哪段实现（例如「某融合结构把两个矩阵并成一个，无法单独按名处理」）。
   *判据*：结论能一句话说清「缺什么」；**不许**填假参数、注释开关、改配方让它「看起来跑通」。
3. **最小改动 ＋ patch**：改动落 `<轮次>/patches/0001-<简述>.patch`，**每份带三栏：改了哪个文件／为什么／怎么验证**。
   挂载统一 `git apply`（不用软链），只 apply 到按需切出的 **worktree**（起点＝`train.framework_head`）。
   *判据*：`git apply --check` 通过；patch 与 `variables` 里 `requires_code: true` 的条目**一一对应**。
4. **给机制生效验证命令**：至少一条**可复现**命令证明「机制确实装上了」。
   *判据*：tester 照抄能独立复现；证不出 ⇒ 不许交 `CODE_READY`。
5. **写 `changes.md`**：被改文件与理由、每条 patch 三栏、机制生效验证命令、回滚方式。
   *判据*：tester 与 experimenter 不需要回来问你任何一句。
6. **交接**：`CODE_READY`；改不动 `CODE_FAILED`（回 architect，指名叫点）。

## 3. 模板与命令（可直接复制）

```bash
# ① patch 只挂到干净工作树（起点 = 本轮钉点）
git -C <框架检出> worktree add <工作树> <framework_head>
git -C <工作树> apply --check <轮次>/patches/0001-<简述>.patch
git -C <工作树> apply       <轮次>/patches/0001-<简述>.patch
# ② 跑完由 runtime/framework_patch.sh 还原 + 机械校验（前后 head/status diff 必须为空）
git -C <工作树> apply -R    <轮次>/patches/0001-<简述>.patch
```

```markdown
<!-- <轮次>/changes.md 每条 patch 的三栏 -->
### patches/0001-<简述>.patch
- 改了哪个文件：<路径>（`<file>:<line>` 附近）
- 为什么：<机制解释；不写「应该能提升」>
- 怎么验证：`<可复现命令>` ⇒ 期望输出 `<…>`
```

## 4. gotchas（症状 → 正确动作）

1. **只改训练侧、没改评测侧驱动** → 症状：训练与评测不是同一个量化往返，数字不可比。正确动作：两侧同一次舍入，驱动写在任务目录 `drivers/`，并在 `changes.md` 写明对账方式。
2. **patch 没真挂上（开关没生效）** → 症状：`没启用` 与 `搜了没搜到` 在日志里长得一样。正确动作：用机制生效验证命令给出「生效」的直接证据。
3. **在框架检出本体上改** → 症状：多轮实验互相污染、`status --porcelain` 不干净。正确动作：只改 worktree，跑完还原并校验。
4. **把补丁写进任务目录脚本** → 症状：换轮次静默不同步。正确动作：单轮改动只进 `<轮次>/patches/`；可复用且已证明稳定的才进 `knowledge/frameworks/patches/`。
5. **`requires_code: false` 却动了代码** → 症状：门规则 11 报错（零代码改动的方案 ③ 只能是 `framework_native`）。正确动作：要么把对应变量改成 `true` 并给出 patch，要么撤掉改动。

## 4.5 钉点复核：本工程**依赖**的框架开关（0.18.26 起）

本工程在 argv / 命令拼装里**直接依赖**下面这些框架行为。它们不是代码改动，但**每轮都真用到**；
若该轮钉点上的框架与建设者验证过的版本不同，**必须先就地复核**，否则会得到"看着正常"的错数字：

| 依赖 | 本工程用在哪 | 复核方式（在**本轮**框架检出里跑） |
|---|---|---|
| `--save-interval N` | `templates/commands/train_argv.txt` 的 `${save_interval}` | `grep -n "save-interval" megatron/training/arguments.py` 有定义 |
| `--load <ckpt父目录>` 恢复迭代数 | `train_cmd.sh` 的续跑分支 | `grep -n "latest_checkpointed_iteration" megatron/training/checkpointing.py`；`args.iteration = state_dict['iteration']` 在 |
| 去掉 `--finetune` 才是真续跑 | 同上 | `checkpointing.py` 里 `args.finetune` 会让迭代数归零、且跳过 optim/RNG 加载 |
| `--no-load-optim` / `--no-load-rng` | 正常轮的 argv | `arguments.py` 有这两个 flag（否则续跑时"去掉它们"毫无意义） |
| `--no-save-optim` / `--no-save-rng`（可选，只存权重） | 未启用（本工程留 2 份全量状态 ≈110 GB） | `arguments.py` 有定义才可用 |

**判定**：任一条不成立 ⇒ **`CODE_FAILED`**，写明"钉点缺少哪个行为"，不要在本工程侧绕过去
（绕过＝训练侧与评测侧不是同一个东西）。复核结论一行写进 `changes.md` 或 `<轮次>/report.md`。

## 5. 校验回路（自查「我真的做对了」）

- 每个 `requires_code: true` 的取值都有一条 patch；每条 patch 都有三栏与一条可复现验证命令。
- `git apply --check` 通过；`train.framework_head` 与本轮钉点一致。
- 训练侧与评测侧是同一个东西（写明逐项对齐方式）。
- `changes.md` 里的路径都能打开；没有指向框架检出本体的写操作。

## 6. 参考

- 本工程：`AGENTS.md` §2 第 1 条（不改框架检出）、`runtime/framework_patch.sh`（挂/还原与 `verify`）。
- `skills/train-recipe/SKILL.md`（脚本与 `run.env` 怎么写）、`skills/local-knowledge/SKILL.md`（怎么查框架能力）。
- `references/framework-capability-triage.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①定位路线五步（先确认**哪棵树在生效** → 找注册表/choices → grep 机制名 → 跑守卫测试 → 判 patch 目标会不会命中）
  ②「表达不了」的四类缺失（参数／内核／层选择／patch 目标）＋ **融合结构**这一类（两个投影融合进一个线性层 ⇒
  无法单独按名豁免）③patch 三栏 ＋ `git apply`／worktree 挂还原纪律
  ④静默降级四种反模式 ⑤机制生效验证命令的最低要求（含「先问这段代码在什么条件下才执行」）。
- 未定的缺口：`TODO(P6)` 具体「量化实现在框架里的入口与缺口」要落 `knowledge/frameworks/<框架>-<主题>.md`（带 `file:line`，
  属 P6 的知识搬运；原标 `TODO(P4)` 是记错步了）；本 skill 只留**方法**，框架路径一律不在 skill 里写死（由 `train.framework_repo` 给出）。
