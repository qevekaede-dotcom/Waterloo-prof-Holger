# 下一次可直接开始的任务

状态标签：**已完成**见 STATE_AND_HISTORY；下列 A/B 项是可开展的本地研究建议，**未开展**。C 项依赖新输入或单独执行范围。不要把用户询问“还能做什么”写成 Roy 已选方向或所有建议都已授权执行。

## A0 — 安全接手与最小核验

先按 [REPRODUCE](REPRODUCE.md) 检查分支、工作区和包内工件哈希。打开面板、三份计划和对应一份原始审计 JSON。只在新改动、具体疑点或环境差异下运行对应测试；不要重启旧作业、重做已经保存的图表或循环复查所有代码。

接手成功条件：能说清每种材料完成到哪一步、下一项实验区分什么解释、需要哪些现成/缺失证据。接下来若用户要求继续本地研究、没有给其他方向，建议从 A1 开始。

## A1 — 首选：SrZrS₃ 晶型身份和公开数据对照

**要回答：** 仓库的初始 CIF、电子 relaxed 结构、声子参考胞，以及 NIMS/论文所用结构是否可对照？α/β 归属能否被原子连接方式支持？不能只凭 Pnma 标签判断。

**起点文件：** `thermo_candidates/SrZrS3/structures/`、`results/workflow_summary.md`、`phono3py/evidence/first_pass_unconverged/`，以及 `phono3py/evidence/3p5541348625A_count_only/relax/final/unitcell.in`。先读该材料 CLAUDE.md；根据审计 provenance 选实际参考结构，不凭文件名推断“最新”。

**步骤与交付：**

1. 提取各结构的来源、晶格、原子数、体积、组成和原子坐标约定；核对 primitive/conventional 与轴置换。保留来源哈希。
2. 用有依据的配位邻接分析区分 ZrS₆ 连接方式；展示距离阈值敏感性，不能任意选阈值使结构符合预想。画来源明确的结构/连接示意，不生成装饰性的假原子结构。
3. 与下面原始论文及公开同 ID 数据核对，形成一张“可比较／不可直接比较／尚缺信息”的表；明确 VASP/QE、泛函、赝势、弛豫条件和 NAC 等差异。
4. 交付一份短报告和 1–2 张结构图；结论可以是“证据仍不足”。如果晶型或基底不匹配，先修对照定义，再讨论虚频来源。不要把外部稳定声子当成推翻本项目结果的直接证据。

**已找到、尚未深入研究的来源：**

- [First–Principles Investigation of the Structural, Elastic, Electronic, and Optical Properties of α– and β–SrZrS₃](https://doi.org/10.3390/ma13040978)；[公开全文索引](https://pmc.ncbi.nlm.nih.gov/articles/PMC7079647/)。初步检索看到两种结构均为 Pnma、连接方式不同；本项目实际晶型尚未判定。
- [NIMS：SrZrS₃ / Pnma / mp-558760](https://mdr.nims.go.jp/datasets/847c52e8-791c-4534-a273-d0890e06145b)。页面列出声子图、`phonopy_params.yaml.xz` 和 VASP 设置；这些外部原件尚未下载到本仓库或做结构比对。解析结构/元数据是轻量任务；不要因此在本机启动 FC 拟合或大规模声子/热导求解。
- [β-SrZrS₃: A superior intermediate temperature thermoelectric through complex band geometry and ultralow lattice thermal conductivity](https://doi.org/10.1103/PhysRevMaterials.7.085403)。已确认论文存在及摘要范围，未完成方法、补充材料和晶型对应核验；不能把其数值当成本项目目标答案。

以上来源初步访问于 2026-09-22。记录获取日期/许可，付费或不可访问的细节标记未读，不补造。

## A2 — 现有电子输运的公平比较

**要回答：** 材料/载流子偏好是否依赖温度、浓度、方向和评价指标？已有 best-PF 表是否掩盖不同采样点的比较差异？

从三材料 `results/workflow_summary.md`、`transport_best_power_factor.csv` 和它们指向的保存 BoltzTraP2 结果开始。先厘清列单位、浓度符号/绝对值、温度、方向和 trace 定义。

- 使用共同已有采样温度和浓度进行比较；缺少共同点时明确标注，不把插值冒充原始采样。
- 分开画 PF/τ、Seebeck、σ/τ、κe/τ 与 zTₑ；不同指标的“最好点”分别说明。已有完整张量时再分析方向性。
- 用保存 DOS/能带支持机制假设，避免只看曲线形状就断言有效质量、谷简并或散射机制。
- 交付 2–4 张简洁图、可追溯表和一页结论；不引入未经验证的 τ、scissor correction、SOC 或 κL，不计算伪最终 zT。

这是已有数据再分析，不是重新跑 QE/BoltzTraP2，也不能替代 dense-k 收敛实验。

## B — 为 A1/A2 服务的精简文献矩阵

按材料收集直接相关的原始研究/实验/官方数据；不为凑数量堆摘要。每条记录：晶型/结构标识、实验还是计算、方法、温度/浓度、是否 SOC/NAC、力常数和 q 网格收敛说明、τ 来源、关键局限、原文位置。

交付重点是“哪些证据可比较、哪里存在研究空白、哪些差异必须做控制实验才能解释”，不是把文献中的低 κL 复制为本项目结果。方法没报告的字段写“未报告”；全文未读写“仅摘要”。完成后由独立审查者核对关键结论，再把确有新增认识的图/内容加入**全英文** PPT，讲稿可中英对照。

## C — 尚未释放的条件任务

| 条件任务 | 所需新条件 | 准备材料已在哪里 |
|---|---|---|
| Rb 11 个名义净零位移任务的现成数据噪声检查 | 单独明确一次有界远端读取范围；核对完整输入等价性、健康和原子顺序，再提取力；不先重算 | [重复来源候选](../experiments/phonon_research_sandbox/round2/duplicate_sources/README.md) |
| SrCu 真实可信运行器集成 | 实际 v2 manifest/QE/pseudo/MPI/调度执行合同；先本地 disposable fixtures，独立审查后才讨论真实运行 | [凭据原型及局限](../experiments/phonon_research_sandbox/tooling/execution_receipts/README.md)、[SrCu 计划](../experiments/phonon_research_sandbox/plans/SrCu2SnS4.md) |
| SrZr 现有 FC2 模态重放 | 明确计算位置与执行范围、拿到可核验 FC2/结构；核对 q 基底与本征矢映射 | [SrZr 计划](../experiments/phonon_research_sandbox/plans/SrZrS3.md)、[几何工具](../experiments/phonon_research_sandbox/tooling/q_commensurability/README.md) |
| 更密 Rb q 网格或新力数据 | Roy/用户的方向、同一力模型来源、真实任务数与计时预算、执行授权 | [Rb 计划](../experiments/phonon_research_sandbox/plans/Rb2Cu2SnS4.md) |
| 英文模拟组会 | 用户实际参与作答 | [PPT 讲稿](../experiments/phonon_research_sandbox/presentation/SPEAKER_SCRIPT_EN_ZH.md)、[问答](../experiments/phonon_research_sandbox/round2/REPORT_QA_EN_ZH.md) |

若必须真实新计算才能回答，保存明确方案和停止条件后继续其他独立任务。没有计时依据时不编造核心小时；不要把任务数直接换成预算。
