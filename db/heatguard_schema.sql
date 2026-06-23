-- HeatGuard 스키마 (자가호스트 sts 서버 PostgreSQL16 공용용)
-- STS Supabase 에 적용한 마이그레이션 전체를 집약. sts 로컬 PG(5433)에 heatguard 스키마로 생성.
-- 실행(서버): sudo -u postgres psql -p 5433 -d <STS_DB> -f heatguard_schema.sql
-- 또는 STS .env 의 DATABASE_URL 역할(kweather)로 실행. 마지막 GRANT 의 역할명은 환경에 맞게.

create schema if not exists heatguard;

create table if not exists heatguard.tenants(
  id bigserial primary key,
  email text unique,
  password_hash text,
  api_key text unique not null,
  name text,
  is_demo boolean not null default false,
  is_admin boolean not null default false,
  plan text,
  sub_status text not null default 'none',
  kw_user_id text,
  kw_api_key text,                 -- 암호화 저장(Fernet, 'enc:' 접두)
  plan_started_at timestamptz,
  plan_renews_at timestamptz,
  pg_provider text,
  billing_key text,                -- 암호화 저장
  card_name text,
  next_billing_at timestamptz,
  last_paid_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists heatguard.sites(
  id bigserial primary key,
  tenant_id bigint not null references heatguard.tenants(id) on delete cascade,
  name text not null,
  region text,
  address text,
  created_at timestamptz not null default now()
);

create table if not exists heatguard.devices(
  id bigserial primary key,
  tenant_id bigint not null references heatguard.tenants(id) on delete cascade,
  site_id bigint references heatguard.sites(id) on delete set null,
  serial text not null,
  name text,
  kind text not null default 'outdoor',
  model text,
  device_type text,
  location text,
  source text not null default 'kweather',
  created_at timestamptz not null default now(),
  constraint uq_devices_tenant_serial unique(tenant_id, serial)
);

create table if not exists heatguard.payments(
  id bigserial primary key,
  tenant_id bigint not null references heatguard.tenants(id) on delete cascade,
  provider text not null default 'mobilians',
  plan text,
  amount bigint not null,
  status text not null default 'pending',
  method text,
  pg_tid text,
  message text,
  created_at timestamptz not null default now()
);
create index if not exists ix_payments_tenant on heatguard.payments(tenant_id, created_at desc);

create table if not exists heatguard.sensor_logs(
  id bigserial primary key,
  tenant_id bigint not null references heatguard.tenants(id) on delete cascade,
  serial text not null,
  measured_at timestamptz not null,
  temperature double precision,
  humidity double precision,
  feels_like double precision,
  recorded_at timestamptz not null default now(),
  constraint uq_sensorlog unique(tenant_id, serial, measured_at)
);
create index if not exists ix_sensorlog on heatguard.sensor_logs(tenant_id, serial, measured_at desc);

-- 데모 계정 + 데모 사업장/기기 시드
insert into heatguard.tenants(email, password_hash, api_key, name, is_demo, sub_status)
values ('demo@heatguard.local', null, 'demo-key', '데모 사업장', true, 'demo')
on conflict (api_key) do nothing;

insert into heatguard.sites(tenant_id, name, region, address)
select t.id, '데모 제1사업장', '수도권', '서울특별시 금천구' from heatguard.tenants t
where t.api_key='demo-key' and not exists (select 1 from heatguard.sites s where s.tenant_id=t.id and s.name='데모 제1사업장');
insert into heatguard.sites(tenant_id, name, region, address)
select t.id, '데모 제2사업장', '영남', '부산광역시 사상구' from heatguard.tenants t
where t.api_key='demo-key' and not exists (select 1 from heatguard.sites s where s.tenant_id=t.id and s.name='데모 제2사업장');

insert into heatguard.devices(tenant_id, serial, name, kind, model, device_type, source, site_id)
select t.id, d.serial, d.name, d.kind, d.model, d.dtype, 'demo',
       (select s.id from heatguard.sites s where s.tenant_id=t.id and s.name=d.site)
from heatguard.tenants t,
(values
  ('HG-IN-001','용해로 작업동(밀폐)','indoor','실내 공기질','실내공기질(IAQ)','데모 제1사업장'),
  ('HG-IN-002','사무동 휴게실','indoor','실내 체감온도계','실내공기질(IAQ)','데모 제1사업장'),
  ('HG-OUT-001','A현장 옥외작업장','outdoor','실외 체감온도계','실외대기(OAQ)','데모 제2사업장'),
  ('HG-OUT-002','B현장 자재야적장','outdoor','실외 미세먼지','실외대기(OAQ)','데모 제2사업장')
) as d(serial,name,kind,model,dtype,site)
where t.api_key='demo-key'
on conflict (tenant_id, serial) do nothing;

-- 앱 접속 역할에 권한 부여 (sts 환경의 역할명으로 교체: 예) kweather
-- grant usage, create on schema heatguard to kweather;
-- grant all privileges on all tables in schema heatguard to kweather;
-- grant all privileges on all sequences in schema heatguard to kweather;
-- alter default privileges in schema heatguard grant all on tables to kweather;
-- alter default privileges in schema heatguard grant all on sequences to kweather;
