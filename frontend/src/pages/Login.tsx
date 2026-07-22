import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { loginAndStoreToken, register } from '../api/auth';
import type { CurrentUser } from '../types';

export default function LoginPage({
  onAuthenticated,
}: {
  onAuthenticated: (user: CurrentUser) => void;
}) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password || loading) return;

    setLoading(true);
    setError(null);
    try {
      if (mode === 'register') {
        await register(username.trim(), password);
      }
      const user = await loginAndStoreToken(username.trim(), password);
      onAuthenticated(user);
      navigate('/', { replace: true });
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : '认证失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#070d16] px-5 py-10 text-slate-100">
      <section className="grid min-h-[680px] w-full max-w-6xl overflow-hidden rounded-[28px] border border-white/10 bg-[#0b1420] shadow-2xl shadow-black/30 lg:grid-cols-[1fr_430px]">
        <div className="relative overflow-hidden border-b border-white/10 p-8 lg:border-b-0 lg:border-r">
          <div className="absolute inset-x-0 top-0 h-1 bg-sky-500" />
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-300">工业设备智能运维 AI Agent 平台</p>
          <h1 className="mt-5 max-w-2xl text-4xl font-semibold leading-tight text-white">
            工业设备智能诊断与运维控制中心
          </h1>
          <p className="mt-5 max-w-2xl text-sm leading-7 text-slate-400">
            面向企业设备运维场景，融合设备数据、维修知识、Agent 工作流和大模型推理，
            帮助团队完成风险发现、故障诊断、维修建议和经验沉淀。
          </p>

          <div className="mt-10 grid gap-4 md:grid-cols-3">
            {[
              ['设备感知', '读取设备状态、运行参数与报警记录'],
              ['知识增强', '检索维修手册和历史案例作为依据'],
              ['可信诊断', '输出可追溯的结构化诊断报告'],
            ].map(([title, detail]) => (
              <div key={title} className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                <div className="text-sm font-semibold text-white">{title}</div>
                <div className="mt-2 text-xs leading-5 text-slate-400">{detail}</div>
              </div>
            ))}
          </div>

          <div className="mt-10 rounded-2xl border border-sky-300/20 bg-sky-300/10 p-5">
            <div className="text-sm font-semibold text-sky-100">权限边界</div>
            <div className="mt-3 grid gap-3 text-xs leading-5 text-slate-300">
              <p>User：查看设备画像、风险事件、诊断报告和维修闭环。</p>
              <p>Admin：维护知识库、执行诊断、管理系统和查看全量报告。</p>
            </div>
          </div>
        </div>

        <form onSubmit={submit} className="grid content-center gap-4 p-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-sky-300">
              {mode === 'login' ? '登录平台' : '注册账号'}
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-white">
              {mode === 'login' ? '欢迎回来' : '创建只读账号'}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              {mode === 'login'
                ? '请输入账号密码进入工业 AI 运维控制台。'
                : '公开注册默认创建 User 账号，管理员权限由初始化脚本或系统管理员分配。'}
            </p>
          </div>

          <label className="grid gap-1 text-sm font-medium text-slate-300">
            用户名
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="field-control h-11"
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </label>

          <label className="grid gap-1 text-sm font-medium text-slate-300">
            密码
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              className="field-control h-11"
              placeholder="请输入密码"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </label>

          {error ? (
            <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
              {error}
            </div>
          ) : null}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="primary-button"
          >
            {loading ? '处理中...' : mode === 'login' ? '登录' : '注册并登录'}
          </button>

          <button
            type="button"
            disabled={loading}
            onClick={() => {
              setError(null);
              setMode((current) => (current === 'login' ? 'register' : 'login'));
            }}
            className="control-button"
          >
            {mode === 'login' ? '没有账号？注册 User' : '已有账号？返回登录'}
          </button>
        </form>
      </section>
    </main>
  );
}
