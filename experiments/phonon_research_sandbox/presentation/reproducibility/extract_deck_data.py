"""Extract only saved, already-derived results for editable presentation charts."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / 'experiments/phonon_research_sandbox/presentation/reproducibility/deck_data.json'
files = {}
def source(relative):
    p = ROOT / relative
    files[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
    return p

mats = ['SrCu2SnS4', 'SrZrS3', 'Rb2Cu2SnS4']
electronic = {}
for mat in mats:
    rel = f'thermo_candidates/{mat}/results/transport_best_power_factor.csv'
    rows = list(csv.DictReader(source(rel).open()))
    electronic[mat] = {carrier: [float(next(r for r in rows if float(r['temperature_K']) == t and r['carrier_type'] == carrier)['power_factor_over_tau_W_m-1_K-2_s-1']) for t in [300,900]] for carrier in ['n','p']}
rb_path = 'thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json'
rb = json.loads(source(rb_path).read_text())
sr_path = 'thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json'
sr = json.loads(source(sr_path).read_text())
source('thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json')
source('thermo_candidates/SrCu2SnS4/results/dos_qe_vs_boltztrap2.png')
last = rb['qmesh_ladder'][-1]
prev = rb['qmesh_ladder'][-2]
changes = []
for i,t in enumerate(last['temperature_K']):
    a=prev['conventional_kappa_W_mK'][i][:3]
    b=last['conventional_kappa_W_mK'][i][:3]
    changes.append({'temperature_K':t,'average_percent':abs(sum(b)-sum(a))/sum(b)*100,'maximum_diagonal_percent':max(abs(y-x)/y*100 for x,y in zip(a,b))})
result = {'change_denominator':'current (denser) mesh value, matching archived convergence gate', 'scope':'Derived from repository CSV and saved remote-audit JSON. No new physical calculations or remote HDF5 revalidation.', 'electronic_PF_over_tau_W_m_minus1_K_minus2_s_minus1':electronic, 'rb_ladder':rb['qmesh_ladder'],'rb_last_changes':changes,'sr_audit':sr,'source_sha256':files}
OUT.write_text(json.dumps(result,indent=2)+'\n')
print(OUT.relative_to(ROOT))
print(json.dumps(changes))
