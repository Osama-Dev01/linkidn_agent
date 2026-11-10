// import React from 'react';
// import { pages } from './schema';
// import { fieldsOf, visible } from './profile';

// function Answers({ fields, values }) {
//   return <dl className="answers">{fields.filter(field => visible(field.key, values)).map(field => {
//     const value = values[field.key];
//     if (value == null || value === '' || Array.isArray(value) && !value.length) return null;
//     return <div key={field.key}><dt>{field.label}</dt><dd>{Array.isArray(value)
//       ? <div className="chips">{value.map((item, i) => <span className="answer-tag" key={i}>{item}</span>)}</div> : String(value)}</dd></div>;
//   })}</dl>;
// }

// export default function Review({ user, profile, onEdit }) {
//   const count = Object.keys(profile.sections).length;
//   return <><div className="step">YOUR AUTHOR PROFILE</div><h1>Your voice, in one place.</h1><p className="intro">Your saved profile, fetched from your account.</p>
//     <section className="profile-banner"><div className="profile-avatar">{user.name[0].toUpperCase()}</div><div><h2>{profile.sections.identity?.name || user.name}</h2>
//       <p>{profile.sections.identity?.professional_role || 'Your author profile starts here'}</p><small>{user.email}</small></div><span className="saved-badge">{count} / 8 sections saved</span></section>
//     <div className="review-grid">{pages.map((page, index) => {
//       const values = profile.sections[page.key];
//       return <section className="card review-card" key={page.key}><div className="review-heading"><h2><span className="section-number">{String(index + 1).padStart(2, '0')}</span>{page.label}</h2>
//         <button className="btn quiet" onClick={() => onEdit(index)}>{values ? 'Edit' : 'Add details'} →</button></div>
//         {!values ? <p className="sub">You haven’t saved this section yet.</p> : page.repeat ? values.items.length ? values.items.map((item, i) => <div className="review-record" key={item.id}>
//           <h3>{page.item} {i + 1}</h3><Answers fields={page.fields} values={item} /></div>) : <p className="sub">No {page.label.toLowerCase()} added.</p> : <Answers fields={fieldsOf(page)} values={values} />}
//       </section>;
//     })}</div><small className="account-id">Account ID: {user.user_id}</small></>;
// }


import React from 'react';

import { pages } from './schema';
import { fieldsOf, visible } from './profile';

function Answers({ fields, values }) {
  const visibleFields = fields.filter(function (field) {
    return visible(field.key, values);
  });

  function renderTag(item, index) {
    return (
      <span className="answer-tag" key={index}>
        {item}
      </span>
    );
  }

  function renderValue(value) {
    if (Array.isArray(value)) {
      return (
        <div className="chips">
          {value.map(renderTag)}
        </div>
      );
    }

    return String(value);
  }

  function renderAnswer(field) {
    const value = values[field.key];

    if (value === null || value === undefined || value === '') {
      return null;
    }

    if (Array.isArray(value) && value.length === 0) {
      return null;
    }

    return (
      <div key={field.key}>
        <dt>{field.label}</dt>
        <dd>{renderValue(value)}</dd>
      </div>
    );
  }

  return (
    <dl className="answers">
      {visibleFields.map(renderAnswer)}
    </dl>
  );
}

export default function Review({ user, profile, onEdit }) {
  const sectionKeys = Object.keys(profile.sections);
  const count = sectionKeys.length;

  const firstLetter = user.name[0];
  const avatarLetter = firstLetter.toUpperCase();

  const displayName = profile.sections.identity?.name || user.name;

  const professionalRole =
    profile.sections.identity?.professional_role ||
    'Your author profile starts here';

  function renderSectionContent(page, values) {
    if (!values) {
      return (
        <p className="sub">
          You haven’t saved this section yet.
        </p>
      );
    }

    if (!page.repeat) {
      const fields = fieldsOf(page);

      return (
        <Answers
          fields={fields}
          values={values}
        />
      );
    }

    if (values.items.length === 0) {
      const sectionName = page.label.toLowerCase();

      return (
        <p className="sub">
          No {sectionName} added.
        </p>
      );
    }

    function renderRecord(item, index) {
      return (
        <div className="review-record" key={item.id}>
          <h3>
            {page.item} {index + 1}
          </h3>

          <Answers
            fields={page.fields}
            values={item}
          />
        </div>
      );
    }

    return values.items.map(renderRecord);
  }

  function renderSection(page, index) {
    const values = profile.sections[page.key];
    const sectionNumber = String(index + 1).padStart(2, '0');

    let buttonText = 'Add details';

    if (values) {
      buttonText = 'Edit';
    }

    function handleEdit() {
      onEdit(index);
    }

    return (
      <section className="card review-card" key={page.key}>
        <div className="review-heading">
          <h2>
            <span className="section-number">
              {sectionNumber}
            </span>

            {page.label}
          </h2>

          <button
            className="btn quiet"
            onClick={handleEdit}
          >
            {buttonText} →
          </button>
        </div>

        {renderSectionContent(page, values)}
      </section>
    );
  }

  return (
    <>
      <div className="step">
        YOUR AUTHOR PROFILE
      </div>

      <h1>Your voice, in one place.</h1>

      <p className="intro">
        Your saved profile, fetched from your account.
      </p>

      <section className="profile-banner">
        <div className="profile-avatar">
          {avatarLetter}
        </div>

        <div>
          <h2>{displayName}</h2>
          <p>{professionalRole}</p>
          <small>{user.email}</small>
        </div>

        <span className="saved-badge">
          {count} / 8 sections saved
        </span>
      </section>

      <div className="review-grid">
        {pages.map(renderSection)}
      </div>

      <small className="account-id">
        Account ID: {user.user_id}
      </small>
    </>
  );
}