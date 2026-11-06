#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# install.sh —— 把 lpta 出厂包装进一个**目标工程根目录**（安装／升级／状态／卸载）
#
# 用法
#   bash deploy/install.sh <目标目录> [动作] [选项]
#
# 动作（默认 = 安装；目标已有安装 ⇒ 自动按升级走）
#   --status            只报「目标版本 vs 包版本」与逐文件差异，**不写任何东西**
#   --uninstall         卸载本工程：按安装记录删 managed；**seeded 一律保留**（使用者写过的内容不是我们的）
#   --uninstall-agents  顺带卸掉**已装成 subagent** 的四个角色（在 `--agents-dir` 里；默认不碰宿主）
#
# 选项
#   --with-agents       把四个角色**导出成 DSH subagent**（写进 `--agents-dir`，默认 `${DSH_HOME:-$HOME/.dsh}/agents`）
#   --agents-dir <DIR>  指定那个目录（给了它就等于给了 `--with-agents`）
#   --force-managed     覆盖「被改过的」managed 文件（覆盖前存 `<文件>.bak`）
#   --force-downgrade   允许装比目标**更旧**的版本
#   --no-git            不在目标目录 `git init`
#   --dry-run           只打印计划，不落盘
#
# ★ 四个角色要不要装成 subagent（两种用法都合法，别选错）
#   A 一个主 Agent 依次扮四个角色（自己读 `agents/<角色>/AGENT.md` ＋按 `AGENTS.md` §5 挂载 skill）
#     ⇒ **不用装**。工程文件齐了就够，默认就是这个模式。
#   B 真用 `use_agent architect` 之类**派子代理**
#     ⇒ **必须** `--with-agents`，且装完要**重启 dsh**（工具名册是装载时静态构建的）。
#   本脚本**默认不碰宿主注册表**，只在结尾提醒你选了哪种。
#   ⚠ 若跳过这一步却按 B 用，症状是 `use_agent architect` 报 unknown agent，
#     而 `agents/*/AGENT.md` 明明都在 —— 见 `PREREQUISITES.md` §2.1。
#
# 四条纪律（fail-closed）
#   ① **冲突先报后停**：有 managed 冲突却没给 `--force-managed` ⇒ 列全清单后退出 2，**一个字节都不写**；
#      给了 `--with-agents` 时，subagent 侧的预检也在**落盘之前**做，同样「先报后停」
#   ② **seeded 永不覆盖**：装一次就不再动（`config/project.yaml`、`knowledge/INDEX.md`、
#      `records/conclusions/_EXAMPLE.yaml` —— 使用者会往里写东西）
#   ③ **记录无时间戳**：`.lpta-install.tsv` 只有 `sha256<TAB>class<TAB>路径` ⇒ 同一份包装两次，记录逐字节相同
#   ④ **不动你没点名的盘**：subagent 只在给了 `--with-agents`／`--agents-dir` 时才写；
#      `--uninstall` **不**顺手删宿主里的角色（要删得显式 `--uninstall-agents`）——
#      agent 文件可能是别人手调过的 persona，不由项目安装器替人决定
#
# 退出码：0 成功｜2 前置条件/冲突不过（fail-closed）
set -euo pipefail

