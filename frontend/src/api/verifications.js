import {api} from './client.js';
export const verificationsApi={
  list:relationId=>api('/verifications'+(relationId?('?relation_id='+relationId):'')),
  verify:id=>api('/dependencies/'+id+'/verify','POST'),
  adopt:id=>api('/dependencies/'+id+'/adopt','POST')
};
