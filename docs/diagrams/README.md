# `docs/diagrams/` —— 图的位图导出（可选）

四张图的**唯一源在 `docs/DESIGN.md` 的 mermaid 代码块里**（§0.3 架构、§1.3 状态机、
§3.7 时间线、§4.1 数据流）。本目录只放**导出的位图／矢量图**，供 PPT、文档附件、离线阅读使用；
`docs/DESIGN.md` 不引用这里的文件（文档自己就带图，避免"图与源两处"）。

## 什么时候需要导出

- 只在查看器**不渲染 mermaid** 时才需要（例如纯文本终端、部分 Wiki、PPT）。
- GUI／GitHub／GitLab／VS Code 都原生渲染 mermaid，不需要本目录。

## 怎么导出（一次性依赖，不进工程）

```bash
mkdir -p /tmp/mmdc && cd /tmp/mmdc && npm init -y >/dev/null
npm i --no-audit --no-fund @mermaid-js/mermaid-cli jsdom

# 从 DESIGN.md 抽出四个 mermaid 块（顺序固定：架构 / 状态机 / 时间线 / 数据流）
python3 - <<'PY'
import re, pathlib
src = pathlib.Path("docs/DESIGN.md").read_text(encoding="utf-8")
names = ["architecture", "state-machine", "round-timeline", "data-flow"]
blocks = re.findall(r"```mermaid\n(.*?)```", src, re.S)
for name, body in zip(names, blocks):
    pathlib.Path(f"/tmp/mmdc/{name}.mmd").write_text(body, encoding="utf-8")
print("抽出", len(blocks), "块")
PY

cd /tmp/mmdc
for n in architecture state-machine round-timeline data-flow; do
  npx mmdc -i "$n.mmd" -o "/path/to/repo/docs/diagrams/$n.svg" -b white
  npx mmdc -i "$n.mmd" -o "/path/to/repo/docs/diagrams/$n.png" -b white -w 2400
done
```

> `-w 2400` 是宽度像素（PPT 用够清）；`-b white` 把背景刷白（默认透明，贴深色主题会看不清字）。