# >>> LP_INSTALL_PLAN（打包器在本行之后注入安装计划；源代码里本行之后为空）<<<
LP_EMBEDDED_MANIFEST=$(cat <<'LP_MANIFEST_EOF'
804b8c4567784d23ed5ef74edecfbe801825d424f0aec7a10ca5dfd7f5100172	managed	.gitignore
7ceba2ed0a3cb84431b64c87f3fb8fd439625e0d3dca98234cd837fcfbbf30d2	managed	AGENTS.md
9d621c323a6cd5cba550734099ec065804c9758b7d3eac0c3909ca91aa8aaa68	managed	README.md
4403eab7571357b9005e5983d3ee10739bdb3112b297d939de3d21d580f2a4f0	managed	ReleaseNotes.md
0cfb045081b8859cfa59ad1c2a3902703aa3c5bc8c7c692d4fd02fab9fb10f78	managed	VERSION
daa318e66dc8003fcfe99aef496c786d564ddc2801d857605b3a951e6d121f18	managed	agents/architect/AGENT.md
a66d23f41f87daf0d184104c98c128a2665092fcae2b151c9e7419844f0eb651	managed	agents/developer/AGENT.md
9b6fa8b04ebc6a90c11cb728f868534ddb2b90e133a98f2f5b23dd532ad3f006	managed	agents/experimenter/AGENT.md
ef728d87878884dba52102411350de482c13c0dda6af8ae21925bc0edaf8c94d	managed	agents/tester/AGENT.md
eba85403946525569d82dac7bd5af6d755e63a9e140cd69b09c730f9b6d92631	seeded	config/project.yaml
67c0028967bb1398e662ee9c393eca32b4cdcdc3b0588bdd08ba1a5502101a47	managed	config/task.schema.json
63e266ade8c042b2e491b455e711ff8d3cf6612c49a6a08160db38fe22ed2344	managed	config/tasks/_TEMPLATE.yaml
b3b5d8ccc00501ef5707591e071b07c7cd74709a7c9e6731a47a5a4748adcce8	managed	docs/ARCHITECTURE.md
f7f961cb6f358fbaf21087fe03bd2232539e86cd8c80b2a513163cf62b66017f	managed	docs/CAPABILITIES.md
2f7c066f35f4ad3ccac319c74e2d0acb5f2c377bb84cc668f213b75538d1fbd8	managed	docs/CONFIG.md
215f20d9f2dbc479ee85730621c03679528b6387db6f242bd1fb31a50d82e6a8	managed	docs/DESIGN.md
8725c64dbeadf7aafb1213c326a824e6f4830b0a249d065eb35e413371057f39	managed	docs/MAP.md
a09b5491c9a0cfd8de8167f305deb7924a81f9568e4aa199b5562daf596daf55	managed	docs/PIPELINE.md
58b3aec4702545ec9198776dc9a1aa24e0059ba4003a4a9ff6700c03d43f4d53	managed	docs/diagrams/README.md
53aeb556f0093c198fc75e8b5b3dc3222887c9b20b922cca05d416703eddc1a2	managed	experiments/README.md
cf3bfd6c6bbde0d19ab391c32458b550e22e797a26af8ff1a45b207638fdee1a	seeded	knowledge/INDEX.md
c06bf254bec9c34736f081176b4be87ef97ff73fe8e6b972085e0d6079f4a6b2	managed	knowledge/README.md
d2f11f1acb82ea85885873b88b9770e919400107ba2ce057b875dc6477d726d0	seeded	knowledge/external/01-transposition-invariant-scaling.md
cb4de95a05ce8bbbc654572c3b49b47b532b7503ac14443f4d80dd25397e07f2	seeded	knowledge/external/02-macro-block-scaling.md
9abb2b2df2cc5011ca745c561f676df5812fecfbb1f3ace411f24a77f1a6e507	seeded	knowledge/external/03-residual-aware-binarization.md
2fbfb28fdd3e615393ffa34d1574390495e47197bfd9b44580820552beae51e5	seeded	knowledge/external/04-muon-optimizer-quantization.md
dc07e91c7957f3e3caf704c44fd444d120ed0b1d426c3a44dbde9bd07b0a7d7d	seeded	knowledge/external/05-qat-schedule.md
a8ccd6d1f563f60d72a6297c9fb7eba2b12620d6f80f524500e4d3bc6f094bd9	seeded	knowledge/external/06-parameter-efficient-qat.md
1e13039d0638f4461893b0712d9a47790e5f36cbda3181ff5f109545980c44dc	seeded	knowledge/external/07-reasoning-qat-reqat.md
0a1377558a8f3dbf993ff1a19d430b9bd0f141d8e0b0ed55fe7bb4dfe19c3d5b	seeded	knowledge/external/08-mixed-precision-fallback.md
a00c24d15b9556f598ceb1dee741c5d40db2e545aea6caec01ca2ebaee3dd6da	seeded	knowledge/external/09-outlier-suppression-rotation.md
436de9a2d0bbf3f4b760b69a4251fddbf6805055e147760bf8aef970bdca7869	seeded	knowledge/external/10-calibration-initialization.md
22abf51eb9fe3ab9590d6f28faa243d95a9c844fab6917abfde42033af5b8fd1	seeded	knowledge/external/_README.md
3301368752b844e48ceae79954e7e3d7d22e0b1d2144fe224572026a2ead6805	managed	knowledge/frameworks/MindSpeed-mxfp4-mask-fix.md
8ac433625aa337d0b43cc6ec4fe921127624d6d6721dce6bb076f7eb8d2ca26d	managed	knowledge/frameworks/MindSpeed-qat-qsnr-probe.md
998ae3813f7cb58b61978e36ab02524916589e4adebc2edbc3cd87ea08ee03cc	managed	knowledge/frameworks/README.md
5e734f41b21ef213379774d8b4bf9a3ca35180405478fb29beaf9dabc846ec84	managed	knowledge/frameworks/patches/mxfp4-mask-fix/core/mindspeed/core/qat/w4a16_fake_quantization.patch
42c42cbba0c971ad82cec45819831004a79a8e8366db06fad02e8b81fa90ff6a	managed	knowledge/frameworks/patches/qat-qsnr-probe/core/mindspeed/core/qat/qsnr_probe.patch
f2735607cbbce343a2895d1d53c9b9f153bf02629d6eee3c8bf0240aa2855589	managed	knowledge/frameworks/patches/qat-qsnr-probe/llm/mindspeed_llm/features_manager/qat/qat_quant_engine.patch
b76627b0817fed136ec132b62d7e0ac6c2ee659b624f6047256e9bce9ee88494	managed	knowledge/models/DeepSeek-V4-Flash.yaml
3314bc67dded5d68981fedfc4a52b8b4c45c8b9a7db112d37a993bb6d59686c5	managed	knowledge/models/Qwen3-4B.yaml
f0822b899cb71a45dc2d4c9213dffe7db9c5c8a02a3b392a640235b779bb581e	managed	knowledge/models/Qwen3.5-35B-A3B.yaml
d83d9be8198635dde09ff2680b87b1e1ecdc1e699723f323d62f41b71d60691a	seeded	records/conclusions/_EXAMPLE.yaml
a2a20e4b1bffdf2f2807cc046c9ebdab6cd27ebe63f6a26d8317d8ee0a653932	managed	requests/README.md
5002fe1f8e2b638d826ef0959f7623d6dd1caace7dea1a06079fc132ab7664d5	managed	requests/_TEMPLATE.yaml
f95016d6a839f9fdc363c9f2a6cd02d68002de984129f7fa527326ed13e6836d	managed	runtime/README.md
e76c59689172202fed7e36edc393c10cf2eb935f8c98739eb50b5c966a9b6d47	managed	runtime/_common.sh
5132e9907eda7efb082f62939f59d21d9cdbff37f736b950422033f6fe2848b1	managed	runtime/charts.py
9c69635d0bb11be476112f41b6668ff7c77c5b28580e6fe2223257e2f3ef6d75	managed	runtime/config.py
cdaf78cb49b46bb67f76837feb2561da4d1de8883f2772cf5e7a4c8766bf8911	managed	runtime/executor.py
578be9a2659830ab7a06b5f9d26be9c4f30db8e9174f893c9de0ecd0bf58ca3d	managed	runtime/framework_patch.sh
ddb167798de9f50fae310d3aac6cf2008391badb7bcf6e27d1e8d85f53c718dd	managed	runtime/metrics.py
2b5cb6dfaad710362098290bdda7ac31f8409eb850e66c564d5a0d53b06a6f62	managed	runtime/resources.py
3297a0942ff553d44b4f1fa0472e8165a384bbc2aa2de67bc1e6707ef36d1207	managed	runtime/state.py
9ff2a84c680dc661a373616a5262fed384e4501b05c7c90a5f6ba4c5474a448a	managed	runtime/validate_round.py
a0cbf67afe3abaf1864f2dc7d7042a0f2de86bca356205eef489fc0a5590d69e	managed	scripts/README.md
d8f9979a6fd4841cf14ca9206df77f92d6741ce57aa8ceddb859b9ba9f0a30a4	managed	scripts/convert_weights.sh
ecea389c55ca9940c0b1a6192675a5c4425a1388e1063f1c5f6a7cdf250395ee	managed	scripts/detect_heads.sh
8235c82954cc03b08ac91b55ede4e8d795dbb2e99d80e6a68ea465686d8f89b1	managed	scripts/fetch_code.sh
83afb832e201ddb8c1209e731b614eb0577ef780366e4288d6ca005be2a2c1d2	managed	scripts/fetch_model.sh
1c588197f16e4680803e12770f7ba19b6fac91f70cc93e099e0431acecc28af3	managed	scripts/init_task_dir.sh
47de2e4f271425327baddd3aab8834b9339e67247ca2e9e8203460ec336f8fc9	managed	scripts/install_agents.sh
34fd645ad8e0cdaead1a59cc88f450a2af6dfa95d89988137bcddbfc724c209f	managed	scripts/install_env.sh
f74262350bafc641c76aeb0d60d4eba9235ac72389e232b2b3b1fef827fb50e1	managed	scripts/install_skills.sh
b065feb334caa737be70ded19c69da3af87cc2ad92c6b7c4fb417fb3bdb45e91	managed	scripts/preflight.sh
6a55af853b9037864e645133e4aba59cb16384f8de2f99ace5f4d337547fe991	managed	scripts/start_experiment.sh
c973bf0f55e1c231793b7cc82c603321a807ddbabd6a50939e96770b27a6e33c	managed	scripts/uninstall_agents.sh
61c7c221425c15c2a2c5032ce40e6c6fc7a7cf43e16c3652c3e158994771bc3f	managed	skills/autotune/SKILL.md
8281f35cde095df327cd5b873bc376bd5d7c73460fb4061de798f7d3c7a98daf	managed	skills/autotune/references/sweep-and-bottleneck.md
bd224f19a4e0237d670f40273902a7e8d2058bc3ee276d8dc470f444c5d0af51	managed	skills/bootstrap-eval-env/SKILL.md
b8ebfd5da46da6c1c862f8c7469b6e7d7c595f1681bf7494146c2018be3f895a	managed	skills/code-change/SKILL.md
5f2f9915903c60b993ae568d6fb5261e48124e8dac1fa850ac5872e2ab574cb2	managed	skills/code-change/references/framework-capability-triage.md
eacef63c0bd5c5f4d24dc8f8083f8a744c281086a89a924e6f721379c0885cc6	managed	skills/eval-lm-eval/SKILL.md
72489110772ec90fed41e4c228a71a85522a03545e492649bc78d73607a88720	managed	skills/eval-lm-eval/references/lm-eval-driver-contract.md
92954fa6b50577977016fd3e5946eca37eb6cdd6ce5233e3a6fc10554dad8e11	managed	skills/knowledge-curation/SKILL.md
a73a02ef26f314c21387995197b2e976c47cffe3b8e8b0a3902196b4503f3491	managed	skills/knowledge-curation/references/curation-checklist.md
2df56cccc4f99b3050a20d223bcc8b945100953148e53a81f5d9dbd174044de2	managed	skills/local-knowledge/SKILL.md
e19be66636bfa369650b008861d3630205eb93c8cde4f8590971b5f597ea6b25	managed	skills/local-knowledge/references/retrieval-playbook.md
4f0a618d668ff6c5f42077cadb998c80f607d727cc2198fae59b16586b6d1691	managed	skills/model-and-code-fetch/SKILL.md
c3c13285b63d56ea8033e96261ed5fcc1b0b34ec7b4821bc6796b83fdd9748fc	managed	skills/model-and-code-fetch/references/mirror-and-failure.md
370d5b896142ce37e4b58c230e6d1f155c1bb16e9981ee8bbba21076aaf72b46	managed	skills/report-and-conclusion/SKILL.md
530cbc276d8436ee7ea5cdee8002d2fcb22a1521c35d881b1c9228cbd1f759a2	managed	skills/report-and-conclusion/references/verdict-and-fields.md
4785aec9c944ae08ef2c309a741c30c55da5b0b605728efd2156f80423496db7	managed	skills/run-observation/SKILL.md
c867bca35b18e8341db86b56557e50b3b87f7f8a83e3cb25623bd6ca6b469063	managed	skills/run-observation/references/exit-codes-and-trace-reading.md
17128ae6281e09943089d3ab7043bb37b9c5cc2fdbcb5e58dc353f5c7182b95c	managed	skills/scheme-design/SKILL.md
665335c3ef72ea9f3e5943b544468224c8c8c9e55fee41a75bb0682adbf71195	managed	skills/scheme-design/references/scheme-playbook.md
cab9caa237c244cbf9ded81b8e69601e6687fdc595d79eefc27252c43c12a277	managed	skills/train-recipe/SKILL.md
0824a1527b220c05fbe4082672b18c20380e65cd9084c99e151f38b1de463695	managed	skills/train-recipe/references/three-stage-and-exit-codes.md
79f5d22d82f674abb932f5a29af98aa82321ce8b4ef85e302368b95e11fe02c7	managed	skills/weights-convert/SKILL.md
1b65987c6bf353adfb52286da2af5769f2ea5e1ec6bb013aaa246605f13c7cb2	managed	templates/changes.md
8bfa555af92c32d8d988c80b0c1c3a250df94fffa08aa4fae83b01e95d47acbe	managed	templates/commands/README.md
7ad35a0536090f4c983ae939cd3fd456866ec9540b16f6c2b9235baa9d212ef6	managed	templates/commands/_stage_args.sh
e3f6fadbac5aeb999988a87622dac9fb30fa7961ed95f4b37a129679404e7dbb	managed	templates/commands/_taskcfg.sh
8bd1414928f4d67c19a9181ed401e1710367438a8967e385d86e322cf03b96bd	managed	templates/commands/convert_cmd.sh
a042f0de64604dd3816f02cbf45eea43cdc550a828c905ac4562be36cbc5b602	managed	templates/commands/eval_cmd.sh
e7dbd70f102ab7c5240483009a185e5ec221076fccbd52a746c9ba4e90222da4	managed	templates/commands/eval_protocol_gate.sh
45a017b565a4a52b4bb4e02844195874b7881a486f25fca19bc1b6246438c43d	managed	templates/commands/gate.sh
c1f415b61aacb82897a91f091e1d19b6f45f8aa5c46de0cbebe1056f98db6878	managed	templates/commands/report.py
c6152492a93f134639c82ee23d8e3da89d38e829daa40765c4f50f1be8862434	managed	templates/commands/switch_consistency.py
f6e96b4b1067e0d4039c2328e3e283eda5d025fa9538d6b3c87cfc6da04eef43	managed	templates/commands/train_argv.txt
fe623028449c02ad10c4df6b2350c028fcd1b4398df9a639535d9e7d2318f1df	managed	templates/commands/train_cmd.sh
aad3fb3f6040540f404542af2dd54c5350dd1b7c0c8245e876d95c1636ba326f	managed	templates/commands/validate_design.sh
57f41485d9159e609d9355ac30de3e5b462fa9b6cfb84d9dc47df6a0014379e2	managed	templates/criterion.yaml
af4d21c66a191c28de3428904f1b495cc108cb4c19cd2b71cee81fd04046bf82	managed	templates/design.md
fab978bf040181ffc16d4b7b7738340ee1b0a4c6763be12452b31aef85cb9abb	managed	templates/drivers/lm_eval_driver.py
504aa08e80f7644b6a46dea937a94a85e97344593a6f098c128bbe91ff47effa	managed	templates/report.md
01949513e823aef521bca7f823cdeffd8c95a5d3b45e408c2da52ef995cd7cfa	managed	templates/run.env
fdfb0889c723df0612338a53d23897640cb2e66a0c6607e0a7eb21c92790e0ec	managed	templates/sets/README.md
d153eb6e2f74d46ed151596392b9de1a3a3875e3d24d6dc64025f67216652923	managed	templates/state-entry.json
a0cc4ea333085aa883c27e9e83c292d09f621984e4b04c2a6d4678d2de349040	managed	templates/task/convert.sh
142386dea21ed8fe86b13b6e28aa06f0d21f8b0da8e17b7466ac4c1457ad2b1f	managed	templates/task/eval.sh
646affaee1d190d4c96e2f6c778d7729b3c2d201927218e0c2c6f4394fe6ee85	managed	templates/task/train.sh
1b6d94683ea81cba5752d7d7ff575762708ea081f5c9764aa0ba179ea9473ba8	managed	templates/test.md
LP_MANIFEST_EOF
)
LP_EMBEDDED_SEED_DIRS=$(cat <<'LP_SEED_EOF'
config/tasks
requests
experiments
records/conclusions
records/best
knowledge/techniques
knowledge/frameworks
knowledge/frameworks/patches
LP_SEED_EOF
)

