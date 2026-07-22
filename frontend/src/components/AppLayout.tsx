import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { KeyboardEvent, useMemo, useState } from 'react';
import { clearAuthToken } from '../api';
import type { CurrentUser, UserRole } from '../types';
import { resolvePrimaryRole } from '../utils/permissions';

interface NavItem {
  to: string;
  label: string;
  description: string;
  section?: string;
}

const menuByRole: Record<UserRole, NavItem[]> = {
  user: [
    { to: '/', label: '运营总览', description: '设备与风险概览', section: '运维工作台' },
    { to: '/devices/DEV-003', label: '设备中心', description: '设备画像与长期记忆', section: '运维工作台' },
    { to: '/evaluation', label: '智能报告', description: '历史诊断与风险报告', section: '分析结果' },
  ],
  admin: [
    { to: '/', label: '运营总览', description: '设备、风险与服务态势', section: '运营视图' },
    { to: '/devices/DEV-003', label: '设备中心', description: '设备画像与长期记忆', section: '运营视图' },
    { to: '/evaluation', label: '智能报告', description: '历史诊断与风险报告', section: '运营视图' },
    { to: '/diagnosis', label: '智能诊断', description: '设备诊断与全局风险分析', section: 'AI 能力' },
    { to: '/knowledge', label: '知识中心', description: '维修资料与故障知识', section: 'AI 能力' },
    { to: '/maintenance', label: '维修闭环', description: '现场处理与经验沉淀', section: 'AI 能力' },
    { to: '/settings', label: '系统管理', description: '权限与运行配置', section: '治理' },
  ],
};

