<!-- templates/design.md —— architect 的「一组方案」骨架（照抄到 <轮次>/design.md 再改） -->
<!-- 规则：机器要读的进 YAML 块／人看的进 Markdown／同一内容不许两处。
     块内**只**放自变量与实现手段；依据、假设、排序理由写在正文（块外）。
     块里**不许**出现依据/假设/阈值/判据（门规则 6）。 -->
# <轮次> 方案组 —— <一句话问题>

- 任务：`config/tasks/<任务名>.yaml`（场景 ①，只读）
- intent_ref: <序号>「<该条 intent 的原文首句>」—— 本轮服务 `intents[]` 的哪一条；按轮次的预算计数就认这一行
- 本轮问题：<这一轮到底要回答什么；必要的话指向上一轮报告>
- 轮次目录：`<artifacts.root>/rounds/<轮次>/`

## 0. 架构与显存预算（判完才动方案）

| 项 | 值 | 来源 |
|---|---|---|
| 架构类型（dense/MoE/MLA/GQA） | | `knowledge/models/<模型名>.yaml#arch.*` |
| 显存分项（权重/梯度/优化器/激活/通信缓冲） | | `knowledge/models/<模型名>.yaml#memory.*` ＋ 算式 |
| 可行并行与序列长度/微批锚点 | | `<paths.experiments>/<任务名>/` 锚点配置 |

## 1. 候选组（3–6 个，**至少含一个组合方案**）

> 每个候选一块，块内 `variables:` 的键名与取值**由 architect 自己读框架代码判定**（0.18.0 起没有旋钮字典了）：
> 每个旋钮都要在本节正文写清它在这份框架检出的哪一行生效；排序理由写在本节文字里，
> 与块内 `rank` 一一对应。

<!-- LP-SCHEME-BEGIN -->
```yaml
schema: 1
id: <方案名>                      # 同一轮内唯一；与 <轮次>/patches、conclusions 的引用一致
axis: <受控轴名>                  # 枚举：precision|scale_granularity|rotation|layer_policy|clamp|
                                  #       rounding|qat_schedule|master_weight|train_hparam|kernel_fix
question_ref: <本份 criterion.yaml 的 id>
rank: 1
strength_target: "<一句话自由文本>"   # 自由文本或 null；**不是档位枚举**，内容不参与机器判定
supersedes: null
variables:
  # 每个写出来的变量必须同时有 value 与 requires_code（门只查这一条自洽：true ⇒ 本轮必须有 patch）
  # 键名/取值没有白名单；写错的旋钮会在起训练时报错，不静默
  <变量名>: {value: <取值>, requires_code: false}
implementation: {mode: framework_native}
```
<!-- LP-SCHEME-END -->

<!-- 需要改代码时，implementation 换成：
implementation:
  mode: patch
  patch:
    - ref: patches/0001-<简述>.patch     # 相对本轮次目录；文件必须真实存在
      why: <为什么必须改代码；一句话>
-->

### 1.1 排序与依据

| rank | 方案名 | 与其它候选的差别 | 依据（知识库/历史结论/框架能力） |
|---|---|---|---|
| 1 | | | |

## 2. 外部来源（两条入口，都只到候选为止）

> **可以作候选来源**：外部来源能触发候选方案。但它是**未验证**的 —— 每个候选都要写清
> ① 借了哪一条（§2.1 的文件名 / §2.2 的 URL ＋ 一句话）；② 它在这个模型/框架上**可能为什么不成立**；
> 都没有就写「无先验」。**判据不许来自这里**（不进 `criterion.yaml`、不作 `variables:` 的取值理由）。

### 2.1 归档命中（`knowledge/external/`）

- 命中的文件：<无 / `knowledge/external/NN-xxx.md`：一句话>
- 没命中也写一句：<查了哪些主题词>

### 2.2 关键字检索（`intents[].external.keywords` → `web_search`；`sources` → `web_fetch`）

> 取关键词的顺序：本轮 intent 的 `external.keywords` → 任务配置 `knowledge.external.keywords` → 都没有就写「未配置，未检索」。
> 命中**不落盘**进 `knowledge/external/`（只在这里留痕）；工具不可用就写「工具不可用，未检索」，不许编来源。

| 查询词 | 命中的来源（URL / 标题） | 采信 / 丢弃及理由 |
|---|---|---|
| | | |

## 3. 落盘自检

```bash
python3 runtime/validate_round.py <轮次>/design.md      # 每轮必跑的门：退出 0 才算方案落盘
# （建设者侧另有一件同规则的开发期自检，住 devtools/；**出厂包里没有它**，也不需要）
```
