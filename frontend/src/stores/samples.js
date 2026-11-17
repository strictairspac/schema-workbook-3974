import {samplesApi} from '../api/samples.js';
export const samplesStore={items:[],relationId:null,async refresh(relationId){if(relationId!==undefined)this.relationId=relationId;this.items=await samplesApi.list(this.relationId);return this.items;}};
