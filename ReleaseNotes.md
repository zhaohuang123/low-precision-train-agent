# ReleaseNotes — 低精度训练Agent（`lpta`）

> 规则：**框架机制**变化（`runtime/`、`agents/`、`skills/`、`templates/`、`state/`、`config/task.schema.json`、`devtools/` 契约）才升 `VERSION`；每次升版本必须补一段；**每轮实验结束必须追加一行**「框架版本 ＋ 配置版本 ＋ 框架仓库版本」。
> 只改 `config/tasks/*.yaml` 的内容**不升框架版本**，只变 `config_version`（任务配置内容哈希前 8 位，形如 `cfg-9f2c1a40`）。

<!-- 出厂包只带**本版本**那一段；完整变更账本在建设者侧的仓库里。 -->

## 0.20.3 — 2026-11-04（文档体检：配置契约补全 ＋ 过时事实修正）

> 0.20.2 已发出的包里，`docs/CONFIG.md` **完全没讲 `eval.protocol`**（schema 里有四个键），
> §4.x 编号乱序且有两个 4.2，另有多处过时数字（`run_all` 步数、devtools 件数、自检分母）。
> 这一版只改文档，不动代码与契约。

| 位置 | 改了什么 |
|---|---|
| `docs/CONFIG.md` | **新增 §4.1 `eval.protocol` 与逐集覆盖**：`num_fewshot`／`max_gen_toks`／`batch_size`／`prompt_type` 四条含义与"不写会怎样"，逐键覆盖与 `null`＝显式清空（`eval_cmd.sh` 的真实语义），带 YAML 示例；补 `objective`（标明无读者）；§4 开头加**最小可跑完整示例**（`<…>` 占位，`config.py validate` 实测 rc=0）；§4.x 按物理顺序重排为 4.1–4.7（原两个 4.2、4.0.x 排在 4.1 之后） |
| `docs/ARCHITECTURE.md` | `run_all` **9 步 → 12 步**、`devtools` **九件 → 12 件**；`MIGRATION.md` 标注"建设者文档，不随包" |
| `docs/DESIGN.md` | 自检分母按实测更新（`validate_round` 49/49、`metrics` 144/144、`executor` 67/67、`_common.sh` 62/62）；11 步 → 12 步 |
| `docs/PIPELINE.md` | `devtools/` 标注不随包 |
| `README.md` | docs 行指向能力图谱；`§4.1.1` → `§4.6.3` |
| `VERSION` | 0.20.2 → **0.20.3**（文档变更也需要独立版本号，否则"哪包装的是哪份文档"说不清） |

**为什么单独发一版**：0.20.2 的包已经发出去了，里面是你手上那份缺 `eval.protocol` 的 CONFIG.md。
不重打就是"包与仓库两份文档"，事后谁读哪份都对不上。

**自检**：`run_all.sh` 12 步全绿；`make_release` 泄漏扫描硬失败 0；文档示例过 `config.py validate`。

