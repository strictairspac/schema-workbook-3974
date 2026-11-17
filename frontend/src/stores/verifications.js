import {verificationsApi} from '../api/verifications.js';
export const verificationsStore={items:[],async refresh(relationId){this.items=await verificationsApi.list(relationId);return this.items;}};
