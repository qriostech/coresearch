import { RouterProvider } from 'react-router'
import { router } from './routes'
import { WorkflowProvider } from './context/workflow-context'

export default function App() {
  return (
    <WorkflowProvider>
      <RouterProvider router={router} />
    </WorkflowProvider>
  )
}
