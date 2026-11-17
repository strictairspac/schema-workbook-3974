"""核验/采纳生命周期：状态流转、空样本拒绝、失效拒绝、重复采纳幂等、移除反例。"""
import pytest
from fastapi import HTTPException
from src.models.entities import Dependency,Sample
from src.services import verification as v
from src.services import samples as sp
from src.schemas.sample import SampleInput,SampleUpdate

def make_dep(db,rel,lhs,rhs):
    dep=Dependency(relation_id=rel.id,lhs=lhs,rhs=rhs,note='t',verify_status='pending',counterexamples=[])
    db.add(dep);db.commit();return dep

def add_sample(db,rel,label,values,user):
    return sp.create(db,SampleInput(relation_id=rel.id,label=label,values=values),user)

class U:email='operator@nanlu.test'
USER=U()

def test_full_lifecycle_pending_adoptable_adopted(session,relation,actor):
    db,_=session
    dep=make_dep(db,relation,['委托号'],['客户'])
    # 初始待核验
    assert dep.verify_status=='pending'
    # 空样本核验：仍待核验，且采纳被拒绝
    v.verify(db,dep.id,USER);db.refresh(dep)
    assert dep.verify_status=='pending' and dep.counterexamples==[]
    with pytest.raises(HTTPException) as e:v.adopt(db,dep.id,USER)
    assert e.value.status_code==422
    # 增加支持样本后核验 -> 可采纳 -> 已采纳
    add_sample(db,relation,'w1',{'委托号':'W1','客户':'南麓','检测项':'拉伸','方法':'M','结果':'r'},USER)
    add_sample(db,relation,'w2',{'委托号':'W2','客户':'江北','检测项':'冲击','方法':'M2','结果':'r2'},USER)
    out=v.verify(db,dep.id,USER)
    assert out['verify_status']=='adoptable' and out['sample_count']==2
    adopted=v.adopt(db,dep.id,USER)
    assert adopted['verify_status']=='adopted' and adopted['adopted_version']==relation.sample_version
    # 重复采纳不重复登记（审计条数不变、版本不变）
    from src.models.entities import Audit
    before=db.query(Audit).count()
    again=v.adopt(db,dep.id,USER)
    after=db.query(Audit).count()
    assert again['verify_status']=='adopted' and before==after

def test_conflict_blocks_adoption_with_locateable_rows(session,relation,actor):
    db,_=session
    dep=make_dep(db,relation,['委托号'],['客户'])
    add_sample(db,relation,'w1',{'委托号':'W1','客户':'南麓','检测项':'拉伸','方法':'M','结果':'r'},USER)
    add_sample(db,relation,'w2',{'委托号':'W1','客户':'江北','检测项':'冲击','方法':'M2','结果':'r2'},USER)
    out=v.verify(db,dep.id,USER)
    assert out['verify_status']=='conflict'
    assert out['counterexamples'][0]['sample_a']['label']=='w1'
    assert out['counterexamples'][0]['sample_b']['label']=='w2'
    with pytest.raises(HTTPException) as e:v.adopt(db,dep.id,USER)
    assert e.value.status_code==409

def test_remove_counterexample_then_verify_and_adopt(session,relation,actor):
    db,_=session
    dep=make_dep(db,relation,['委托号'],['客户'])
    s1=add_sample(db,relation,'w1',{'委托号':'W1','客户':'南麓','检测项':'拉伸','方法':'M','结果':'r'},USER)
    s2=add_sample(db,relation,'w2',{'委托号':'W1','客户':'江北','检测项':'冲击','方法':'M2','结果':'r2'},USER)
    v.verify(db,dep.id,USER);db.refresh(dep)
    assert dep.verify_status=='conflict'
    # 更正反例：把 w2 的委托号改成 W2，冲突消除
    sp.update(db,s2['id'],SampleUpdate(label='w2',values={'委托号':'W2','客户':'江北','检测项':'冲击','方法':'M2','结果':'r2'}),USER)
    # 旧结论标记失效
    overview=v.status_overview(db,relation.id)
    assert overview[0]['stale'] is True
    out=v.verify(db,dep.id,USER)
    assert out['verify_status']=='adoptable' and out['counterexamples']==[]
    v.adopt(db,dep.id,USER);db.refresh(dep)
    assert dep.verify_status=='adopted'
    # 采纳后写入违反规则的样本会被整批拒绝；合规样本可以写入并移除
    with pytest.raises(HTTPException) as e:
        add_sample(db,relation,'bad',{'委托号':'W1','客户':'第三人','检测项':'硬度','方法':'M3','结果':'r3'},USER)
    assert e.value.status_code==409
    s3=add_sample(db,relation,'w3',{'委托号':'W3','客户':'第三人','检测项':'硬度','方法':'M3','结果':'r3'},USER)
    sp.remove(db,s3['id'],USER)

