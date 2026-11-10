# Profile storage schema

This is the proposed MongoDB storage contract for the current React form. It is a design document, not an installed database validator or implemented API. No profile or preference versions are needed.

## Collections

| Collection | Purpose | Cardinality |
| --- | --- | --- |
| `users` | Account identity and authentication | One document per user |
| `profiles` | Explicit inputs submitted through the profile form | One document per user |

Keep login credentials out of `profiles` and out of profile API responses. Embed writing samples, stances, and experiences because the current form caps each collection at 20 records.

## Notation and missing values

The shapes below use TypeScript-style notation to describe MongoDB documents; they are not JSON examples. `?` means optional. `Date` means a MongoDB BSON date, serialized as an ISO timestamp in API responses. IDs are backend-generated UUID strings; MongoDB also generates its own `_id` ObjectId.

- A section may be absent until the user saves it. If present, all its required fields must be valid. Do not insert empty objects as saved sections.
- Optional text and numbers are omitted when blank. Optional lists can be empty arrays.
- An absent repeatable section means it has not been saved; `{ items: [] }` means the user saved an empty collection.
- Conditional fields must be omitted when their controlling option no longer applies.
- Store tags, multi-selects, and one-item-per-line inputs as arrays of strings, not comma-separated text.
- Browser draft storage is temporary; MongoDB is the source for saved profile data.

## Account document: `users`

```ts
type User = {
  _id: ObjectId;
  user_id: string;           // Generated UUID; immutable public account identifier
  name: string;              // Required registration name
  email: string;             // Required; trim and normalize consistently at login/register
  password_hash: string;     // Salted password hash; never store the submitted password
  created_at: Date;          // Server-generated
  updated_at: Date;          // Server-generated
};
```

Registration accepts `name`, `email`, and `password`. Password length is 10–128 characters. `password` is an API input only and must not be stored or returned. Account `name` is the registration name; `identity.name` below is the author name and may differ. The profile editor owns `identity.name`.

## Profile document: `profiles`

Keep the current frontend section keys and field names so the API does not need a second field mapping. Preferences remain one object, grouped logically below with comments.

```ts
type Profile = {
  _id: ObjectId;
  user_id: string;           // Required; references users.user_id; unique
  identity?: Identity;
  expertise?: Expertise;
  audience?: Audience;
  interests?: Interests;
  preferences?: Preferences;
  writing_samples?: { items: WritingSample[] };
  stances?: { items: Stance[] };
  experiences?: { items: Experience[] };
  created_at: Date;
  updated_at: Date;
};

type Identity = {
  name: string;
  professional_role: string;
  industry: string[];        // At least one
  background: string;
  public_positioning: string;
  default_speaker_role: "Practitioner" | "Learner" | "Critic" | "Observer";
};

type Expertise = {
  experienced_topics?: string[];
  experienced_notes?: string;
  learning_topics?: string[];
  learning_notes?: string;
  // At least one experienced_topics OR learning_topics entry is required.
};

type Audience = {
  target_audience: string[]; // At least one; custom values allowed
  audience_level: "Beginner" | "Intermediate" | "Advanced" | "Mixed";
  audience_problems: string[]; // At least one
  posting_goals: ("Share knowledge" | "Build credibility" | "Find jobs" |
    "Attract clients" | "Grow network" | "Start discussions" | "Document learning")[];
  content_themes: string[];  // 3–6
};

type Interests = {
  primary_topics: string[];  // At least one
  secondary_topics?: string[];
  hard_excluded_topics?: string[];
  soft_excluded_topics?: string[];
  preferred_content_types: ("Tutorial" | "Explainer" | "News analysis" | "Opinion" |
    "Case study" | "Project breakdown" | "Personal lesson" | "Research summary" |
    "Tool comparison")[];
  search_keywords?: string[];
  preferred_sources?: string[];  // Source names or URLs
  distrusted_sources?: string[];
  freshness: "Timely" | "Evergreen" | "Balanced";
  recency_window?: number;   // Integer 1–365; REQUIRED for Timely/Balanced
};

type Preferences = {
  // Voice
  tone: ("Professional" | "Conversational" | "Thoughtful" | "Direct" |
    "Curious" | "Witty" | "Encouraging")[];
  formality: "Casual" | "Balanced" | "Formal";
  point_of_view: "First person" | "Third person" | "Depends on content";
  technical_depth: "Accessible" | "Moderately technical" | "Deeply technical" | "Adapt to audience";
  voice_instructions?: string;

  // Structure
  preferred_opening: ("Direct statement" | "Question" | "Personal observation" |
    "Problem" | "Evidence-backed fact")[];
  preferred_organisation: ("Problem → solution" | "Story → lesson" | "Step-by-step" |
    "Claim → evidence" | "Comparison")[];
  post_length: "Short" | "Medium" | "Long" | "Custom";
  word_range?: string;       // REQUIRED for Custom; e.g. "100-200"
  closing_style: ("Practical takeaway" | "Open question" | "Summary" |
    "Call to action" | "No fixed closing")[];

  // Formatting
  paragraph_style: "Short" | "Mixed lengths" | "No preference";
  lists: "Prefer" | "When helpful" | "Avoid";
  emojis: "None" | "Occasional" | "Frequent";
  hashtags: "None" | "Limited" | "Automatic";
  hashtag_max?: number;      // Integer 0–30; REQUIRED for Limited
  citations: "Inline references" | "Sources at end" | "Decide per post";

  // Topic selection and research
  preferred_angles?: string[];
  repeat_policy: "Avoid repeats" | "Allow a new angle" | "Allow substantial updates";
  cooldown_days?: number;    // Integer 0–3650
  research_depth: "Quick overview" | "Standard" | "Deep research";
  minimum_sources: number;   // Integer 1–20
  preferred_evidence: ("Official documentation" | "Research papers" |
    "First-hand reports" | "Reproducible tests" | "Reputable reporting")[];
  uncertain_claims: "Omit" | "Include with qualification" | "Ask me";

  // Anti-style
  avoided_phrases?: string[];
  avoided_patterns?: string[];
  additional_restrictions?: string;
};

type UsagePermission = "May use in drafts" | "Ask before using" | "Private context only";

type WritingSample = {
  id: string;               // Stable record UUID; retain on edits
  text: string;
  content_type: "LinkedIn post" | "Article" | "Comment" | "Email" | "Other";
  authorship: "Written by me" | "AI-assisted and edited by me" |
    "Written by someone else" | "Mixed / unknown";
  sounds_like_me: "Yes" | "Partly" | "No";
  notes?: string;
};

type Stance = {
  id: string;
  topic: string;
  position: string;
  reasoning: string;
  conditions?: string[];
  exceptions?: string[];
  permission_to_share: UsagePermission;
};

type Experience = {
  id: string;
  situation: string;
  personal_role: string;
  actions: string[];         // At least one
  outcome?: string;         // Unknown outcomes remain absent; never invent them
  lesson: string;
  permitted_details?: ("Role" | "Actions" | "Outcomes" | "Exact metrics" |
    "Organisation name" | "Client name" | "Dates")[];
  usage_permission: UsagePermission;
  anonymisation?: string;
};
```

