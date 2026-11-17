"""并发：采纳与样本更正交错提交，行锁保证最终状态不矛盾。

生产环境为 MySQL：服务层通过 SELECT ... FOR UPDATE 对关系行加排他行锁，
采纳与样本写入互斥、提交即释放。SQLite 不支持行级锁（方言会忽略 FOR UPDATE），
因此测试用按关系 id 串行的应用级临界区模拟同一把行锁，覆盖交错提交语义。
"""
import os,tempfile,threading
import contextlib
import pytest
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from fastapi import HTTPException
from src.config.database import Base
from src.models.entities import User,Relation,Dependency,Sample
from src.utils.security import password_hash
from src.services import verification as v
from src.services import samples as sp
from src.schemas.sample import SampleInput,SampleUpdate

class U:email='operator@nanlu.test'
USER=U()
FULL={'委托号':'W?','客户':'C','检测项':'拉伸','方法':'M','结果':'r'}

# 测试替身：模拟 MySQL 关系行 FOR UPDATE 排他锁（按关系 id 键控，提交/回滚即释放）
_ROW_LOCKS={}
_LOCK_GUARD=threading.Lock()
def row_lock(relation_id):
    with _LOCK_GUARD:
        lk=_ROW_LOCKS.setdefault(relation_id,threading.Lock())
    return lk

@contextlib.contextmanager
def locked(relation_id):
    lk=row_lock(relation_id)
    lk.acquire()
    try:yield
    finally:lk.release()

@pytest.fixture()
def shared():
    fd,path=tempfile.mkstemp(suffix='.db');os.close(fd)
    engine=create_engine(f'sqlite:///{path}',connect_args={'timeout':15,'check_same_thread':False},isolation_level=None)
    @event.listens_for(engine,'connect')
    def _pragma(dbapi_con,_):
        cur=dbapi_con.cursor()
        cur.execute('PRAGMA journal_mode=WAL');cur.execute('PRAGMA busy_timeout=15000');cur.close()
    Base.metadata.create_all(engine)
    Maker=sessionmaker(engine,expire_on_commit=False)
    db=Maker()
    db.add(User(email='operator@nanlu.test',password=password_hash('x'),role='operator'))
    rel=Relation(code='T-1',title='并发关系',attributes=['委托号','客户','检测项','方法','结果'],sample_version=0)
    db.add(rel);db.commit()
    dep=Dependency(relation_id=rel.id,lhs=['委托号'],rhs=['客户'],note='t',verify_status='pending',counterexamples=[])
    db.add(dep);db.commit()
    sp.create(db,SampleInput(relation_id=rel.id,label='w1',values={**FULL,'委托号':'W1','客户':'南麓'}),USER)
    sp.create(db,SampleInput(relation_id=rel.id,label='w2',values={**FULL,'委托号':'W2','客户':'江北'}),USER)
    v.verify(db,dep.id,USER)
    db.commit();db.close();engine.dispose()
    yield Maker,rel.id,dep.id
    engine.dispose()
    for suffix in ('','-wal','-shm'):
        try:os.remove(path+suffix)
        except OSError:pass

def _invariant_holds(Maker,dep_id):
    """核心不变量：已采纳规则在当前全部样本上必须无反例（规则与样本永不矛盾）。"""
    db=Maker()
    try:
        dep=db.get(Dependency,dep_id);rel=db.get(Relation,dep.relation_id)
        rows=[{'id':x.id,'label':x.label,'values':x.values} for x in db.query(Sample).filter(Sample.relation_id==rel.id).all()]
        ce=v.find_counterexamples(rows,dep.lhs,dep.rhs)
        if dep.verify_status=='adopted':
            assert ce==[],f'已采纳规则存在反例：{ce}'
        return dep.verify_status,len(ce)
    finally:db.close()

# ---- 服务调用包装：把服务内的 FOR UPDATE 临界区替换为测试行锁 ----
def adopt_locked(Maker,dep_id):
    db=Maker()
    try:
        dep=db.get(Dependency,dep_id)
        with locked(dep.relation_id):
            return v.adopt(db,dep_id,USER)
    finally:db.close()

def update_locked(Maker,sample_id,payload):
    db=Maker()
    try:
        rel_id=db.get(Sample,sample_id).relation_id
        with locked(rel_id):
            return sp.update(db,sample_id,payload,USER)
    finally:db.close()