ACTION="install"
FORCE_MANAGED=0; FORCE_DOWNGRADE=0; NO_GIT=0; DRY=0
WITH_AGENTS=0; AGENTS_DIR_OPT=""
TARGET=""

# 头部的用法块：从第 3 行打到 `set -euo` 之前。**不写死行号** —— 否则头部一长就读不全。
usage() { awk 'NR>2 && /^set -euo pipefail/{exit} NR>2' "$0" | sed 's/^#\s\{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --install) ACTION="install" ;;
    --upgrade) ACTION="upgrade" ;;
    --status)  ACTION="status" ;;
    --uninstall) ACTION="uninstall" ;;
    --uninstall-agents) ACTION="uninstall-agents" ;;
    --with-agents) WITH_AGENTS=1 ;;
    --agents-dir) [ $# -ge 2 ] || { echo "install.sh：--agents-dir 后面缺目录" >&2; exit 2; }
                  AGENTS_DIR_OPT="$2"; WITH_AGENTS=1; shift ;;
    --force-managed)   FORCE_MANAGED=1 ;;
    --force-downgrade) FORCE_DOWNGRADE=1 ;;
    --no-git) NO_GIT=1 ;;
    --dry-run) DRY=1 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "install.sh：未知选项 $1" >&2; exit 2 ;;
    *) if [ -z "$TARGET" ]; then TARGET="$1"; else echo "install.sh：多余参数 $1" >&2; exit 2; fi ;;
  esac
  shift
