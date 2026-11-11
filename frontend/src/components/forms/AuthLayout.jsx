import { Link } from 'react-router-dom';

export default function AuthLayout({ title, children, footer }) {
  return (
    <div className="auth">
      <section className="auth-art">
        <Link to="/login" className="wordmark">Subwise<i /></Link>
        <h1>Know what you pay for before it renews.</h1>
        <ul>
          <li>Totals stay in the currency you pay in. Nothing is converted.</li>
          <li>The AI answers only from your own saved records.</li>
          <li>Nothing is saved from an import until you confirm it.</li>
        </ul>
      </section>
      <main className="auth-form">
        <div>
          <h2>{title}</h2>
          {children}
          <p className="swap">{footer}</p>
        </div>
      </main>
    </div>
  );
}
