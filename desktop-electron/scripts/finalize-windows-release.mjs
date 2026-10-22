import { createHash } from 'node:crypto';
import { readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { basename, join, resolve } from 'node:path';

/**
 * Windows 发布收尾：按**磁盘真实文件名**重写 latest.yml。
 *
 * ## 为什么需要这一步
 *
 * electron-builder 生成 latest.yml 时,`path` / `files[].url` 用的是
 * `computeSafeArtifactNameIfNeeded(installerFilename, generateGitHubInstallerName)`:
 *
 *   - 安装包名**全 ASCII** → `isSafeGithubName` 通过 → 直接用真实文件名 ✅
 *   - 安装包名**含中文** → 不安全 → 回退到 `generateGitHubInstallerName()`,
 *     即 `${name}-setup-${version}.exe`(纯 ASCII)→ **与磁盘上的真实文件名对不上** ❌
 *
 * 1.1.3 就踩过这个坑:磁盘上是 `老马AI工作台-1.1.3-setup.exe`,
 * latest.yml 却写 `laoma-ai-workbench-setup-1.1.3.exe` → 自动更新链路直接失效。
 *
 * 现在 `build.artifactName` 已改为 ASCII(`LaomaAI-${version}-setup.${ext}`),
 * 根源已断。但**仍保留本脚本作为兜底**:它以磁盘为准重写 latest.yml,
 * 任何时候「文件名 / 大小 / sha512」都以真实文件为准,不会与产物漂移。
 *
 * ## 依赖说明
 *
 * 早期版本这里会 `require('app-builder-lib/out/targets/blockmap/blockmap')`
 * 重新生成 blockmap —— 但 **electron-builder 24.13.3 里没有这个模块路径**
 * (blockmap 由 `targets/differentialUpdateInfoBuilder.js` 内部实现),
 * 于是该脚本一跑就 `MODULE_NOT_FOUND`,因此从没被接进过构建流程。
 *
 * 现在改为:**校验 electron-builder 已经生成的 .blockmap 存在且非空**,
 * 不再自己重算 blockmap(electron-builder 生成的就是对的)。
 *
 * 用法：node scripts/finalize-windows-release.mjs <release-dir> <semver>
 * 例：node scripts/finalize-windows-release.mjs dist-out/v4 1.1.4
 */

const MIN_BLOCKMAP_BYTES = 1024;

async function findInstaller(releaseDir) {
  const entries = await readdir(releaseDir, { withFileTypes: true });
  const installers = entries
    .filter((entry) => entry.isFile() && entry.name.toLowerCase().endsWith('.exe'))
    .map((entry) => join(releaseDir, entry.name));
  if (installers.length !== 1) {
    throw new Error(
      `Expected exactly one Windows installer in ${releaseDir}, found ${installers.length}. ` +
        `（目录里残留旧安装包会导致本脚本拒绝写入 latest.yml,请先清理）`
    );
  }
  return installers[0];
}

async function sha512(file) {
  return createHash('sha512').update(await readFile(file)).digest('base64');
}

async function finalizeRelease(releaseDir, version) {
  const installer = await findInstaller(releaseDir);
  const installerName = basename(installer);
  const blockmap = `${installer}.blockmap`;

  // blockmap 必须与安装包同目录、同名（差分更新必需）
  let blockmapInfo;
  try {
    blockmapInfo = await stat(blockmap);
  } catch {
    throw new Error(`blockmap 缺失：${blockmapName(installerName)}`);
  }
  if (!blockmapInfo.isFile() || blockmapInfo.size < MIN_BLOCKMAP_BYTES) {
    throw new Error(
      `blockmap 异常：${blockmapName(installerName)}（size=${blockmapInfo.size}）`
    );
  }

  const fileStat = await stat(installer);
  const digest = await sha512(installer);

  const metadata = [
    `version: ${version}`,
    'files:',
    `  - url: ${JSON.stringify(installerName)}`,
    `    sha512: ${digest}`,
    `    size: ${fileStat.size}`,
    `path: ${JSON.stringify(installerName)}`,
    `sha512: ${digest}`,
    `releaseDate: ${JSON.stringify(new Date().toISOString())}`,
    ''
  ].join('\n');
  await writeFile(join(releaseDir, 'latest.yml'), metadata, 'utf8');
  return { installer, blockmap, size: fileStat.size, sha512: digest };
}

function blockmapName(installerName) {
  return `${installerName}.blockmap`;
}

const [releaseDirArg, version] = process.argv.slice(2);
if (!releaseDirArg || !/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(version ?? '')) {
  throw new Error('Usage: finalize-windows-release.mjs <release-dir> <semver>');
}

const result = await finalizeRelease(resolve(releaseDirArg), version);
console.log(
  `Finalized release metadata for ${basename(result.installer)} ` +
    `(size=${result.size}, latest.yml rewritten from disk truth).`
);