done

die() { echo "install.sh：$*" >&2; exit 2; }
note() { echo "  $*"; }

[ -n "$TARGET" ] || { [ "$ACTION" = "uninstall-agents" ] && TARGET="(不涉及工程目录)" || { usage; exit 2; }; }
if [ "$ACTION" != "uninstall-agents" ]; then
  [ -d "$TARGET" ] || die "目标目录不存在：$TARGET（本安装器不替人建工程根，先 mkdir）"
  # 绝对化：本脚本不改自己的 cwd，但把相对路径规范化能避免「在不同目录调用 → 记录里写相对路径」这类隐患
  TARGET="$(cd "$TARGET" && pwd)"
fi

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECORD_REL=".lpta-install.tsv"

# 安装计划（sha256／class／dest，以及要建的空目录）由打包器**注入到本文件**，
# 不再单独出 MANIFEST.tsv／SEED_DIRS.txt：那是安装器的输入，不是给读者的账目。
# 兼容旧包：文件还在时照样读文件。
LP_PLAN_ROWS() {
  if [ -n "${LP_EMBEDDED_MANIFEST:-}" ]; then printf '%s\n' "$LP_EMBEDDED_MANIFEST"
  elif [ -f "$PKG_ROOT/MANIFEST.tsv" ]; then cat "$PKG_ROOT/MANIFEST.tsv"
  else return 1; fi
}
LP_SEED_ROWS() {
  if [ -n "${LP_EMBEDDED_SEED_DIRS:-}" ]; then printf '%s\n' "$LP_EMBEDDED_SEED_DIRS"
  elif [ -f "$PKG_ROOT/SEED_DIRS.txt" ]; then cat "$PKG_ROOT/SEED_DIRS.txt"
  else return 1; fi
}
LP_PLAN_ROWS >/dev/null 2>&1 || die "包里没有安装计划（deploy/install.sh 未被打包器注入，也没有 MANIFEST.tsv）—— 这不是一个完整的出厂包"
[ -f "$PKG_ROOT/VERSION" ] || die "找不到 $PKG_ROOT/VERSION"
PKG_VERSION="$(tr -d '[:space:]' < "$PKG_ROOT/VERSION")"

