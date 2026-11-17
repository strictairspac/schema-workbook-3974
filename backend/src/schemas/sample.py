from typing import Any,Optional,Literal
from pydantic import BaseModel,Field,field_validator
class SampleInput(BaseModel):
    relation_id:int=Field(gt=0)
    label:str=Field(min_length=1,max_length=120)
    values:dict[str,Optional[Any]]=Field(default_factory=dict)
    @field_validator('label')
    @classmethod
    def label_clean(cls,v):
        v=v.strip()
        if not v:raise ValueError('样本定位标签不能为空')
        return v
class SampleUpdate(BaseModel):
    label:str=Field(min_length=1,max_length=120)
    values:dict[str,Optional[Any]]=Field(default_factory=dict)
    @field_validator('label')
    @classmethod
    def label_clean(cls,v):
        v=v.strip()
        if not v:raise ValueError('样本定位标签不能为空')
        return v
class BatchOp(BaseModel):
    op:Literal['add','update','remove']
    sample_id:Optional[int]=Field(default=None,gt=0)
    label:Optional[str]=Field(default=None,max_length=120)
    values:Optional[dict[str,Optional[Any]]]=None
class BatchInput(BaseModel):
    operations:list[BatchOp]=Field(min_length=1,max_length=200)
