"""Read-only pinned repository syntax/import inventory; never import drivers.

This does not certify every optional module's runtime. Ambiguous imports stay
unresolved, rather than being called missing local files or harmless packages.
"""
import argparse
import ast
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from scripts.oracle_gold.history import digest

ROOT = Path(__file__).resolve().parents[2]


def inspect(root, receipt):
    mismatch=[]
    for f in receipt["source_files"]:
        path=root/f["path"]
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=f["sha256"]:
            mismatch.append(f["path"])
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    if actual!=receipt['source_commit']:
        mismatch.append('GIT_HEAD')
    paths=subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines()
    modules=[]
    local_names={p.split('/')[0] for p in paths}
    local_names|={Path(p).stem for p in paths if p.endswith('.py')}
    for name in paths:
        if not name.endswith('.py'):
            continue
        raw=(root/name).read_bytes()
        rec={'path':name,'sha256':hashlib.sha256(raw).hexdigest(),'imports':[]}
        try:
            compile(raw,name,'exec')
            tree=ast.parse(raw,filename=name)
            rec['syntax']='COMPILED_WITHOUT_EXECUTION'
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):
                    refs=[v.name for v in node.names]
                elif isinstance(node,ast.ImportFrom):
                    refs=['.'*node.level+(node.module or '')]
                else:
                    continue
                for ref in refs:
                    top=ref.split('.')[0]
                    kind='RELATIVE_LOCAL_REFERENCE' if ref.startswith('.') else 'STDLIB' if top in sys.stdlib_module_names else 'LOCAL_REFERENCE' if top in local_names else 'EXTERNAL_OR_UNRESOLVED_REFERENCE'
                    rec['imports'].append({'module':ref,'line':node.lineno,'classification':kind})
        except (SyntaxError,UnicodeError) as exc:
            rec['syntax']='SYNTAX_UNSUPPORTED_OR_INVALID_FOR_RECORDED_RUNTIME'
            rec['error_type']=type(exc).__name__
            rec['line']=getattr(exc,'lineno',None)
        modules.append(rec)
    licences=[{'path':p,'sha256':hashlib.sha256((root/p).read_bytes()).hexdigest()} for p in paths if Path(p).name.lower().startswith(('license','licence','copying'))]
    return {'source_url':receipt['source_url'],'source_commit':actual,'frozen_receipt_files_checked':len(receipt['source_files']),
            'integrity_mismatches':mismatch,'modules':modules,'licence_files':licences,
            'runtime_import_success_not_implied':True}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--sources',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path)
    a=p.parse_args()
    receipts=json.loads((ROOT/'reports/gold_oracle/source_access_receipts.json').read_text())
    records=[]
    for r in receipts:
        key=hashlib.sha256(r['source_url'].encode()).hexdigest()[:16]
        root=a.sources/key/'repo'
        if root.exists():
            records.append(inspect(root,r))
    report={'schema':'oracle.gold.phase04.dependency_inventory.v1','python':platform.python_version(),
            'repositories':records,'source_drivers_executed':False,
            'limits':'Syntax/import inventory is not full strategy/native execution verification. Optional modules and external references require their selected runtime.'}
    report['sha256']=digest(report)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print('PINNED_REPOSITORIES',len(records),'PYTHON_FILES',sum(len(r['modules']) for r in records),
          'INTEGRITY_MISMATCHES',sum(len(r['integrity_mismatches']) for r in records))


if __name__=='__main__':
    main()
