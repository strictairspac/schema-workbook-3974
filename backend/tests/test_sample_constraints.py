"""已采纳规则约束后续样本写入：违反整批拒绝（单条与批量），空值未知不拦截。"""
import pytest
from fastapi import HTTPException
from src.models.entities import Dependency,Sample
from src.services import verification as v
from src.services import samples as sp
from src.schemas.sample import SampleInput,SampleUpdate,BatchInput,BatchOp

class U:email='operator@nanlu.test'
USER=U()
FULL={'委托号':'W?','客户':'C','检测项':'拉伸','方法':'M','结果':'r'}

def adopt_rule(session,relation,lhs,rhs,rows):
    db,_=session
    dep=Dependency(relation_id=relation.id,lhs=lhs,rhs=rhs,note='t',verify_status='pending',counterexamples=[])
    db.add(dep);db.commit()
    for label,values in rows:sp.create(db,SampleInput(relation_id=relation.id,label=label,values=values),USER)
    v.verify(db,dep.id,USER);v.adopt(db,dep.id,USER)
    return dep

def test_single_insert_violating_adopted_rule_rejected(session,relation,actor):
    db,_=session
    adopt_rule(session,relation,['委托号'],['客户'],
               [('w1',{**FULL,'委托号':'W1','客户':'南麓'}),('w2',{**FULL,'委托号':'W2','客户':'江北'})])
    # W1 已对应南麓，再插一条 W1→江北 违反规则：整批（单条）拒绝
    with pytest.raises(HTTPException) as e:
        sp.create(db,SampleInput(relation_id=relation.id,label='w3',values={**FULL,'委托号':'W1','客户':'江北'}),USER)
    assert e.value.status_code==409
    payload=e.value.detail
    assert payload['counterexamples'][0]['sample_b']['label']=='w3'
    # 拒绝后不落库
    assert db.query(Sample).filter(Sample.label=='w3').count()==0

def test_single_update_violating_adopted_rule_rejected(session,relation,actor):
    db,_=session
    adopt_rule(session,relation,['委托号'],['客户'],
               [('w1',{**FULL,'委托号':'W1','客户':'南麓'}),('w2',{**FULL,'委托号':'W2','客户':'江北'})])
    w2=db.query(Sample).filter(Sample.label=='w2').one()
    with pytest.raises(HTTPException):
        sp.update(db,w2.id,SampleUpdate(label='w2',values={**FULL,'委托号':'W1','客户':'江北'}),USER)
    db.refresh(w2)
    assert w2.values['委托号']=='W2'  # 回滚，原值保留

def test_null_value_does_not_violate_adopted_rule(session,relation,actor):
    db,_=session
    adopt_rule(session,relation,['委托号'],['客户'],
               [('w1',{**FULL,'委托号':'W1','客户':'南麓'})])
    # 客户未知（None）：空值不是相等也不是冲突，允许写入
    obj=sp.create(db,SampleInput(relation_id=relation.id,label='w2',values={**FULL,'委托号':'W1','客户':None}),USER)
    assert obj['values']['客户'] is None

def test_batch_all_or_nothing_on_conflict(session,relation,actor):
    db,_=session
    adopt_rule(session,relation,['委托号'],['客户'],[('w1',{**FULL,'委托号':'W1','客户':'南麓'})])
    w1=db.query(Sample).filter(Sample.label=='w1').one()
    # update 把 w1 的客户改坏（W1 同时存在两条不同客户），并夹带一个合规 add：整批仍应拒绝
    ops=[BatchOp(op='add',label='ok',values={**FULL,'委托号':'W9','客户':'江北'}),
         BatchOp(op='update',sample_id=w1.id,label='w1',values={**FULL,'委托号':'W1','客户':'被改坏'}),
         BatchOp(op='add',label='dup-w1',values={**FULL,'委托号':'W1','客户':'另一客户'})]
    with pytest.raises(HTTPException) as e:
        sp.batch_apply(db,relation.id,BatchInput(operations=ops).operations,USER)
    assert e.value.status_code==409
    # 整批不落库：ok/dup-w1 不存在，w1 未被修改
    assert db.query(Sample).filter(Sample.label.in_(['ok','dup-w1'])).count()==0
    db.refresh(w1);assert w1.values['客户']=='南麓'

def test_batch_valid_mix_applied_and_version_bumped(session,relation,actor):
    db,_=session
    dep=adopt_rule(session,relation,['委托号'],['客户'],[('w1',{**FULL,'委托号':'W1','客户':'南麓'})])
    w1=db.query(Sample).filter(Sample.label=='w1').one()
    version_before=relation.sample_version
    ops=[BatchOp(op='add',label='w2',values={**FULL,'委托号':'W2','客户':'江北'}),
         BatchOp(op='update',sample_id=w1.id,label='w1-renamed',values={**FULL,'委托号':'W1','客户':'南麓'}),
         BatchOp(op='remove',sample_id=w1.id)]
    out=sp.batch_apply(db,relation.id,BatchInput(operations=ops).operations,USER)
    assert out['applied']==3
    assert relation.sample_version==version_before+1
    labels={x['label'] for x in out['samples']}
    assert labels=={'w2'}
    # 移除样本不违反规则，采纳状态保留
    db.refresh(dep);assert dep.verify_status=='adopted'

def test_sample_schema_validation(session,relation,actor):
    db,_=session
    # 关系外属性拒绝
    with pytest.raises(HTTPException) as e:
        sp.create(db,SampleInput(relation_id=relation.id,label='x',values={'幽灵属性':'v'}),USER)
    assert e.value.status_code==422
    # 标签重复拒绝
    sp.create(db,SampleInput(relation_id=relation.id,label='dup',values=FULL),USER)
    with pytest.raises(HTTPException) as e:
        sp.create(db,SampleInput(relation_id=relation.id,label='dup',values=FULL),USER)
    assert e.value.status_code==409
    # 未知关系 404
    with pytest.raises(HTTPException) as e:
        sp.create(db,SampleInput(relation_id=999,label='x',values={}),USER)
    assert e.value.status_code==404
