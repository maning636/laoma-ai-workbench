import { redirect } from "next/navigation"

/**
 * 趋势分析的实现在 /analytics 页面的「趋势」区块内（可切换播放/点赞/评论/收藏指标）。
 * 这里保留独立路径，侧边栏「趋势分析」点进来直接定位到趋势图表。
 */
export default function TrendsPage() {
    redirect("/analytics#trend")
}
