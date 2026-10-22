/**
 * 联系方式配置（线下人工充值模式）。
 *
 * 背景：线上支付已下线（网站备案 / ICP 许可证未落地，线上收款不具备合规前提），
 * 商业闭环改为「用户加产品方微信 → 人工收款 → 签发注册码 → 用户填入客户端」。
 * 这个模块同时承担**用户沟通**与**拉客**两个作用：
 *   - 用户侧：遇到问题、想加购积分、想开通功能，都从这里进微信；
 *   - 运营侧：微信是沉淀用户、复购与答疑的主阵地。
 *
 * 加微信的流程与官网（https://maning789link.top）**完全一致**：
 *   扫个人微信码 → 备注来意 → 产品方把用户拉进对应微信群。
 * 所以这里**没有单独的「群二维码」**——官网上也没有，群是产品方按来意手动拉的。
 * 群邀请链接（`NEXT_PUBLIC_CONTACT_GROUP_URL`）留作可选口子，以后有固定群链接时再填。
 *
 * 配置来源（构建时注入，按优先级）：
 *   1. `NEXT_PUBLIC_CONTACT_WECHAT_ID`   —— 个人微信号（可搜索的名字）
 *   2. `NEXT_PUBLIC_CONTACT_QR`           —— 微信二维码图片路径（相对 `public/`）
 *   3. `NEXT_PUBLIC_CONTACT_GROUP_URL`    —— 群邀请链接（可空）
 *   4. `NEXT_PUBLIC_CONTACT_NOTICE`       —— 附加说明文案
 *
 * ⚠️ 刻意**不写死**具体微信号：那是运营信息，发布时统一用环境变量注入，
 * 避免改一次微信号就要改代码、重新打包。默认值是空字符串 ——
 * 没配就显示「未配置」提示，而不是露出一个错误的微信号。
 */

/** 个人微信号（空字符串 = 尚未配置） */
export const CONTACT_WECHAT_ID: string =
  process.env.NEXT_PUBLIC_CONTACT_WECHAT_ID ?? ""

/**
 * 微信二维码图片路径（相对 `public/` 根）。
 *
 * 默认值指向**仓库内置的二维码图** `public/wechat-contact-qr.png`，
 * 所以运营最省事的路径是：直接用新的二维码覆盖那个文件，不必改环境变量。
 * 图片真的缺失时，`contact-card.tsx` 会用 `onError` 降级成文字提示，不出破图。
 */
export const CONTACT_QR: string =
  process.env.NEXT_PUBLIC_CONTACT_QR ?? "/wechat-contact-qr.png"

/** 群邀请链接（可空；为空时只展示二维码） */
export const CONTACT_GROUP_URL: string =
  process.env.NEXT_PUBLIC_CONTACT_GROUP_URL ?? ""

/** 附加说明（可空） */
export const CONTACT_NOTICE: string =
  process.env.NEXT_PUBLIC_CONTACT_NOTICE ?? ""

/** 是否配置了可用的联系方式（用于 UI 决定展示哪种形态） */
export const hasContactWechat = (): boolean => CONTACT_WECHAT_ID.trim().length > 0

/**
 * 是否配置了二维码入口。
 *
 * 注意：二维码路径有内置默认值，所以这个判断**通常恒为 true** ——
 * 入口永远存在，只是图可能还没换成真的。
 * 真图缺失时 `contact-card.tsx` 会用 `onError` 降级成文字提示，不出破图。
 */
export const hasContactQr = (): boolean => CONTACT_QR.trim().length > 0

/**
 * 统一的充值引导文案。
 *
 * 线上支付下线后，**所有**「付费 / 升级 / 充值」的引导都指向这里，
 * 口径只有一份，避免各处各写一套导致用户看到互相矛盾的说法。
 */
export const RECHARGE_GUIDE: string =
  "充值与开通请通过微信联系产品方人工办理（线上支付暂未开放）。加微信可获取使用支持、新版本通知与优惠。"

/** 引导按钮/链接的目标（设置页锚点） */
export const CONTACT_ANCHOR = "/settings#contact"
