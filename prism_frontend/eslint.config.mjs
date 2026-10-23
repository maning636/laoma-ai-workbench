import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Keep only critical errors; everything else is handled via warnings and/or linting only changed files.
      "no-undef": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",

      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": "warn",
      "@next/next/no-img-element": "warn",

      // React Compiler 时代的规则（eslint-plugin-react-hooks v6 新增）：
      // set-state-in-effect / static-components / refs / use-memo。
      // 它们描述的是「React 编译器会怎么优化」，不是当下的运行错误，
      // 全仓一次性报出 80+ 条会把真错误淹没。按本文件开头「只保留关键错误，
      // 其余走 warning」的既定策略，先降为 warning，后续按模块逐步整改。
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/use-memo": "warn",
      // eslint-plugin-react-hooks v7 新增的同族规则：
      // purity（渲染期调用 Date.now / Math.random 等非纯函数）
      // preserve-manual-memoization（手写 memo 阻止编译器优化）。
      // 两者都是「编译器优化提示」，不是当下的运行错误，处置口径同上。
      "react-hooks/purity": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
    },
  },
  {
    // TypeScript / TSX: 未定义标识符由 tsc 自己报（tsc --noEmit 是独立硬门）。
    // ESLint 的 no-undef 不认识 DOM / NodeJS / TS 全局类型
    // （RequestInfo、RequestInit、NodeJS.Timeout、React 等），开着只会产生
    // 几百条误报，直接把真错误淹没，所以这里关掉。
    files: ["**/*.ts", "**/*.tsx"],
    rules: {
      "no-undef": "off",
    },
  },
  {
    // exhaustive-deps 债务清单（显式登记，逐条销账）
    //
    // 背景：react-hooks/exhaustive-deps 全仓有 30 条历史欠账，散落在 20 个文件里。
    // 这些文件都是「能跑、但依赖数组写得不完整」的既有代码。逐个改正则要动
    // useMemo 的数据流，风险远大于收益（前端行为改动 → 需要重跑 vitest 回归）。
    //
    // 处置：新代码保持硬门（见上方 rules 里的 "error"），
    // 只有下面这份**显式名单**里的文件降为 warn。
    // 新增文件不会自动进名单 —— 想豁免必须手工加进来，这就是「销账」的入口。
    // 名单里每一条都注明了欠的是什么，改完一条就从名单里删掉一行。
    files: [
      "src/app/page.tsx",                              // 搜索结果 memo 缺 matchesSearch 依赖
      "src/app/analytics/page.tsx",                    // 账号 id 归一函数未进依赖
      "src/app/analytics/videos/[[]platform[]]/page.tsx", // 视频归一/打分函数未进依赖
      "src/app/ai-agent/prompts/page.tsx",             // loadStructure / loadConfig 未进依赖
      "src/app/campaigns/page.tsx",                    // campaigns 逻辑表达式每次渲染新引用
      "src/app/campaigns/[[]id[]]/new/page.tsx",       // accounts / materials 逻辑表达式同上
      "src/app/tasks/page.tsx",                        // tasks 逻辑表达式同上
      "src/app/tasks/distribution/page.tsx",           // tasks 逻辑表达式同上
      "src/app/tools/page.tsx",                        // tools 逻辑表达式同上
      "src/app/settings/hooks/useSettingsActions.ts",  // apiBase 未进依赖
      "src/components/Aurora.tsx",                     // blend / colorStops 未进依赖
      "src/components/FadeContent.tsx",                // 动效参数未进依赖
      "src/components/GradientText.tsx",               // progress 未进依赖
      "src/components/ai-agent-chat.tsx",              // loadModels 未进依赖
      "src/components/image-editor/image-editor.tsx",  // cleanupFabric / commitHistory / resetEditor 未进依赖
      "src/components/material-editor-sheet.tsx",      // material 未进依赖
      "src/components/automation/execution-history.tsx", // fetchExecutions 未进依赖
      "src/components/automation/script-manager.tsx",  // fetchScripts 未进依赖
      "src/components/campaigns/create-campaign-dialog.tsx", // fetchAccounts / fetchMaterials 未进依赖
      "src/hooks/useAgentStream.ts",                   // handleEvent 未进依赖
    ],
    rules: {
      "react-hooks/exhaustive-deps": "warn",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "src/public/mockServiceWorker.js",
    "public/mockServiceWorker.js",
  ]),
]);

export default eslintConfig;
