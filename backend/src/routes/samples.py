from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.utils.security import current,writer
from src.schemas.sample import SampleInput,SampleUpdate,BatchInput
from src.services import samples as service
router=APIRouter()
@router.get('/relations/{relation_id}/samples')
def listing(relation_id:int,db=Depends(db_session),user=Depends(current)):return service.listing(db,relation_id)
@router.post('/samples',status_code=201)
def create(data:SampleInput,db=Depends(db_session),user=Depends(writer)):return service.create(db,data,user)
@router.put('/samples/{ident}')
def update(ident:int,data:SampleUpdate,db=Depends(db_session),user=Depends(writer)):return service.update(db,ident,data,user)
@router.delete('/samples/{ident}')
def remove(ident:int,db=Depends(db_session),user=Depends(writer)):return service.remove(db,ident,user)
@router.post('/relations/{relation_id}/samples/batch')
def batch(relation_id:int,data:BatchInput,db=Depends(db_session),user=Depends(writer)):return service.batch_apply(db,relation_id,data.operations,user)
