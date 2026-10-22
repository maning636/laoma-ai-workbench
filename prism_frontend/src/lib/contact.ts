/**
 * 联系方式配置（线下人工充值模式）。
 *
 * 背景：线上支付已下线（网站备案 / ICP 许可证未落地，线上收款不具备合规前提），
 * 商业闭环改为「用户加产品方微信 → 人工收款 → 签发注册码 → 用户填入客户端」。
 * 这个模块同时承担**用户沟通**与**拉客**两个作用：
 *   - 用户侧：遇到问题、想加购积分、想开通功能，都从这里进微信群；
 *   - 运营侧：群是沉淀用户、复购与答疑的主阵地。
 *
 * 配置来源（构建时注入，按优先级）：
 *   1. `NEXT_PUBLIC_CONTACT_WECHAT_ID`   —— 个人微信号
 *   2. `NEXT_PUBLIC_CONTACT_GROUP_QR`   —— 微信群二维码图片路径（相对 `public/`）
 *   3. `NEXT_PUBLIC_CONTACT_GROUP_URL`  —— 群链接（企业微信/群聊邀请链接，可空）
 *   4. `NEXT_PUBLIC_CONTACT_NOTICE`     —— 附加说明文案
 *
 * ⚠️ 刻意**不写死**具体微信号：那是运营信息，发布时统一用环境变量注入，
 * 避免改一次微信号就要改代码、重新打包。同时默认值是空字符串 ——
 * 没配就显示「未配置」提示，而不是露出一个错误的微信号。
 */

/** 个人微信号（空字符串 = 尚未配置） */
export const CONTACT_WECHAT_ID: string =
  process.env.NEXT_PUBLIC_CONTACT_WECHAT_ID ?? ""

/**
 * 微信群二维码图片路径（相对 `public/` 根）。
 *
 * 默认值指向**仓库内置的占位图** `public/wechat-group-qr.png`，
 * 所以运营最省事的路径是：直接用真实群二维码覆盖那个文件，不必改环境变量。
 * 真图没到位时占位图会明确写着「待替换」，不会让人误当成群码。
 */
export const CONTACT_GROUP_QR: string =
  process.env.NEXT_PUBLIC_CONTACT_GROUP_QR ?? "/wechat-group-qr.png"
/** 群链接（可空；为空时只展示二维码） */
export const CONTACT_GROUP_URL: string =
  process.env.NEXT_PUBLIC_CONTACT_GROUP_URL ?? ""

/** 附加说明（可空） */
export const CONTACT_NOTICE: string =
  process.env.NEXT_PUBLIC_CONTACT_NOTICE ?? ""

/** 是否配置了可用的联系方式（用于 UI 决定展示哪种形态） */
export const hasContactWechat = (): boolean => CONTACT_WECHAT_ID.trim().length > 0

/**
 * 是否配置了群入口（链接或二维码）。
 *
 * 注意：二维码路径有内置默认值，所以这个判断**通常恒为 true** ——
 * 群入口永远存在，只是图可能还没换成真的。
 * 真图缺失时 `contact-card.tsx` 会用 `onError` 降级成文字提示，不出破图。
 */
export const hasContactGroup = (): boolean =>
  CONTACT_GROUP_URL.trim().length > 0 || CONTACT_GROUP_QR.trim().length > 0

/**
 * 统一的充值引导文案。
 *
 * 线上支付下线后，**所有**「付费 / 升级 / 充值」的引导都指向这里，
 * 口径只有一份，避免各处各写一套导致用户看到互相矛盾的说法。
 */
export const RECHARGE_GUIDE: string =
  "充值与开通请通过微信联系产品方人工办理（线上支付暂未开放）。加群可获取使用支持、新版本通知与优惠。"

/** 引导按钮/链接的目标（设置页锚点） */
export const CONTACT_ANCHOR = "/settings#contact"
