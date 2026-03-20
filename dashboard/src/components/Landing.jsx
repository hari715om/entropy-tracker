import React from 'react';
import { Link } from 'react-router-dom';

/**
 * Landing Page — entropy.kwixlab.com
 * Job: get a visitor to click into the demo within 10 seconds.
 */
export default function Landing() {
  return (
    <div className="landing">
      <div className="landing-hero">
        <h1 className="landing-title">
          Your codebase is aging.<br />
          <span className="landing-accent">Entropy shows you where.</span>
        </h1>

        <p className="landing-subtitle">
          Entropy computes a decay score per module in your codebase by analyzing git history,
          dependency drift, churn patterns, and knowledge silos. It tells you which parts
          of your code are silently becoming dangerous — before they break.
        </p>

        <Link to="/demo" className="landing-cta">
          Explore live demo →
        </Link>
      </div>

      <div className="landing-install">
        <div className="landing-install-title">Quick Start</div>
        <code>pip install entropy-tracker</code>
        <code>entropy init ./my-repo</code>
        <code>entropy report --top 10</code>
      </div>

      {/* Features grid */}
      <div className="stats-grid" style={{ marginTop: 'var(--space-2xl)', maxWidth: 900 }}>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-sm)' }}>🧠</div>
          <div className="card-title">Knowledge Decay</div>
          <div className="card-label">Track which modules have lost their original authors</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-sm)' }}>📦</div>
          <div className="card-title">Dependency Drift</div>
          <div className="card-label">Measure how far behind your dependencies are</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-sm)' }}>📈</div>
          <div className="card-title">Churn Patterns</div>
          <div className="card-label">Spot chaotic edits vs intentional refactoring</div>
        </div>
        <div className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '2rem', marginBottom: 'var(--space-sm)' }}>⏰</div>
          <div className="card-title">Age Since Refactor</div>
          <div className="card-label">Find code drifting from team understanding</div>
        </div>
      </div>

      <p className="text-muted" style={{ marginTop: 'var(--space-2xl)', fontSize: '0.8rem' }}>
        <a href="https://github.com/entropy-tracker/entropy" target="_blank" rel="noopener">GitHub</a>
        {' · '}
        <Link to="/docs">Documentation</Link>
        {' · '}
        <a href="/api/docs" target="_blank" rel="noopener">API Docs</a>
      </p>
    </div>
  );
}
