-- Andes Travel PoC: data for the watsonx Orchestrate tools API (src/andes/apps/tools_api).
--
-- Apply in the Supabase SQL editor (or psql) once, then load supabase/seed.sql.
-- The tools API connects with the database owner role, which bypasses row level
-- security. RLS is enabled with no policies so the Supabase public REST/GraphQL
-- endpoints (anon and authenticated keys) cannot read or write any of these tables.

create table if not exists packages (
    id              uuid primary key,
    destination     text   not null,
    name            text   not null,
    description     text   not null,
    duration_days   int    not null check (duration_days > 0),
    tags            text[] not null default '{}',
    rate_per_person bigint not null check (rate_per_person > 0),
    currency        text   not null default 'COP',
    active          boolean not null default true
);

-- traveler_id is the normalized e-mail (lowercase) or phone (E.164) the traveler gives.
create table if not exists travelers (
    id         text primary key,
    created_at timestamptz not null default now()
);

create table if not exists traveler_profiles (
    traveler_id             text primary key references travelers (id) on delete cascade,
    attributes              jsonb not null default '{}'::jsonb,
    persona_prompt          text check (char_length(persona_prompt) <= 600),
    consent_personalization boolean not null default false,
    consent_at              timestamptz,
    updated_at              timestamptz not null default now()
);

create table if not exists quotes (
    id           uuid primary key,
    traveler_id  text   not null references travelers (id) on delete cascade,
    package_id   uuid   not null references packages (id),
    start_date   date   not null,
    end_date     date   not null check (end_date > start_date),
    travelers    int    not null check (travelers between 1 and 20),
    lines        jsonb  not null,
    total_amount bigint not null,
    currency     text   not null,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null
);
create index if not exists quotes_traveler_idx on quotes (traveler_id);

create table if not exists reservations (
    id                uuid primary key,
    traveler_id       text   not null references travelers (id) on delete cascade,
    quote_id          uuid   not null references quotes (id),
    idempotency_key   text   not null unique,
    status            text   not null,
    total_amount      bigint not null,
    currency          text   not null,
    commission_amount bigint not null,
    created_at        timestamptz not null default now()
);
create index if not exists reservations_traveler_idx on reservations (traveler_id);

create table if not exists handoffs (
    id          uuid primary key,
    traveler_id text references travelers (id) on delete cascade,
    reason      text not null,
    summary     text not null,
    status      text not null default 'queued',
    created_at  timestamptz not null default now()
);

alter table packages          enable row level security;
alter table travelers         enable row level security;
alter table traveler_profiles enable row level security;
alter table quotes            enable row level security;
alter table reservations      enable row level security;
alter table handoffs          enable row level security;
