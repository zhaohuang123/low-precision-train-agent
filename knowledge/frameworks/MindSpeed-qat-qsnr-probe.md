# MindSpeed —— 在线 QSNR 探针（量化误差可观测性）

> **这条笔记回答什么**：怎样在**训练进程里**持续量出"假量化把张量弄坏了多少"，
> 而不必等一次评测跑完才知道；以及为什么它**是记录项、不是判据**。
> 落点：`knowledge/frameworks/patches/qat-qsnr-probe/`（按「仓 / 目标路径」分目录）。
> 性质：**公共 patch**（跨轮复用；已在两个上游 `master` 干净树上验过可 apply ＋ 自检 32/32）。

## 1. 一句话与数学

```
QSNR = 10 * log10( Σ x² / Σ (x − x̂)² )   [dB]
x   = 量化前张量
x̂   = 假量化（dequant 回同一个 dtype）后的同一个张量
相对误差 ε = 10^(-QSNR/20)
```

| QSNR | 20 dB | **26.02 dB** | 30 dB | 40 dB |
|---|---|---|---|---|
| ε | 10% | **5%** | 3.16% | 1% |

**权重与激活分开算**：W4A4 里激活那一半才是训练期最不稳定的；只看聚合值会被权重稀释。
逐层算 → 按层类型族聚合 → 全模型聚合，三层都留在 JSON 里。

## 2. patch 怎么组织、按需怎么打

```
patches/qat-qsnr-probe/
  core/mindspeed/core/qat/qsnr_probe.patch                          ← 新增文件（核心层实现）
  llm/mindspeed_llm/features_manager/qat/qat_quant_engine.patch     ← 改一个文件的三处（LLM 层接线）
```

目录树**就是目标路径**（`<仓>/<仓内相对路径>.patch`），不用再对说明：

```bash
cd <MindSpeed>     && git apply .../qat-qsnr-probe/core/mindspeed/core/qat/qsnr_probe.patch
cd <MindSpeed-LLM> && git apply .../qat-qsnr-probe/llm/mindspeed_llm/features_manager/qat/qat_quant_engine.patch
cd <MindSpeed>     && python3 mindspeed/core/qat/qsnr_probe.py --selftest    # 期望 32/32 PASSED
```

**"按需"有三个层次**（这是设计过的，不是碰巧）：

| 层次 | 怎么按需 | 代价 |
|---|---|---|
| ① **按仓/目录** | 只打 `core/` 那一份 ⇒ 得到实现但**不自动装**（需要自己在"模型建好"处调 `install_on_model(models)`）；连 `llm/` 一起打 ⇒ `get_model` 上自动装 | 无 |
| ② **按行为** | `QAT_QSNR_WATCHDOG=0` 只要观测不要 kill switch；`QAT_QSNR_{DROP,FLOOR}_DB` 换护栏阈值；`QAT_QSNR_KERNEL` 换尺子 | 无（纯环境变量） |
| ③ **按代码子集** | **不支持，刻意不做**。探针是一个整体（1100 行）：切块装出来的"半装"探针会写出一份**看起来像样**的记录（`n_layers>0` 但缺 family 聚合、或缺看门狗），比不装更危险。要减功能就关开关，不要删代码 | —— |

★ 为什么 patch 只到"一个目标文件"这粒度就够：它已经是**最小可独立验证**的单位；
再往上切（按函数/按 hunk）会让补丁与上游的漂移冲突面变大，而多轮实验真正要区分的是
「装哪个仓」「开哪些行为」，那两件事一个靠目录、一个靠环境变量就够了。

## 3. 环境变量（唯一的开关面）

