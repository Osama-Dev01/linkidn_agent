import React from 'react';

export default function PublishedPosts({ posts }) {
  return (
    <>
      <div className="step">YOUR PUBLISHED POSTS</div>
      <h1>Published on LinkedIn</h1>
      <p className="intro">Your published post titles and content, newest first.</p>
      {posts.length === 0 && <p>No published posts yet.</p>}
      {posts.map(post => (
        <article className="card" key={post.post_id}>
          <h2>{post.title}</h2>
          <p className="published-post-content">{post.final_text}</p>
        </article>
      ))}
    </>
  );
}
