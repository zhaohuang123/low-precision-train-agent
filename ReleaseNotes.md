# ReleaseNotes — 低精度训练Agent（`lpta`）

> 规则：**框架机制**变化（`runtime/`、`agents/`、`skills/`、`templates/`、`state/`、`config/task.schema.json`、`devtools/` 契约）才升 `VERSION`；每次升版本必须补一段；**每轮实验结束必须追加一行**「框架版本 ＋ 配置版本 ＋ 框架仓库版本」。
> 只改 `config/tasks/*.yaml` 的内容**不升框架版本**，只变 `config_version`（任务配置内容哈希前 8 位，形如 `cfg-9f2c1a40`）。

<!-- 出厂包只带**本版本**那一段；完整变更账本在建设者侧的仓库里。 -->

## 0.20.5 — 2026-11-04（回退 0.20.4 的包根瘦身，保留 README 改动）

> 0.20.4 把 `MANIFEST.tsv`／`SEED_DIRS.txt`／`LEAK_REPORT.txt` 从包里删掉、把安装计划注入
> `deploy/install.sh`。复核后判定这个手段**重于它解决的问题**，本版回退；README 删 §4 的改动保留。

| 位置 | 改了什么 |
|---|---|
| `devtools/make_release.py` | 恢复写出 `MANIFEST.tsv`（sha256/class/dest）、`SEED_DIRS.txt`（空目录）、`LEAK_REPORT.txt`（历史出处清单）；去掉注入逻辑 |
| `deploy/install.sh` | 恢复读 `$PKG_ROOT/MANIFEST.tsv` 与 `SEED_DIRS.txt`；去掉注入变量与锚点 |
| `deploy/verify_install.sh` | 恢复 `wc -l MANIFEST.tsv` 的行数比对（不再 awk 解析 bash 文件） |
| `docs/DESIGN.md`、`devtools/README.md` | 恢复对 `MANIFEST` 的表述（安装资产不进清单） |
| `README.md` | 保持 0.20.4 的改动：§4「新工程与旧工程的边界」已删，§5／§6 → §4／§5 |

**回退理由（三条，都是 0.20.4 引入的真实代价）**：
1. **`install.sh` 不再可钉**：安装计划注入后它每次打包都变，外部无法用固定 sha256 校验安装器。
2. **`verify_install.sh` 靠 awk 数 bash 文件里的行**：注入格式一改就数成 0，虽是大喊失败，但这种耦合不该有。
3. **多出一个几乎跑不到的兼容分支**（新安装器只跟新包走）——按本工程“没有读者就是死字段”的标准不合格。

**代价对冲**：包根会重新出现这三份文件。它们是安装器的输入与打包者的报告，不是产品内容；
`README`／`PREREQUISITES` 里写明它们各自的用途，不必靠“看不见”来保持整洁。

**自检**：`run_all.sh` 12 步全绿；`make_release` 硬失败 0；安装演练写入 113／已一致 0／记录 99+14 行；
`verify_install.sh` ✅ 全过；包根含正文 ＋ `VERSION` ＋ `deploy/` ＋ 三份账目。

