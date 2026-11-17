from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.utils.security import current,writer
from src.services import verification as service
router=APIRouter()
@router.get('/verifications')
def overview(relation_id:int|None=None,db=Depends(db_session),user=Depends(current)):return service.status_overview(db,relation_id)
@router.post('/dependencies/{ident}/verify')
def verify(ident:int,db=Depends(db_session),user=Depends(writer)):return service.verify(db,ident,user)
@router.post('/dependencies/{ident}/adopt')
def adopt(ident:int,db=Depends(db_session),user=Depends(writer)):return service.adopt(db,ident,user)
