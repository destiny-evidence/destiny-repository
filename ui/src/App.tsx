import Router from "preact-router";
import { AuthProvider } from "./auth/AuthContext";
import AuthButton from "./components/auth/AuthButton";
import HomePage from "./pages/HomePage";
import NotFoundPage from "./pages/NotFoundPage";
import ReferencesPage from "./pages/ReferencesPage";

export function App() {
  return (
    <AuthProvider>
      <nav class="navbar">
        <span class="navbar-title">DESTINY Repository</span>
        <div class="navbar-actions">
          <a class="navbar-link active" href="/references">
            References
          </a>
          <div id="auth-btn-container" style={{ marginLeft: 24 }}>
            <AuthButton />
          </div>
        </div>
      </nav>
      <div class="main-content">
        <Router>
          <HomePage path="/" />
          <ReferencesPage path="/references" />
          <NotFoundPage default />
        </Router>
      </div>
    </AuthProvider>
  );
}
