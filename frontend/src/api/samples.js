import {api} from './client.js';
export const samplesApi={
  list:relationId=>api('/relations/'+relationId+'/samples'),
  create:data=>api('/samples','POST',data),
  update:(id,data)=>api('/samples/'+id,'PUT',data),
  remove:id=>api('/samples/'+id,'DELETE'),
  batch:(relationId,operations)=>api('/relations/'+relationId+'/samples/batch','POST',{operations})
};
