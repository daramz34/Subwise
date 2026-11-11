import { Component } from 'react';

export default class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="main">
        <h1 className="page-title">Something broke on this screen.</h1>
        <p className="page-sub mono">{String(this.state.error.message || this.state.error)}</p>
        <button className="btn" onClick={() => { window.location.hash = '#/'; window.location.reload(); }}>
          Back to overview
        </button>
      </div>
    );
  }
}