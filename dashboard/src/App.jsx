import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Link, useParams, useNavigate } from 'react-router-dom';
import Heatmap from './components/Heatmap';
import ModuleDetail from './components/ModuleDetail';
import TrendChart from './components/TrendChart';
import Landing from './components/Landing';
import { getRepos, getModules, getAlerts } from './api';

/* ─── Header ─── */
function Header() {
  return (
    <header className="header">
      <div className="header-brand">
        <Link to="/" style={{ textDecoration: 'none' }}>
          <div className="header-logo">ENTROPY</div>
        </Link>
        <div className="header-subtitle">Code Aging Tracker</div>
      </div>
      <nav className="header-nav">
        <Link to="/demo" className="nav-link">Demo</Link>
        <Link to="/docs" className="nav-link">Docs</Link>
        <a href="/api/docs" className="nav-link" target="_blank" rel="noopener">API</a>
      </nav>
    </header>
  );
}

/* ─── Loading ─── */
function Loading({ text = 'Loading…' }) {
  return (
    <div className="loading-container">
      <div className="spinner" />
      <div className="loading-text">{text}</div>
    </div>
  );
}

/* ─── Severity helpers ─── */
function getSeverityColor(score) {
  if (score >= 85) return 'var(--critical)';
  if (score >= 70) return 'var(--high)';
  if (score >= 50) return 'var(--medium)';
  return 'var(--healthy)';
}

function getSeverityLabel(score) {
  if (score >= 85) return 'CRITICAL';
  if (score >= 70) return 'HIGH';
  if (score >= 50) return 'MEDIUM';
  return 'HEALTHY';
}

