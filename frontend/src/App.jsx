

import React, { useEffect, useState } from 'react';

import Auth from './Auth';
import Field from './Field';
import Review from './Review';
import PublishedPosts from './PublishedPosts';

import { api } from './api';
import { pages } from './schema';
import { fieldsOf, payload, validatePage, visible } from './profile';

function draftKey(id) {
  return `author-draft:${id}`;
}

function readDrafts(id) {
  try {
    const key = draftKey(id);
    const storedDrafts = sessionStorage.getItem(key);
    const value = JSON.parse(storedDrafts || '{}');

    if (!value) {
      return {};
    }

    if (typeof value !== 'object') {
      return {};
    }

    if (Array.isArray(value)) {
      return {};
    }

    return value;
  } catch {
    return {};
  }
}

export default function App() {
  const [user, setUser] = useState(null);

  const [profile, setProfile] = useState({
    sections: {},
  });

  const [drafts, setDrafts] = useState({});
  const [pageIndex, setPageIndex] = useState(0);
  const [review, setReview] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [errors, setErrors] = useState({});
  const [storageError, setStorageError] = useState('');
  const [engineNotice, setEngineNotice] = useState(null);
  const [startingEngine, setStartingEngine] = useState(false);
  const [publishedPosts, setPublishedPosts] = useState(null);

  const page = pages[pageIndex];

  let data = drafts[page.key];

  if (data === null || data === undefined) {
    data = profile.sections[page.key];
  }

  if (data === null || data === undefined) {
    if (page.repeat) {
      data = {
        items: [],
      };
    } else {
      data = {};
    }
  }

  const savedSectionKeys = Object.keys(profile.sections);
  const savedCount = savedSectionKeys.length;

  const draftKeys = Object.keys(drafts);
  const hasUnsavedChanges = draftKeys.length > 0;

  const progressPercentage = (savedCount / 8) * 100;
  const pageNumber = String(pageIndex + 1).padStart(2, '0');
  const tipNote = page.note.replace(/<\/?strong>/g, '');

  let statusText = 'Up to date';

  if (busy) {
    statusText = 'Saving or loading…';
  } else if (hasUnsavedChanges) {
    statusText = 'Unsaved changes';
  }

  let saveButtonText = 'Save & continue →';

  if (busy) {
    saveButtonText = 'Saving…';
  } else if (pageIndex === 7) {
    saveButtonText = 'Save & review ✓';
  }

  async function initialize(auth) {
    setLoading(true);
    setError('');

    try {
      let session = auth;

      if (!session) {
        session = await api('/auth/me');
      }

      const saved = await api('/profile');
      const savedDrafts = readDrafts(session.user.user_id);
      const sectionKeys = Object.keys(saved.sections);
      const hasSavedSections = sectionKeys.length > 0;

      setUser(session.user);
      setPublishedPosts(null);
      setProfile(saved);
      setDrafts(savedDrafts);
      setReview(hasSavedSections);
    } catch (error) {
      if (error.status === 401) {
        setUser(null);
      } else {
        setError(error.message);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(function () {
    initialize();
  }, []);

  useEffect(function () {
    if (!user) {
      return;
    }

    try {
      const key = draftKey(user.user_id);
      const draftJson = JSON.stringify(drafts);

      sessionStorage.setItem(key, draftJson);
      setStorageError('');
    } catch {
      setStorageError(
        'Browser draft storage is unavailable. Save this section before refreshing.'
      );
    }
  }, [drafts, user]);

  function update(patch) {
    setDrafts(function (previous) {
      let sectionData = previous[page.key];

      if (sectionData === null || sectionData === undefined) {
        sectionData = profile.sections[page.key];
      }

      if (sectionData === null || sectionData === undefined) {
        sectionData = {};
      }

      const updatedSection = {
        ...sectionData,
        ...patch,
      };

      return {
        ...previous,
        [page.key]: updatedSection,
      };
    });

    setErrors({});
    setError('');
  }

  function edit(index) {
    setPublishedPosts(null);
    setPageIndex(index);
    setReview(false);
    setErrors({});
    setError('');

    window.scrollTo(0, 0);
  }

  function failed(error) {
    setError(error.message);

    if (error.status === 401) {
      setUser(null);
    }
  }

  async function save(event) {
    event.preventDefault();

    const clean = payload(page, data);
    const found = validatePage(page, clean);
    const errorKeys = Object.keys(found);

    setErrors(found);
    setError('');

    if (errorKeys.length > 0) {
      setError('Complete the highlighted fields before saving.');

      return;
    }

    setBusy(true);

    try {
      const saved = await api(`/profile/${page.key}`, {
        method: 'PUT',
        body: JSON.stringify(clean),
      });

      setProfile(saved);

      setDrafts(function (previous) {
        const next = { ...previous };

        delete next[page.key];

        return next;
      });

      if (pageIndex < pages.length - 1) {
        edit(pageIndex + 1);
      } else {
        setReview(true);
      }
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }

  async function openReview() {
    setBusy(true);
    setError('');

    try {
      const savedProfile = await api('/profile');

      setProfile(savedProfile);
      setPublishedPosts(null);
      setReview(true);

      window.scrollTo(0, 0);
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);

    try {
      await api('/auth/logout', {
        method: 'POST',
      });

      try {
        const key = draftKey(user.user_id);

        sessionStorage.removeItem(key);
      } catch {
        // Storage may be disabled.
      }

      setUser(null);
      setDrafts({});

      setProfile({
        sections: {},
      });

      setError('');
      setPageIndex(0);
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }

  async function openPublishedPosts() {
    setBusy(true);
    setError('');

    try {
      const result = await api('/published-posts');
      setPublishedPosts(result.posts);
      window.scrollTo(0, 0);
    } catch (error) {
      failed(error);
    } finally {
      setBusy(false);
    }
  }

  async function runEngine() {
    setEngineNotice(null);
    setStartingEngine(true);

    try {
      const result = await api('/engine/run', { method: 'POST' });
      setEngineNotice({ text: result.message, error: false });
    } catch (error) {
      setEngineNotice({ text: error.message, error: error.status !== 409 });
      if (error.status === 401) setUser(null);
    } finally {
      setStartingEngine(false);
    }
  }

  function retryConnection() {
    initialize();
  }

  function goBack() {
    edit(pageIndex - 1);
  }

  function addRecord() {
    const existingItems = data.items || [];

    const newRecord = {
      id: crypto.randomUUID(),
    };

    const updatedItems = [...existingItems, newRecord];

    update({
      items: updatedItems,
    });
  }

  function removeRecord(recordId) {
    const remainingItems = data.items.filter(function (item) {
      return item.id !== recordId;
    });

    update({
      items: remainingItems,
    });
  }

  function updateRecord(recordId, patch) {
    const updatedItems = data.items.map(function (item) {
      if (item.id !== recordId) {
        return item;
      }

      return {
        ...item,
        ...patch,
      };
    });

    update({
      items: updatedItems,
    });
  }

  function renderFields(definitions, values, onUpdate, prefix = '') {
    const visibleFields = definitions.filter(function (field) {
      return visible(field.key, values);
    });

    function renderField(field) {
      const errorKey = `${prefix}${field.key}`;

      function handleChange(value) {
        onUpdate({
          [field.key]: value,
        });
      }

      return (
        <Field
          key={field.key}
          field={field}
          data={values}
          value={values[field.key]}
          error={errors[errorKey]}
          onChange={handleChange}
        />
      );
    }

    return (
      <div className="fields">
        {visibleFields.map(renderField)}
      </div>
    );
  }

  function renderNavigationItem(item, index) {
    const isActive = publishedPosts === null && !review && pageIndex === index;

    let className = 'nav';
    let ariaCurrent;
    let sectionNumber = String(index + 1).padStart(2, '0');

    if (isActive) {
      className = 'nav active';
      ariaCurrent = 'step';
    }

    if (profile.sections[item.key]) {
      sectionNumber = '✓';
    }

    function handleClick() {
      edit(index);
    }

    return (
      <button
        key={item.key}
        type="button"
        disabled={busy}
        className={className}
        aria-current={ariaCurrent}
        onClick={handleClick}
      >
        <span className="num">{sectionNumber}</span>
        {item.label}
      </button>
    );
  }

  function renderRecord(record, index) {
    const itemName = page.item.toLowerCase();
    const errorPrefix = `${index}.`;

    function handleRemove() {
      removeRecord(record.id);
    }

    function handleUpdate(patch) {
      updateRecord(record.id, patch);
    }

    return (
      <section className="card" key={record.id}>
        <button
          type="button"
          className="remove"
          onClick={handleRemove}
        >
          Remove {itemName} {index + 1}
        </button>

        <h2>
          {page.item} {index + 1}
        </h2>

        <p className="sub">
          Required fields are marked *. Leave unknown details empty.
        </p>

        {renderFields(
          page.fields,
          record,
          handleUpdate,
          errorPrefix
        )}
      </section>
    );
  }

  function renderGroup(group) {
    return (
      <section className="card" key={group.title}>
        <h2>{group.title}</h2>
        <p className="sub">{group.sub}</p>

        {renderFields(group.fields, data, update)}
      </section>
    );
  }

  function renderPageFields() {
    if (!page.repeat) {
      return page.groups.map(renderGroup);
    }

    const items = data.items || [];
    const sectionName = page.label.toLowerCase();
    const itemName = page.item.toLowerCase();
    const hasReachedLimit = items.length >= 20;

    return (
      <>
        {items.map(renderRecord)}

        {items.length === 0 && (
          <section className="card">
            <h2>Add your {sectionName}</h2>

            <p className="sub">
              Add real examples when available. You can save this section empty.
            </p>
          </section>
        )}

        <button
          type="button"
          className="add"
          disabled={hasReachedLimit}
          onClick={addRecord}
        >
          + Add {itemName}
        </button>
      </>
    );
  }

  function renderContent() {
    if (publishedPosts !== null) {
      return (
        <>
          {error && <p className="error" role="alert">{error}</p>}
          <PublishedPosts posts={publishedPosts} />
        </>
      );
    }

    if (review) {
      return (
        <>
          {hasUnsavedChanges && (
            <p className="notice">
              You have unsaved edits. Open a section to continue; this review
              shows your saved profile.
            </p>
          )}

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}

          <Review
            user={user}
            profile={profile}
            onEdit={edit}
          />
        </>
      );
    }

    return (
      <>
        <div className="step">
          AUTHOR PROFILE / {pageNumber}
        </div>

        <h1>{page.title}</h1>
        <p className="intro">{page.desc}</p>

        <div className="layout">
          <form onSubmit={save} noValidate>
            <fieldset disabled={busy} className="form-body">
              {renderPageFields()}

              {error && (
                <p className="error" role="alert">
                  {error}
                </p>
              )}

              {errors._page && (
                <p className="error">
                  {errors._page}
                </p>
              )}

              <div className="footer">
                <button
                  type="button"
                  className="btn"
                  disabled={pageIndex === 0}
                  onClick={goBack}
                >
                  ← Back
                </button>

                <button
                  className="btn primary"
                  type="submit"
                >
                  {saveButtonText}
                </button>
              </div>
            </fieldset>
          </form>

          <div className="rail">
            <section className="card tip">
              <h2>{page.tip}</h2>
              <p>{tipNote}</p>
            </section>

            <section className="card">
              <h2>Your profile, your voice</h2>

              <p className="sub">
                Required fields are marked *. Save each section to keep it
                in your account.
              </p>
            </section>
          </div>
        </div>
      </>
    );
  }

  if (loading) {
    return (
      <div className="auth-wrap">
        <p role="status">Loading your workspace…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <>
        {error && (
          <div className="connection-error" role="alert">
            {error}{' '}

            <button
              className="btn"
              onClick={retryConnection}
            >
              Retry connection
            </button>
          </div>
        )}

        <Auth onLogin={initialize} />
      </>
    );
  }

  return (
    <>
      <aside>
        <div className="brand">
          <span className="logo">a</span>
          {' '}author studio.
        </div>

        <div className="eyebrow">
          YOUR CONTENT DNA
        </div>

        <nav aria-label="Profile sections">
          {pages.map(renderNavigationItem)}
        </nav>

        <div className="sidefoot">
          <b>{user.name}</b>

          <p>{savedCount} of 8 sections saved</p>

          <div className="bar">
            <span
              style={{
                width: `${progressPercentage}%`,
              }}
            />
          </div>

          <p>Unsaved edits survive refresh in this tab.</p>
        </div>
      </aside>

      <main>
        <header>
          <div className="crumb">
            Workspace / <b>Author profile</b>
          </div>

          <div className="header-actions">
            <span className="saved" role="status">
              {statusText}
            </span>

            <button
              className="btn"
              disabled={busy}
              onClick={openReview}
            >
              Review profile
            </button>

            <button
              className="btn"
              disabled={busy}
              onClick={openPublishedPosts}
            >
              View published post
            </button>

            <button
              className="btn primary"
              disabled={busy || startingEngine}
              onClick={runEngine}
            >
              {startingEngine ? 'Starting engine…' : 'Run engine'}
            </button>

            <button
              className="btn quiet"
              disabled={busy}
              onClick={logout}
            >
              Log out
            </button>
          </div>
        </header>

        <div className="content">
          {engineNotice && (
            <p className={engineNotice.error ? 'error' : 'notice'} role={engineNotice.error ? 'alert' : 'status'}>
              {engineNotice.text}
            </p>
          )}

          {storageError && (
            <p className="error" role="alert">
              {storageError}
            </p>
          )}

          {renderContent()}
        </div>
      </main>
    </>
  );
}
