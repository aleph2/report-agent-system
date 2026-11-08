"""Offline, scripted Coordinator and owner for the hash-pinned synthetic Writer verification case."""
from . import legacy_state as legacy
import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

from .catalog import Catalog
from .commission_plan import save_plan, request_checkpoint, reply
from .commission_planning import _owner_rank_binding
from .commission_requirements import install_requirements, read_requirements, propose_requirements
from .content_store import ContentStore
from .hierarchical_tools import actor_for
from .method_pack import register_reviewed_method_pack
from .source_materials import issue, block_material
from .store import Store
from .workspace import Workspace

# The scripted approval applies only to these exact fictional inputs.
INPUT_SHA256 = {
    "00_scope.md": "04deb3abc4784b49d47c6d7bf41aa7f34d3a0141d7d79a35f2e1dca5d3633d83",
    "01_initial.pdf": "a36128335a49345fde678591e409e0731898f3a37e52c9f478f02bbfbfb0b7da",
    "02_revision.pdf": "54f9d3e543eb1e271f6af17df1f2a5ee03a1f5586a9376fcb7931c0dace366aa",
    "03_requirements.pdf": "971eac1d289175272f6566e62486e859616eae21f726821dd96c38593d86324a",
    "04_design.pdf": "8b7587d9c31c6ecc0c8af6558aece8f317c698b69be37b4e0bba5a8e6a826a1c",
    "05_survey.pdf": "a7b8b8f79ba7f19eca64bb2f0051278a595945a4d93ec3d936ebca4754dbacd0",
    "06_drawing.pdf": "01d13ae492e6ef96b7c75ea0f969e247045e90ee4cfe94e12307a2b7cfae9852",
    "07_region.pdf": "cedb480a6c3df5bd82adff6b0cba6df349e6f4e02577863a7e8a475f1351e890",
    "08_template.docx": "97e15102a603fa36daa387f6715796706db2ffdc651d8dad523122fa0c2728f6"
}
METHOD_SOURCE_NAME = 'system-method-high-slope.txt'
METHOD_CATALOG_SHA256 = 'a986b71512ca846cc5fc8e2edf030a9fcc83db472d6b7df1ae368d417db00931'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _method_material():
    raw = files('report_agent').joinpath('methods/high_slope_guideline.json').read_bytes()
    if _sha(raw) != METHOD_CATALOG_SHA256:
        raise ValueError('MINI_REVIEWED_METHOD_CHANGED')
    method = json.loads(raw)
    text = ['模拟委托引用的方法摘录：' + method['metadata']['name']]
    for rule in method['indicators']:
        text.append(f"{rule['id']} {rule['label']}：{rule['notes']}")
        text.extend(g['description'] + f" [{g['min_value']}–{g['max_value']}]" for g in rule['grades'])
    for table in method['weight_tables']:
        text.append('表 ' + table['id'] + '：' + json.dumps(table['rows'], ensure_ascii=False))
    text.append('总体风险分级：' + json.dumps(method['risk_bands'], ensure_ascii=False))
    return method, '\n'.join(text)


def prepare_mini_commission(inputs, destination):
    """Stage verified originals; submit and approve exactly one scripted fake plan for A and B."""
    inputs, destination = Path(inputs).absolute(), Path(destination).absolute()
    if (not inputs.is_dir() or destination.exists() or destination.is_relative_to(inputs)
            or any(p.is_symlink() for base in (inputs, destination) for p in (base,*base.parents))):
        raise ValueError('MINI_FRESH_INDEPENDENT_PATHS_REQUIRED')
    if {p.name for p in inputs.iterdir()} != set(INPUT_SHA256):
        raise ValueError('MINI_UNEXPECTED_OR_MISSING_INPUT')
    sources = {}
    for name, expected in INPUT_SHA256.items():
        p = inputs/name
        if p.is_symlink() or not p.is_file():
            raise ValueError('MINI_REGULAR_INPUT_REQUIRED')
        sources[name] = p.read_bytes()
        if _sha(sources[name]) != expected:
            raise ValueError('MINI_FIXTURE_DIGEST_MISMATCH: ' + name)
    method, method_text = _method_material()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent, prefix='.mini-preparation-') as tmp:
        case = Path(tmp)/'case'
        store = Store(case)
        method_hash = _sha(method_text.encode())
        store.initialize({'goal':'按模拟委托范围对青禾路堑工程进行资料核对及评估。',
            'sources':[{'id':'system-method','title':METHOD_SOURCE_NAME,'filename':METHOD_SOURCE_NAME,
                        'content':method_text,'sha256':method_hash,'coverage':'complete'}],
            'content_contract':'hierarchical-review-v1','coverage_contract':'object-coverage-v1',
            'commission_checkpoint_required':True,'assembly_contract':'system-assembler-v1'})
        ws, cs, co = Workspace(store), ContentStore(store), actor_for('coordinator')
        ws.initialize()
        catalog = Catalog(store)
        ids = {name:catalog.import_file(name, data)['source']['id'] for name,data in sources.items()}
        ids[METHOD_SOURCE_NAME] = 'system-method'
        captured = cs.import_inputs(co,'mini-capture',list(ids.values()))['result']['source_refs']
        refs = {name:ref for name,ref in zip(ids,captured,strict=True)}
        legacy.set_commission_source_roles(store, {n:{'id':sid,'purpose':'commission' if n=='00_scope.md'
                  else 'template' if n=='08_template.docx' else 'source_or_applicable_standard'} for n,sid in ids.items()})
        plan, requirements_ref = _plan(ws, cs, co, ids, refs, catalog, method)
        plan_ref = save_plan(cs,co,'mini-scripted-plan',plan)['result']['plan_ref']
        checkpoint = request_checkpoint(ws)
        reply(ws,checkpoint['issue_id'],{'plan_ref':plan_ref,'requirements_ref':requirements_ref,'approved':True,
              'corrections':'','reductions':[{'object_id':'C','reason':'中心桩号 K0+620 超出委托界线 K0+500。'}]})
        decision_ref = legacy.get_commission_confirmation(store)
        if destination.exists():
            raise FileExistsError(destination)
        case.rename(destination)
    return {'version':'mini-commission-writer-preparation-v1','case_path':str(destination),'plan_ref':plan_ref,
            'decision_ref':decision_ref,'requirements_ref':requirements_ref,'object_ids':['A','B'],
            'assessment_section_id':'3','fixture_sha256':dict(INPUT_SHA256),'method_catalog_sha256':METHOD_CATALOG_SHA256,
            'method_source_name':METHOD_SOURCE_NAME,'method_source_sha256':method_hash,
            'coordinator':'scripted_fixture','owner':'scripted_fixture','assessment_outcomes_supplied':0}


