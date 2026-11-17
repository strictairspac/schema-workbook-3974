from sqlalchemy import select,func
from src.config.database import Session,Base,engine
from src.models.entities import User,Relation,Dependency,Report,Sample
from src.utils.security import password_hash
from src.services.verification import _refresh
from datetime import datetime,timezone

def seed():
    Base.metadata.create_all(engine)
    with Session() as db:
        for role in ('admin','operator','viewer'):
            email=role+'@nanlu.test'
            if not db.scalar(select(User).where(User.email==email)):db.add(User(email=email,password=password_hash('Demo2026!'),role=role))
        cases=[('NL-1117-A','材料检测委托单',['委托号','客户','检测项','方法','结果'],[(['委托号'],['客户']),(['检测项'],['方法']),(['委托号','检测项'],['结果'])],
                [('委托 W1 · 拉伸',{'委托号':'W1','客户':'南麓重工','检测项':'拉伸','方法':'GB/T 228','结果':'412 MPa'}),
                 ('委托 W1 · 冲击',{'委托号':'W1','客户':'南麓重工','检测项':'冲击','方法':'GB/T 229','结果':'68 J'}),
                 ('委托 W2 · 拉伸',{'委托号':'W2','客户':'江北造船','检测项':'拉伸','方法':'GB/T 228','结果':'398 MPa'}),
                 ('委托 W2 · 硬度（结果待录入）',{'委托号':'W2','客户':'江北造船','检测项':'硬度','方法':None,'结果':None})]),
               ('NL-1117-B','循环编号与独立属性',['A','B','C'],[(['A'],['B']),(['B'],['A'])],
                [('样本 b1',{'A':'a1','B':'b1','C':'c1'}),
                 ('样本 b2（与 b1 同 A 不同 B，构成反例）',{'A':'a1','B':'b2','C':None})]),
               ('NL-1117-C','尚未确认业务依赖',['批号','容器','记录人'],[],[])]
        for code,title,attrs,fds,sample_rows in cases:
            rel=db.scalar(select(Relation).where(Relation.code==code))
            if rel:continue
            rel=Relation(code=code,title=title,attributes=attrs,note='南麓材料实验室 · 09:15 委托表复核');db.add(rel);db.flush()
            for lhs,rhs in fds:db.add(Dependency(relation_id=rel.id,lhs=lhs,rhs=rhs,note='业务确认依赖'))
            for label,values in sample_rows:db.add(Sample(relation_id=rel.id,label=label,values=values))
            db.flush()
            if sample_rows:rel.sample_version=1
            # B 案第一条依赖演示“冲突”态；其余保持待核验，由用户在页面走核验/采纳流程
            if code=='NL-1117-B':
                first=db.scalars(select(Dependency).where(Dependency.relation_id==rel.id).order_by(Dependency.id)).first()
                _refresh(db,first,rel,datetime.now(timezone.utc))
        db.commit()
        print({cls.__tablename__:db.scalar(select(func.count()).select_from(cls)) for cls in (User,Relation,Dependency,Report,Sample)})
if __name__=='__main__':seed()
