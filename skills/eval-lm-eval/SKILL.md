---
name: eval-lm-eval
description: 当 experimenter / tester 要跑低精度评测时加载——讲清怎么安装并接入 lm_eval（包名、版本、命令）、怎么选驱动与施加量化补丁、口径怎么对齐、输出怎么落盘。不用于判定。
version: 1.0.0
applies_to: [experimenter, tester]
---

# 评测接入（`eval-lm-eval`）

## 0. 什么时候用 / 什么时候不用

- **用**：装评测环境、选驱动、施加量化补丁、对齐口径、把评测原始输出落进 `evidence/`。
- **不用**：判定与结论（`report-and-conclusion`）；抽数（数字只由 `runtime/metrics.py` 抽）。
- **红线**：**训练侧与评测侧必须是同一个量化往返**；口径必须与判据**逐项一致**。

## 1. 开工前要读的文件（路径 + 字段名）

| 读什么 | 取哪些字段 | 为什么 |
|---|---|---|
| `config/tasks/<任务名>.yaml`（只读） | `eval.{engine,lm_eval.{package,version,python,driver},task_type,datasets,protocol}` | 包名/版本/解释器/驱动/口径的唯一落点 |
| `<轮次>/criterion.yaml`（只读） | `eval_protocol.{dataset,prompt_type,mode,max_gen_toks,limit,batch_size}` | 判定用的口径；必须与任务配置 `eval.protocol` 逐项一致 |
| `<轮次>/scheme_resolved.json`（只读） | 量化取值（位宽/格式/粒度/旋转/豁免等） | 驱动要按同一组取值施加补丁 |
| `<任务目录>/drivers/` | 本任务的评测驱动（拼 lm_eval argv 并执行） | 驱动是方案/任务专有的，写死在任务目录 |
| `knowledge/frameworks/*.md` | 量化实现与融合结构的 `file:line` | 判「哪些层能单独豁免」 |

## 2. 步骤（每步带判据）

1. **装评测环境（钉版本）**：用任务配置里写的 `eval.lm_eval.{package,version,python}`；环境由 `scripts/install_env.sh` 建（`TODO(P10)`）。
   *判据*：`<python> -c "import lm_eval, importlib.metadata as m; print(m.version('<package>'))"` 输出与配置的 `version` **完全一致**。
2. **选驱动**：用任务目录 `drivers/` 里本任务的那个驱动；驱动负责施加与训练侧**同一次舍入**的量化补丁。
   *判据*：驱动里施加的取值与 `scheme_resolved.json` 的展开值逐项一致；不一致就停下报错，不许硬跑。
3. **对齐口径**：把 `criterion.yaml` 的 `eval_protocol.*` 与任务配置 `eval.protocol.*` 逐项比对（数据集、模板、模式、生成长度、样本上限、批大小）。
   *判据*：逐项一致的清单写进 `<轮次>/evidence/`；有任何一项不一致 ⇒ 退出 `6`（评测侧无效），本轮不产生精度结论。
4. **落盘**：评测原始输出（stdout/stderr、结果文件、命令与版本）**原样**进 `<轮次>/evidence/`；随后交给 `runtime/metrics.py` 抽数。
   *判据*：`evidence/` 里能独立复现这次评测（命令、版本、驱动 sha、口径）。

## 3. 模板与命令（可直接复制）

```bash
# 环境自检（版本必须与 config/tasks/<任务名>.yaml 的 eval.lm_eval.version 一致）
"$LP_EVAL_PYTHON" - <<'PY'
import importlib.metadata as m, sys
print(sys.executable, m.version("<package>"))
PY

# 跑评测（命令的逐字来源是 <任务目录>/run.env，不在这里重定义）
bash <任务目录>/eval.sh --round <轮次> 2>&1 | tee <轮次>/evidence/eval.log
```

## 4. gotchas（症状 → 正确动作）

1. **量补丁只打在训练侧** → 症状：数字虚高、不可比。正确动作：驱动施加同一次舍入，并在 `evidence/` 写明对账依据。
2. **口径少了一项（如生成长度）** → 症状：同一模型两轮不可比。正确动作：逐项对账，缺项即退出 `6`。
4. **版本没钉** → 症状：换机器结果漂移。正确动作：包版本写进任务配置并现场校验。
5. **把评测结果手抄进报告** → 症状：数字不可追溯。正确动作：原始输出进 `evidence/`，数字只由 `runtime/metrics.py` 抽。

## 5. 校验回路（自查「我真的做对了」）

- 版本自检输出与配置一致；驱动取值与 `scheme_resolved.json` 一致；口径逐项一致。
- `evidence/` 里有命令、版本、驱动 sha、口径清单。
- 退出码：口径不全 ⇒ `6`；不把评测失败含糊成训练失败。

## 6. 参考

- 本工程：`docs/CONFIG.md` §5（`eval.*` 与评测环境）、`experiments/<任务名>/drivers/lm_eval_driver.py`（调用器骨架）。
- `skills/train-recipe/SKILL.md`（`run.env` 与退出码）、`skills/run-observation/SKILL.md`。
- `references/lm-eval-driver-contract.md` —— **深化材料（正文只留入口，长内容在这里）**：
  ①为什么评测侧必须施加**同一次**假量化（QAT 是假量化、ckpt 仍是主权重精度）
  ②「驱动 ↔ 环境变量」逐项对齐与已发生的真事故（开关下发给**不认它的驱动**被静默丢弃 ⇒ 看起来像「改了没用」）
  ③自证标记（机制生效的直接证据；先确认标记真的会打印，否则会判成一次**假失败**）
  ④必须的评测口径**项**清单（值只在任务配置与 `criterion.yaml`）⑤`evidence/` 落盘要求
  ⑦离线可验 vs 必须上真机验 ⑧目录命名与导入。
- **落点已交付（P4c），实例 P4d 起是真驱动**：驱动与补丁的实物落点是 `<任务目录>/drivers/`
  （实例见任一任务目录的 `<任务目录>/drivers/lm_eval_driver.py`：拼 lm_eval argv 并执行；
  不可用／结果没落盘 ⇒ 退出 `6`）。★ 它**从未真跑过**（只被 `--print` 核过 argv 形状）
  ⇒ 与真实的一次评测运行逐项对账**仍没有实物可对**（等第一次真跑）。
- `TODO(P10)` 评测环境（venv ＋ 钉版本）由 `scripts/install_env.sh` 建，**P10 已实现**；本机的评测 venv 还没建（P4d 不许起评测）。
