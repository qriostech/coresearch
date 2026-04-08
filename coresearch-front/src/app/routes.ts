import { createBrowserRouter } from 'react-router'
import { Canvas } from './components/canvas'

export const router = createBrowserRouter([
  { path: '/', Component: Canvas },
])