sha() { if [ -f "$1" ]; then sha256sum "$1" | cut -d' ' -f1; else echo "-"; fi; }
# 从记录里取某个路径上次装下去时的 sha
rec_sha() { [ -f "$TARGET/$RECORD_REL" ] || { echo "-"; return; }; awk -F'\t' -v p="$1" '$3==p{print $1}' "$TARGET/$RECORD_REL" | head -1; }
rec_has() { [ -f "$TARGET/$RECORD_REL" ] || return 1; awk -F'\t' -v p="$1" '$3==p{found=1} END{exit !found}' "$TARGET/$RECORD_REL"; }

# ── subagent 侧：四个角色导出成 DSH subagent。**只在被点名时才碰宿主**（纪律④）──────
# 注意它写的是**另一个盘**（`${DSH_HOME:-$HOME/.dsh}/agents`），不是目标工程目录。
AGENTS_SH="$PKG_ROOT/scripts/install_agents.sh"
UNINSTALL_AGENTS_SH="$PKG_ROOT/scripts/uninstall_agents.sh"
AGENTS_DIR=""
if [ "$WITH_AGENTS" = 1 ] || [ "$ACTION" = "uninstall-agents" ]; then
  AGENTS_DIR="${AGENTS_DIR_OPT:-${DSH_HOME:-$HOME/.dsh}/agents}"
  case "$AGENTS_DIR" in "~/"*) AGENTS_DIR="$HOME/${AGENTS_DIR#\~/}" ;; esac
  [ -f "$AGENTS_SH" ] || die "包里找不到 scripts/install_agents.sh —— 这不是一个完整的出厂包"
fi