def test_stale_verdict_rejected_on_adopt_after_source_change(session,relation,actor):
    db,_=session
    dep=make_dep(db,relation,['委托号'],['客户'])
    add_sample(db,relation,'w1',{'委托号':'W1','客户':'南麓','检测项':'拉伸','方法':'M','结果':'r'},USER)
    add_sample(db,relation,'w2',{'委托号':'W2','客户':'江北','检测项':'冲击','方法':'M2','结果':'r2'},USER)
    v.verify(db,dep.id,USER);db.refresh(dep)
    assert dep.verify_status=='adoptable'
    # 源数据变化：引入冲突样本，旧的“可采纳”结论失效
    add_sample(db,relation,'w3',{'委托号':'W1','客户':'第三人','检测项':'硬度','方法':'M3','结果':'r3'},USER)
    with pytest.raises(HTTPException) as e:v.adopt(db,dep.id,USER)
    assert e.value.status_code==409
    db.refresh(dep)
    # 采纳失败且状态已被锁内重算刷新为冲突，规则与样本不矛盾
    assert dep.verify_status=='conflict' and dep.counterexamples

def test_empty_lhs_and_composite_dependencies(session,relation,actor):
    db,_=session
    # 空决定项 ∅→客户
    const_dep=make_dep(db,relation,[],['客户'])
    add_sample(db,relation,'w1',{'委托号':'W1','客户':'同一客户','检测项':'拉伸','方法':'M','结果':'r'},USER)
    add_sample(db,relation,'w2',{'委托号':'W2','客户':'同一客户','检测项':'冲击','方法':'M2','结果':'r2'},USER)
    out=v.verify(db,const_dep.id,USER)
    assert out['verify_status']=='adoptable'
    v.adopt(db,const_dep.id,USER)
    db.refresh(const_dep);assert const_dep.verify_status=='adopted'
    # 复合决定项 (委托号,检测项)→结果
    comp_dep=make_dep(db,relation,['委托号','检测项'],['结果'])
    add_sample(db,relation,'w3',{'委托号':'W1','检测项':'拉伸','结果':'r','客户':'同一客户','方法':'M'},USER)
    out=v.verify(db,comp_dep.id,USER)
    assert out['verify_status']=='adoptable'

def test_adopted_dependency_is_immutable(session,relation,actor):
    db,_=session
    dep=make_dep(db,relation,['委托号'],['客户'])
    add_sample(db,relation,'w1',{'委托号':'W1','客户':'南麓','检测项':'拉伸','方法':'M','结果':'r'},USER)
    v.verify(db,dep.id,USER);v.adopt(db,dep.id,USER)
    from src.schemas.dependency import DependencyInput
    from src.services import dependencies as dsvc
    with pytest.raises(HTTPException) as e:
        dsvc.update(db,dep.id,DependencyInput(relation_id=relation.id,lhs=['委托号'],rhs=['结果'],note='x'),USER)
    assert e.value.status_code==409

def test_updating_dependency_resets_verification(session,relation,actor):
    db,_=session
    dep=make_dep(db,relation,['委托号'],['客户'])
    add_sample(db,relation,'w1',{'委托号':'W1','客户':'南麓','检测项':'拉伸','方法':'M','结果':'r'},USER)
    v.verify(db,dep.id,USER);db.refresh(dep)
    assert dep.verify_status=='adoptable'
    from src.schemas.dependency import DependencyInput
    from src.services import dependencies as dsvc
    dsvc.update(db,dep.id,DependencyInput(relation_id=relation.id,lhs=['委托号'],rhs=['方法'],note='改'),USER)
    db.refresh(dep)
    assert dep.verify_status=='pending' and dep.checked_version is None and dep.counterexamples==[]
