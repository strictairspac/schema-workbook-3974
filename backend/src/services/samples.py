"""委托样本管理：增改移除与批量写入；已采纳规则约束全部后续样本写入。"""
from functools import wraps
from fastapi import HTTPException
from sqlalchemy import select,func
from src.models.entities import Relation,Dependency,Sample,Audit
from src.utils.serialization import record
from .verification import find_counterexamples

def atomic(fn):
    """服务层原子性：任何异常都回滚本请求内已 flush 的改动，再原样抛出。"""
    @wraps(fn)
    def wrapper(db,*args,**kwargs):
        try:return fn(db,*args,**kwargs)
        except Exception:
            db.rollback();raise
    return wrapper

MAX_SAMPLES_PER_RELATION=500
MAX_BATCH_OPS=200
MAX_VALUE_LEN=200
MAX_LABEL_LEN=120

def listing(db,relation_id):
    relation=db.get(Relation,relation_id)
    if not relation:raise HTTPException(404,'关系不存在')
    rows=db.scalars(select(Sample).where(Sample.relation_id==relation_id).order_by(Sample.id)).all()
    return [record(x) for x in rows]

def _validate_values(relation,payload):
    attrs=set(relation.attributes)
    if not isinstance(payload,dict):raise HTTPException(422,'样本取值必须是 属性→值 的对象')
    if set(payload)-attrs:raise HTTPException(422,'样本包含关系属性之外的字段')
    clean={}
    for attr in relation.attributes:
        value=payload.get(attr)
        if value is None:clean[attr]=None;continue
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):
            raise HTTPException(422,f'属性 {attr} 的取值只能是文本、数字或空值')
        if isinstance(value,str) and len(value)>MAX_VALUE_LEN:
            raise HTTPException(422,f'属性 {attr} 的文本取值不能超过 {MAX_VALUE_LEN} 字')
        clean[attr]=value
    return clean

def _validate_label(label):
    label=(label or '').strip()
    if not label or len(label)>MAX_LABEL_LEN:raise HTTPException(422,'样本定位标签不能为空且不超过120字')
    return label

def _adopted_rules(db,relation_id):
    return list(db.scalars(select(Dependency).where(Dependency.relation_id==relation_id,Dependency.verify_status=='adopted')))

def _enforce_adopted(rules,working_set):
    """对写入后的完整样本集重放全部已采纳规则；任一违反即给出可定位反例。"""
    for dep in rules:
        counterexamples=find_counterexamples(working_set,dep.lhs,dep.rhs)
        if counterexamples:
            raise HTTPException(409,{'detail':f'写入违反已采纳依赖 #{dep.id}（{"，".join(dep.lhs) or "∅"} → {"，".join(dep.rhs)}），整批拒绝',
                                     'dependency_id':dep.id,'counterexamples':counterexamples})

def _working_set(rows):
    return [{'id':x.id,'label':x.label,'values':x.values} for x in rows]

@atomic
def create(db,data,user):
    db.rollback()  # 清理取锁前的隐式读事务，保证锁内为最新读视图
    relation=db.get(Relation,data.relation_id)
    if not relation:raise HTTPException(404,'关系不存在')
    label=_validate_label(data.label);values=_validate_values(relation,data.values)
    # 锁关系行：与采纳流程互斥，保证规则与样本不会交错出矛盾状态
    db.query(Relation).filter(Relation.id==relation.id).with_for_update().one()
    count=db.scalar(select(func.count()).select_from(Sample).where(Sample.relation_id==relation.id))
    if count>=MAX_SAMPLES_PER_RELATION:raise HTTPException(422,f'每个关系最多 {MAX_SAMPLES_PER_RELATION} 条样本')
    if db.scalar(select(Sample.id).where(Sample.relation_id==relation.id,Sample.label==label)):
        raise HTTPException(409,'同关系下样本定位标签已存在')
    obj=Sample(relation_id=relation.id,label=label,values=values)
    db.add(obj);db.flush()
    rows=db.scalars(select(Sample).where(Sample.relation_id==relation.id).order_by(Sample.id)).all()
    _enforce_adopted(_adopted_rules(db,relation.id),_working_set(rows))
    relation.sample_version=(relation.sample_version or 0)+1
    db.add(Audit(actor=user.email,action=f'新增委托样本 {label}（关系 {relation.code}）'))
    db.commit()
    return record(obj)