| 变量 | 必需 | 含义 | 缺省 |
|---|---|---|---|
| `QAT_QSNR_PROBE` | **是** | `1`/`2` 打开；其他值（含未设）⇒ 什么都不做（不 import、不挂钩子、不打印） | 关 |
| `QAT_QSNR_EVERY` | 否 | 采样间隔；必须能解析成正整数，否则抛 `QATProbeConfigError`（**不许静默退回默认**） | `50` ⇒ step `1,10,50,150,250,300` |
| `QAT_QSNR_OUT` | 否 | 产物落点目录 | cwd（**不**猜一个工程路径） |
| `QAT_QSNR_LABELS` | 否 | 身份标签，JSON 对象，**原样透传**进产物的 `labels` 字段 | `null` |
| `QAT_QSNR_WATCHDOG` | 否 | `0` = 整只关掉看门狗（只要观测）；并在 `notes` 里写明"关了 ≠ 没问题" | 开 |
| `QAT_QSNR_DROP_DB` | 否 | 相对地板（比第 10 步跌多少 dB 触发）；非数/负数 ⇒ `QATProbeConfigError` | `3.0` |
| `QAT_QSNR_FLOOR_DB` | 否 | 绝对地板（低于多少 dB 触发） | `15.0` |
| `QAT_QSNR_KERNEL` | 否 | 量 QSNR 用的假量化内核，`<module>:<attr>`；解析失败 ⇒ `QATProbeConfigError` | `mindspeed.core.qat.w4a16_fake_quantization:w4a16_fake_quant` |

★ 后三个是关键：**框架代码里不钉死实验策略**。阈值、开关、尺子都是调用方的决定，
框架只提供"默认值 + 覆盖入口"。

## 4. 产物与自证

- `<OUT>/eval_clamp_qsnr.json`（rank 0）／`eval_clamp_qsnr.rank<r>.json`（其余 rank）；
  顶层键：`labels` / `probe_enabled` / `installed` / `probe_invalid`(+`_reason`) /
  `sampled_at_steps` / `qat_qsnr_every` / `tripped` / `samples[]` / `notes[]`；每个样本带
  `step`、`aggregate_db`、`weight.{aggregate_db,by_family_db,layers}`、
  `activation.{…}`、`n_layers`、`n_activation_recorded`。
- **跨 rank 不做聚合**（训练期不引入额外集合通信）；要跨 rank 就看所有 rank 文件。
- stdout 自证两行（**最贵的缺陷是"没装上却不报错"**）：
  `[qat-qsnr] installed layers=144 sampling=[1, 10] n_microbatches=8 out=…`、
  `[qat-qsnr] step=<k> aggregate_db=<v> (weight=… activation=…) layers=… act_recorded=…`。
  ★ `act_recorded` 是 0 ⇒ 钩子没挂上，**不许**读成"没问题"。

## 5. 看门狗：工程护栏，不是科学判据

| 规则 | 阈值（可覆盖） | 位置 |
|---|---|---|
| 相对地板：任一步 `k ≥ 10` 比第 10 步低超过 | `QAT_QSNR_DROP_DB`（默认 `3.0`） | `mindspeed/core/qat/qsnr_probe.py:838`（`_watchdog_cfg`）|
| 绝对地板：聚合值低于 | `QAT_QSNR_FLOOR_DB`（默认 `15.0`） | `mindspeed/core/qat/qsnr_probe.py:838` |

命中 ⇒ `QSNRWatchdogTrip(BaseException)`：**真停**（torchrun rc≠0，`except Exception` 接不住）
＋ 先落盘 `qsnr_watchdog_trip.json` 再 raise（`mindspeed/core/qat/qsnr_probe.py:860`）。
★ 默认的 3.0 / 15.0 是"宁可早停"的工程阈值，**没有**跨网络锚点；"未触发"**不等于**
"量化误差没问题"；`QAT_QSNR_WATCHDOG=0` 时 `tripped` 恒为 `null`，读的人必须知道这一点。

## 6. 已知限制（集成前先读）

1. **默认内核是 w4a16**：它量的是"按这个格式量化会坏多少"，与训练当前 scheme 的前向无关。
   要按 w4a4 的口径量，写一个 4 参适配函数并用 `QAT_QSNR_KERNEL` 挂上 —— **适配器属于调用方**
   （任务目录 `drivers/`），不进框架：换尺子不该动框架一个字节，写进框架会被上游升级冲掉。
2. **采样是离散步**，不是每步；`QAT_QSNR_EVERY` 决定点数。步数少于 `every` 时只拿到 1–2 个点
   ⇒ 只能当时点看，不能判趋势。
3. **探针自身故障不终止训练**：`probe_invalid` 时序列缺失，训练照跑。下游必须把"未测"和"达标"
   分开表达，否则会得到一条看起来很干净的假结论。
4. **标定批固定为第 1 个 GBS 的第 1 个 micro-batch**：曲线量的是同分布上的漂移，不是泛化。
5. **附加成本**：每个采样步多跑 1 个 micro-batch 的前向（不是整个 GBS）；300 步 × 6 次采样
   ≈ 1–2% 墙钟。