/* ─── Dashboard Page ─── */
function Dashboard() {
  const { repoId } = useParams();
  const navigate = useNavigate();
  const [repos, setRepos] = useState([]);
  const [modules, setModules] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeRepo, setActiveRepo] = useState(repoId || null);
  const [view, setView] = useState('heatmap');
  const [selectedModule, setSelectedModule] = useState(null);

  useEffect(() => {
    getRepos()
      .then(r => {
        setRepos(r);
        if (!activeRepo && r.length > 0) setActiveRepo(r[0].id);
      })
      .catch(() => setRepos([]));
  }, []);

  useEffect(() => {
    if (!activeRepo) { setLoading(false); return; }
    setLoading(true);
    Promise.all([
      getModules(activeRepo),
      getAlerts(activeRepo),
    ])
      .then(([m, a]) => { setModules(m); setAlerts(a); })
      .catch(() => { setModules([]); setAlerts([]); })
      .finally(() => setLoading(false));
  }, [activeRepo]);

  const critical = modules.filter(m => m.entropy_score >= 85).length;
  const high = modules.filter(m => m.entropy_score >= 70 && m.entropy_score < 85).length;
  const medium = modules.filter(m => m.entropy_score >= 50 && m.entropy_score < 70).length;
  const healthy = modules.filter(m => m.entropy_score < 50).length;
  const avgScore = modules.length
    ? (modules.reduce((a, m) => a + m.entropy_score, 0) / modules.length).toFixed(1)
    : '—';

  if (loading) return <Loading text="Analyzing codebase…" />;

  if (!repos.length && !modules.length) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">🔬</div>
        <div className="empty-state-text">
          No repositories tracked yet. Use <code>entropy init ./repo</code> to add one.
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Repo Selector */}
      {repos.length > 0 && (
        <div className="repo-selector">
          {repos.map(r => (
            <button
              key={r.id}
              className={`repo-chip ${activeRepo === r.id ? 'active' : ''}`}
              onClick={() => setActiveRepo(r.id)}
            >
              {r.name}
            </button>
          ))}
        </div>
      )}

      {/* Stats Cards */}
      <div className="stats-grid">
        <div className="card">
          <div className="card-title">Average Entropy</div>
          <div className="card-value" style={{ color: getSeverityColor(parseFloat(avgScore) || 0) }}>{avgScore}</div>
          <div className="card-label">{modules.length} modules</div>
        </div>
        <div className="card">
          <div className="card-title">Critical</div>
          <div className="card-value severity-critical">{critical}</div>
          <div className="card-label">score &gt; 85</div>
        </div>
        <div className="card">
          <div className="card-title">High Risk</div>
          <div className="card-value severity-high">{high}</div>
          <div className="card-label">score 70–85</div>
        </div>
        <div className="card">
          <div className="card-title">Healthy</div>
          <div className="card-value severity-healthy">{healthy}</div>
          <div className="card-label">score &lt; 50</div>
        </div>
      </div>

      {/* View Tabs */}
      <div className="header-nav" style={{ marginBottom: 'var(--space-xl)' }}>
        <button className={`nav-link ${view === 'heatmap' ? 'active' : ''}`} onClick={() => { setView('heatmap'); setSelectedModule(null); }}>Heatmap</button>
        <button className={`nav-link ${view === 'modules' ? 'active' : ''}`} onClick={() => { setView('modules'); setSelectedModule(null); }}>Modules</button>
        <button className={`nav-link ${view === 'trend' ? 'active' : ''}`} onClick={() => { setView('trend'); setSelectedModule(null); }}>Trend</button>
        <button className={`nav-link ${view === 'alerts' ? 'active' : ''}`} onClick={() => { setView('alerts'); setSelectedModule(null); }}>Alerts ({alerts.length})</button>
      </div>

      {/* Views */}
      {selectedModule ? (
        <div>
          <button className="nav-link" onClick={() => setSelectedModule(null)} style={{ marginBottom: 'var(--space-lg)' }}>← Back to {view}</button>
          <ModuleDetail module={selectedModule} repoId={activeRepo} />
        </div>
      ) : (
        <>
          {view === 'heatmap' && (
            <section className="section">
              <h2 className="section-title">Entropy Heatmap</h2>
              <Heatmap modules={modules} onSelect={setSelectedModule} />
            </section>
          )}

          {view === 'modules' && (
            <section className="section">
              <h2 className="section-title">All Modules — Sorted by Entropy</h2>
              <div className="card" style={{ padding: 0, overflow: 'auto' }}>
                <table className="module-table">
                  <thead>
                    <tr>
                      <th>Module</th>
                      <th>Score</th>
                      <th>Knowledge</th>
                      <th>Deps</th>
                      <th>Churn</th>
                      <th>Age</th>
                      <th>Blast</th>
                      <th>Bus</th>
                      <th>Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modules.map(m => (
                      <tr key={m.module_path} style={{ cursor: 'pointer' }} onClick={() => setSelectedModule(m)}>
                        <td className="module-path">{m.module_path}</td>
                        <td className="score-cell" style={{ color: getSeverityColor(m.entropy_score) }}>{m.entropy_score.toFixed(0)}</td>
                        <td className="numeric">{m.knowledge_score?.toFixed(0) ?? '—'}</td>
                        <td className="numeric">{m.dep_score?.toFixed(0) ?? '—'}</td>
                        <td className="numeric">{m.churn_score?.toFixed(0) ?? '—'}</td>
                        <td className="numeric">{m.age_score?.toFixed(0) ?? '—'}</td>
                        <td className="numeric">{m.blast_radius ?? '—'}</td>
                        <td className="numeric">{m.bus_factor ?? '—'}</td>
                        <td>
                          <span className={`severity-badge ${getSeverityLabel(m.entropy_score).toLowerCase()}`}>
                            {getSeverityLabel(m.entropy_score)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {view === 'trend' && (
            <section className="section">
              <h2 className="section-title">Repo Health Over Time</h2>
              <div className="card">
                <TrendChart repoId={activeRepo} />
              </div>
            </section>
          )}

          {view === 'alerts' && (
            <section className="section">
              <h2 className="section-title">Active Alerts</h2>
              {alerts.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon">✓</div>
                  <div className="empty-state-text">No active alerts. Your codebase is in good shape!</div>
                </div>
              ) : (
                alerts.map(a => (
                  <div key={a.id} className="alert-item">
                    <div className={`alert-dot ${a.severity?.toLowerCase()}`} />
                    <div className="alert-message">{a.message}</div>
                    <span className={`severity-badge ${a.severity?.toLowerCase()}`}>{a.severity}</span>
                    <div className="alert-time">{a.fired_at ? new Date(a.fired_at).toLocaleDateString() : ''}</div>
                  </div>
                ))
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

/* ─── Docs Page ─── */
function DocsPage() {
  return (
    <div style={{ maxWidth: 700 }}>
      <h1 className="page-title">Quick Start Guide</h1>
      <p className="page-description" style={{ marginBottom: 'var(--space-xl)' }}>
        Get your first entropy scores in under 3 minutes.
      </p>

      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <h3 style={{ fontSize: '0.9rem', marginBottom: 'var(--space-md)' }}>1. Install</h3>
        <code className="text-mono" style={{ color: 'var(--accent-light)', fontSize: '0.85rem' }}>
          $ pip install entropy-tracker
        </code>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <h3 style={{ fontSize: '0.9rem', marginBottom: 'var(--space-md)' }}>2. Initialize & Scan</h3>
        <code className="text-mono" style={{ color: 'var(--accent-light)', fontSize: '0.85rem', display: 'block' }}>
          $ entropy init ./my-repo
        </code>
        <code className="text-mono" style={{ color: 'var(--accent-light)', fontSize: '0.85rem', display: 'block', marginTop: 4 }}>
          $ entropy scan ./my-repo
        </code>
      </div>

      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <h3 style={{ fontSize: '0.9rem', marginBottom: 'var(--space-md)' }}>3. View Results</h3>
        <code className="text-mono" style={{ color: 'var(--accent-light)', fontSize: '0.85rem', display: 'block' }}>
          $ entropy report --top 10
        </code>
        <code className="text-mono" style={{ color: 'var(--accent-light)', fontSize: '0.85rem', display: 'block', marginTop: 4 }}>
          $ entropy inspect payments/gateway.py
        </code>
      </div>

      <div className="card">
        <h3 style={{ fontSize: '0.9rem', marginBottom: 'var(--space-md)' }}>4. Start Dashboard (optional)</h3>
        <code className="text-mono" style={{ color: 'var(--accent-light)', fontSize: '0.85rem' }}>
          $ entropy server
        </code>
      </div>
    </div>
  );
}

/* ─── App ─── */
export default function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Routes>
          <Route path="/" element={<><Header /><Landing /></>} />
          <Route path="/demo" element={<><Header /><Dashboard /></>} />
          <Route path="/demo/:repoId" element={<><Header /><Dashboard /></>} />
          <Route path="/docs" element={<><Header /><DocsPage /></>} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
