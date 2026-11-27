-- NEÜ Kardiyoloji web sitesi: Supabase şeması (taslak)
-- Supabase projesini EU (Frankfurt, eu-central-1) bölgesinde oluşturun.
-- SQL Editor'da çalıştırın. RLS tüm tablolarda açıktır.

-- ===== Kullanıcı profilleri ve roller =====
create type app_role as enum ('admin', 'editor', 'researcher', 'member');

create table profiles (
  id uuid primary key references auth.users on delete cascade,
  full_name text,
  role app_role not null default 'member',
  created_at timestamptz not null default now()
);

create or replace function has_role(r app_role) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where id = auth.uid() and (role = r or role = 'admin'));
$$;

-- ===== Haberler ve literatür (herkese açık okuma) =====
create table news (
  id bigint generated always as identity primary key,
  slug text unique not null,
  title text not null,
  summary text,
  body text,
  published boolean not null default false,
  published_at timestamptz,
  created_by uuid references profiles(id)
);

create table literature (
  id bigint generated always as identity primary key,
  title text not null,
  journal text,
  topic text,
  summary text,
  url text,
  published boolean not null default false,
  published_at timestamptz,
  created_by uuid references profiles(id)
);

-- ===== Soru bankası (Streamlit şemasıyla uyumlu) =====
create table questions (
  id text primary key,               -- SoruID
  active boolean not null default true,  -- Aktif
  category text not null,            -- Kategori
  text text not null,                -- Soru
  option_a text, option_b text, option_c text, option_d text, option_e text,
  correct char(1) not null check (correct in ('A','B','C','D','E')), -- Dogru
  explanation text,                  -- Aciklama
  source text,                       -- Kaynak
  media_kind text check (media_kind in ('photo','video')),
  media_path text                    -- Supabase Storage yolu (GorselDosya / VideoDosya)
);

create table quiz_attempts (
  id bigint generated always as identity primary key,
  user_id uuid not null references profiles(id) on delete cascade,
  question_id text not null references questions(id) on delete cascade,
  picked char(1) not null,
  is_correct boolean not null,
  created_at timestamptz not null default now()
);

-- ===== Klinik çalışmalar =====
create table studies (
  id bigint generated always as identity primary key,
  slug text unique not null,
  title text not null,
  area text,
  summary text,
  participant_info text,               -- etik kurulun onayladığı bilgilendirme metni
  ethics_committee text,
  ethics_approval_no text,             -- girilmeden veri girişi kapalı
  ethics_approval_date date,
  status text not null default 'hazırlık' check (status in ('hazırlık','aktif','tamamlandı')),
  subject_code_prefix text not null    -- ör. 'HT' -> HT-001
);

create table study_members (
  study_id bigint references studies(id) on delete cascade,
  user_id uuid references profiles(id) on delete cascade,
  primary key (study_id, user_id)
);

-- Sadece anonim veri: kimlik/telefon/dosya no sütunu YOK.
create table study_records (
  id bigint generated always as identity primary key,
  study_id bigint not null references studies(id) on delete restrict,
  subject_code text not null,          -- takma kod; eşleştirme listesi sitede tutulmaz
  visit text not null,
  data jsonb not null default '{}'::jsonb,
  created_by uuid not null references profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (study_id, subject_code, visit),
  check (subject_code ~ '^[A-Z]{2,6}-[0-9]{3,5}$')
);

create table audit_log (
  id bigint generated always as identity primary key,
  user_id uuid,
  action text not null,                -- insert / update / delete
  table_name text not null,
  record_id bigint,
  at timestamptz not null default now()
);

create or replace function log_study_record() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into audit_log (user_id, action, table_name, record_id)
  values (auth.uid(), lower(tg_op), 'study_records', coalesce(new.id, old.id));
  return coalesce(new, old);
end $$;

create trigger study_records_audit
after insert or update or delete on study_records
for each row execute function log_study_record();

create or replace function is_study_member(sid bigint) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from study_members where study_id = sid and user_id = auth.uid())
      or has_role('admin');
$$;

create or replace function study_ethics_ok(sid bigint) returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from studies where id = sid and coalesce(ethics_approval_no, '') <> '');
$$;

-- ===== RLS =====
alter table profiles enable row level security;
alter table news enable row level security;
alter table literature enable row level security;
alter table questions enable row level security;
alter table quiz_attempts enable row level security;
alter table studies enable row level security;
alter table study_members enable row level security;
alter table study_records enable row level security;
alter table audit_log enable row level security;

create policy "profil: kendi" on profiles for select using (id = auth.uid() or has_role('admin'));

create policy "haber: yayındakini herkes okur" on news for select using (published or has_role('editor'));
create policy "haber: editör yazar" on news for all using (has_role('editor')) with check (has_role('editor'));

create policy "literatür: yayındakini herkes okur" on literature for select using (published or has_role('editor'));
create policy "literatür: editör yazar" on literature for all using (has_role('editor')) with check (has_role('editor'));

create policy "soru: aktifleri herkes okur" on questions for select using (active or has_role('editor'));
create policy "soru: editör yazar" on questions for all using (has_role('editor')) with check (has_role('editor'));

create policy "deneme: kendi" on quiz_attempts for all using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy "çalışma: herkes okur" on studies for select using (true);
create policy "çalışma: admin yazar" on studies for all using (has_role('admin')) with check (has_role('admin'));

create policy "üyelik: kendi veya admin" on study_members for select using (user_id = auth.uid() or has_role('admin'));
create policy "üyelik: admin yazar" on study_members for all using (has_role('admin')) with check (has_role('admin'));

create policy "kayıt: üye okur" on study_records for select using (is_study_member(study_id));
create policy "kayıt: üye + etik onay ile ekler" on study_records for insert
  with check (is_study_member(study_id) and study_ethics_ok(study_id) and created_by = auth.uid());
create policy "kayıt: üye düzenler" on study_records for update
  using (is_study_member(study_id)) with check (is_study_member(study_id) and study_ethics_ok(study_id));
create policy "kayıt: sadece admin siler" on study_records for delete using (has_role('admin'));

create policy "denetim: admin okur" on audit_log for select using (has_role('admin'));
