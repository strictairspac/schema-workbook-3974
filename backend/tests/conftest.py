import os,pytest
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from src.config.database import Base
from src.models import entities
from src.models.entities import User,Relation,Dependency,Sample
from src.utils.security import password_hash

@pytest.fixture()
def session():
    engine=create_engine('sqlite:///:memory:')
    # 模拟 MySQL 行为：写串行化、锁等待而非立即报 database is locked
    @event.listens_for(engine,'connect')
    def _wal(dbapi_con,_):
        cur=dbapi_con.cursor()
        cur.execute('PRAGMA journal_mode=WAL');cur.execute('PRAGMA busy_timeout=5000');cur.close()
    Base.metadata.create_all(engine)
    Maker=sessionmaker(engine,expire_on_commit=False)
    db=Maker()
    db.add(User(email='operator@nanlu.test',password=password_hash('x'),role='operator'))
    db.add(User(email='viewer@nanlu.test',password=password_hash('x'),role='viewer'))
    db.commit()
    yield db,Maker
    db.close();engine.dispose()

@pytest.fixture()
def actor(session):
    db,_=session
    return db.query(User).filter(User.email=='operator@nanlu.test').one()

@pytest.fixture()
def relation(session):
    db,_=session
    rel=Relation(code='T-1',title='测试关系',attributes=['委托号','客户','检测项','方法','结果'],sample_version=0)
    db.add(rel);db.commit()
    return rel
