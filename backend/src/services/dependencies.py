from sqlalchemy import select,func
from fastapi import HTTPException
from src.models.entities import Relation,Dependency
from src.utils.serialization import record
from .common import save
def listing(db):return [record(x) for x in db.scalars(select(Dependency).order_by(Dependency.id))]
def validate(db,data,exclude=None):
    relation=db.get(Relation,data.relation_id)
    if not relation:raise HTTPException(404,'关系不存在')
    if not set(data.lhs+data.rhs)<=set(relation.attributes):raise HTTPException(422,'依赖属性必须属于选定关系')
    count=db.scalar(select(func.count()).select_from(Dependency).where(Dependency.relation_id==data.relation_id))
    if not exclude and count>=64:raise HTTPException(422,'最多64条函数依赖，请合并后重试')
def create(db,data,user):
    validate(db,data);return save(db,Dependency(**data.model_dump()),user,'创建函数依赖')
def update(db,ident,data,user):
    obj=db.get(Dependency,ident)
    if not obj:raise HTTPException(404,'依赖不存在')
    if obj.verify_status=='adopted':
        raise HTTPException(409,'该依赖已采纳为正式规则，不能修改决定项/被决定项；如需调整请先基于样本重新登记规则')
    validate(db,data,ident)
    changed=obj.lhs!=data.lhs or obj.rhs!=data.rhs
    for k,v in data.model_dump().items():setattr(obj,k,v)
    if changed:
        obj.verify_status='pending';obj.checked_version=None;obj.counterexamples=[];obj.last_checked_at=None
    return save(db,obj,user,'更新函数依赖')
