export const ROLES={admin:'管理员',operator:'操作员',viewer:'观察员'};
export const RUN_STATES={queued:'排队中',running:'执行中',completed:'已完成',failed:'失败'};
export const VERIFY_STATES={pending:'待核验',adoptable:'可采纳',conflict:'冲突',adopted:'已采纳'};
export const VERIFY_HINT={pending:'尚无核验结论或样本为空，先补充委托样本',adoptable:'当前样本无反例支持，可采纳为正式依赖',conflict:'样本存在可定位反例，更正后重新核验',adopted:'已采纳为正式依赖，约束后续样本写入'};