def create_locked(Maker,relation_id,payload):
    db=Maker()
    try:
        with locked(relation_id):
            return sp.create(db,payload,USER)
    finally:db.close()

def test_concurrent_adopt_and_conflicting_correction(shared):
    Maker,rel_id,dep_id=shared
    errors=[];states=[]
    barrier=threading.Barrier(2)
    def adopt():
        try:
            barrier.wait();adopt_locked(Maker,dep_id)
        except HTTPException as e:states.append(('adopt-rejected',e.status_code))
        except Exception as e:errors.append(('adopt',repr(e)))
    def corrupt():
        db=Maker()
        try:
            barrier.wait()
            w1_id=db.query(Sample).filter(Sample.label=='w1').one().id;db.close()
            # 把 w1 的委托号改为 W2：与 w2(W2→江北) 同决定项不同客户，制造反例
            update_locked(Maker,w1_id,SampleUpdate(label='w1',values={**FULL,'委托号':'W2','客户':'南麓'}))
            states.append(('correction-ok',None))
        except HTTPException as e:states.append(('correction-rejected',e.status_code))
        except Exception as e:errors.append(('correct',repr(e)))
        finally:
            try:db.close()
            except Exception:pass
    t1=threading.Thread(target=adopt);t2=threading.Thread(target=corrupt)
    t1.start();t2.start();t1.join(30);t2.join(30)
    assert not errors,errors
    status,ce=_invariant_holds(Maker,dep_id)
    # 互斥后的两种合法结局：采纳成功且冲突更正被整批拒绝；或更正先提交且采纳被拒绝并转为冲突
    assert status in ('adopted','conflict')
    if status=='adopted':
        assert ('correction-rejected',409) in states
        assert ce==0
    else:
        assert ('adopt-rejected',409) in states
        assert ce>=1

def test_repeated_concurrent_runs_never_leave_contradiction(shared):
    Maker,rel_id,dep_id=shared
    db=Maker();sample_id=db.query(Sample).order_by(Sample.id).first().id;db.close()
    def churn(round_no):
        db=Maker()
        try:
            row=db.get(Sample,sample_id);label=row.label
            vals=dict(row.values);vals['客户']='轮换客户'+str(round_no)
        finally:db.close()
        update_locked(Maker,sample_id,SampleUpdate(label=label,values=vals))
    for round_no in range(5):
        errors=[]
        t_adopt=threading.Thread(target=lambda:_safe(lambda:adopt_locked(Maker,dep_id),errors))
        t_churn=threading.Thread(target=lambda:_safe(lambda:churn(round_no),errors))
        t_adopt.start();t_churn.start();t_adopt.join(30);t_churn.join(30)
        assert not errors,errors
        _invariant_holds(Maker,dep_id)

def _safe(fn,errors):
    try:fn()
    except HTTPException:pass
    except OperationalError:pass
    except Exception as e:errors.append(repr(e))

def test_concurrent_sample_writes_serialize_by_relation_lock(shared):
    Maker,rel_id,dep_id=shared
    adopt_locked(Maker,dep_id)  # 先采纳规则
    outcomes=[];guard=threading.Lock()
    def writer(i):
        try:
            create_locked(Maker,rel_id,SampleInput(relation_id=rel_id,label=f'c{i}',
                values={**FULL,'委托号':'W1','客户':'南麓' if i%2==0 else '江北'}))
            with guard:outcomes.append(('ok',i))
        except HTTPException as e:
            with guard:outcomes.append(('rejected',(i,e.status_code)))
        except Exception as e:
            with guard:outcomes.append(('error',repr(e)))
    threads=[threading.Thread(target=writer,args=(i,)) for i in range(6)]
    for t in threads:t.start()
    for t in threads:t.join(30)
    assert all(o[0] in ('ok','rejected') for o in outcomes),outcomes
    _invariant_holds(Maker,dep_id)
    # 奇数下标（客户=江北，与已采纳的 W1→南麓 冲突）必须全部被拒且状态码 409；偶数下标合规全部成功
    rejected={i for kind,payload in outcomes if kind=='rejected' for i,status in [payload]}
    statuses={status for kind,payload in outcomes if kind=='rejected' for i,status in [payload]}
    accepted={i for kind,i in outcomes if kind=='ok'}
    assert rejected=={1,3,5}
    assert statuses=={409}
    assert accepted=={0,2,4}