def _plan(ws, cs, co, ids, refs, catalog, method):
    rows = {name:catalog.read(sid,0,50) for name,sid in ids.items()}
    def cite(name, quote):
        matches = [b for b in rows[name]['blocks'] if quote and quote in b['text']]
        if len(matches) != 1:
            raise ValueError(f'MINI_QUOTE_NOT_UNIQUE: {name} {quote}')
        return {'source_ref':refs[name],'locator':matches[0]['locator'],'quote':quote}
    scope, initial, revision, checks, design, survey, drawing, region, template = INPUT_SHA256
    commissioned = install_requirements(cs,refs[scope],refs[template])
    anchors = read_requirements(cs,commissioned)['payload']['anchors']
    if any(a.get('parse_error') for a in anchors):
        raise ValueError('MINI_SCOPE_OR_TEMPLATE_UNRESOLVED')
    conventions = [{'source':a['source'],'requirement_anchor_id':a['id'],'interpretation':a['source']['quote']}
                   for a in anchors if a['kind']=='convention']
    sections = {a['section_id']:a['source'] for a in anchors if a['kind']=='section'}
    fixed = next(a['source'] for a in anchors if a['kind']=='instruction' and a.get('section_id')=='1')
    if set(sections) != {'1','2','3','4'}:
        raise ValueError('MINI_OUTLINE_CHANGED')
    items=[]
    for a in anchors:
        k=a['kind']
        if k=='section':
            caps=['fixed_text' if a['section_id']=='1' else 'section']
        elif k=='scope':
            caps=['scope_boundary' if a['scope_section']=='4' else 'inventory']
        elif k=='convention':
            quote=a['source']['quote']
            caps=['source_priority'] if '设计与地勘' in quote else ['deliverables'] if '交付' in quote else ['assumptions'] if '无法确定' in quote else ['method_pack']
        else:
            caps=['fixed_text'] if a.get('section_id')=='1' else []
        items.append({'anchor_id':a['id'],'status':'required','interpretation':a['source']['quote'],'capabilities':caps})
    req=propose_requirements(cs,co,'mini-scripted-requirements',commissioned,items)['result']['requirements_ref']
    header = '模拟委托引用的方法摘录：' + method['metadata']['name']
    pack={'method_id':'mini-commission-reviewed-high-slope','version':1,'sources':[cite(METHOD_SOURCE_NAME,header)],
          'indicators':[{k:r[k] for k in ('id','label','category','notes','grades')} for r in method['indicators']],
          'risk_bands':[{k:v for k,v in b.items() if k!='label'} for b in method['risk_bands']],
          'weight_tables':[{'id':t['id'],'source':cite(METHOD_SOURCE_NAME,'表 '+t['id']+'：'),
                            'rows':t['rows']} for t in method['weight_tables']]}
    register_reviewed_method_pack(ws.store,pack,'Synthetic Writer verification; unaltered definitions and numerical rules from the pinned reviewed repository transcription.')
    weight=cite(scope,'按表 A.3-1（n=11）计算权重')
    conventions.append({'source':weight,'interpretation':'采用委托指定的 n=11 权重行。'})
    boundary=cite(scope,'界外对象列入排除清单并随计划提交业主确认。')
    bounds=cite(scope,'评估范围为 K0+000 至 K0+500。界外对象列入排除清单并随计划提交业主确认。')
    plan_sections=[
        {'section_id':'1','title':'概述','kind':'fixed','outline':sections['1'],'sources':[fixed],'text':fixed['quote']},
        {'section_id':'2','title':'资料与范围','kind':'extracted','outline':sections['2'],'sources':[bounds]},
        {'section_id':'3','title':'边坡评估','kind':'extracted','outline':sections['3'],'sources':[
            cite(initial,'坡段 A：坡高 18 米'),cite(initial,'坡段 B：坡高 25 米'),cite(revision,'更正通知'),
            cite(checks,'审核要点'),cite(design,'施工图设计说明'),cite(survey,'工程地质调查记录'),
            {'source_ref':refs[drawing],'locator':'page 1','quote':''},cite(region,'区域气象与灾害资料')]},
        {'section_id':'4','title':'待核事项','kind':'extracted','outline':sections['4'],'sources':[cite(checks,'资料不足时保留待核事项')]}]
    objects=[]
    for oid,station in [('A','K0+120'),('B','K0+380'),('C','K0+620')]:
        point=cite(design,station)
        locs=[point];attrs=[{'name':'中心桩号','values':[{'value':station,'source':point,'reason':'设计资料标示的位置。'}]}]
        geometry=next((line for block in rows[initial]['blocks'] for line in block['text'].splitlines()
                       if line.startswith('坡段 '+oid+'：坡高')),None)
        for field,value in zip(('坡高（m）','坡长（m）'),re.findall(r'(\d+) 米',geometry) if geometry else (None,None),strict=True):
            loc=cite(initial,geometry) if geometry else None
            attrs.append({'name':field,'values':[{'value':value,'source':loc,'reason':'初始资料所列。' if value else '所给资料未列数值。'}]})
            if loc and loc not in locs: locs.append(loc)
        date = cite(revision,'施工开始日期由 2026-03-01 改为 2026-04-15') if oid != 'C' else None
        attrs.append({'name':'施工开始日期','values':[{'value':'2026-04-15' if date else None, 'source':date,
                     'reason':'采用更正通知，初始日期 2026-03-01 已被替代。' if date else '界外对象，未纳入评估。'}]})
        attrs.append({'name':'坡率','values':[
            {'value':'1:0.75','source':cite(design,'设计坡率为 1:0.75'),'reason':'按设计优先约定采用。'},
            {'value':'1:1.0','source':cite(survey,'实测坡率为 1:1.0'),'reason':'地勘值，仅记录差异。'}]
            if oid=='A' else [{'value':None,'source':None,'reason':'所给文字资料未确认坡率。'}]})
        attrs.append({'name':'地下水调查记录','values':[{'value':None,
              'source':cite(initial,'未提供地下水调查记录') if oid=='B' else None,
              'reason':'未提供调查记录，地下水存在情况待核。' if oid=='B' else '所给资料未确认。'}]})
        if oid=='B':
            locs.append({'source_ref':refs[drawing],'locator':'page 1','quote':''})
        if oid in ('A','B'):
            locs += [cite(revision,'施工开始日期由 2026-03-01 改为 2026-04-15'),cite(region,'年均降雨量为 720 mm')]
            if oid=='A': locs.append(cite(survey,'实测坡率为 1:1.0'))
        objects.append({'object_id':oid,'label':'坡段 '+oid,'included':oid!='C','origin':'interpretation','attributes':attrs,
                        'reason':'中心桩号在委托范围内。' if oid!='C' else '范围外，提交业主确认排除。','sources':locs})
    # The real public read and its located blocks are available for the ordinary exclusion check.
    page = rows[design]
    issue(ws,co,'read_source_page',json.dumps(page,ensure_ascii=False),block_material(page))
    return {'requirements_ref':req,'sections':plan_sections,'inventory_attributes':['中心桩号','坡高（m）','坡长（m）','施工开始日期','坡率','地下水调查记录'],
            'objects':objects,'conventions':conventions,'deliverables':['Word','Excel'],
            'reconciliations':[{'sources':[cite(design,'设计坡率为 1:0.75'),cite(survey,'实测坡率为 1:1.0')],
                'result':'坡段 A 按设计坡率 1:0.75 记录。','differences':['地勘实测为 1:1.0，差异保留。']},
                {'sources':[cite(initial,'施工开始日期：2026-03-01'),cite(revision,'改为 2026-04-15')],
                 'result':'开工日期依更正通知采用 2026-04-15。','differences':['初始版本日期被更正。']}],
            'open_questions':[],'scope_boundary':{'start_meter':'0','end_meter':'500','source':bounds,'customer_basis':boundary},
            'method_pack':pack,'method_conventions':[{'key':'weights','source':weight,'interpretation':'采用 11 指标对应行。',
                'status':'specified','method_id':pack['method_id'],'strategy_id':'A.3-1'}],
            'indicator_rank_order':_owner_rank_binding(conventions,pack['indicators'])}, req
