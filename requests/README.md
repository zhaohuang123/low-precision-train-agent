# `requests/` —— 使用者 → 建设者的诉求（change request）

> 一句话：**轮次跑着的时候，你发现"框架层面该改"，就写一个文件放这里；不要改 `runtime/`。**
>
> 目录位置由 `config/project.yaml` 的 `paths.requests` 决定（默认就是本目录，可指到共享盘）。
> 本目录**不进流水线**：不发 token、不进 `state/`、不设门、不影响 `preflight.sh`。

## 1. 什么时候写

**该写**（框架级缺口，四类）：

| 类 | 例子 |
|---|---|
| `rule` | 某条硬禁令/规则在实际场景里没法执行 |
| `schema` | 任务配置 / 方案块 / 判据缺一个字段，或者校验太严/太松 |
| `script` | `scripts/` 或 `runtime/` 的某个工具没有覆盖你的场景 |
| `doc` | 文档与代码不一致、步骤跑不通 |
| `error-msg` | 报错只说"失败"，不说"哪一步、怎么办" |
| `tooling` | 缺一个本该有的辅助能力（不是"想加一个门"） |

**不该写**（这些有各自的落点）：实验结论 → `<轮次>/report.md` ＋ `records/conclusions/`；方案 → `<轮次>/design.md`；训练参数 → 任务配置；模型/代码没就位 → 用 `model-and-code-fetch` skill。

## 2. 怎么放

一个诉求一个文件，命名 `<任务ID>-<轮次>-<序号>.yaml`：

```
Qwen3-...-R0007-01.yaml      # 某个任务某一轮提的第 1 条
ALL-R0007-02.yaml            # 跨任务/跨轮（"ALL" 表示不限定）
```

文件名只是索引，**事实以文件内字段为准**（`task_id`／`round_id`）。
骨架照抄 `_TEMPLATE.yaml`；字段不许自创（要加字段 ⇒ 先自己提一条 `schema` 类诉求）。

## 3. 字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 目录内唯一，建议 `CR-<四位序号>` |
| `status` | 是 | `open`／`accepted`／`rejected`／`done` —— **只有建设者改** |
| `task_id` | 是 | 哪个任务；跨任务写 `ALL` |
| `round_id` | 是 | 哪一轮（如 `R-0007`）；跨轮写 `ALL` |
| `raised_by` | 是 | `user`／`architect`／`developer`／`tester`／`experimenter` |
| `raised_at` | 是 | 日期（`YYYY-MM-DD`） |
| `category` | 是 | 上表六类之一 |
| `severity` | 是 | `blocker`（挡着跑不下去）／`annoyance`（能绕）／`idea`（想要） |
| `title` | 是 | 一句话说清"哪里不对" |
| `context` | 是 | 现象 ＋ **证据**：命令、`file:line`、日志片段。没有证据的诉求不算诉求 |
| `expected` | 是 | 期望变成什么样（一句可验收的话） |
| `workaround` | 否 | 现在怎么绕过去；没有写"无" |
| `resolution` | 否 | **建设者填**：哪个版本、怎么改的、为什么不改 |

## 4. 纪律（三条）

1. **轮次进行中不提改动、只提诉求**：框架层面缺东西 ⇒ 写文件，别动 `runtime/`／`templates/`／`config/task.schema.json`（那是硬禁令，见 `AGENTS.md` §2）。
2. **一条一文件，append-only**：写错了就再提一条并注明"取代 CR-xxxx"，不要改别人写的条目。
3. **状态与结论只由建设者改**：`status` 与 `resolution` 之外的字段写完就别动。

## 5. 建设者怎么用

```bash
grep -l '^status: open' requests/*.yaml      # 还有哪些没看
```

处理完一条：`status: done` ＋ `resolution: 0.18.x —— 改了什么`（版本号必须写，便于对账）。
