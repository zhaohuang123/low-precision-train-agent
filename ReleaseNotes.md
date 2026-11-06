# ReleaseNotes — 低精度训练Agent（`lpta`）

> 规则：**框架机制**变化（`runtime/`、`agents/`、`skills/`、`templates/`、`state/`、`config/task.schema.json`、`devtools/` 契约）才升 `VERSION`；每次升版本必须补一段；**每轮实验结束必须追加一行**「框架版本 ＋ 配置版本 ＋ 框架仓库版本」。
> 只改 `config/tasks/*.yaml` 的内容**不升框架版本**，只变 `config_version`（任务配置内容哈希前 8 位，形如 `cfg-9f2c1a40`）。

<!-- 出厂包只带**本版本**那一段；完整变更账本在建设者侧的仓库里。 -->

## 0.20.4 — 2026-11-04（出厂包瘦身：包根不再摆构建账目）

> 0.20.3 的包根上还躺着 `MANIFEST.tsv`／`SEED_DIRS.txt`／`LEAK_REPORT.txt` 三份账目，`README` 里还留着
> 「新工程与旧工程的边界」一节。前者让"产品"看着像"一次构建的产物"，后者对拿到包的人毫无意义
> （他没有旧工程）。这一版把两件事一起清掉，**不动引擎与契约**。

| 位置 | 改了什么 |
|---|---|
| `README.md` | **删去 §4「新工程与旧工程的边界」**（内容本来就在 `docs/MIGRATION.md` §7）；后续 §5／§6 顺次改为 §4／§5，`§6.1` → `§5.1`；`devtools/` 行按实际改成"12 件、12 步" |
| 出厂包 | **不再生成** `MANIFEST.tsv`／`SEED_DIRS.txt`／`LEAK_REPORT.txt`；安装计划**注入 `deploy/install.sh`**（`LP_EMBEDDED_MANIFEST`／`LP_EMBEDDED_SEED_DIRS`） |
| `deploy/install.sh` | 读安装计划改为"注入优先、旧包 `MANIFEST.tsv` 兼容"；空目录清单同理；缺计划仍 fail-closed 退出 2 |
| `deploy/verify_install.sh` | 记录行数比对改为从注入块取（无 `MANIFEST.tsv` 的包也能核对） |
| `devtools/make_release.py` | 写盘阶段：注入安装计划后 `chmod 755`；泄漏扫描的历史出处清单**只打屏幕、不落盘**；锚点缺失即退出 2 |

**为什么保留"注入"而不是彻底不打包**：安装器的输入不能凭空消失——它要知道每个文件的 sha256／class／目标路径，
否则没法判"已一致"与"被谁改过"。注入让它从"包根的一份账目"变成"安装器自己的一部分"。

**代价（写在这里，免得以后有人以为是 bug）**：`deploy/install.sh` 的内容每次打包都变，所以它的 sha256 不稳定。

**自检**：`run_all.sh` 12 步全绿；`make_release` 硬失败 0；安装演练（临时目录）写入 113／一致 0／记录 99+14 行；
`verify_install.sh` ✅ 全过；解包后包根只剩正文 ＋ `VERSION` ＋ `deploy/`。

