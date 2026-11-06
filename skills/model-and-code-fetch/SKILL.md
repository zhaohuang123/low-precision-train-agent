---
name: model-and-code-fetch
description: 当模型权重或代码仓还没就位、或要把本地代码切到指定分支/提交时加载——先用一句话问清用户要什么（模型 id／仓 URL／分支），再跑 scripts/fetch_model.sh（官方端点先试、失败自动换 HF 镜像，下完自证）或 scripts/fetch_code.sh（从零克隆或在已有检出上切 ref，脏树拒绝，切完打印钉点要改成什么）。只做「取与切」，不做权重格式转换、不建评测环境、不改任务配置。
version: 1.0.0
applies_to: [developer, tester, experimenter]
---

# 模型与代码的取用（`model-and-code-fetch`）

## 0. 谁用 / 什么时候用 / 不做什么

**用**：① 任务配置指到了某个权重目录，但那个目录**还不存在**；② 要用的框架仓**还没克隆**；
③ 本地检出**不在要用的分支/提交**上。

**不用**：① HF 权重转 mcore 训练起点（那是 `weights-convert`，**本 skill 只负责"把东西取下来"**）；
② 建评测 venv（`bootstrap-eval-env`）；③ 改任务配置里的任何字段（回填由人做，见 §2.3）；
④ **轮次进行中**（会打碎本轮钉点，见 §3.2）。

## 1. 先问，再动手（本 skill 的硬规矩）

**模型和代码"要哪个"，永远先问用户，不许猜**：

| 缺什么 | 问法（一句话，给候选而不是开放式） |
|---|---|
| 模型 | 「权重从哪个仓取？给 `<org>/<repo>`；本地已有目录的话给我路径，我直接校验不下载」 |
| 仓 URL | 「这个仓的远端地址是哪个？（任务配置里 `*_url` 是空的，只能问你）」 |
| 分支/提交 | 「要切到哪个分支或提交？不指定的话我按任务配置的钉点校验现状」 |

问完把答案落成命令；**没有答案就先别跑**。用户给了本地已有路径 ⇒ 走"只校验"（`--check`／`--dry-run`），不下载。

## 2. 模型：`scripts/fetch_model.sh`

### 2.1 一条命令

```bash
# 任务配置里有 model.source.{url,path} 时（推荐：落点不用手打）
bash scripts/fetch_model.sh --task <任务名>            # 真下
bash scripts/fetch_model.sh --task <任务名> --dry-run   # 只查依赖/磁盘/现状
bash scripts/fetch_model.sh --task <任务名> --print     # 只打印将执行的命令

# 任务配置还没填时（手工场景）
bash scripts/fetch_model.sh --repo <org>/<repo> --dest <目录> [--revision <branch|tag|sha>]
```

### 2.2 它会做什么（按顺序，全部可复现）

1. 端点与镜像**只从** `config/project.yaml` 的 `fetch.{hf_endpoint,hf_mirror,min_free_gb}` 读（缺 ⇒ 内建默认，并打印"内建默认"）。
2. **幂等**：目标目录已有 `config.json`（能解析）＋ 至少一个非空权重文件 ⇒ 判"已就绪"，打印实测摘要后退出 `0`，**不重下**。
3. **下载前查目标盘空闲**（默认要求 ≥ 50 GiB，可配）：不够就退出 `2`，不许下到一半炸。
4. 官方端点先**探 3s**（连不上就跳过，别让官方工具空转重试几分钟），再试；**失败才换镜像**（`HF_ENDPOINT` 换成 `fetch.hf_mirror`）。两次都失败 ⇒ 退出 `2`，打印两条可复现命令与原样报错尾部。
   镜像一律带 `HF_HUB_DISABLE_XET=1`（`hf` 1.x 的权重默认走 Xet CAS，镜像不代理那个域 ⇒ `401`）。
5. 下完**自证**：`config.json` 可解析 ＋ 权重文件非空 ＋ 文件数/总大小。自证不过也算失败（不当成功）。

### 2.3 下完只做一件事：告诉人往哪填

