# 流水线（PIPELINE）—— 状态机、交接 token 与「谁写状态」

> 给谁看：人。讲**一轮怎么走**：四个角色、十条状态转移、交接物、反馈环、多轮开关。
> 落点的唯一来源是 `runtime/state.py`（状态的唯一写者）与四份 `agents/*/AGENT.md`；
> 本文件只描述机制，**不新增字段、不新增 token**。改了机制才改本文件（与 `VERSION` 同步）。

## 1. 四个角色（`reviewer`／`arbiter` 两个角色已废除，本工程零残留）

| Agent | 职责一句话 | 输入 | 输出（落点） | 交接 token |
|---|---|---|---|---|
| `architect` | 把含糊需求变成一组（3–6 个，含组合）可实验方案 ＋ 跑前冻结的判据 | `config/tasks/<任务名>.yaml`、`knowledge/**`、上一轮反馈 | `<轮次>/{design.md,criterion.yaml}`；`knowledge/` 增补 | `ARCHITECT_READY` / `ARCHITECT_FAILED` / `NEXT_ROUND` |
| `developer` | 把方案落成框架侧改动，改不动就当场报错 | `design.md` 的 `variables:`、任务配置 | `<轮次>/{changes.md,patches/}` | `CODE_READY` / `CODE_FAILED` |
| `tester` | 先冒烟再扫参，交可复现候选配置 | `changes.md`、`criterion.yaml` | `<轮次>/{test.md,round.env}` | `TEST_READY` / `TEST_BLOCKED` |
| `experimenter` | 跑训练→转换→评测→抽数，出报告与结论；跑完还原框架 | `round.env`、`criterion.yaml`、`test.md`、`scheme_resolved.json` | `<轮次>/{report.md,metrics.json,artifacts.json,evidence/}`、`records/conclusions/C-<序号>.yaml` | `EXPERIMENT_DONE` / `EXPERIMENT_INVALID` |

废除的角色的能力去向：**「机制真装上了吗」的验证证据**由 developer 在 `changes.md` 里给（可复现命令）＋ tester 冒烟复跑；
**瓶颈定位**归 tester；**结论裁决**整条上移到 experimenter（`report.md` 含判定段，结论入库）。
数字纪律不随角色废除而放松：报告里**每个数字只能引用 `metrics.json`**。

## 2. 文本流程图

```text
   上层编排/用户 ──① 写 config/tasks/<任务名>.yaml ──② 启动一轮 <轮次>（多轮边界见 loop.max_rounds）
                       │
                       ▼
   architect ──ARCHITECT_READY（design.md ＋ criterion.yaml）──▶ developer
       ▲        │                                                   │ CODE_READY
       │        └─【每轮必跑的门】runtime/validate_round.py
       │           方案冻结、花卡之前；不过 ⇒ 拒绝开跑、显式错误行进 test.md/report.md
       │                                                          ▼
       │                                          tester ──TEST_READY──▶ experimenter
       │                                             ▲                        │
       │                       TEST_BLOCKED（回炉重改）│                        │ EXPERIMENT_DONE
       │                                             └──── developer ◀─────────┤
       │                                                                       ▼
       │      ★ 反馈环：architect ◀── report.md ＋ conclusions/（＋框架还原校验记录）
       │         ① 有记录价值 ⇒ 增补 knowledge/techniques、knowledge/external
       │         ② 人/上层编排决定接着开 ⇒ 开新一轮 → developer（NEXT_ROUND）
       │         ③ 否则 ⇒ LOOP_STOP，交回上层编排/用户
       └── NEXT_ROUND
   分支：tester ──TEST_BLOCKED──▶ developer；developer ──CODE_FAILED──▶ architect（指名缺哪个分支）；
         experimenter ──EXPERIMENT_INVALID──▶ 自己（说清改什么，否则不许原样重跑）
   终止：ARCHITECT_FAILED / CODE_FAILED（连改两次仍不行）/ LOOP_STOP ⇒ done 或 abort
```

## 3. 状态转移表（十条）

