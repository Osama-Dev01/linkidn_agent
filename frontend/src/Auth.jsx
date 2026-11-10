// import React, { useState } from 'react';
// import { api } from './api';

// export default function Auth({ onLogin }) {
//   const [register, setRegister] = useState(false);
//   const [error, setError] = useState('');
//   const [busy, setBusy] = useState(false);
//   async function submit(event) {
//     event.preventDefault(); setError(''); setBusy(true);
//     const input = Object.fromEntries(new FormData(event.currentTarget));
//     try { onLogin(await api(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(input) })); }
//     catch (error) { setError(error.message); }
//     finally { setBusy(false); }
//   }
//   return <div className="auth-wrap"><section className="auth-card"><div className="brand"><span className="logo">a</span> author studio.</div>
//     <h1>{register ? 'Make it your own.' : 'Welcome back.'}</h1><p className="intro">{register ? 'Create an account to build your author profile.' : 'Log in to continue shaping your voice.'}</p>
//     <form onSubmit={submit}>{register && <label>Your name<input name="name" autoComplete="name" required maxLength={300} pattern=".*\S.*" /></label>}
//       <label>Email address<input name="email" type="email" autoComplete="email" required maxLength={254} /></label>
//       <label>Password<input name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} required minLength={10} maxLength={128} /></label>
//       <small>Use 10–128 characters.</small>{error && <p className="error" role="alert">{error}</p>}
//       <button className="btn primary" disabled={busy}>{busy ? 'Please wait…' : register ? 'Create account' : 'Log in'}</button>
//     </form><button className="btn quiet" disabled={busy} onClick={() => { setRegister(!register); setError(''); }}>{register ? 'Already have an account? Log in' : 'New here? Create an account'}</button>
//   </section></div>;
// }

import React, { useState } from 'react';

import { api } from './api';

export default function Auth({ onLogin }) {
  const [register, setRegister] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  let title = 'Welcome back.';
  let description = 'Log in to continue shaping your voice.';
  let passwordAutoComplete = 'current-password';
  let submitButtonText = 'Log in';
  let switchButtonText = 'New here? Create an account';

  if (register) {
    title = 'Make it your own.';
    description = 'Create an account to build your author profile.';
    passwordAutoComplete = 'new-password';
    submitButtonText = 'Create account';
    switchButtonText = 'Already have an account? Log in';
  }

  if (busy) {
    submitButtonText = 'Please wait…';
  }

  async function submit(event) {
    event.preventDefault();

    setError('');
    setBusy(true);

    const formData = new FormData(event.currentTarget);
    const input = Object.fromEntries(formData);

    let endpoint = '/auth/login';

    if (register) {
      endpoint = '/auth/register';
    }

    try {
      const session = await api(endpoint, {
        method: 'POST',
        body: JSON.stringify(input),
      });

      onLogin(session);
    } catch (error) {
      setError(error.message);
    } finally {
      setBusy(false);
    }
  }

  function toggleRegister() {
    setRegister(!register);
    setError('');
  }

  return (
    <div className="auth-wrap">
      <section className="auth-card">
        <div className="brand">
          <span className="logo">a</span>
          {' '}author studio.
        </div>

        <h1>{title}</h1>
        <p className="intro">{description}</p>

        <form onSubmit={submit}>
          {register && (
            <label>
              Your name

              <input
                name="name"
                autoComplete="name"
                required
                maxLength={300}
                pattern=".*\S.*"
              />
            </label>
          )}

          <label>
            Email address

            <input
              name="email"
              type="email"
              autoComplete="email"
              required
              maxLength={254}
            />
          </label>

          <label>
            Password

            <input
              name="password"
              type="password"
              autoComplete={passwordAutoComplete}
              required
              minLength={10}
              maxLength={128}
            />
          </label>

          <small>Use 10–128 characters.</small>

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <button
            className="btn primary"
            disabled={busy}
          >
            {submitButtonText}
          </button>
        </form>

        <button
          className="btn quiet"
          disabled={busy}
          onClick={toggleRegister}
        >
          {switchButtonText}
        </button>
      </section>
    </div>
  );
}