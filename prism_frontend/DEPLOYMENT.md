
# Deployment Steps

This document outlines the steps to deploy this Next.js application.

## Prerequisites

Before you begin, ensure you have the following installed:
- [Node.js](https://nodejs.org/) (version 18.x or later recommended)
- [npm](https://www.npmjs.com/) or [yarn](https://yarnpkg.com/)

## Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    ```

2.  **Navigate to the project directory:**
    ```bash
    cd prism_frontend
    ```

3.  **Install dependencies:**
    ```bash
    npm install
    ```

## Development Server

To run the application in development mode with hot-reloading, use the following command:

```bash
npm run dev
```

The application will be available at `http://localhost:3000` (or another port if 3000 is in use).

## Building for Production

To create an optimized production build of the application, run:

```bash
npm run build
```

This command will generate a `.next` folder containing the production-ready application.

## Running in Production

After building the application, you can start the production server with:

```bash
npm start
```

The application will be served from the `.next` folder and will be available at `http://localhost:3000`.

## Environment Variables

If your application requires environment variables, create a `.env.local` file in the root of the project and add them there. For example:

```
NEXT_PUBLIC_API_URL=https://api.example.com
```

These variables will be loaded automatically by Next.js.

## 联系方式配置（线下人工充值模式）

线上支付已下线（备案 / ICP 许可证未落地），商业闭环改为「加产品方微信 → 人工收款 →
签发注册码 → 用户填入客户端」。以下变量控制设置页「联系我们」卡片的展示：

| 变量 | 必填 | 说明 |
|---|---|---|
| `NEXT_PUBLIC_CONTACT_WECHAT_ID` | **是** | 产品方个人微信号。不配则卡片显示「微信号尚未配置」提示 |
| `NEXT_PUBLIC_CONTACT_GROUP_QR` | 否 | 微信群二维码图片路径（相对 `public/`）。默认 `/wechat-group-qr.png` |
| `NEXT_PUBLIC_CONTACT_GROUP_URL` | 否 | 群邀请链接（企业微信 / 群聊链接）。不配则只展示二维码 |
| `NEXT_PUBLIC_CONTACT_NOTICE` | 否 | 附加说明文案，显示在卡片底部 |

**群二维码默认不需要配环境变量**：仓库内置了占位图 `public/wechat-group-qr.png`
（画面上写着「待替换」）。运营拿到真实群二维码后**直接覆盖这个文件**即可，
不必改代码、不必重新配置环境变量。

前端所有「升级 / 续费 / 充值」入口统一指向 `/settings#contact`，
文案为 Community「加微信开通」、Pro「续费联系」。

> 注意：这些是 `NEXT_PUBLIC_*` 变量，会被打进浏览器 bundle，构建后**再改必须重新构建**。
> 微信号是运营信息，不要写死在源码里。
