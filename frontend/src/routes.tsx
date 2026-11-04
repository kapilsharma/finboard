import { Navigate, type RouteObject } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { ImportDetailPage } from './pages/import/ImportDetailPage'
import { ImportPage } from './pages/import/ImportPage'
import { DashboardPage, NotFoundPage, ReviewPage, TransactionsPage } from './pages/placeholders'
import { SettingsPage } from './pages/settings/SettingsPage'

export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'transactions', element: <TransactionsPage /> },
      { path: 'review', element: <ReviewPage /> },
      { path: 'import', element: <ImportPage /> },
      { path: 'import/:id', element: <ImportDetailPage /> },
      { path: 'settings', element: <Navigate to="/settings/accounts" replace /> },
      { path: 'settings/:tab', element: <SettingsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
]