export default function AppLayout({
  currentUser,
  onLogout,
}: {
  currentUser: CurrentUser | null;
  onLogout: () => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const activeRole = resolvePrimaryRole(currentUser);
  const navItems = menuByRole[activeRole];
  const isUser = activeRole === 'user';
  const navSections = groupNavItems(navItems);
  const [searchQuery, setSearchQuery] = useState('');
  const searchActions = useMemo(() => buildSearchActions(searchQuery, navItems), [searchQuery, navItems]);

  function runSearch(target?: string) {
    const next = target ?? searchActions[0]?.to;
    if (!next) return;
    navigate(next);
    setSearchQuery('');
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      runSearch();
    }
    if (event.key === 'Escape') {
      setSearchQuery('');
    }
  }

  return (
    <div className="min-h-screen bg-[#070d16] text-slate-100">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-72 border-r border-white/10 bg-[#08111d]/95 text-white shadow-2xl shadow-black/30 backdrop-blur-xl lg:flex lg:flex-col">
        <div className="border-b border-white/10 px-6 py-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl border border-sky-400/30 bg-sky-400/10 text-sm font-black text-sky-300">
              AI
            </div>
            <div>
              <p className="text-[11px] font-semibold tracking-[0.28em] text-cyan-300">INDUSTRIAL AI</p>
              <h1 className="mt-1 text-lg font-semibold leading-6">工业设备智能运维 AI Agent 平台</h1>
            </div>
          </div>
          <p className="mt-4 text-xs leading-5 text-slate-400">
            面向设备运维、风险监控、知识治理和智能诊断的企业级控制中心。
          </p>
        </div>

        <nav className="grid gap-6 overflow-y-auto p-4">
          {navSections.map(([section, items]) => (
            <div key={section}>
              <div className="mb-2 px-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                {section}
              </div>
              <div className="grid gap-1.5">
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === '/'}
                    className={({ isActive }) =>
                      `group relative overflow-hidden rounded-2xl px-4 py-3 transition ${
                        isActive
                          ? 'border border-sky-400/25 bg-sky-500/16 text-white shadow-lg shadow-sky-950/20'
                          : 'border border-transparent text-slate-400 hover:border-white/10 hover:bg-white/[0.06] hover:text-slate-100'
                      }`
                    }
                  >
                    <span className="absolute inset-y-3 left-0 w-1 rounded-r-full bg-sky-400 opacity-0 transition group-[.active]:opacity-100" />
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-sm font-semibold">{item.label}</div>
                      <span className="h-1.5 w-1.5 rounded-full bg-cyan-300 opacity-0 transition group-hover:opacity-100" />
                    </div>
                    <div className="mt-1 text-xs leading-5 opacity-75">{item.description}</div>
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="mt-auto border-t border-white/10 p-4">
          <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4">
            <div className="text-xs text-slate-400">当前角色</div>
            <div className="mt-1 text-sm font-semibold">{roleLabel(activeRole)}</div>
            <div className="mt-2 text-xs leading-5 text-slate-400">{roleDescription(activeRole)}</div>
          </div>
        </div>
      </aside>

      <div className="lg:pl-72">
        <header className="sticky top-0 z-20 border-b border-white/10 bg-[#08111d]/82 backdrop-blur-xl">
          <div className="flex min-h-16 flex-col gap-3 px-5 py-3 lg:flex-row lg:items-center lg:justify-between lg:px-8">
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <span>{activePageLabel(navItems, location.pathname)}</span>
                <span className="text-slate-600">/</span>
                <span>Industrial AI Control Center</span>
              </div>
              <p className="mt-1 text-sm text-slate-400">
                {isUser
                  ? '查看设备运行状态、AI 发现的风险事件、诊断报告和现场处理结果。'
                  : '接入设备数据、维修资料、长期上下文和智能诊断能力，支撑企业运维决策。'}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="relative hidden xl:block">
                <input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  onKeyDown={handleSearchKeyDown}
                  className="h-9 w-[320px] rounded-xl border border-white/10 bg-white/[0.04] px-3 text-xs text-slate-200 outline-none transition placeholder:text-slate-500 focus:border-sky-400/40 focus:bg-white/[0.07]"
                  placeholder="输入 DEV-005、E404、报告、知识..."
                  aria-label="全局快速跳转"
                />
                {searchQuery.trim() ? (
                  <div className="absolute right-0 top-11 z-40 w-[320px] overflow-hidden rounded-2xl border border-white/10 bg-[#0b1420] p-2 shadow-2xl shadow-black/40">
                    {searchActions.length ? (
                      searchActions.map((item) => (
                        <button
                          key={`${item.to}-${item.label}`}
                          type="button"
                          onClick={() => runSearch(item.to)}
                          className="grid w-full rounded-xl px-3 py-2 text-left transition hover:bg-sky-400/10"
                        >
                          <span className="text-xs font-semibold text-slate-100">{item.label}</span>
                          <span className="mt-0.5 text-[11px] text-slate-500">{item.description}</span>
                        </button>
                      ))
                    ) : (
                      <div className="px-3 py-3 text-xs leading-5 text-slate-500">
                        未找到可跳转入口。可输入设备编号 DEV-003，或输入报告、知识、诊断。
                      </div>
                    )}
                  </div>
                ) : null}
              </div>
              <div className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1.5 text-xs font-semibold text-slate-200">
                {currentUser?.username ?? '未登录'} · {roleLabel(activeRole)}
              </div>
              <div className="hidden max-w-[360px] truncate rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1.5 text-xs font-semibold text-cyan-200 md:block">
                {roleDescription(activeRole)}
              </div>
              <button
                type="button"
                onClick={() => {
                  clearAuthToken();
                  onLogout();
                  navigate('/login', { replace: true });
                }}
                className="rounded-xl border border-white/10 bg-white/[0.05] px-3 py-2 text-sm font-semibold text-slate-200 transition hover:border-sky-400/30 hover:bg-sky-400/10 hover:text-sky-100"
              >
                退出登录
              </button>
            </div>
          </div>

          <nav className="flex gap-2 overflow-x-auto border-t border-white/10 px-5 py-2 lg:hidden">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-xl px-3 py-2 text-sm font-semibold ${
                    isActive ? 'bg-sky-600 text-white' : 'text-slate-400'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>

        <Outlet />
      </div>
    </div>
  );
}

function roleLabel(role: UserRole): string {
  return role === 'admin' ? '系统管理员' : '运维用户';
}

function roleDescription(role: UserRole): string {
  if (role === 'user') return '拥有设备画像、风险事件、维修记录和历史报告查看权限。';
  return '拥有知识、Agent、风险和系统治理权限。';
}

function groupNavItems(items: NavItem[]): Array<[string, NavItem[]]> {
  const groups = new Map<string, NavItem[]>();
  items.forEach((item) => {
    const section = item.section ?? '导航';
    groups.set(section, [...(groups.get(section) ?? []), item]);
  });
  return Array.from(groups.entries());
}

function activePageLabel(items: NavItem[], pathname: string): string {
  const exact = items.find((item) => item.to === pathname);
  if (exact) return exact.label;
  if (pathname.startsWith('/devices')) return '设备中心';
  if (pathname.startsWith('/reports')) return '报告详情';
  return '运营总览';
}

interface SearchAction {
  label: string;
  description: string;
  to: string;
}

function buildSearchActions(query: string, navItems: NavItem[]): SearchAction[] {
  const keyword = query.trim();
  if (!keyword) return [];
  const normalized = keyword.toLowerCase();
  const actions: SearchAction[] = [];
  const canOpen = (path: string) => navItems.some((item) => item.to === path || (path.startsWith('/devices') && item.to.startsWith('/devices')));

  const deviceCode = keyword.match(/dev[-\s]?\d{3}/i)?.[0]?.replace(/\s+/g, '-').toUpperCase();
  if (deviceCode && canOpen('/devices/DEV-003')) {
    actions.push({
      label: `查看设备 ${deviceCode}`,
      description: '打开设备画像、风险趋势、历史报警和维修记忆。',
      to: `/devices/${deviceCode}`,
    });
  }

  if (/(报告|历史|report|analysis|诊断记录)/i.test(keyword) && canOpen('/evaluation')) {
    actions.push({
      label: '查看智能服务报告',
      description: '进入历史诊断与风险报告列表。',
      to: '/evaluation',
    });
  }

  if (/(知识|手册|资料|案例|rag|e101|e201|e203|e404|manual)/i.test(keyword) && canOpen('/knowledge')) {
    actions.push({
      label: '进入知识中心',
      description: '查看企业维修资料、故障知识和可引用文档。',
      to: '/knowledge',
    });
  }

  if (/(诊断|分析|agent|故障|风险分析)/i.test(keyword) && canOpen('/diagnosis')) {
    actions.push({
      label: '启动智能诊断',
      description: '进入设备诊断与全局风险分析工作台。',
      to: '/diagnosis',
    });
  }

  if (/(维修|处理|闭环|工单|maintenance)/i.test(keyword) && canOpen('/maintenance')) {
    actions.push({
      label: '进入维修闭环',
      description: '查看现场处理记录并沉淀维修经验。',
      to: '/maintenance',
    });
  }

  const matchedMenu = navItems
    .filter((item) => item.label.includes(keyword) || item.description.includes(keyword) || item.label.toLowerCase().includes(normalized))
    .map((item) => ({ label: item.label, description: item.description, to: item.to }));

  return dedupeActions([...actions, ...matchedMenu]).slice(0, 5);
}

function dedupeActions(actions: SearchAction[]): SearchAction[] {
  const seen = new Set<string>();
  return actions.filter((item) => {
    if (seen.has(item.to)) return false;
    seen.add(item.to);
    return true;
  });
}
