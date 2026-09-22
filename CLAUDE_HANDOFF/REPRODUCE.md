# 定位文件、跨电脑接手和按需复现

以下所有相对路径都从仓库根目录解释。现成 PPT、HTML、CSV/JSON 已提交，不需要安装绘图库或重建 PPT 才能开始阅读。

## 先确认 Git 来源

```bash
pwd
git status --short --branch
git worktree list
git fetch origin
git log -5 --oneline origin/main
git log -1 --oneline origin/main -- CLAUDE_HANDOFF
```

本次发布前 main 为 `7e789f52da331274b8b636536098edfd07334e32`，实验分支为 `712602c9fb1b6d8414b9e5cc34256a3978d6f275`，前者是后者祖先。发布后应从 main 的新交接提交接手，旧分支 `codex/two-material-phonons` 不是最新基线。详细发布验证见 [INTEGRATION](INTEGRATION.md)。

已有干净 main checkout 可以 `git pull --ff-only`。如果当前 worktree 有工作或属于其他任务，保留它，另建独立 worktree/工作分支从 `origin/main` 开始；先检查拟用分支和路径是否存在，不 reset、强制 checkout 或覆盖已有分支。不要自动复制 ignored 背景材料、scratch 或缓存。

## 当前机器信息是提示，不是可移植契约

原主目录为 `/Users/kaede/research/Waterloo Holger thermoelectric materials`；实验 worktree 为 `/Users/kaede/.codex/worktrees/phonon-research-sandbox`。另两处历史 worktree 在 `3392` 与 `7994` 下；均未被这两轮编辑。跨电脑不应硬编码这些路径。

已用的本机科学 Python 为 `/Users/kaede/scientific-tools/envs/thermo-bt2/bin/python`，含 PyYAML、numpy 2.4.6、matplotlib 3.11.0。系统 Python 可跑标准库工具测试，但没有 PyYAML；当时打包文档用的 Python 也没有 matplotlib。先检查现有依赖，按需要选择环境，不重装一套无关软件。

## 核心文件与用途

| 目的 | 入口 |
|---|---|
| 状态与原始证据链接 | [CURRENT_STATE](../experiments/phonon_research_sandbox/CURRENT_STATE.md) |
| 两轮时间线/失败尝试 | [追加 WORKLOG](../experiments/phonon_research_sandbox/WORKLOG.md) |
| 物理流程学习 | [QE→κL 文件导读](../experiments/phonon_research_sandbox/LEARNING_GUIDE.md)、[项目教程](../WORKFLOW_EXPLAINED.md) |
| 科学方案/来源 | [plans](../experiments/phonon_research_sandbox/README.md)、[原始论文与官方文档](../experiments/phonon_research_sandbox/references/targeted_sources.md) |
| 旧的真实代码修复 | [tooling 说明](../experiments/phonon_research_sandbox/tooling/README.md)及共享 `qe_output.py`、v2 scripts |
| 执行凭据/精确几何/Rb 清单 | [第二轮入口](../experiments/phonon_research_sandbox/round2/README.md) |
| 可打开的图表和汇报 | [sandbox README](../experiments/phonon_research_sandbox/README.md)、[PPT 说明](../experiments/phonon_research_sandbox/presentation/README.md) |

## 不改文件的工件核对

```bash
python3 - <<'PY'
from pathlib import Path
import hashlib, json
root = Path.cwd()
inventory = json.loads((root / 'CLAUDE_HANDOFF/ARTIFACT_MANIFEST.json').read_text())
bad = []
for entry in inventory['artifacts']:
    path = root / entry['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        bad.append(entry['path'])
print('checked', len(inventory['artifacts']), 'artifacts; mismatches:', bad)
raise SystemExit(bool(bad))
PY
```

这只检查打包时列出的核心工件是否变动，不是科学验收。如果后续有合法修改，先解释差异，更新清单/交接；不要为了匹配哈希回滚别人的工作。

## 按需的局部软件检查

以下命令不会执行真实 QE/FC/κL。只有修改到相应部分或有明确疑点才运行；交接文件本身不要求重跑全部历史套件。

```bash
# stdlib-only，11 个 SYNTHETIC 过程记录测试
python3 -m unittest discover -s experiments/phonon_research_sandbox/tooling/execution_receipts/tests -v
# 9 个几何/输入约定测试
python3 -m unittest discover -s experiments/phonon_research_sandbox/tooling/q_commensurability -p 'test_*.py' -v
# 2 个文件存在性/单位失败模式测试
python3 -m unittest discover -s experiments/phonon_research_sandbox/analysis/rb_reuse -p 'test_*.py' -v
```

共享 parser 被修改时：

```bash
PYTHONPATH=thermo_candidates/scripts/phono3py_campaign python3 -m unittest -v \
  thermo_candidates.scripts.phono3py_campaign.tests.test_qe_output \
  thermo_candidates.scripts.phono3py_campaign.tests.test_srcu_legacy_gate
```

v2 被修改时，用含 PyYAML 的 Python：

```bash
PYTHONPATH=thermo_candidates/scripts/phono3py_campaign python3 -m unittest discover \
  -s thermo_candidates/SrCu2SnS4/phono3py_v2/tests -p test_v2.py
```

历史通过数字：435 shared / 13 focused / 18 v2；第二轮 11+9+2。它们是保存的验证记录，不保证另一台电脑的任意版本或下一次修改仍会通过。原型测试使用临时合成夹具；真实历史输出也用于 parser 回归检查。两者都不是新物理计算或材料验收。

## 派生分析再生成（会写派生工件）

只在独立干净工作分支按需运行；生成后查看 diff，保留未修改的原始证据。

| 命令（仓库根目录） | 依赖及写入范围 |
|---|---|
| `python3 experiments/phonon_research_sandbox/analysis/build_dashboard_data.py` | 标准库；更新 sandbox/results、300 K SVG、HTML 嵌入数据 |
| `python3 experiments/phonon_research_sandbox/analysis/rb_reuse/build_inventory.py` | 标准库；更新同目录 JSON/CSV |
| `python3 experiments/phonon_research_sandbox/analysis/rb_component_diagnostics/build_diagnostics.py` | matplotlib/numpy；更新 48 行表、摘要和 PNG/SVG |
| `python3 experiments/phonon_research_sandbox/round2/duplicate_sources/analyze_sources.py` | PyYAML；更新来源分组 JSON，无力读取或拟合 |
| `python3 experiments/phonon_research_sandbox/tooling/q_commensurability/generate_examples.py` | 标准库；更新数学例子 JSON，相位 SVG 是已保存示意 |

PPT 数据提取脚本是 `experiments/phonon_research_sandbox/presentation/reproducibility/extract_deck_data.py`；构建器为同目录 `build_deck.mjs`。后者依赖桌面 presentation skill 的 artifact runtime 和环境变量 `RESEARCH_ROOT`、`PRESENTATIONS_SKILL`、`RUNTIME_PYTHON`、`RUNTIME_NODE_MODULES`，不是普通 Node 独立包。若另一台机器没有该 runtime，可直接使用现成 PPTX；不要声称已经重新渲染。改 PPT 后应逐页渲染核验，保持正文和嵌入备注全英文，双语讲稿单独保存。

## 保存与交接

追加相应 WORKLOG，更新简洁 HANDOFF，分阶段 commit/push 工作分支。未来 main 合并按当时用户授权处理；本次交接的 main 授权不是永久合并授权。不改历史发送文件，不把测试输出当真实计算，不因为某个旧 Slurm ID 出现在日志里就启动监控或恢复。
