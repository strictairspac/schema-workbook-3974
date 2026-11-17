"""HTTP 端到端：登录 → 样本增改移除 → 核验 → 冲突 → 更正 → 采纳 → 规则约束写入。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import src.config.database as dbconf
from src.config.database import Base
from src.models.entities import User
from src.utils.security import password_hash

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv('SEED_DEMO','false')
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Maker=sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(dbconf,'engine',engine)
    monkeypatch.setattr(dbconf,'Session',Maker)
    Base.metadata.create_all(engine)
    with Maker() as db:
        for role in ('admin','operator','viewer'):
            db.add(User(email=f'{role}@nanlu.test',password=password_hash('Demo2026!'),role=role))
        db.commit()
    import src.main as main_mod
    with TestClient(main_mod.app) as c:
        yield c,Maker

def token(client,role='operator'):
    r=client.post('/auth/login',json={'email':f'{role}@nanlu.test','password':'Demo2026!'})
    assert r.status_code==200
    return r.headers and r.json()['token']

def auth(t):return {'Authorization':f'Bearer {t}'}

def test_full_verification_flow_over_http(client):
    c,Maker=client;h=auth(token(c))
    # 建关系（含空决定项与复合决定项场景属性）
    r=c.post('/relations',headers=h,json={'code':'NL-X','title':'HTTP端到端','attributes':['委托号','客户','检测项','结果']})
    assert r.status_code==201;rid=r.json()['id']
    # 登记两条依赖：委托号→客户，(委托号,检测项)→结果
    d1=c.post('/dependencies',headers=h,json={'relation_id':rid,'lhs':['委托号'],'rhs':['客户'],'note':''})
    d2=c.post('/dependencies',headers=h,json={'relation_id':rid,'lhs':['委托号','检测项'],'rhs':['结果'],'note':''})
    dep1,dep2=d1.json()['id'],d2.json()['id']
    # 空样本核验保持待核验，采纳被 422 拒绝
    assert c.post(f'/dependencies/{dep1}/verify',headers=h).json()['verify_status']=='pending'
    r=c.post(f'/dependencies/{dep1}/adopt',headers=h)
    assert r.status_code==422
    # 写入支持样本
    base={'检测项':'拉伸','结果':'412'}
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'w1','values':{**base,'委托号':'W1','客户':'南麓'}})
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'w2','values':{**base,'委托号':'W2','客户':'江北'}})
    # 核验通过并采纳
    assert c.post(f'/dependencies/{dep1}/verify',headers=h).json()['verify_status']=='adoptable'
    r=c.post(f'/dependencies/{dep1}/adopt',headers=h);assert r.status_code==200 and r.json()['verify_status']=='adopted'
    # 重复采纳幂等：仍 200，采纳审计不重复登记（登录本身也会写审计，故只统计采纳动作）
    admin_h=auth(token(c,'admin'))
    adopts_before=[x for x in c.get('/audit',headers=admin_h).json() if '采纳' in x['action']]
    assert c.post(f'/dependencies/{dep1}/adopt',headers=h).json()['verify_status']=='adopted'
    adopts_after=[x for x in c.get('/audit',headers=admin_h).json() if '采纳' in x['action']]
    assert len(adopts_after)==len(adopts_before)==1
    # 已采纳规则约束后续写入：冲突样本整批拒绝并带可定位反例
    r=c.post('/samples',headers=h,json={'relation_id':rid,'label':'bad','values':{**base,'委托号':'W1','客户':'江北'}})
    assert r.status_code==409
    body=r.json()['detail']
    assert body['counterexamples'][0]['sample_b']['label']=='bad'
    # 空值（未知）不违反规则
    r=c.post('/samples',headers=h,json={'relation_id':rid,'label':'nullish','values':{**base,'委托号':'W1','客户':None}})
    assert r.status_code==201
    # 复合决定项：同 (W1,拉伸) 不同结果 => 冲突，核验给出反例行
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'w3','values':{'委托号':'W1','检测项':'拉伸','结果':'999','客户':'南麓'}})
    r=c.post(f'/dependencies/{dep2}/verify',headers=h)
    assert r.json()['verify_status']=='conflict'
    ce=r.json()['counterexamples'][0]
    assert ce['attribute']=='结果' and {ce['sample_a']['label'],ce['sample_b']['label']}=={'w1','w3'}
    # 移除反例样本后重新核验 -> 可采纳
    sid=c.get(f'/relations/{rid}/samples',headers=h).json()
    w3=[x for x in sid if x['label']=='w3'][0]['id']
    assert c.delete(f'/samples/{w3}',headers=h).status_code==200
    assert c.post(f'/dependencies/{dep2}/verify',headers=h).json()['verify_status']=='adoptable'
    # 总览含四态与失效标记
    overview=c.get('/verifications',headers=h,params={'relation_id':rid}).json()
    assert {x['verify_status'] for x in overview}=={'adopted','adoptable'}

def test_empty_lhs_constant_dependency_over_http(client):
    c,Maker=client;h=auth(token(c))
    r=c.post('/relations',headers=h,json={'code':'NL-C','title':'常量依赖','attributes':['批号','记录人']});rid=r.json()['id']
    d=c.post('/dependencies',headers=h,json={'relation_id':rid,'lhs':[],'rhs':['记录人'],'note':''}).json()['id']
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'s1','values':{'批号':'b1','记录人':'同一人'}})
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'s2','values':{'批号':'b2','记录人':'同一人'}})
    assert c.post(f'/dependencies/{d}/verify',headers=h).json()['verify_status']=='adoptable'
    # 引入不同记录人 -> 空决定项常量依赖冲突
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'s3','values':{'批号':'b3','记录人':'另一人'}})
    r=c.post(f'/dependencies/{d}/verify',headers=h)
    assert r.json()['verify_status']=='conflict'

def test_viewer_cannot_write_samples_or_adopt(client):
    c,Maker=client
    h=auth(token(c))  # operator 建关系
    rid=c.post('/relations',headers=h,json={'code':'NL-V','title':'权限','attributes':['A','B']}).json()['id']
    vh=auth(token(c,'viewer'))
    assert c.post('/samples',headers=vh,json={'relation_id':rid,'label':'x','values':{'A':'1','B':'2'}}).status_code==403
    d=c.post('/dependencies',headers=h,json={'relation_id':rid,'lhs':['A'],'rhs':['B'],'note':''}).json()['id']
    assert c.post(f'/dependencies/{d}/adopt',headers=vh).status_code==403
    # 只读接口可访问
    assert c.get(f'/relations/{rid}/samples',headers=vh).status_code==200
    assert c.get('/verifications',headers=vh).status_code==200

def test_batch_is_all_or_nothing_over_http(client):
    c,Maker=client;h=auth(token(c))
    rid=c.post('/relations',headers=h,json={'code':'NL-B','title':'批量','attributes':['委托号','客户']}).json()['id']
    d=c.post('/dependencies',headers=h,json={'relation_id':rid,'lhs':['委托号'],'rhs':['客户'],'note':''}).json()['id']
    c.post('/samples',headers=h,json={'relation_id':rid,'label':'w1','values':{'委托号':'W1','客户':'南麓'}})
    c.post(f'/dependencies/{d}/verify',headers=h);c.post(f'/dependencies/{d}/adopt',headers=h)
    w1=c.get(f'/relations/{rid}/samples',headers=h).json()[0]['id']
    # 夹带一条与已采纳 W1→南麓 冲突的新增，整批必须拒绝
    ops=[{'op':'add','label':'ok','values':{'委托号':'W9','客户':'江北'}},
         {'op':'add','label':'bad','values':{'委托号':'W1','客户':'江北'}},
         {'op':'update','sample_id':w1,'label':'w1','values':{'委托号':'W1','客户':'南麓'}}]
    r=c.post(f'/relations/{rid}/samples/batch',headers=h,json={'operations':ops})
    assert r.status_code==409
    labels={x['label'] for x in c.get(f'/relations/{rid}/samples',headers=h).json()}
    assert labels=={'w1'}  # 整批不落库，连合规的 ok 也不写入