# ── 动作：uninstall-agents（宿主级；**只删本工程装过且未改动**的四个角色）─────────────
# 交给 scripts/uninstall_agents.sh：它按 `$AGENTS_DIR/.lpta-install.json` 只删 sha256 未变的文件，
# 被改过就报错退出 2（那是别人手调过的 persona，不由我们抹掉）。
if [ "$ACTION" = "uninstall-agents" ]; then
  echo "install.sh：卸载 subagent"
  note "目标目录 : $AGENTS_DIR"
  [ -d "$AGENTS_DIR" ] || die "目录不存在：$AGENTS_DIR（不是本工程装过的地方 ⇒ 一个都不碰）"
  [ -f "$AGENTS_DIR/.lpta-install.json" ] || die "$AGENTS_DIR 里没有 .lpta-install.json（不是本工程装的）⇒ 一个都不碰"
  if [ "$DRY" = 1 ]; then
    bash "$UNINSTALL_AGENTS_SH" --target "$AGENTS_DIR" --dry-run || exit 2
  else
    bash "$UNINSTALL_AGENTS_SH" --target "$AGENTS_DIR" || exit 2
  fi
  exit 0
fi

# ── 读包清单 ────────────────────────────────────────────────────────────────
MANAGED=(); SEEDED=()
while IFS=$'\t' read -r s c r; do
  [ -n "${r:-}" ] || continue
  case "$c" in
    managed) MANAGED+=("$s|$r") ;;
    seeded)  SEEDED+=("$s|$r") ;;
    *) die "MANIFEST.tsv 里有未知 class：$c（本安装器只认 managed/seeded）" ;;
  esac
done < <(LP_PLAN_ROWS)

say_plan() { echo "  包版本   : $PKG_VERSION"; note "目标目录 : $TARGET"; note "managed  : ${#MANAGED[@]} 个文件"; note "seeded   : ${#SEEDED[@]} 个文件"; }

# ── 动作：status ────────────────────────────────────────────────────────────
if [ "$ACTION" = "status" ]; then
  echo "install.sh：状态（只读，未写任何文件）"
  TGT_VER="(未安装)"; [ -f "$TARGET/VERSION" ] && TGT_VER="$(tr -d '[:space:]' < "$TARGET/VERSION")"
  note "包版本   : $PKG_VERSION"
  note "目标版本 : $TGT_VER"
  n_missing=0; n_same=0; n_diff=0; n_new=0
  for e in "${MANAGED[@]}"; do
    s="${e%%|*}"; r="${e#*|}"
    if [ ! -f "$TARGET/$r" ]; then n_missing=$((n_missing+1)); printf '    %-10s %s\n' "缺失" "$r"
    elif [ "$(sha "$TARGET/$r")" = "$s" ]; then n_same=$((n_same+1))
    elif rec_has "$r" && [ "$(sha "$TARGET/$r")" = "$(rec_sha "$r")" ]; then n_diff=$((n_diff+1)); printf '    %-10s %s\n' "可升级" "$r"
    else n_new=$((n_new+1)); printf '    %-10s %s\n' "冲突(改过)" "$r"; fi
  done
  note "managed：一致 $n_same ｜ 可升级 $n_diff ｜ 缺失 $n_missing ｜ 冲突(被改过) $n_new"
  n_keep=0
  for e in "${SEEDED[@]}"; do s="${e%%|*}"; r="${e#*|}"; [ -f "$TARGET/$r" ] && n_keep=$((n_keep+1)); done
  note "seeded ：已存在 $n_keep ／ ${#SEEDED[@]}（永不覆盖）"
  exit 0
fi