6. 该 patch 只**接线 get_model**：若你的框架版本里 `get_model` 已被别的特性 patch 过，
   注册顺序决定包裹层次（本补丁在 `register_patches` **末尾**注册 ⇒ 叠在最外层、最先跑）。

## 7. 与本工程的关系

- 本工程钉点（`train.framework_head` / `train.core_head`）**已内置**等价实现
  （接线在 LLM 层那次提交里），因此 `config/tasks/*.yaml` 的 `train.monitor_metrics: [loss, quant_error]`
  一写，`commands/train_cmd.sh` 就 export `QAT_QSNR_*` 把探针打开（**声明即开关**）：
  `QAT_QSNR_OUT=<轮次>/evidence`、`QAT_QSNR_LABELS={"round":…,"task":…}`、
  `LP_QSNR_WATCHDOG=0` 时再 export `QAT_QSNR_WATCHDOG=0`。
- 抽数侧：`runtime/metrics.py` 的 `load_qsnr()` 读第 4 节的 JSON ⇒ `metrics.json.quant_error`
  （`status ∈ measured / unmeasured / probe_invalid`，**只登记数**）。
- `stop_conditions.quant_error_max`（**任务配置**，0.18.14 起真生效）：`commands/train_cmd.sh` 把它
  换算成 `QAT_QSNR_FLOOR_DB = −20·log10(ε)` 注入探针，看门狗据此在训练中途停跑
  （`absolute_floor` 命中 ⇒ 该 run 无效）。★ 3 dB 的相对跌落仍是**固定工程护栏**、没有 YAML 旋钮；
  拿这里的 3/15 dB 当精度判据就是拿护栏当科学结论。

## 8. 关键 `file:line`（装完之后的位置）

| 你要找什么 | 在哪 |
|---|---|
| QSNR 的定义（唯一实现） | `mindspeed/core/qat/qsnr_probe.py:237` |
| 采样步表（`EVERY=50` ⇒ `1,10,50,150,250,300`） | `mindspeed/core/qat/qsnr_probe.py:228` |
| 产物落点（只认 `QAT_QSNR_OUT`） | `mindspeed/core/qat/qsnr_probe.py:302` |
| 身份标签（`QAT_QSNR_LABELS` 原样透传） | `mindspeed/core/qat/qsnr_probe.py:285` |
| 在模型上装探针（也可自己调它，不必用 get_model 补丁） | `mindspeed/core/qat/qsnr_probe.py:428` |
| 假量化内核（默认 w4a16，`QAT_QSNR_KERNEL` 可换） | `mindspeed/core/qat/qsnr_probe.py:682` |
| 看门狗阈值解析 / 触发 | `mindspeed/core/qat/qsnr_probe.py:838`、`:860` |
| `get_model` 的装饰器式补丁入口 | `mindspeed/core/qat/qsnr_probe.py:919` |
| CPU 自检 | `mindspeed/core/qat/qsnr_probe.py:936`（32 条） |
| QAT 训练方案的取值集合 | `mindspeed_llm/features_manager/qat/qat_quant_engine.py:11` |
| 接线调用点 / 静态方法 | `mindspeed_llm/features_manager/qat/qat_quant_engine.py:114`、`:117` |

## 9. 就地验证过什么（2026-10-27）

| 验证 | 结果 |
|---|---|
| 两个补丁在**上游干净树** `git apply --check` | 通过（core `7f89fa89`、llm `d2513bf0`） |
| `qsnr_probe.py --selftest`（补丁后的上游树） | **32/32 PASSED** |
| 内置槽位表 vs 框架 `layer_exempt` 的 `parse_native`/`canonical_of` | 5 组输入**逐字相同**（含 `module.module.` 前缀、`.bias` 后缀、融合槽位返回元组） |
| 环境开关：阈值覆盖 / 阈值写坏 / `WATCHDOG=0` / 标签透传 / 无标签 | 5 条自检用例逐个覆盖 |
| 接线文件 `py_compile` | 通过 |
| 补丁内是否残留某个工程的词汇（`LP_*`／旧工程串／轮次号） | **0 处**（框架侧只认自己的 `QAT_QSNR_*` 键） |
