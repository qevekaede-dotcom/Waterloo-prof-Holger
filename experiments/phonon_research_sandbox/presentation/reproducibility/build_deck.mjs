import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation, PresentationFile} from '@oai/artifact-tool';
const ROOT=process.env.RESEARCH_ROOT;
const SKILL=process.env.PRESENTATIONS_SKILL;
if(!ROOT || !SKILL) throw Error('Set RESEARCH_ROOT and PRESENTATIONS_SKILL absolute paths');
const DIR=path.join(ROOT,'experiments/phonon_research_sandbox/presentation');
const BUILD=path.join(DIR,'.build');
const data=JSON.parse(await fs.readFile(path.join(DIR,'reproducibility/deck_data.json'),'utf8'));
const {applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')));
const pres=Presentation.create({slideSize:{width:1280,height:720}});
const C={ink:'#18333C',muted:'#596B71',green:'#007F7B',amber:'#B46936',red:'#AD4438',blue:'#4D6CAF',paper:'#F7F8F5',white:'#FFFFFF'};
const font='Arial';
const notes=[];
function text(sl,t,x,y,w,h,size=28,color=C.ink,bold=false){const sh=sl.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});sh.text=t;sh.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return sh;}
function slide(title,subtitle=''){const s=pres.slides.add();s.background.fill=C.paper;text(s,title,62,42,1156,76,44,C.ink,true);if(subtitle)text(s,subtitle,64,122,1140,56,23,C.muted);text(s,String(pres.slides.items.length).padStart(2,'0'),1160,675,58,24,17,C.muted);return s;}
function note(s,title,en,zh,sources){s.speakerNotes.textFrame.setText(en+'\n\nSources:\n'+sources.join('\n'));notes.push({title,en,zh,sources});}
// Presentation charts use 10 significant digits for Excel portability; raw data remain untouched.
function chart(s,type,cfg){cfg.series=cfg.series.map(a=>({...a,values:a.values.map(v=>Number(v.toPrecision(10)))}));let ch=s.charts.add(type,{chartFill:C.paper,chartLine:{fill:'none',width:0},plotAreaFill:C.paper,plotAreaLine:{fill:'none',width:0},...cfg});applyPresentationChartFont(ch,{fontFamily:font});return ch;}
function table(s,values,widths,top=202,height=340,size=25){const t=s.tables.add({rows:values.length,columns:values[0].length,left:64,top,width:1150,height,columnWidths:widths,values});t.borders.assign({fill:'#DBE1DD',width:1,style:'solid'});for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const a=t.getCell(r,c);a.fill=r===0?C.ink:(r%2?C.white:C.paper);a.text.style={typeface:font,fontSize:size,color:r===0?C.white:C.ink,bold:r===0};}return t;}
const mat=['SrCu2SnS4','SrZrS3','Rb2Cu2SnS4'];
const electronicSources=mat.map(m=>`thermo_candidates/${m}/results/transport_best_power_factor.csv`);
const rbSource='thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json';
const srSource='thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json';
const v2Source='thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json';
{
 const s=pres.slides.add();s.background.fill=C.ink;
 text(s,'Thermoelectric sulfides',72,100,1100,100,62,C.white,true);
 text(s,'Electronic screening and phonon research progress',76,225,1060,70,34,'#D3E6DF');
 text(s,'SrCu2SnS4   /   SrZrS3   /   Rb2Cu2SnS4',76,355,1100,62,32,C.white);
 text(s,'Research update for Holger and Roy',76,559,1080,50,26,'#D3E6DF');
 text(s,'Repository evidence reviewed 21 September 2026',76,615,1070,40,21,'#B7CDC6');
 note(s,'Thermoelectric sulfides','I have completed the three electronic first passes and tested the phonon workflow. The present milestone is a traceable research record and a focused plan for the remaining scientific questions. None of the three materials currently has an accepted lattice thermal conductivity under our current criteria. This update uses saved repository evidence, not a current cluster check.','我已完成三种材料的电子输运 first pass，并开展了声子流程。当前成果是可追溯的科研记录和针对剩余科学问题的计划。按照目前标准，三种材料都还没有验收后的晶格热导率。本汇报基于仓库保存证据，不是实时超算检查。',['experiments/phonon_research_sandbox/CURRENT_STATE.md']);
}
{
 const s=slide('Electronic workflow completed','Material-specific convergence tests, relaxation, SCF/NSCF and BoltzTraP2');
 s.images.add({blob:new Uint8Array(await fs.readFile(path.join(ROOT,'thermo_candidates/SrCu2SnS4/results/dos_qe_vs_boltztrap2.png'))),contentType:'image/png',alt:'Existing SrCu2SnS4 QE and BoltzTraP2 density of states comparison',fit:'contain',position:{left:60,top:205,width:750,height:395}});
 text(s,'An existing validation example',856,224,350,60,30,C.green,true);
 text(s,'SrCu2SnS4\nQE and interpolated DOS',856,316,340,96,26);
 text(s,'Transport-property convergence\non denser k meshes remains open.',856,467,340,120,25,C.muted);
 note(s,'Electronic workflow completed','Each material used its own convergence workflow before the electronic transport first pass. This existing SrCu2SnS4 plot compares the Quantum ESPRESSO density of states with the BoltzTraP2 interpolation. It supports a workflow comparison but does not by itself establish convergence of every transport property. The calculations use PBE without explicit spin–orbit coupling.','每种材料都独立进行了收敛工作后再进入电子输运初算。此图是已有的 SrCu2SnS4 QE 态密度与 BoltzTraP2 插值比较，它支持流程比较，但不能单独证明所有输运性质都已收敛。电子计算采用 PBE，未加入显式自旋轨道耦合。',['thermo_candidates/SrCu2SnS4/results/dos_qe_vs_boltztrap2.png',...mat.map(m=>`thermo_candidates/${m}/results/workflow_summary.md`)]);
}
{
 const s=slide('Electronic screening at 300 K','Best PF/τ on the sampled carrier-density grid');
 chart(s,'bar',{position:{left:68,top:204,width:755,height:402},categories:mat,series:['n','p'].map((car,i)=>({name:car+'-type',values:mat.map(m=>data.electronic_PF_over_tau_W_m_minus1_K_minus2_s_minus1[m][car][0]/1e11),fill:i?C.green:C.blue,valuesFormatCode:'0.00',dataLabelOverrides:mat.map((m,j)=>({idx:j,textStyle:{typeface:font,fontSize:21},text:(data.electronic_PF_over_tau_W_m_minus1_K_minus2_s_minus1[m][car][0]/1e11).toFixed(2)}))})),barOptions:{direction:'column',grouping:'clustered',gapWidth:100},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:23}},xAxis:{textStyle:{fontSize:23},majorGridlines:null},yAxis:{title:{text:'PF/τ (10¹¹ W m⁻¹ K⁻² s⁻¹)',textStyle:{fontSize:22}},min:0,numberFormatCode:'0.0',textStyle:{fontSize:21},majorGridlines:{fill:'#DFE4E1',width:1}},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:20},}});
 text(s,'Rb2Cu2SnS4',864,242,345,55,30,C.green,true);
 text(s,'The p-type first pass is a useful\nfollow-up candidate.',864,314,335,106,28);
 text(s,'PF/τ is not absolute PF.\nElectronic-only zT is not full zT.',864,487,330,100,25,C.muted);
 note(s,'Electronic screening at 300 K','The bars are the best power-factor-over-relaxation-time values selected independently for each carrier sign on the sampled 300 K grid. Rb2Cu2SnS4 has the largest p-type value among these first passes. This does not establish the best final thermoelectric material, because relaxation time and accepted lattice thermal conductivity remain missing. SrZrS3 carrier preference depends on the metric and temperature, so I do not assign one universal doping preference.','柱状图对应 300 K 采样载流子浓度网格中，两种载流子分别选出的最佳 PF/τ。Rb2Cu2SnS4 的 p 型数值在这三种初算里最大，但弛豫时间和验收晶格热导率仍然缺失，不能据此判断最终热电性能。SrZrS3 的载流子偏好取决于指标和温度，不能简单给它贴上统一标签。',electronicSources);
}
{
 const s=slide('Phonon evidence and acceptance','Execution, file integrity and scientific convergence are separate checks');
 table(s,[['Material','Forces and FCs','Current limitation'],['SrCu2SnS4','Historical dataset\nv2 preparation only','Units, mixed settings,\nterminal health and mesh'],['SrZrS3','788 force records\nFC2 / FC3 generated','Sampled imaginary modes\nκL rejected'],['Rb2Cu2SnS4','Recovery recorded\nLimited FC audit passed','Every tested mesh step fails\nκL unaccepted']],[243,385,522],200,355,25);
 text(s,'No accepted lattice thermal conductivity for any of the three materials',67,598,1138,54,29,C.red,true);
 note(s,'Phonon evidence and acceptance','The table separates artifact creation from scientific acceptance. SrCu2SnS4 preserves a historical campaign with known problems, while its corrected workflow remains preparation only. SrZrS3 produced force constants but failed a sampled-frequency gate. Rb2Cu2SnS4 has a saved artifact audit with limited integrity checks, but all tested mesh transitions fail the convergence rule. For the latter two, this update reads the saved audit records rather than revalidating the remote HDF5 files.','这个表格把生成文件和科学验收分开。SrCu2SnS4 保留有问题的历史计算，修正流程仍只是准备。SrZrS3 已生成力常数，但没有通过采样频率检查。Rb2Cu2SnS4 的保存审计通过了有限完整性检查，却没有通过任何一次网格转换的收敛检查。这次读取的是已保存审计，并没有重新核验远端 HDF5。',[srSource,rbSource,v2Source,'fourth step result (phono3py lattice thermal conductivity)/README.md']);
}
{
 const s=slide('SrCu2SnS4: a separate corrected campaign','Correct units and consistent inputs are necessary preparation');
 text(s,'Historical cutoff',68,211,480,48,28,C.muted);
 text(s,'4 bohr = 2.1167 Å',68,278,1130,74,51,C.red,true);
 text(s,'Intended v2 cutoff',68,393,490,48,28,C.muted);
 text(s,'4 Å ≈ 7.5589 bohr',68,460,1130,74,51,C.green,true);
 text(s,'Historical forces mix settings and include unhealthy terminal outputs.\nThe corrected v2 workflow has not produced a new validated dataset.',70,573,1130,80,26);
 note(s,'SrCu2SnS4: a separate corrected campaign','The historical Quantum ESPRESSO interface interpreted the pair cutoff in bohr. The value four therefore meant about 2.12 angstrom, and the included pair groups were onsite only. The new preparation explicitly converts four angstrom to about 7.5589 bohr and requests uniform force settings. These software corrections do not demonstrate a converged force dataset. The old raw outputs and sent attachments remain unchanged.','历史 QE 接口的成对位移截断单位是 bohr，因此数值 4 实际只有约 2.12 埃，包含的 pair groups 仅限 onsite。新的准备流程显式换算 4 埃为约 7.5589 bohr，并要求统一力计算设置。修正代码不能证明力数据已收敛。旧输出和已发送附件全部保留。',[v2Source,'thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml','fourth step result (phono3py lattice thermal conductivity)/README.md']);
}
{
 const s=slide('SrCu2SnS4 v2: minimal proposed pilot','Plan only. A corrected input contract still needs computational evidence.');
 text(s,'01',67,211,90,60,42,C.green,true);text(s,'Healthy pristine reference',175,210,995,56,33,C.ink,true);text(s,'Independent SCF, residual forces, exact input and pseudopotential binding',177,275,1000,64,25,C.muted);
 text(s,'02',67,358,90,60,42,C.green,true);text(s,'Small displaced-force controls',175,357,995,56,33,C.ink,true);text(s,'Repeated single and pair displacements, then amplitude and force-setting checks',177,422,1000,64,25,C.muted);
 text(s,'03',67,505,90,60,42,C.green,true);text(s,'Conditional expansion',175,504,995,56,33,C.ink,true);text(s,'Only after signal, health and mapping checks: cutoff, supercell and q-mesh studies',177,569,1000,64,25,C.muted);
 note(s,'SrCu2SnS4 v2: minimal proposed pilot','I propose beginning with a healthy independent pristine calculation and a small set of repeated single and pair displacement controls. The detailed plan defines how to distinguish numerical noise from incremental force signal and when to stop. Amplitude and force-setting sensitivity should inform any larger production campaign. The exact displacement count and cost require real generation and measured timing. No new campaign has been submitted.','建议先做健康的独立 pristine SCF，再选少量单、双位移做重复对照。详细计划规定了如何区分数值噪声和增量力信号，以及何时停止。位移幅度和力设置敏感性应决定是否扩展。实际位移数量与费用需要真实生成和计时，目前没有提交新计算。',[v2Source,'experiments/phonon_research_sandbox/plans/']);
}
{
 const s=slide('SrZrS3: imaginary-mode origin is unresolved','The finite diagnostic κL cannot be used for zT');
 text(s,'−1.0716 THz',67,211,560,90,62,C.red,true);
 text(s,'Minimum sampled frequency\nq = (0, 0.4, 0)',70,321,555,100,28);
 text(s,'Pristine maximum force\n9.342 × 10⁻⁵ Ry/bohr\nPreferred gate: 5 × 10⁻⁵',70,470,555,132,26,C.muted);
 text(s,'Small discriminating controls',696,218,500,54,31,C.green,true);
 text(s,'Residual forces and SCF sensitivity\n\nHarmonic range and supercell size\n\nMode character and structural response',698,314,500,252,29);
 text(s,'No direct claim of real-material instability',695,592,500,45,23,C.red);
 note(s,'SrZrS3: imaginary-mode origin is unresolved','The saved first-pass audit reports a minimum frequency of minus 1.0716 terahertz at the stated q point. Twelve sampled modes are below minus 0.1 terahertz. The pristine residual force exceeded the preferred threshold, and a historical exception allowed a diagnostic continuation. Residual forces, force convergence and finite-range effects deserve targeted controls before a physical instability interpretation. Eigenvectors and structural response would help distinguish competing explanations. Simply removing imaginary modes would not validate thermal conductivity.','保存审计给出的最低频率为 −1.0716 THz，12 个采样模式低于 −0.1 THz。pristine 残余力高于首选门槛，当时以例外继续了诊断计算。在解释成物理不稳定前，应通过最小对照区分残余力、力收敛和有限作用范围等因素，并结合本征矢及结构响应。不能靠直接删除虚频来得到有效热导率。',[srSource,'experiments/phonon_research_sandbox/plans/']);
}
{
 const s=slide('Rb2Cu2SnS4: direction-dependent mesh response','300 K, saved first-pass diagnostic tensors');
 chart(s,'line',{position:{left:66,top:203,width:834,height:405},categories:data.rb_ladder.map(r=>String(r.length_angstrom)),series:['xx','yy','zz'].map((label,i)=>({name:label,values:data.rb_ladder.map(r=>r.conventional_kappa_W_mK[0][i]),line:{fill:[C.green,C.blue,C.amber][i],width:3},marker:{symbol:'circle',size:7}})),hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:23}},xAxis:{title:{text:'q-mesh density length (Å)',textStyle:{fontSize:23}},textStyle:{fontSize:22}},yAxis:{min:0.06,max:0.17,title:{text:'κL (W m⁻¹ K⁻¹)',textStyle:{fontSize:23}},numberFormatCode:'0.00',textStyle:{fontSize:22},majorGridlines:{fill:'#DDE2DE',width:1}}});
 text(s,'zz changes most',949,228,266,80,31,C.amber,true);
 text(s,'A smoother average can\nhide a poorly converged\ndirection.',949,348,266,170,27);
 text(s,'No extrapolated value',949,564,270,60,23,C.muted);
 note(s,'Rb2Cu2SnS4: direction-dependent mesh response','This figure replots the conventional Cartesian tensor components recorded in the September 20 audit. The horizontal axis is the phono3py q-mesh density length, not a real-space cutoff or a supercell size. The zz component changes substantially across the ladder, while yy is comparatively less sensitive. All values are rejected first-pass diagnostics. I have neither fitted an asymptote nor estimated a supposedly converged thermal conductivity.','图中重新绘制了 9 月 20 日保存审计里的常规笛卡尔张量分量。横轴是 phono3py 的 q 网格密度长度参数，不是实空间截断或超胞尺寸。zz 随网格变化明显，yy 相对较不敏感。图中所有点都只是未验收的初算诊断，没有外推收敛值。',[rbSource]);
}
{
 const s=slide('Rb2Cu2SnS4: the final step still fails','90 to 105 Å. Relative change uses the denser-mesh value as denominator.');
 chart(s,'bar',{position:{left:70,top:205,width:800,height:400},categories:data.rb_last_changes.map(r=>r.temperature_K+' K'),series:[{name:'trace / 3 change',values:data.rb_last_changes.map(r=>r.average_percent),fill:C.green,valuesFormatCode:'0.00',dataLabelOverrides:data.rb_last_changes.map((r,j)=>({idx:j,textStyle:{typeface:font,fontSize:21},text:r.average_percent.toFixed(2)}))},{name:'Largest diagonal change',values:data.rb_last_changes.map(r=>r.maximum_diagonal_percent),fill:C.amber,valuesFormatCode:'0.00',dataLabelOverrides:data.rb_last_changes.map((r,j)=>({idx:j,textStyle:{typeface:font,fontSize:21},text:r.maximum_diagonal_percent.toFixed(2)}))}],barOptions:{direction:'column',grouping:'clustered',gapWidth:100},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:22}},xAxis:{textStyle:{fontSize:23}},yAxis:{min:0,max:12,title:{text:'Absolute relative change (%)',textStyle:{fontSize:22}},textStyle:{fontSize:22},majorGridlines:{fill:'#DDE2DE',width:1}},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:21}},});
 text(s,'Current acceptance rule',919,233,296,76,30,C.ink,true);
 text(s,'Average < 3%\nEach diagonal < 5%\nAt every temperature',921,342,290,158,27);
 text(s,'Two consecutive\npassing transitions',921,554,290,70,25,C.muted);
 note(s,'Rb2Cu2SnS4: the final step still fails','I recalculated these changes using the same denominator as the implemented gate: the denser mesh result. At 300 kelvin, the average changes by about 4.266 percent and the largest diagonal by about 10.192 percent. Both fail. The same conclusion holds at 600 and 900 kelvin, and no earlier transition passes. A denser mesh could reuse the force constants only for the same underlying force model with retained provenance. It would still not establish supercell, cutoff or amplitude convergence.','变化率采用与现有代码一致的分母，即更密一级网格值。在 300 K，平均值变化约 4.266%，最大对角分量约 10.192%，两项都失败；600 和 900 K 也一样。更密网格只能在保留来源、保持相同力模型的前提下复用力常数，它不能解决超胞、截断和幅度收敛。',[rbSource,'thermo_candidates/Rb2Cu2SnS4/phono3py/run_postprocess_firstpass.py']);
}
{
 const s=slide('Proposed next research choices','Each route starts with a bounded question and a stopping decision');
 table(s,[['Material','Smallest useful next question','Expansion depends on'],['SrCu2SnS4','Can a clean v2 pilot resolve\nforce signal consistently?','Healthy pristine, reproducible\nforces and uniform settings'],['SrZrS3','Does the soft mode persist\nunder numerical controls?','Mode diagnosis and\nindependent harmonic evidence'],['Rb2Cu2SnS4','Which force-model uncertainty\nshould be checked first?','Reuse audit, focused sensitivity\nand measured mesh cost']],[240,455,455],201,356,25);
 text(s,'Cost estimates need measured timings and generated displacement counts.',70,597,1135,56,28,C.muted);
 note(s,'Proposed next research choices','These are alternatives for discussion, not a decision made on behalf of Roy. For SrCu2SnS4, the benefit is a clean corrected baseline. For SrZrS3, the key benefit is understanding a failure mechanism. For Rb2Cu2SnS4, existing force data may support a bounded convergence study, but provenance and force-model limitations must remain explicit. I will estimate resource use from actual task counts and measured timing before asking to expand any route.','这些是讨论选项，并没有替 Roy 做决定。SrCu2SnS4 的收益是建立干净的修正基线；SrZrS3 的收益是理解失败机理；Rb2Cu2SnS4 的现有力数据可能支持小范围收敛研究，但必须明确来源和力模型局限。扩展前应依据真实任务数量与计时估算资源。',['experiments/phonon_research_sandbox/plans/','experiments/phonon_research_sandbox/CURRENT_STATE.md']);
}
{
 const s=slide('Discussion with Roy','I would appreciate guidance on the next scientific priority.');
 text(s,'A corrected baseline',69,223,1110,62,37,C.green,true);
 text(s,'Prioritize a new SrCu2SnS4 v2 pilot',71,297,1100,52,29);
 text(s,'An instability diagnosis',69,390,1110,62,37,C.blue,true);
 text(s,'Investigate SrZrS3 before further thermal transport',71,464,1100,52,29);
 text(s,'A convergence study',69,557,1110,62,37,C.amber,true);
 text(s,'Continue Rb2Cu2SnS4 with a bounded, evidence-based scope',71,625,1100,48,28);
 note(s,'Discussion with Roy','I have sent the revised status update and am awaiting guidance on the next priority. I would appreciate guidance on whether to prioritize the corrected SrCu2SnS4 baseline, diagnose SrZrS3, or continue a bounded Rb2Cu2SnS4 convergence study. The accompanying plans and local evidence dashboard make these options reviewable. No new cluster calculation or email was initiated during this preparation round.','我已发送修订后的阶段汇报，目前还在等待下一步方向。希望 Roy 指导优先开展 SrCu2SnS4 修正基线、SrZrS3 虚频诊断，还是有明确边界的 Rb2Cu2SnS4 收敛研究。配套计划和本地证据面板便于审阅。本轮准备没有发起新的超算计算或邮件。',['experiments/phonon_research_sandbox/CURRENT_STATE.md']);
}
await fs.mkdir(BUILD,{recursive:true});
await (await PresentationFile.exportPptx(pres)).save(path.join(BUILD,'candidate.pptx'));
await fs.writeFile(path.join(BUILD,'presentation.json'),JSON.stringify(pres.toProto()));
const english=notes.map((n,i)=>`## ${i+1}. ${n.title}\n\n${n.en}\n\nSources: ${n.sources.map(s=>'`'+s+'`').join(', ')}`).join('\n\n');
const bilingual=notes.map((n,i)=>`## ${i+1}. ${n.title}\n\n**EN**\n${n.en}\n\n**中文**\n${n.zh}\n\nSources: ${n.sources.map(s=>'`'+s+'`').join(', ')}`).join('\n\n');
await fs.writeFile(path.join(DIR,'SPEAKER_SCRIPT_EN_ZH.md'),'# Research update: bilingual speaker script\n\nAll slide content and embedded speaker notes are English. Chinese appears only in this companion file.\n\n'+bilingual+'\n');
await fs.writeFile(path.join(DIR,'reproducibility/slide_content.md'),'# English slide notes and sources\n\n'+english+'\n');
for(let i=0;!process.env.SKIP_PREVIEWS && i<pres.slides.items.length;i++){
 const s=pres.slides.items[i];
 const png=await pres.export({slide:s,format:'png',scale:1});await fs.writeFile(path.join(BUILD,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
}
const finalName=process.env.FINAL_NAME||'Waterloo_Phonon_Research_Update.pptx';
const result=await finalizePresentation({workspaceDir:DIR,candidatePath:path.join(BUILD,'candidate.pptx'),finalPath:path.join(DIR,'output',finalName),pythonExecutable:process.env.RUNTIME_PYTHON,integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit','--require-native-table-slide','4','--require-native-table-slide','10'],requiredNativeChartOwnerSlides:[3,8,9],requiredNativeTableOwnerSlides:[4,10],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:path.join(BUILD,finalName+'.validation.json')});
console.log(JSON.stringify(result));
