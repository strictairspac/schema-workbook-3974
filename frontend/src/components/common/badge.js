import {RUN_STATES,VERIFY_STATES} from '../../constants/enums.js';
import {esc} from '../../utils/html.js';
export const badge=value=>`<span class="badge ${esc(value)}">${esc(RUN_STATES[value]||value)}</span>`;
export const verifyBadge=value=>`<span class="badge verify ${esc(value)}">${esc(VERIFY_STATES[value]||value)}</span>`;
