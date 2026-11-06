# ReleaseNotes — 低精度训练Agent（`lpta`）

> 规则：**框架机制**变化（`runtime/`、`agents/`、`skills/`、`templates/`、`state/`、`config/task.schema.json`、`devtools/` 契约）才升 `VERSION`；每次升版本必须补一段；**每轮实验结束必须追加一行**「框架版本 ＋ 配置版本 ＋ 框架仓库版本」。
> 只改 `config/tasks/*.yaml` 的内容**不升框架版本**，只变 `config_version`（任务配置内容哈希前 8 位，形如 `cfg-9f2c1a40`）。

<!-- 出厂包只带**本版本**那一段；完整变更账本在建设者侧的仓库里。 -->

## 0.20.6 — 2026-11-06（Qwen3_8B_w4a4 R-0001 的 5 条 blocker：全部修复）

> 输入：`/mnt/lpta-request/Qwen3_8b/*.yaml`（CR-0001…CR-0005，由 tester／developer 在真跑中提出）。
> 五条都按代码核过：全部成立，其中 CR-0001／0003／0004 是**脚手架自相矛盾**（模板与消费者对同一件事的假设不同）。

| CR | 改了什么 | 落点 |
|---|---|---|
| CR-0001 | 模板是多行 argv，`train_cmd.sh` 却 `exec bash -c` ⇒ 第 2 行起被当独立命令（exit 127）。**在消费方归一**：读入后去注释（行首／行尾）再把各行拼成一条命令；占位符替换移到归一之后（值里含 `#` 也不会被切） | `templates/commands/train_cmd.sh:43-53` |
| CR-0002 | TP>1／CP>1 时框架硬断言 `CUDA_DEVICE_MAX_CONNECTIONS=1`，而引擎从不设置。**引擎从 argv 读并行度**，TP／CP>1 时自动 export 并打印来源；调用方已设成别的值 ⇒ 退出 2（不静默覆盖） | `templates/commands/train_cmd.sh:228-250` |
| CR-0003 | 驱动用 `is_file()` 校验 `--dataset`，目录型数据集（mmlu）被判非法。改为**双形态**：文件直接过；目录需含 csv 或 task yaml；都不是才报错并指名缺什么 | `templates/drivers/lm_eval_driver.py:495-512` |
| CR-0004 | 驱动从不把本地数据目录传给 lm_eval ⇒ 离线必炸 `ConnectionError`。新增 `eval.lm_eval.include_path`（schema ＋ 模板 ＋ CONFIG），`eval_cmd.sh` 传 `--include-path`，驱动翻成 `lm_eval --include_path`；另加**上卡自证**：日志里出现 `device map {'': 'cpu'}` ⇒ 评测侧无效（退出 6） | `config/task.schema.json`、`templates/commands/eval_cmd.sh:100-104`、`templates/drivers/lm_eval_driver.py:130-135,540-575` |
| CR-0005 | `model.start.path` 带尾斜杠时 `dirname` 退化成父目录、`launch` 落进不存在的目录 ⇒ 转换前 rc=1。路径先归一（去尾斜杠） | `scripts/convert_weights.sh:89-93` |

**同批追加（同目录后到的两条 blocker，也按代码核过）**

| CR | 改了什么 | 落点 |
|---|---|---|
| CR-0006 | `<venv>/bin/lm_eval` 这个 console script 不 import torch_npu ⇒ `--device npu` 被当"无加速器"，**静默**退回 CPU（日志 `device map {'': 'cpu'}`，8B 在 CPU 上跑不动）。`--device npu` 时改用 `python -c` 启动器：先 `import torch_npu.contrib.transfer_to_npu`（把 torch.cuda 映射到 npu）再走 lm_eval 入口。配合 CR-0004 加的自证：日志里出现 cpu 落点 ⇒ 退出 6 | `templates/drivers/lm_eval_driver.py:176-192` |
| CR-0007 | 冻结的 `max_gen_toks` 被模型 `generation_config.max_new_tokens` 压过（实测 518 > 512）。① `--gen_kwargs` 同时给 `max_new_tokens`（`generate()` 自己的参数，优先级最高）；② 跑完**回读 samples 逐样本核生成长度**，超协议值 ⇒ 打出超标样本并退出 6 | `templates/drivers/lm_eval_driver.py:120-125,470-520` |

**CR-0007 的诚实边界**：本机没有真 lm_eval 源码（`/tmp/*/fakelib` 只是空壳），
`--gen_kwargs` 里 `max_gen_toks` 与 `max_new_tokens` 同时给时 lm_eval 内部如何取舍**未在本机验证**。
所以 ② 的样本长度自证是这条的主要保证：真机上如果仍然超限，驱动会**明确报错**而不是出分数。

**顺带修掉的文档假话**：`templates/commands/train_argv.txt` 头部原写"多行无害（`bash -c` 执行时 `#` 之后被忽略）"
—— 正是这条错误认识导致了 CR-0001。改成"多行会被归一；但参数值里别用 `#`"。

**验证**：`devtools/check_templates.sh` 23/23（它用的就是多行模板，`--print` 出的命令现在是单行）；
手工夹具实测：TP=4 未设变量 ⇒ 打印"设置 CUDA_DEVICE_MAX_CONNECTIONS=1"，设成 2 ⇒ rc=2；
数据集三种形态（文件／含 csv 目录／不存在的路径）分别 0／0／2 且报错指名；
`--include-path a,b` 翻成两条 `--include_path`；`run_all.sh` 12 步全绿。

**未做（等真跑反馈）**：CR-0004 提的"起跑前就断言上了 NPU"只在**评测段**做了日志核对；
训练段仍在 `runtime/executor.py` 侧按退出码判，没有额外的设备自证——没有真卡环境，不写没验过的断言。