@atomic
def update(db,ident,data,user):
    db.rollback()
    obj=db.get(Sample,ident)
    if not obj:raise HTTPException(404,'样本不存在')
    relation=db.get(Relation,obj.relation_id)
    db.query(Relation).filter(Relation.id==relation.id).with_for_update().one()
    label=_validate_label(data.label)
    if label!=obj.label and db.scalar(select(Sample.id).where(Sample.relation_id==relation.id,Sample.label==label,Sample.id!=ident)):
        raise HTTPException(409,'同关系下样本定位标签已存在')
    values=_validate_values(relation,data.values)
    obj.label=label;obj.values=values;db.flush()
    rows=db.scalars(select(Sample).where(Sample.relation_id==relation.id).order_by(Sample.id)).all()
    _enforce_adopted(_adopted_rules(db,relation.id),_working_set(rows))
    relation.sample_version=(relation.sample_version or 0)+1
    db.add(Audit(actor=user.email,action=f'更正委托样本 {label}（关系 {relation.code}）'))
    db.commit()
    return record(obj)

@atomic
def remove(db,ident,user):
    db.rollback()
    obj=db.get(Sample,ident)
    if not obj:raise HTTPException(404,'样本不存在')
    relation=db.get(Relation,obj.relation_id)
    db.query(Relation).filter(Relation.id==relation.id).with_for_update().one()
    label=obj.label
    db.delete(obj);db.flush()
    relation.sample_version=(relation.sample_version or 0)+1
    db.add(Audit(actor=user.email,action=f'移除委托样本 {label}（关系 {relation.code}）'))
    db.commit()
    return {'removed':ident}

@atomic
def batch_apply(db,relation_id,operations,user):
    """整批增改移除：先在工作副本上应用全部操作并校验采纳规则，任一违反整批不落库。"""
    db.rollback()
    relation=db.get(Relation,relation_id)
    if not relation:raise HTTPException(404,'关系不存在')
    if not operations:raise HTTPException(422,'批量操作不能为空')
    if len(operations)>MAX_BATCH_OPS:raise HTTPException(422,f'单批最多 {MAX_BATCH_OPS} 条操作')
    db.query(Relation).filter(Relation.id==relation.id).with_for_update().one()
    rows=list(db.scalars(select(Sample).where(Sample.relation_id==relation_id).order_by(Sample.id)).all())
    by_id={x.id:x for x in rows};labels={x.label for x in rows}
    working=_working_set(rows);work_by_id={x['id']:x for x in working}
    touched=0
    for op in operations:
        kind=getattr(op,'op',None)
        if kind=='add':
            label=_validate_label(op.label)
            if label in labels:raise HTTPException(409,f'批量写入失败：标签 {label} 已存在，整批拒绝')
            if len(working)>=MAX_SAMPLES_PER_RELATION:raise HTTPException(422,f'每个关系最多 {MAX_SAMPLES_PER_RELATION} 条样本')
            item={'id':None,'label':label,'values':_validate_values(relation,op.values)}
            working.append(item);labels.add(label);touched+=1
        elif kind=='update':
            target=work_by_id.get(op.sample_id)
            if not target:raise HTTPException(404,f'批量写入失败：样本 #{op.sample_id} 不存在，整批拒绝')
            label=_validate_label(op.label)
            if label!=target['label'] and label in labels:raise HTTPException(409,f'批量写入失败：标签 {label} 已存在，整批拒绝')
            labels.discard(target['label']);target['label']=label;target['values']=_validate_values(relation,op.values);labels.add(label);touched+=1
        elif kind=='remove':
            target=work_by_id.pop(op.sample_id,None)
            if target is None:raise HTTPException(404,f'批量写入失败：样本 #{op.sample_id} 不存在，整批拒绝')
            labels.discard(target['label']);working.remove(target);touched+=1
        else:
            raise HTTPException(422,'操作类型 op 必须是 add/update/remove')
    _enforce_adopted(_adopted_rules(db,relation_id),working)
    # 全部校验通过后才落库
    for op in operations:
        if op.op=='add':
            db.add(Sample(relation_id=relation_id,label=_validate_label(op.label),values=_validate_values(relation,op.values)))
        elif op.op=='update':
            by_id[op.sample_id].label=_validate_label(op.label)
            by_id[op.sample_id].values=_validate_values(relation,op.values)
        else:
            db.delete(by_id[op.sample_id])
    relation.sample_version=(relation.sample_version or 0)+1
    db.add(Audit(actor=user.email,action=f'批量写入委托样本 {touched} 条（关系 {relation.code}）'))
    db.commit()
    return {'applied':touched,'sample_version':relation.sample_version,
            'samples':[record(x) for x in db.scalars(select(Sample).where(Sample.relation_id==relation_id).order_by(Sample.id)).all()]}
