"use client"

import { Suspense, useEffect, useState } from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import {
  ArrowLeft,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Mail,
  ShieldCheck,
  User,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/use-toast"
import { CloudAuthError, cloudAuth } from "@/lib/cloud-auth"
import { cloudBaseUrl } from "@/lib/env"

function LoginCard({ mode: initialMode }: { mode: "login" | "register" }) {
  const { toast } = useToast()
  const router = useRouter()
  const searchParams = useSearchParams()
  const redirect = searchParams?.get("redirect") || "/"

  const [mode, setMode] = useState<"login" | "register">(initialMode)
  const [username, setUsername] = useState("")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [showPassword, setShowPassword] = useState(false)
  const [busy, setBusy] = useState(false)
  const [serverNote, setServerNote] = useState<string | null>(null)

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault()
    if (busy) return
    setBusy(true)
    setServerNote(null)
    try {
      if (mode === "login") {
        if (!username.trim() || !password) throw new Error("请输入用户名和密码")
        await cloudAuth.login({ username: username.trim(), password })
        toast({ title: "登录成功", description: "已保存登录状态,正在跳转…" })
        router.replace(redirect)
        router.refresh()
      } else {
        if (!username.trim() || !email.trim() || password.length < 8) {
          throw new Error("请完善用户名、邮箱和密码(至少 8 位)")
        }
        const user = await cloudAuth.register({
          username: username.trim(),
          email: email.trim(),
          password,
        })
        toast({ title: "注册成功", description: `账号 ${user.username} 已创建,正在登录…` })
        await cloudAuth.login({ username: user.username, password })
        router.replace(redirect)
        router.refresh()
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      const cloudErr = err instanceof CloudAuthError ? err : null
      const friendly =
        cloudErr?.code === "network"
          ? `云端不可达(当前配置:${cloudBaseUrl || "未设置"})`
          : cloudErr?.code === "unauthorized"
            ? "用户名或密码错误"
            : msg
      setServerNote(friendly)
      toast({
        variant: "destructive",
        title: mode === "login" ? "登录失败" : "注册失败",
        description: friendly,
      })
    } finally {
      setBusy(false)
    }
  }

  const passwordField = (
    <div className="space-y-1.5">
      <Label htmlFor="password">密码</Label>
      <div className="relative">
        <KeyRound className="absolute left-2.5 top-2.5 h-4 w-4 text-foreground/50" />
        <Input
          id="password"
          type={showPassword ? "text" : "password"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="pl-8 pr-9"
          autoComplete="current-password"
        />
        <button
          type="button"
          className="absolute right-2 top-2 rounded-md p-1 text-foreground/60 hover:bg-popover"
          onClick={() => setShowPassword((v) => !v)}
          aria-label="切换密码可见"
        >
          {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
    </div>
  )

  return (
    <div className="mx-auto w-full max-w-[440px]">
      <Card className="border-border/70 bg-card shadow-[0_0_0_1px_rgba(255,255,255,0.06)]">
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-popover p-2 text-foreground">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-foreground">云端账号</CardTitle>
              <CardDescription className="text-muted-foreground">
                订阅版账号 · 登录后使用云端 AI 与高级 Prompt
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit}>
            <Tabs
              value={mode}
              onValueChange={(v) => setMode(v as "login" | "register")}
              className="w-full"
            >
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="login">登录</TabsTrigger>
                <TabsTrigger value="register">注册</TabsTrigger>
              </TabsList>
              <TabsContent value="login" className="mt-4 space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="username">用户名</Label>
                  <div className="relative">
                    <User className="absolute left-2.5 top-2.5 h-4 w-4 text-foreground/50" />
                    <Input
                      id="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="pl-8"
                      autoComplete="username"
                      placeholder="your_username"
                    />
                  </div>
                </div>
                {passwordField}
              </TabsContent>
              <TabsContent value="register" className="mt-4 space-y-3">
                <div className="space-y-1.5">
                  <Label htmlFor="username-r">用户名</Label>
                  <div className="relative">
                    <User className="absolute left-2.5 top-2.5 h-4 w-4 text-foreground/50" />
                    <Input
                      id="username-r"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className="pl-8"
                      autoComplete="username"
                      placeholder="字母/数字/下划线,2-32 字符"
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="email-r">邮箱</Label>
                  <div className="relative">
                    <Mail className="absolute left-2.5 top-2.5 h-4 w-4 text-foreground/50" />
                    <Input
                      id="email-r"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="pl-8"
                      autoComplete="email"
                      placeholder="name@example.com"
                    />
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="password-r">密码(≥ 8 位)</Label>
                  <div className="relative">
                    <KeyRound className="absolute left-2.5 top-2.5 h-4 w-4 text-foreground/50" />
                    <Input
                      id="password-r"
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="pl-8 pr-9"
                      autoComplete="new-password"
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-2 rounded-md p-1 text-foreground/60 hover:bg-popover"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label="切换密码可见"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </TabsContent>
            </Tabs>
            {serverNote ? <p className="mt-3 text-xs text-red-400">{serverNote}</p> : null}
            <Button
              type="submit"
              disabled={busy}
              className="mt-4 w-full border-border/70 bg-popover text-foreground hover:bg-popover/80"
            >
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {mode === "login" ? "登录中…" : "注册中…"}
                </>
              ) : mode === "login" ? (
                "登录"
              ) : (
                "注册并登录"
              )}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="justify-center">
          <Link
            href={redirect}
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回工作台(以离线模式继续)
          </Link>
        </CardFooter>
      </Card>
    </div>
  )
}

function LoginInner() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    let mounted = true
    ;(async () => {
      const tokenPair = await cloudAuth.getCurrentTokenPair()
      if (mounted && tokenPair) {
        router.replace(searchParams?.get("redirect") || "/")
        return
      }
      if (mounted) setChecked(true)
    })()
    return () => {
      mounted = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!checked) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-foreground/50" />
      </div>
    )
  }

  return <LoginCard mode="login" />
}

export default function LoginPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-12 md:px-6">
      <Suspense
        fallback={
          <div className="flex min-h-[40vh] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-foreground/50" />
          </div>
        }
      >
        <LoginInner />
      </Suspense>
    </div>
  )
}
