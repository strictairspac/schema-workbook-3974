"""样本规则核验：函数依赖在委托样本上的反例检查与采纳。

空值语义：None 表示未知，而不是一个可比较的相等值。
- 决定项 LHS 中任一属性为空，则该样本不参与“同决定项”分组；
- 被决定项 RHS 中任一属性为空，该属性不参与冲突判定（未知不构成反例）；
- 仅当两条样本 LHS 全部已知且逐项相等、且某个 RHS 属性两边均已知但取值不同时，才形成反例。
"""
from datetime import datetime,timezone
from fastapi import HTTPException
from sqlalchemy import select
from src.models.entities import Relation,Dependency,Sample,Audit
from src.utils.serialization import record
from functools import wraps

def atomic(fn):
    @wraps(fn)
    def wrapper(db,*args,**kwargs):
        try:return fn(db,*args,**kwargs)
        except Exception:
            db.rollback();raise
    return wrapper

MAX_COUNTEREXAMPLES=20

def _known(value):
    return value is not None

def lhs_agrees(left,right,lhs):
    """LHS 全等：所有决定项属性均已知（非 None）且逐项相等。空值视为未知，不相等。"""
    for attr in lhs:
        a,b=left.get(attr),right.get(attr)
        if not _known(a) or not _known(b) or a!=b:return False
    return True

def rhs_conflicts(left,right,rhs):
    """返回首个两边均已知但取值不同的 RHS 属性；空值（未知）跳过，不判冲突。"""
    for attr in rhs:
        a,b=left.get(attr),right.get(attr)
        if _known(a) and _known(b) and a!=b:return attr
    return None

def find_counterexamples(samples,lhs,rhs):
    """枚举全体样本的无序对，输出可定位的反例行（含样本 id/label 与冲突属性及取值）。"""
    findings=[]
    for i in range(len(samples)):
        for j in range(i+1,len(samples)):
            s1,s2=samples[i],samples[j]
            if not lhs_agrees(s1['values'],s2['values'],lhs):continue
            attr=rhs_conflicts(s1['values'],s2['values'],rhs)
            if attr is None:continue
            findings.append({'sample_a':{'id':s1['id'],'label':s1['label']},
                             'sample_b':{'id':s2['id'],'label':s2['label']},
                             'lhs':{a:s1['values'].get(a) for a in lhs},
                             'attribute':attr,
                             'values':{s1['label']:s1['values'].get(attr),s2['label']:s2['values'].get(attr)}})
            if len(findings)>=MAX_COUNTEREXAMPLES:return findings
    return findings

def evaluate(lhs,rhs,samples):
    """纯判定：返回 (状态, 反例列表)。无样本时保持待核验（空样本不允许采纳）。"""
    counterexamples=find_counterexamples(samples,lhs,rhs)
    if counterexamples:return 'conflict',counterexamples
    if not samples:return 'pending',[]
    return 'adoptable',[]

def _load_samples(db,relation_id):
    rows=db.scalars(select(Sample).where(Sample.relation_id==relation_id).order_by(Sample.id)).all()
    return [{'id':x.id,'label':x.label,'values':x.values} for x in rows]

def _refresh(db,dep,relation,now):
    samples=_load_samples(db,relation.id)
    status,counterexamples=evaluate(dep.lhs,dep.rhs,samples)
    dep.verify_status=status
    dep.counterexamples=counterexamples
    dep.checked_version=relation.sample_version
    dep.last_checked_at=now
    return status,counterexamples,samples

@atomic
def verify(db,ident,user):
    """按指定依赖检查全体样本。核验期间样本可继续更正；结论记录所依据的样本版本。"""
    dep=db.get(Dependency,ident)
    if not dep:raise HTTPException(404,'依赖不存在')
    if dep.verify_status=='adopted':return record(dep)
    relation=db.get(Relation,dep.relation_id)
    now=datetime.now(timezone.utc)
    status,counterexamples,samples=_refresh(db,dep,relation,now)
    db.add(Audit(actor=user.email,action=f'核验函数依赖 #{dep.id} → {status}'))
    db.commit()
    result=record(dep)
    result['sample_count']=len(samples)
    result['stale']=False
    return result

@atomic
def adopt(db,ident,user):
    """采纳为正式依赖。重复采纳不重复登记；源数据变化使旧结论失效时拒绝采纳。"""
    # 先结束取锁前可能已隐式开启的读事务，避免持有旧快照导致锁内读到过期样本
    db.rollback()
    dep=db.get(Dependency,ident)
    if not dep:raise HTTPException(404,'依赖不存在')
    relation=db.get(Relation,dep.relation_id)
    # 行锁串行化采纳与样本更正，杜绝“规则已采纳但样本违反规则”的交错提交
    db.query(Relation).filter(Relation.id==relation.id).with_for_update().one()
    # 取锁后重新加载依赖与样本版本：锁等待期间对方可能已提交更正
    db.refresh(dep);db.refresh(relation)
    now=datetime.now(timezone.utc)
    if dep.verify_status=='adopted':
        db.commit();return record(dep)
    if dep.verify_status=='conflict' and dep.checked_version==relation.sample_version:
        raise HTTPException(409,'样本存在反例，请先更正样本后重新核验')
    # 锁内重算，覆盖核验后、采纳前的并发样本更正
    status,counterexamples,samples=_refresh(db,dep,relation,now)
    if not samples:
        db.commit()  # 落账“待核验/空样本”现状，再拒绝采纳
        raise HTTPException(422,'样本为空，当前没有任何委托样本可佐证该依赖，不允许采纳')
    if status=='conflict':
        db.commit()  # 旧结论已失效，落账最新冲突结论与可定位反例，再拒绝采纳
        raise HTTPException(409,'样本存在反例，请先更正样本后重新核验')
    dep.verify_status='adopted';dep.adopted_version=relation.sample_version
    db.add(Audit(actor=user.email,action=f'采纳函数依赖 #{dep.id} 为正式依赖（样本版本 {relation.sample_version}）'))
    db.commit()
    return record(dep)

def status_overview(db,relation_id=None):
    stmt=select(Dependency).order_by(Dependency.id)
    if relation_id is not None:stmt=stmt.where(Dependency.relation_id==relation_id)
    out=[]
    for dep in db.scalars(stmt):
        item=record(dep)
        relation=db.get(Relation,dep.relation_id)
        item['stale']=dep.verify_status!='adopted' and dep.checked_version is not None and dep.checked_version!=relation.sample_version
        item['sample_count']=db.query(Sample).filter(Sample.relation_id==dep.relation_id).count()
        out.append(item)
    return out