## Validation contract

Validate on the backend, even when the frontend has already validated.

- Reject unknown fields, including removed language/region, tools/boundaries, and discovery preference fields.
- Required strings must contain non-whitespace text. Trim submitted strings.
- Profile text fields have a maximum of 10,000 characters; array strings have a maximum of 300 characters each. Arrays have a maximum of 50 entries, except content themes (3–6) and repeatable records (20).
- Required arrays must contain at least one valid entry. Optional arrays may be empty. Reject blank entries and options outside their declared enum. Tag inputs accept custom values.
- Check the expertise either/or requirement and all three conditional fields on every section save.
- For `word_range`, require `min-max` integers with `1 <= min <= max <= 10000`.
- For repeated records, validate every item and require unique, stable item IDs within that section. Assign IDs to new records on the backend; do not regenerate them on reads or edits.
- Missing `permitted_details` grants no detail-sharing permission. Usage permissions and anonymisation apply in addition to the allowed details.

## Indexes

```python
db.users.create_index("user_id", unique=True)
db.users.create_index("email", unique=True)
db.profiles.create_index("user_id", unique=True)
```

MongoDB does not enforce the reference between these collections. The API must create and access profiles only for an existing authenticated account.

## Save and fetch flow

1. Register: validate credentials, generate `user_id`, hash the password, insert the account. A profile may be created lazily on the first section save.
2. Save section: obtain `user_id` from the authenticated session, allow only the eight declared section names, validate the complete submitted section, then replace that section atomically.
3. Use `$set` for the validated section and `updated_at`; use `$setOnInsert` for `user_id` and `created_at`. Filter every read/update by the authenticated `user_id` and use upsert for first save. Handle duplicate-key conflicts from simultaneous first saves by retrying the update without upsert.
4. Replace a whole section rather than merging arbitrary nested keys. This removes cleared optional fields and obsolete conditional values without touching other sections.
5. Fetch profile: load by authenticated `user_id`. If none exists, return an empty onboarding state. Return profile data without credentials or MongoDB internals.
6. Review: display the saved profile returned by the server. Derive completion from saved, valid sections rather than storing another boolean that can become stale.

The proposed API remains compatible with the frontend's section shape: ordinary sections submit an object, repeatable sections submit `{ "items": [...] }`. IDs, timestamps, and ownership are server-controlled. Concurrent edits to the same section use last-save-wins for this initial implementation.

## Keep future system data separate

Do not write inferred preferences over explicit user choices. When implemented, store system-learned preferences in a separate `learned_preferences` collection keyed uniquely by `user_id`; explicit profile choices take precedence. Learned rules must not grant permissions the user has not given.

Published posts/topics and their short summaries should be separate documents in a `published_posts` collection keyed by `user_id`, because that history grows without a small fixed bound. Checkpoints belong in the workflow checkpointer's storage, scoped to the user and workflow run. Neither history nor checkpoint data belongs in this onboarding profile document.

Authentication sessions are also separate from profiles. No profile versions, preference versions, or additional onboarding inputs are introduced by this design.
