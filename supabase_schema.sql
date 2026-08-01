create table if not exists public.fixed_schedule (
    mode text not null check (mode in ('day', 'week')),
    profile text not null check (
        profile in ('部活なし', '部活あり', 'デフォルト３', 'デフォルト４', 'デフォルト５')
    ),
    slot_minutes integer not null check (slot_minutes in (60, 30, 20, 15, 10, 5)),
    fixed_grid jsonb not null,
    block_recoveries jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    primary key (mode, profile)
);

alter table public.fixed_schedule enable row level security;

-- Data APIの「Automatically expose new tables」を無効にした場合も、
-- StreamlitサーバーのSecret keyだけはこのテーブルを読み書きできるようにする。
grant usage on schema public to service_role;
grant select, insert, update, delete on table public.fixed_schedule to service_role;

-- 公開用のPublishable keyでは、固定時間の読込・新規保存・上書きだけを許可する。
-- 行の削除や、ほかのテーブルへのアクセスは許可しない。
grant usage on schema public to anon;
grant select, insert, update on table public.fixed_schedule to anon;

drop policy if exists "Anyone can read fixed schedules" on public.fixed_schedule;
create policy "Anyone can read fixed schedules"
on public.fixed_schedule for select to anon
using (true);

drop policy if exists "Anyone can insert fixed schedules" on public.fixed_schedule;
create policy "Anyone can insert fixed schedules"
on public.fixed_schedule for insert to anon
with check (
    mode in ('day', 'week')
    and profile in ('部活なし', '部活あり', 'デフォルト３', 'デフォルト４', 'デフォルト５')
);

drop policy if exists "Anyone can update fixed schedules" on public.fixed_schedule;
create policy "Anyone can update fixed schedules"
on public.fixed_schedule for update to anon
using (true)
with check (
    mode in ('day', 'week')
    and profile in ('部活なし', '部活あり', 'デフォルト３', 'デフォルト４', 'デフォルト５')
);

-- このアプリはStreamlitサーバー側のSecretsに保存したSecret keyで接続します。
-- Secret keyはRLSを迂回するため、ブラウザやGitHubへ公開しないでください。
