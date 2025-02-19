import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'
import { EmptyState } from '../components/ui'

export default function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you were looking for does not exist."
      icon={<Compass size={30} />}
      action={
        <Link to="/" className="btn-primary text-sm">
          Back to the overview
        </Link>
      }
    />
  )
}
