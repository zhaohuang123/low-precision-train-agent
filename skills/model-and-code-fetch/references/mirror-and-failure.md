# 镜像与失败排查（`model-and-code-fetch` 的参考页）

> 只讲"取不到时怎么办"。规矩与命令在 `skills/model-and-code-fetch/SKILL.md`，这里不重复。

## 1. HF 端点与镜像

| 概念 | 落点 | 说明 |
|---|---|---|
| 官方端点 | `config/project.yaml` 的 `fetch.hf_endpoint` | 空 ⇒ 官方工具默认（`https://huggingface.co`） |
| 镜像端点 | `config/project.yaml` 的 `fetch.hf_mirror` | 官方失败时用它；以环境变量 `HF_ENDPOINT` 传给官方工具 |
| 走不走镜像 | 脚本行为 | 默认"官方 → 失败 → 镜像"；`--mirror-only` 直接走镜像（内网/官方被封时用） |
| 官方端点被黑洞 | 脚本行为（0.18.24 起） | 起手先用 **3s 建连探测**试官方端点：连不上就打印「跳过官方端点」直接走镜像 —— 否则官方工具会在那儿空转重试好几分钟 |
| 大文件走 Xet | 脚本行为（0.18.24 起） | **镜像一律带 `HF_HUB_DISABLE_XET=1`**：`hf` 1.x 的权重大文件默认走 Xet CAS（`cas-server.xethub.hf.co`），镜像不代理那个域 ⇒ 元数据能下、权重 `401` |

**镜像只换"从哪拿"，不换"拿的是什么"**：同一个仓 id、同一个 revision。所以镜像下的东西**不需要额外校验**，
自证照旧（`config.json` 可解析 ＋ 权重非空 ＋ 文件数/大小）。**不要**为了"镜像更快"去改仓 id 或 revision。

## 2. 常见失败与处置

| 症状（报错里会出现） | 含义 | 处置 |
|---|---|---|
| `401`／`403`／`gated repo`／`Access to model ... is restricted` | 该仓要授权（或你的 token 没权限） | 去仓页面接受条款；`hf auth login`（或设 `HF_TOKEN`）后重跑；**不要**换镜像绕过授权 |
| `404`／`Repository not found` | 仓 id 或 revision 写错 | 核对 `<org>/<repo>`（区分大小写）与 `--revision`；不要猜相近名字 |
| `ConnectionError`／`Timeout`／`Name or service not known` | 网络不通 | 先 `--mirror-only` 重试；仍不通 ⇒ 环境问题，报给人（不是实验失败） |
| `No space left on device` | 盘满 | 换盘或清空间；`fetch.min_free_gb` 只是**下限**，不是目标 |
| 下了一半断了 | 正常（大文件常态） | 直接重跑同一条命令：官方工具会**续传**；脚本失败**不删**已下内容 |
| `config.json` 在、权重是 0 字节 | 半截包（常见于被中断后手工拷过） | 删掉**那个 0 字节文件**再重跑（脚本会重新拉缺的）；不要删整个目录（会从头下） |
| `Permission denied`（目标目录） | 目录属主/权限不对 | 换落点或让有权限的人建目录；**不要** `chmod 777` |
| 权重 `401`，域名是 `cas-server.xethub.hf.co` | Xet CAS 取数被挡（镜像不代理它） | 带 `HF_HUB_DISABLE_XET=1` 重跑（脚本对镜像端点**已默认加**）；已下的部分会续传 |

## 3. 代码仓的失败与处置

| 症状 | 含义 | 处置 |
|---|---|---|
| `git clone` 失败：`Could not resolve host` | 网络/DNS | 换可达地址（内网镜像仓）或让用户给本地已有检出路径 |
| `Authentication failed`／`Permission denied (publickey)` | 没配凭据 | 由人配 SSH key / token；脚本不代管凭据、不把 token 写进文件 |
| `fetch` 拿不到 `<ref>` | ref 名写错或远端没这个分支 | 用 `git -C <仓> ls-remote --heads origin` 看真实分支名；不要猜 |
| `checkout` 报 `local changes would be overwritten` | 脏树 | 先处理改动（stash/commit/还原）；**不要** `reset --hard` |
| 切完 `--check` 说"钉点不一致" | 正常：钉点还没同步 | 按脚本打印的"旧 → 新"改任务配置的 `framework_head`／`core_head`，再跑 `preflight.sh` |

## 4. 失败归属一句话

**取不到东西 = 环境未就绪（退出 `2`）**，不是"训练侧无效"（`5`）也不是"评测侧无效"（`6`）。
把它写成 `EXPERIMENT_INVALID` 会让下一轮误以为方案有问题 —— 这条比"下载慢"重要得多。