# ── 动作：uninstall ─────────────────────────────────────────────────────────
if [ "$ACTION" = "uninstall" ]; then
  [ -f "$TARGET/$RECORD_REL" ] || die "$TARGET 里没有 $RECORD_REL —— 不是本安装器装的，拒绝卸载"
  echo "install.sh：卸载（只删 managed；seeded 一律保留）"
  changed=(); removed=0
  while IFS=$'\t' read -r s c r; do
    [ "$c" = "managed" ] || continue
    [ -f "$TARGET/$r" ] || continue
    if [ "$(sha "$TARGET/$r")" != "$s" ]; then changed+=("$r"); continue; fi
    [ "$DRY" = 1 ] || rm -f "$TARGET/$r"; removed=$((removed+1))
  done < "$TARGET/$RECORD_REL"
  if [ ${#changed[@]} -gt 0 ] && [ "$FORCE_MANAGED" != 1 ]; then
    echo "install.sh：❌ 这些 managed 文件**被改过**，不是我们装下去的样子；拒绝删（未删任何文件）：" >&2
    printf '    %s\n' "${changed[@]}" >&2
    echo "    处置：人工确认后重跑并加 --force-managed。" >&2
    exit 2
  fi
  if [ ${#changed[@]} -gt 0 ]; then for r in "${changed[@]}"; do [ "$DRY" = 1 ] || rm -f "$TARGET/$r"; removed=$((removed+1)); done; fi
  # 收空目录（由深到浅），只收**变空**的，不碰 seeded 目录
  if [ "$DRY" != 1 ]; then
    # 自检跑出来的派生物（不是我们装下去的文件，也不该留下）
    find "$TARGET" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
    find "$TARGET" -mindepth 1 -type d -empty -not -path "$TARGET/.git/*" -delete 2>/dev/null || true
    rm -f "$TARGET/$RECORD_REL"
  fi
  note "已删 $removed 个 managed 文件；seeded 文件与目录**全部保留**"
  note "★ 宿主里的四个 subagent（若装过）**本步没动** —— 要卸单跑：bash deploy/install.sh --uninstall-agents"
  exit 0
fi

# ★ 目标已有安装 ⇒ 按升级走（头部用法承诺的就是这个）。`$ACTION` 只影响打印哪行字和
#   要不要打指引指针；写盘计划、seeded 保留、降级检查都不看它 —— 所以这里不需要再记
#   "是不是人显式给的 --install"（为一个标签养一个标志位，是 0.18.37 收掉的东西）。
if [ "$ACTION" = "install" ] && [ -f "$TARGET/$RECORD_REL" ]; then
  ACTION="upgrade"
fi

# ── 动作：install / upgrade —— 先算全量计划，再决定写不写 ──────────────────
if [ -f "$TARGET/VERSION" ] && [ "$FORCE_DOWNGRADE" != 1 ]; then
  TGT_VER="$(tr -d '[:space:]' < "$TARGET/VERSION")"
  if [ "$TGT_VER" != "$PKG_VERSION" ]; then
    newest="$(printf '%s\n%s\n' "$TGT_VER" "$PKG_VERSION" | sort -V | tail -1)"
    [ "$newest" = "$PKG_VERSION" ] || die "拒绝降级：目标已是 $TGT_VER，包是 $PKG_VERSION（要降级加 --force-downgrade）"
  fi
fi

echo "install.sh：$([ "$ACTION" = "install" ] && echo 安装 || echo 升级)"
if [ "$ACTION" = "upgrade" ]; then
  note "升级指引：deploy/UPGRADE.md（会拦住升级的 5 件事 ＋ 任务目录要手工同步的文件）"
fi
say_plan

PLAN=()      # "write|rel" / "keep|rel"
CONFLICT=()
for e in "${MANAGED[@]}"; do
  s="${e%%|*}"; r="${e#*|}"
  if [ ! -f "$TARGET/$r" ]; then PLAN+=("write|$r"); continue; fi
  if [ "$(sha "$TARGET/$r")" = "$s" ]; then PLAN+=("same|$r"); continue; fi
  if rec_has "$r" && [ "$(sha "$TARGET/$r")" = "$(rec_sha "$r")" ]; then PLAN+=("write|$r"); continue; fi
  # 冲突：**照样进计划**（给了 --force-managed 才走得到这里），
  # 否则「报了冲突却没计划写」⇒ --force-managed 变成空操作，下面写记录时还会把漂移洗白。
  PLAN+=("write|$r")
  CONFLICT+=("$r")
done
STALE_SEEDED=()   # seeded 已存在、但内容与**本包**里的不同 ⇒ 升级不覆盖（设计如此），但要喊一声
for e in "${SEEDED[@]}"; do
  r="${e#*|}"
  if [ -f "$TARGET/$r" ]; then
    PLAN+=("keep|$r")
    # 出厂版的那份在解包目录里；比对不上就说明"你这份比新包里旧（或你改过）"
    if [ -f "$PKG_ROOT/$r" ] && [ "$(sha "$TARGET/$r")" != "$(sha "$PKG_ROOT/$r")" ]; then
      STALE_SEEDED+=("$r")
    fi
  else
    PLAN+=("write|$r")
  fi
done

if [ ${#CONFLICT[@]} -gt 0 ] && [ "$FORCE_MANAGED" != 1 ]; then
  echo "install.sh：❌ 有 ${#CONFLICT[@]} 个 managed 文件在目标里**被改过**（内容 ≠ 上次装下去的样子）；" >&2
  echo "           按①「冲突先报后停」，**一个字节都没写**：" >&2
  printf '    %s\n' "${CONFLICT[@]}" >&2
  echo "    处置二选一：" >&2
  echo "      · 你的改动要保留 ⇒ 先自己备份/合并，再重跑（仍会报冲突，直到文件回到我们装下去的样子）" >&2
  echo "      · 你的改动不要了   ⇒ 重跑并加 --force-managed（覆盖前自动存 <文件>.bak）" >&2
  exit 2
fi

# ── subagent 侧**预检**：必须在写任何文件之前（纪律①「先报后停」）──────────────────
# 静默预检一次：subagent 侧若过不了（frontmatter 不合规会被注册表整份丢弃／目标里已有同名角色
# 却非本工程所装／被本地改过），就在**本工程一个字节都没写**的状态下停住，让使用者单独处置。
if [ "$WITH_AGENTS" = 1 ] && [ "$DRY" != 1 ]; then
  if ! ag_pre="$(bash "$AGENTS_SH" --target "$AGENTS_DIR" --dry-run 2>&1)"; then
    { echo "install.sh：❌ subagent 侧预检不过 ⇒ 按①「冲突先报后停」，**本工程一个字节都没写**："
      printf '%s\n' "$ag_pre" | sed 's/^/    /'
      echo "    处置：先单独跑下面这条看细节、按它的提示处理，再回来装；"
      echo "          或在 「--agents-dir <另一个目录>」 另指一个干净目录。"
      echo "      bash '$AGENTS_SH' --target '$AGENTS_DIR'"; } >&2
    exit 2
  fi
fi

if [ "$DRY" = 1 ]; then
  echo "install.sh：[dry-run] 不写盘。计划："
  for p in "${PLAN[@]}"; do printf '    %-6s %s\n' "${p%%|*}" "${p#*|}"; done
  [ ${#CONFLICT[@]} -gt 0 ] && note "此外 ${#CONFLICT[@]} 个冲突（因给了 --force-managed 会被覆盖并存 .bak）"
  if [ "$WITH_AGENTS" = 1 ]; then
    echo "install.sh：[dry-run] subagent 侧（--agents-dir $AGENTS_DIR）："
    bash "$AGENTS_SH" --target "$AGENTS_DIR" --dry-run || exit 2
  else
    note "subagent 侧：未点名 ⇒ 本次不碰 ${DSH_HOME:-$HOME/.dsh}/agents（要装见 --with-agents）"
  fi
  exit 0
fi

# ── 落盘 ────────────────────────────────────────────────────────────────────
n_w=0; n_s=0; n_k=0
for p in "${PLAN[@]}"; do
  kind="${p%%|*}"; r="${p#*|}"
  case "$kind" in
    same) n_s=$((n_s+1)) ;;
    keep) n_k=$((n_k+1)) ;;
    write)
      mkdir -p "$TARGET/$(dirname "$r")"
      if [ -f "$TARGET/$r" ] && [ "$FORCE_MANAGED" = 1 ]; then cp -p "$TARGET/$r" "$TARGET/$r.bak"; fi
      cp -p "$PKG_ROOT/$r" "$TARGET/$r"
      n_w=$((n_w+1)) ;;
  esac
done

# 空内容目录（seeded 的容器）：只在缺失时建
if LP_SEED_ROWS >/dev/null 2>&1; then
  while IFS= read -r d; do [ -n "$d" ] || continue; mkdir -p "$TARGET/$d"; done < <(LP_SEED_ROWS)
fi

# 安装记录（无时间戳 ⇒ 幂等）
# ★ managed 记**包里那一份的 sha**（＝我们装下去的样子），不记磁盘现值 ——
#   否则「我没覆盖它，却把它的现值记成基线」会把漂移洗白，下次就当成没被动过。
{ for e in "${MANAGED[@]}"; do s="${e%%|*}"; r="${e#*|}"; printf '%s\tmanaged\t%s\n' "$s" "$r"; done
  for e in "${SEEDED[@]}";  do s="${e%%|*}"; r="${e#*|}"; printf '%s\tseeded\t%s\n'  "$(sha "$TARGET/$r")" "$r"; done
} > "$TARGET/$RECORD_REL"

# 让 AGENTS.md 从**任意子目录**都能被找到：目标根没有 git 就 init 一个（不提交）
if [ "$NO_GIT" != 1 ] && [ ! -d "$TARGET/.git" ]; then
  if command -v git >/dev/null 2>&1; then
    git -C "$TARGET" init -q && note "已 git init（让 AGENTS.md 从子目录也能被找到；**没有**替你做任何提交）"
  else
    note "⚠ 目标目录没有 .git 且找不到 git 命令 —— 请从工程根启动，或自行 git init"
  fi
fi

# ── subagent 侧**落盘**（给了 --with-agents／--agents-dir 才走得到这里）──────────────
AG_LINE="未装（默认；见下）"
if [ "$WITH_AGENTS" = 1 ]; then
  if ag_out="$(bash "$AGENTS_SH" --target "$AGENTS_DIR" 2>&1)"; then
    AG_LINE="已装 4 个角色 ⇒ $AGENTS_DIR"
    printf '%s\n' "$ag_out" | sed 's/^/  /'
  else
    { echo "install.sh：❌ 工程已装好，但 subagent 侧写入失败 ⇒ 退出 2。"
      printf '%s\n' "$ag_out" | sed 's/^/    /'
      echo "    工程文件本身是完整的（它们已经写好了）。单跑这条重试："
      echo "      bash scripts/install_agents.sh --target '$AGENTS_DIR'   # 在 $TARGET 下"; } >&2
    exit 2
  fi
fi

echo "install.sh：✅ 完成"
note "写入/覆盖 $n_w ｜ 已一致 $n_s ｜ seeded 保留 $n_k"
note "安装记录 : $TARGET/$RECORD_REL（${#MANAGED[@]}+${#SEEDED[@]} 行，无时间戳）"
if [ ${#STALE_SEEDED[@]} -gt 0 ]; then
  note "⚠ 有 ${#STALE_SEEDED[@]} 个 seeded 文件**保留了你这边的版本**、但内容与出厂版不同（永不覆盖，设计如此）："
  for r in "${STALE_SEEDED[@]}"; do
    note "    $r"
    note "      出厂版：$PKG_ROOT/$r ｜ 你的：$TARGET/$r"
  done
  note "    要对比：diff -u \"$TARGET/<文件>\" \"$PKG_ROOT/<文件>\"；要采用出厂版就手动覆盖（升级绝不替你决定）"
fi
note "subagent : $AG_LINE"
if [ "$WITH_AGENTS" != 1 ]; then
  echo "  ── 四个角色这次**没有**装成 DSH subagent（默认）。两种用法二选一，别选错："
  echo "     A 一个主 Agent 依次扮四个角色（自己读 agents/<角色>/AGENT.md ＋按 AGENTS.md §5 挂 skill）"
  echo "       ⇒ **不用装**，工程文件齐了就够。"
  echo "     B 要真的 \`use_agent architect\` 派子代理"
  echo "       ⇒ 重跑并加 --with-agents，然后**重启 dsh**（工具名册是装载时静态构建的）。"
  echo "     跳过它却按 B 用 ⇒ \`use_agent architect\` 报 unknown agent，而 agents/*/AGENT.md 明明都在。"
fi
note "下一步   : ① 填 $TARGET/config/project.yaml ② bash deploy/verify_install.sh $TARGET"
