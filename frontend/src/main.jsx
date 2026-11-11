import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import './styles/tokens.css';
import './styles/app.css';
import App from './App';
import ErrorBoundary from './components/feedback/ErrorBoundary';
import { ThemeProvider } from './context/ThemeContext';
import { AuthProvider } from './context/AuthContext';

// No <StrictMode>: its double effect run would fire two refreshes, and refresh tokens rotate.
createRoot(document.getElementById('root')).render(
  <HashRouter>
    <ThemeProvider>
      <AuthProvider>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </AuthProvider>
    </ThemeProvider>
  </HashRouter>
);