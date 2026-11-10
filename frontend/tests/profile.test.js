import assert from 'node:assert/strict';
import { pages } from '../src/schema.js';
import { payload, validatePage } from '../src/profile.js';

assert.ok(Object.keys(validatePage(pages[0], {})).length === 6);
assert.ok(validatePage(pages[1], {}).experienced_topics);
assert.deepEqual(validatePage(pages[1], { learning_topics: ['AI'] }), {});
assert.ok(validatePage(pages[2], { content_themes: ['AI'] }).content_themes);
assert.ok(validatePage(pages[3], { primary_topics: ['AI'], preferred_content_types: ['Tutorial'], freshness: 'Timely' }).recency_window);
assert.equal(payload(pages[3], { freshness: 'Evergreen', recency_window: 20, arbitrary: 'ignore' }).recency_window, undefined);
assert.ok(validatePage(pages[4], { post_length: 'Custom', word_range: '200-10' }).word_range);
assert.ok(validatePage(pages[4], { hashtags: 'Limited' }).hashtag_max);
assert.ok(validatePage(pages[6], { items: [{ id: '1', topic: 'AI' }] })['0.permission_to_share']);
assert.deepEqual(validatePage(pages[6], { items: [] }), {});
assert.deepEqual(payload(pages[1], { learning_topics: [' AI ', ''], learning_notes: '  ' }), { learning_topics: ['AI'] });
console.log('10 frontend validation checks passed.');
