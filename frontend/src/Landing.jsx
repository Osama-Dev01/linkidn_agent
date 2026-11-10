import React, { useEffect, useState } from 'react';
import './landing.css';

function Monogram() {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className="studio-monogram">
      <rect x=".75" y=".75" width="30.5" height="30.5" rx="8" fill="var(--studio-paper)" stroke="currentColor" strokeWidth="1.5" />
      <path d="M9 24.5 16 7.5 23 24.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10.5 19.5C13 16.2 15.6 21.8 18.2 18.4c1.2-1.5 2.4-1.7 3.8-1" fill="none" stroke="var(--studio-blue)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function Wordmark() {
  return <span className="studio-wordmark"><Monogram />Author Studio</span>;
}

function DashboardLink({ className = '' }) {
  return <a className={`studio-button ${className}`} href="/dashboard">Go to dashboard <span aria-hidden="true">→</span></a>;
}

function ProductPreview() {
  return (
    <figure className="studio-preview">
      <div className="studio-window">
        <div className="studio-window-bar">
          <span className="studio-window-label"><span aria-hidden="true">○ ○ ○</span> <span className="studio-label">Studio · This week</span></span>
          <span className="studio-sample">Illustrative sample</span>
        </div>
        <div className="studio-preview-grid">
          <div className="studio-preview-panel">
            <h3>Voice profile</h3><p className="studio-hint">Learned from your preferences</p>
            <ul className="studio-scales">
              {[['Casual', 'Formal', 34], ['Concise', 'Detailed', 28], ['Reflective', 'Direct', 66]].map(([left, right, value]) => (
                <li key={left}><div><span>{left}</span><span>{right}</span></div><div className="studio-scale"><span style={{ width: `${value}%` }} /><i style={{ left: `${value}%` }} /></div></li>
              ))}
            </ul>
            <p className="studio-label studio-panel-label">Sounds like</p>
            <div className="studio-tags">{['Warm', 'Practical', 'Curious'].map(t => <span key={t}>{t}</span>)}</div>
            <p className="studio-label studio-panel-label">Topics</p>
            <div className="studio-tags studio-topics">{['Leadership', 'Product', 'Team culture'].map(t => <span key={t}>{t}</span>)}</div>
          </div>
          <div className="studio-preview-panel">
            <div className="studio-draft-title"><h3>LinkedIn draft</h3><span className="studio-hint">◷ Tue · 9:00</span></div>
            <article className="studio-draft">
              <div className="studio-person"><span className="studio-avatar">JR</span><div><b>Jordan Rivera</b><p>Product lead · Sample profile</p></div></div>
              <div className="studio-post">
                <p>Last month we cut a feature we'd spent weeks building.</p>
                <p>The honest reason: it solved our problem, not our customers'.</p>
                <p>What I'm doing differently now:</p>
                <ul><li>→ Talk to two customers before writing a plan</li><li>→ Share rough ideas early, not polished ones</li><li>→ Treat "not now" as a decision, not a failure</li></ul>
                <p>What's one habit that's helped your team stay focused?</p>
              </div>
            </article>
            <div className="studio-draft-footer"><span>✓ Matches your voice profile</span><div aria-hidden="true"><span>Edit</span><span>Approve</span></div></div>
          </div>
          <div className="studio-preview-panel">
            <h3>Publishing queue</h3><p className="studio-hint">Your week at a glance</p>
            <div className="studio-week" aria-hidden="true">{['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => <div key={i}><span>{d}</span><b className={i === 1 ? 'studio-today' : ''}>{[0, 1, 3, 4].includes(i) ? '●' : ''}</b></div>)}</div>
            <ol className="studio-queue">{[
              ['Mon', '8:30', 'Lessons from a quiet launch', 'Posted'],
              ['Tue', '9:00', 'Why we cut a feature', 'In review'],
              ['Thu', '12:00', 'Hiring for curiosity', 'Scheduled'],
            ].map(([day, time, title, status]) => <li key={day} className={status === 'In review' ? 'studio-in-review' : ''}><div><span>{day} · {time}</span><span>⊙ {status}</span></div><p>{title}</p></li>)}</ol>
            <div className="studio-empty-slot"><span>Fri · Open slot</span><p>+ Room for your next idea</p></div>
          </div>
        </div>
      </div>
      <figcaption>Sample names and posts shown for illustration only.</figcaption>
    </figure>
  );
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    if (!menuOpen) return;
    function closeOnEscape(event) {
      if (event.key === 'Escape') setMenuOpen(false);
    }
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [menuOpen]);

  return (
    <div className="studio-landing" id="top">
      <header className="studio-header">
        <div className="studio-container studio-header-row">
          <a href="#top" aria-label="Author Studio, back to top"><Wordmark /></a>
          <nav className="studio-desktop-nav" aria-label="Main"><a href="#how-it-works">How it works</a><a href="#features">Features</a></nav>
          <div className="studio-header-actions"><DashboardLink /><button className="studio-menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="studio-mobile-menu" aria-label={menuOpen ? 'Close menu' : 'Open menu'} onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? '×' : '☰'}</button></div>
        </div>
        <nav className="studio-mobile-nav studio-container" id="studio-mobile-menu" aria-label="Mobile" hidden={!menuOpen}>
          <a href="#how-it-works" onClick={() => setMenuOpen(false)}>How it works</a><a href="#features" onClick={() => setMenuOpen(false)}>Features</a><DashboardLink />
        </nav>
      </header>
      <main className="studio-main">
        <section className="studio-hero" aria-labelledby="studio-hero-title">
          <div className="studio-container">
            <div className="studio-hero-copy">
              <p className="studio-label studio-hero-badge"><i /><span>Personal posting studio · </span>Starting with LinkedIn</p>
              <h1 id="studio-hero-title">Your ideas.<br />Your voice.<br /><em>On autopilot.</em></h1>
              <p className="studio-hero-description">Author Studio learns from your preferences to write social posts that sound like you — and helps you show up consistently, without the weekly scramble.</p>
              <div className="studio-hero-actions"><DashboardLink /><a className="studio-button studio-button-outline" href="#how-it-works">See how it works</a></div>
            </div>
            <ProductPreview />
          </div>
        </section>
        <section id="how-it-works" className="studio-section studio-container" aria-labelledby="studio-how-title">
          <p className="studio-label">How it works</p><h2 id="studio-how-title">Three steps to posts that sound like you.</h2>
          <ol className="studio-steps">{[
            ['01', 'Share your preferences', "Tell Author Studio your role, who you'd like to reach, the topics you care about, and how often you want to post."],
            ['02', 'Shape your voice', "Choose a tone and react to a few drafts. Author Studio learns what sounds like you — and what doesn't."],
            ['03', 'Review and schedule', 'Approve, edit, or skip each post. Ready posts are lined up on the days that suit you.'],
          ].map(([n, title, body]) => <li key={n}><span>{n}</span><h3>{title}</h3><p>{body}</p></li>)}</ol>
        </section>
        <div className="studio-container"><hr /></div>
        <section id="features" className="studio-section studio-container" aria-labelledby="studio-features-title">
          <div className="studio-features-heading"><div><p className="studio-label">Features</p><h2 id="studio-features-title">Built around you, not a template.</h2></div><p>Everything Author Studio does starts with your preferences — and you stay the final editor.</p></div>
          <div className="studio-features">
            <article className="studio-feature studio-feature-wide"><div className="studio-feature-copy"><p className="studio-label">Personalized voice</p><h3>Sounds like you on a good day.</h3><p>Author Studio learns your words, your rhythm, and the topics you care about, so drafts feel like yours — not like everyone else's.</p></div><div className="studio-feature-visual studio-voice-visual" aria-hidden="true"><div><span>Generic</span><s>Thrilled to announce an exciting new milestone on our journey!</s></div><div><span>Yours</span><p>We shipped something small this week. I'm prouder of it than I expected.</p></div></div></article>
            <article className="studio-feature"><div className="studio-feature-copy"><p className="studio-label">Consistent scheduling</p><h3>Show up, week after week.</h3><p>Pick how often you'd like to post. Author Studio keeps a steady queue so you never start from a blank page.</p></div><div className="studio-feature-visual studio-schedule" aria-hidden="true">{['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].map((d, i) => <div key={d} className={i % 2 === 0 ? 'studio-planned' : ''}><span>{d}</span><b>{i % 2 === 0 ? '●' : '○'}</b></div>)}</div></article>
            <article className="studio-feature"><div className="studio-feature-copy"><p className="studio-label">Stay in control</p><h3>Nothing goes out without you.</h3><p>Every post waits for your approval. Change a word, rewrite it, or skip it entirely.</p></div><ul className="studio-feature-visual studio-control" aria-hidden="true">{['Review every post before it goes out', 'Edit anything, anytime', 'Pause whenever you like'].map(row => <li key={row}>{row}<span>✓</span></li>)}</ul></article>
          </div>
        </section>
        <section className="studio-final studio-container" aria-labelledby="studio-cta-title"><div className="studio-final-panel"><Monogram /><h2 id="studio-cta-title">Start with your <em>preferences.</em></h2><p>It only takes a few minutes, and you can change anything later.</p><DashboardLink /></div></section>
      </main>
      <footer className="studio-footer"><div className="studio-container"><Wordmark /><nav aria-label="Footer"><a href="#how-it-works">How it works</a><a href="#features">Features</a></nav><p>© {new Date().getFullYear()} Author Studio</p></div></footer>
    </div>
  );
}