| # | 从 → 到 | 交接 token | 交接物 | 进入下一步的条件 |
|---|---|---|---|---|
| 1 | `architect → developer` | `ARCHITECT_READY` | `<轮次>/{design.md,criterion.yaml}` | 方案组已落盘；成功/证伪条件已填；每条候选带自变量与依据；**花卡之前**门退出 `0`；不过 ⇒ 停在 architect |
| 2 | `architect → abort` | `ARCHITECT_FAILED` | 卡点说明 | 需求在当前硬件/框架下不可满足，且指名卡点 |
| 3 | `developer → tester` | `CODE_READY` | `<轮次>/changes.md` ＋ `patches/` | 改动清单列出被改文件与理由；每条 patch 带「文件/为什么/怎么验证」；至少一条可复现的机制生效验证命令 |
| 4 | `developer → architect` | `CODE_FAILED` | 卡点说明 ＋ 缺哪个分支 | 框架表达不了该方案；**不许**填假参数静默降级 |
| 5 | `tester → experimenter` | `TEST_READY` | `<轮次>/test.md`、`<轮次>/round.env` | 冒烟通过（能起、loss 有限无异常跳变、不 OOM、步数对得上）；候选配置带 run 命令与预期耗时 |
| 6 | `tester → developer` | `TEST_BLOCKED` | 报错原文 ＋ 复现命令 | 测试暴露的是代码缺陷，不能靠调参绕过 |
| 7 | `experimenter → experimenter` | `EXPERIMENT_INVALID` | 失败证据 ＋ 触发阈值与步数 | 训练无效（发散/早停），本轮不产生精度结论；**必须说清重跑要改什么**，否则不许原样重跑 |
| 8 | `experimenter → architect` | `EXPERIMENT_DONE` | `report.md`（含判定）＋ `metrics.json` ＋ `conclusions/C-<序号>.yaml` ＋ `evidence/` ＋ 框架还原校验记录 | 三段跑完、证据落盘、数字由 `runtime/metrics.py` 抽出、结论已入库（**失败也入库**）、框架检出已还原且校验一致 |
| 9 | `architect → developer` | `NEXT_ROUND` | 新一轮的 `design.md` ＋ `criterion.yaml` | 人/上层编排决定接着开，且未达 `loop.max_rounds`，且知识增补已完成 |
| 10 | `architect → done` | `LOOP_STOP` | 知识增补记录 ＋ 停止理由 | 人/上层编排决定不再开，或已达 `max_rounds`，或连续 `no_progress_rounds` 轮无进展 |

**一个 token 只有一个生产者。** 非法 token 或「当前 `stage` 不是该 token 的生产者」⇒ `runtime/state.py advance` 退出 `2`。

## 4. 状态接口：唯一写者与三件产物

`state/` 只由 `runtime/state.py` 写（两个写者 ＝ 状态不可信）。落点 `<paths.state>/`（默认 `state/`）。

| 文件 | 可变性 | 谁读 | 内容 |
|---|---|---|---|
| `state/current.json` | 整体覆盖 | 上层编排（机器） | 字段表见 `docs/CONFIG.md` §6：当前阶段、轮次、版本、产物、上一步结论、下一步、卡点 |
| `state/rounds.jsonl` | **append-only** | 上层编排（机器） | 每轮结束由 `close` **恰好追加一行**（字段同 `templates/state-entry.json`）；首行是 `_note` 骨架说明行，解析方跳过 |
| `state/STATUS.md` | 整体覆盖 | 人 | 由 `current.json` **渲染**的六段摘要（不是第二个真相） |

三条子命令与硬约束：

```bash
python3 runtime/state.py init --task <任务名> --round <轮次>          # 建/覆盖 current.json 与 STATUS.md
python3 runtime/state.py advance --handoff <TOKEN>                    # 改 stage/last_handoff/next_action/blockers
python3 runtime/state.py close --conclusion C-<序号> --outcome <adopt|reject|inconclusive>
```

> **0.18.0 起别手跑上面那一串**：`bash scripts/start_experiment.sh <任务名> [轮次]` 会先过
> `scripts/preflight.sh`（任务配置／两仓钉点／卡／评测环境）再调 `init`，**并建 `<轮次>/` 目录 ＋
> 复制模板空壳** —— 全工程只有它会建轮次目录。手跑 `init` 只写状态、**不建目录**，
> 后面每个角色都会因为目录不存在而停下。

- `advance` 不追加 `rounds.jsonl` 行（**轮次行只由 `close` 追加**），只改 `stage` 等字段并重渲 `STATUS.md`。
- `close` 的数字**只引用**本轮 `criterion.yaml` 的 `success.require`（第一条为主指标）与 `<轮次>/metrics.json`；
  `metrics.json` 或该主指标项缺失 ⇒ 退出 `2`（数字的唯一落点不在，不许收口、不许补 `0`）。
