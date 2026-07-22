import { useEffect, useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { clearAuthToken, getAuthToken } from './api';
import { fetchCurrentUser } from './api/auth';
import AppLayout from './components/AppLayout';
import DashboardPage from './pages/Dashboard';
import DiagnosisPage from './pages/Diagnosis';
import DeviceDetailPage from './pages/DeviceDetail';
import EvaluationPage from './pages/Evaluation';
import KnowledgePage from './pages/Knowledge';
import LoginPage from './pages/Login';
import MaintenancePage from './pages/Maintenance';
import ReportDetailPage from './pages/ReportDetail';
import SettingsPage from './pages/Settings';
import type { CurrentUser } from './types';
import { canViewReportDetail, getFrontendPermissions } from './utils/permissions';

export default function App() {
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [authLoading, setAuthLoading] = useState(Boolean(getAuthToken()));

  useEffect(() => {
    if (!getAuthToken()) {
      setAuthLoading(false);
      return;
    }

    let cancelled = false;

    async function loadCurrentUser() {
      setAuthLoading(true);
      try {
        const user = await fetchCurrentUser();
        if (!cancelled) setCurrentUser(user);
      } catch {
        clearAuthToken();
        if (!cancelled) setCurrentUser(null);
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    }

    void loadCurrentUser();
    return () => {
      cancelled = true;
    };
  }, []);

  if (authLoading) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#070d16] text-slate-300">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-6 py-5 text-sm shadow-2xl shadow-black/30">
          正在校验登录状态...
        </div>
      </main>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onAuthenticated={setCurrentUser} />} />
      <Route
        element={
          getAuthToken() && currentUser ? (
            <AppLayout currentUser={currentUser} onLogout={() => setCurrentUser(null)} />
          ) : (
            <Navigate to="/login" replace />
          )
        }
      >
        <Route path="/" element={<DashboardPage currentUser={currentUser} />} />
        <Route path="/devices/:deviceCode" element={<DeviceDetailPage />} />
        <Route path="/maintenance" element={<MaintenancePage currentUser={currentUser} />} />
        <Route path="/diagnosis" element={<DiagnosisPage currentUser={currentUser} />} />
        <Route path="/knowledge" element={<KnowledgePage currentUser={currentUser} />} />
        <Route path="/evaluation" element={<EvaluationPage currentUser={currentUser} />} />
        <Route
          path="/reports/:reportId"
          element={canViewReportDetail(currentUser) ? <ReportDetailPage /> : <Navigate to="/" replace />}
        />
        <Route
          path="/settings"
          element={getFrontendPermissions(currentUser).manageSystem ? <SettingsPage currentUser={currentUser} /> : <Navigate to="/" replace />}
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
