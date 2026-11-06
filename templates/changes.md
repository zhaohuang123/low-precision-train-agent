<!-- templates/changes.md —— developer 的改动清单骨架（照抄到 <轮次>/changes.md 再改） -->
<!-- 规则：人读；也是 tester 的输入。核心是「每条改动都能被独立复现验证」。
     机器要读的进 YAML／人看的进 Markdown／同一内容不许两处。 -->
# <轮次> 改动清单 —— <一句话：这轮改了什么>

- 方案块：`<轮次>/design.md`（`id=<方案名>`，`rank=<…>`）
- 框架仓库与钉点：`config/tasks/<任务名>.yaml#train.{framework_repo,framework_head}`
- 工作量估计：<人时>；回滚方式：`git apply -R`（见下）

## 0. 判定：框架能否表达本方案

| 自变量（取值） | 框架里对应实现 | 结论 |
|---|---|---|
| `<变量名>=<取值>` | `<file>:<line>`（参数/开关/量化往返函数/融合结构） | 能表达 / **不能表达** |

- **不能表达时**：本文件到此为止，交 `CODE_FAILED`，并在下面写清**缺哪个分支**：
  - 缺什么：<缺哪段实现/哪个参数/哪个结构分支>
  - 为什么改不动（或要改多大）：<…>

## 1. 改动清单（每条 patch 三栏）

### `patches/0001-<简述>.patch`

<!-- 沿用上一轮已有的补丁时，标题写它真实的家（`### ../R-000X/patches/0001-<简述>.patch`），
     `design.md` 的 `implementation.patch[].ref` 用同一个相对路径；**不要把文件拷进本轮**。
     探针/工具这类每轮都要挂的公共补丁同理，指 `knowledge/frameworks/patches/<特性>/…`。 -->

- **改了哪个文件**：`<路径>`（`<file>:<line>` 附近）
- **为什么**：<机制解释；不写「应该能提升」>
- **怎么验证**：`<可复现命令>` ⇒ 期望输出 `<…>`

<!-- 多份 patch 复制本节；每份都要有三栏；`variables` 里每个 requires_code: true 的取值必须有一条 patch 对应 -->

## 2. 机制生效验证命令（**至少一条可复现**）

```bash
# tester 照抄此命令即可独立确认「机制确实装上了」（不是看起来装上了）
<命令>
```

## 3. 任务级三段入口与命令（写一次、每轮复用）

| 落点 | 说明 |
|---|---|
| `<任务目录>/run.env` | 三段真正要跑的命令与环境变量（**任务级唯一一份**） |
| `<任务目录>/{train,convert,eval}.sh` | 只拼 argv ＋ 调 `runtime/` 引擎；第一行解析 `LP_ROOT` |
| `<任务目录>/{commands/,drivers/,sets/}` | 型号几何写死的命令、闸门、评测驱动、评测集合清单（数据） |

## 4. 挂载与还原

```bash
git -C <框架检出> worktree add <工作树> <framework_head>     # 起点 = 本轮钉点
git -C <工作树> apply --check patches/0001-<简述>.patch
git -C <工作树> apply       patches/0001-<简述>.patch
# 跑完由 runtime/framework_patch.sh：apply -R ＋ 前后 head/status diff 校验（有差异 ⇒ 本轮失败）
```

## 5. 交接

- 交 `CODE_READY`（→ tester）；改不动交 `CODE_FAILED`（→ architect）。
