import { Link } from 'react-router'
import { PageHeader } from '../components/ui'

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Link to="/">Back to the dashboard</Link>
    </>
  )
}