脚本最后会打印 `model.source.path = <实际路径>`。**不要自己改任务配置**（改 YAML 会丢注释，且部署事实必须由人确认）。
如果 `model.source.url` 为空、而用户给的是 HF 仓 ⇒ 顺手告诉他：`url` 建议写成 `hf:<org>/<repo>`（形状能被脚本直接解析）。

## 3. 代码：`scripts/fetch_code.sh`

### 3.1 三种动作

```bash
bash scripts/fetch_code.sh --task <任务名> --repo train --check            # 只校验：HEAD vs 钉点、工作树干净
bash scripts/fetch_code.sh --task <任务名> --repo core --clone --ref <ref> # 从零克隆再切
bash scripts/fetch_code.sh --task <任务名> --repo train --ref <ref>        # 已有检出：fetch + checkout
```

`--repo train|core` 选哪个仓：`train` ⇒ `framework_repo`／`framework_url`／`framework_head`；
`core` ⇒ `core_repo`／`core_url`／`core_head`。

### 3.2 与钉点的关系（**最容易被误用**）

`framework_head`／`core_head` 是**本轮起点的钉点**，`scripts/preflight.sh` 会拿它跟 `git rev-parse HEAD` 比对。
所以：

- **切换 ref ⇒ 钉点必变**。脚本**只切换、不改配置**，切完打印「`train.framework_head`: 旧 → 新」；
  不同步改钉点就开跑 ⇒ **preflight 拒绝**（这是设计如此，不是 bug）。
- **轮次进行中不许切**：先停本轮，或按 `requests/README.md` 提一条诉求（框架层面缺东西 ≠ 就地改）。
- **脏树拒绝**：有未提交改动 ⇒ 退出 `2`，脚本**不 reset、不丢改动**；确认要带着脏树切，由人显式加 `--allow-dirty`。

### 3.3 自证（每次动作之后）

`git rev-parse HEAD` 打出来 ＋ `git status --porcelain` 干净 ⇒ 成功；任一不符 ⇒ 退出 `2`。
`--check` 是默认动作（不给 `--ref`／`--clone` 时）：它只报告，不切换。

## 4. 失败怎么归（别归错桶）

| 现象 | 归哪 | 处置 |
|---|---|---|
| 网络不通、端点 401/403（要授权）、404（id 写错）、超时 | **环境未就绪**，不是训练/评测无效 | 退出 `2`；按报错改 id／申请权限／换镜像重试；**不许**把这类失败写成 `EXPERIMENT_INVALID` 或退出 `5`/`6` |
| 目标盘空闲不够 | 环境 | 换盘或清空间；`fetch.min_free_gb` 是可配的**下限**，不是目标值 |
| 已经就绪（幂等命中） | 正常 | 退出 `0`，继续原计划 |
| 钉点不一致（`--check`） | 契约 | 切回钉点，或按新 ref 同步改钉点后重跑 `preflight.sh` |
| 脏树 | 安全 | 先处理改动；**永远不要**用 `reset --hard` 绕 |

## 5. 交什么（写进 `<轮次>/test.md` 或 `report.md` 的"环境"小节）

1. **取了什么**：模型 `<org>/<repo>`@`<revision>` → 落点路径；或代码 `<url>` → `<ref>`（切前/切后 HEAD）。
2. **怎么验的**：脚本名 ＋ 退出码 ＋ 自证三行（文件数/大小、`rev-parse HEAD`、`status --porcelain`）。
3. **改了钉点没有**：改了 ⇒ 旧值 → 新值；没改 ⇒ 写"未改（与钉点一致）"。
4. **网络事实**：走了哪个端点（官方/镜像）—— 换过镜像要写，因为下次复现可能又要换。

## 6. 不做什么（再说一遍，因为这里最容易越界）

- 不猜模型名、不猜分支名、不猜仓库地址：**缺什么问什么**。
- 不 `git push`／不 commit／不 `reset --hard`／不删目标目录里已有的东西。
- 不改任务配置（`model.source.*`、`train.*_url`、`train.*_head`）：只打印"要改成什么"。
- 不在轮次进行中切钉点；不改框架检出里的任何文件（那是 `code-change` 与 `framework_patch.sh` 的事）。
- 下载失败不重试超过"官方→镜像"两次（无限重试会把问题糊住）。
