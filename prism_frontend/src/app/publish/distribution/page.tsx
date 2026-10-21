import { redirect } from "next/navigation"

/**
 * 扫码派发管理的实现已统一到 /tasks/distribution。
 *
 * 这里保留旧路径做兼容跳转，避免历史链接 / 收藏直接 404。
 * 注意：早期版本这里和 /tasks/distribution 各存了一份完整实现
 * （page + components/task-drawer + publish-otp，共 3 个文件完全重复），
 * 现已收敛为单份实现，见 docs/dev-reports/2026-10-21-e2e-link-audit.md。
 */
export default function PublishDistributionRedirect() {
    redirect("/tasks/distribution")
}
