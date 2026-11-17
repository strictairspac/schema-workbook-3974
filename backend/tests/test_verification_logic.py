"""核验纯逻辑：空决定项、复合决定项、空值未知语义、反例定位。"""
from src.services.verification import find_counterexamples,evaluate,lhs_agrees,rhs_conflicts

def s(i,label,values):return {'id':i,'label':label,'values':values}

def test_empty_lhs_constant_dependency_conflict():
    # 空决定项 ∅→客户：所有已知客户必须相同；两个已知且不同 => 反例
    rows=[s(1,'w1',{'客户':'南麓重工'}),s(2,'w2',{'客户':'江北造船'})]
    ce=find_counterexamples(rows,[],['客户'])
    assert len(ce)==1
    assert ce[0]['sample_a']['label']=='w1' and ce[0]['sample_b']['label']=='w2'
    assert ce[0]['attribute']=='客户'
    assert ce[0]['lhs']=={}
    status,_=evaluate([],['客户'],rows)
    assert status=='conflict'

def test_empty_lhs_null_is_unknown_not_equal_conflict():
    # 一个客户未知（None）不构成反例：空值视为未知，不参与判定
    rows=[s(1,'w1',{'客户':'南麓重工'}),s(2,'w2',{'客户':None})]
    assert find_counterexamples(rows,[],['客户'])==[]
    assert evaluate([],['客户'],rows)[0]=='adoptable'

def test_empty_lhs_all_known_equal_supported():
    rows=[s(1,'w1',{'客户':'南麓重工'}),s(2,'w2',{'客户':'南麓重工'}),s(3,'w3',{'客户':None})]
    assert find_counterexamples(rows,[],['客户'])==[]

def test_composite_lhs_requires_full_agreement():
    # 复合决定项 (委托号,检测项)→结果：只有两个键属性都相等才比较结果
    rows=[s(1,'w1-l',{'委托号':'W1','检测项':'拉伸','结果':'412'}),
          s(2,'w2-l',{'委托号':'W2','检测项':'拉伸','结果':'398'}),
          s(3,'w1-l-b',{'委托号':'W1','检测项':'拉伸','结果':'415'})]
    ce=find_counterexamples(rows,['委托号','检测项'],['结果'])
    assert len(ce)==1
    pair={ce[0]['sample_a']['id'],ce[0]['sample_b']['id']}
    assert pair=={1,3}
    assert ce[0]['attribute']=='结果'
    # 不同委托号、同检测项不构成同决定项，无反例
    assert find_counterexamples(rows[:2],['委托号','检测项'],['结果'])==[]

def test_null_in_lhs_means_unknown_never_matches():
    # 决定项含空值：即使另一条同值，也不视为相等
    rows=[s(1,'a',{'委托号':None,'检测项':'拉伸','结果':'x'}),
          s(2,'b',{'委托号':None,'检测项':'拉伸','结果':'y'})]
    assert lhs_agrees(rows[0]['values'],rows[1]['values'],['委托号']) is False
    assert find_counterexamples(rows,['委托号'],['结果'])==[]

def test_null_in_rhs_skipped():
    # RHS 一侧未知 => 不冲突；两侧已知且不同才冲突
    assert rhs_conflicts({'结果':None},{'结果':'x'},['结果']) is None
    assert rhs_conflicts({'结果':'x'},{'结果':None},['结果']) is None
    assert rhs_conflicts({'结果':'x'},{'结果':'y'},['结果'])=='结果'
    rows=[s(1,'a',{'委托号':'W1','结果':'x'}),s(2,'b',{'委托号':'W1','结果':None})]
    assert find_counterexamples(rows,['委托号'],['结果'])==[]

def test_composite_rhs_reports_first_diverging_attribute():
    rows=[s(1,'a',{'委托号':'W1','客户':'南麓','方法':'M1'}),
          s(2,'b',{'委托号':'W1','客户':'南麓','方法':'M2'})]
    ce=find_counterexamples(rows,['委托号'],['客户','方法'])
    assert ce[0]['attribute']=='方法'

def test_evaluate_empty_samples_stays_pending():
    assert evaluate(['委托号'],['客户'],[])==('pending',[])

def test_evaluate_clean_samples_adoptable():
    rows=[s(1,'a',{'委托号':'W1','客户':'南麓'}),s(2,'b',{'委托号':'W2','客户':'江北'})]
    assert evaluate(['委托号'],['客户'],rows)==('adoptable',[])

def test_counterexample_payload_is_locatable():
    rows=[s(7,'标签七',{'委托号':'W1','客户':'南麓'}),s(9,'标签九',{'委托号':'W1','客户':'江北'})]
    ce=find_counterexamples(rows,['委托号'],['客户'])[0]
    assert ce['sample_a']=={'id':7,'label':'标签七'}
    assert ce['sample_b']=={'id':9,'label':'标签九'}
    assert ce['values']=={'标签七':'南麓','标签九':'江北'}