- `advance --handoff NEXT_ROUND` 时轮次自增；其余 token 不改轮次。
- `state.py` **不跑 git、不猜**：`framework_state.clean` 初始化是 `null`（未核验），`close` 只在调用方
  显式给出 `--framework-restored {true,false}` 时落该事实 ——「空输出 ≠ 干净」。
- `config_version` ＝ 任务配置内容 `sha256` 前 8 位（形如 `cfg-9f2c1a40`）；尚无真实任务配置时是占位 `cfg-00000000`。

## 5. 反馈环的语义

`experimenter → architect` 不是「再跑一遍」，是**交接 ＋ 沉淀 ＋ 决定要不要继续**。architect 按顺序做三件事：

1. **判有没有记录价值（含多轮累计价值）**：同一技术方案的第二次/第三次验证**不新建条目**，
   只在既有 `knowledge/techniques/` 条目里追加 `evidence.rounds` 并更新 `result`；累计到足够轮次才写成「已成立」。
2. **分流写入**：`knowledge/techniques/` ＝ 本轮的技术方案（自变量 ＋ 结果 ＋ 指向 `metrics.json`）；
   `knowledge/external/` ＝ 本轮引用的外部技术方案（且已被本地实验证明有用）；框架改动按 `knowledge/frameworks/` 分流。
3. **决定下一步**：开了自动探测就开新一轮（转移 9），否则 `LOOP_STOP`（转移 10）。

## 6. 多轮循环的**边界**（没有自动开关）

| 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `loop.max_rounds` | int | `3` | 这条线最多连开几轮；到达即**应** `LOOP_STOP`（由 architect／上层编排执行 —— 引擎**不**自动停，0.11.0 已删 `loop.auto_probe`） |
| `loop.no_progress_rounds` | int | `2` | 连续多少轮主指标无实质变化就停整条线（阈值取 `criterion.yaml` 的 `success.require`，不另发明） |

★ **本对象里没有自动开关**（原有的自动探测开关已按「减法」删掉，见 `ReleaseNotes.md` 0.11.0 段）：
**开不开新一轮由人/上层编排按 `report.md` 决定** —— 本工程不替人做这个决定。

三条硬约束：① 开新一轮的**决定权在人/上层编排**，角色不许自己连开；② 连开**不改变判定权**（每轮仍必须写
`report.md` 并入库）；③ **不放松「不许原样重跑」**（新一轮必须与上一轮有可指名的差别，写进新一轮 `design.md`）。

## 7. 每轮必跑的门在流水线里的位置

- 门是 `runtime/validate_round.py`（**每轮**、由流水线在**方案冻结、花卡之前**调用）；不过 ⇒ 退出 `2`、**拒绝开跑**、
  显式错误行进 `<轮次>/test.md`／`<轮次>/report.md`；用户在对话里只看到一句人话。
- `devtools/validate_design.py` 是**开发期**入口（`devtools/` 与 `tests/` **不随出厂包**），**与每轮门共用同一份规则实现**（不各写一套）。
- `devtools/` 其余检查**不是每轮门**：只在人改工程时／CI 跑。

## 8. 端到端演练（P9）实际走成什么样

P9 用 `config/tasks/` 下的**极小演练配置**（文件名带演练标记，一眼可与真实任务区分）**全程 `--dry-run`** 走完
`architect → developer → tester → experimenter → architect(反馈)`，机械结果：

- `state/current.json` 的 `stage == "done"`；
- `state/rounds.jsonl` **恰好 +1** 行（`R-0001`，`outcome: inconclusive`）；
- `records/conclusions/C-<序号>.yaml` 恰好 1 份（演练轮不产生精度结论，故 `inconclusive`）；
- 轮次目录齐备：`design.md`／`criterion.yaml`／`round.env`／`changes.md`／`test.md`／`report.md`／
  `metrics.json`／`artifacts.json`／`evidence/`／`patches/`。


## 9. 上层编排怎么读、怎么调

```bash
python3 -c "import json;print(json.load(open('state/current.json'))['next_action'])"   # 机器读"下一步派谁"
cat state/STATUS.md                                                                     # 人读摘要
python3 runtime/state.py advance --handoff CODE_READY                                   # 推进一次交接
python3 runtime/state.py close --conclusion C-<序号> --outcome adopt                    # 本轮收口
```
