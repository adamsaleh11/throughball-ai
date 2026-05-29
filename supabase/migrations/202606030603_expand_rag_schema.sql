create extension if not exists vector;

alter table documents
    add column if not exists city_id text,
    add column if not exists team_id text,
    add column if not exists source_type text not null default 'seeded';

alter table documents
    alter column source_type set default 'seeded';

update documents
set source_type = 'seeded'
where source_type is null;

alter table documents
    alter column source_type set not null;

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_name = 'document_chunks'
          and column_name = 'content'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_name = 'document_chunks'
          and column_name = 'chunk_text'
    ) then
        alter table document_chunks rename column content to chunk_text;
    end if;
end;
$$;

alter table document_chunks
    add column if not exists updated_at timestamptz not null default now();

alter table document_chunks
    drop constraint if exists document_chunks_content_hash_embedding_model_key;

do $$
begin
    if not exists (
        select 1
        from information_schema.table_constraints
        where table_name = 'document_chunks'
          and constraint_name = 'document_chunks_document_content_hash_model_key'
    ) then
        alter table document_chunks
            add constraint document_chunks_document_content_hash_model_key
            unique (document_id, content_hash, embedding_model);
    end if;
end;
$$;

create table if not exists retrieval_logs (
    id uuid primary key default gen_random_uuid(),
    query_text text,
    top_k integer not null,
    filters jsonb not null default '{}'::jsonb,
    latency_ms integer not null,
    result_count integer not null,
    retrieval_strategy text not null default 'vector',
    created_at timestamptz not null default now()
);

create index if not exists idx_documents_city_id on documents (city_id);
create index if not exists idx_documents_team_id on documents (team_id);
create index if not exists idx_documents_source_type on documents (source_type);
create index if not exists idx_documents_city_category_source
    on documents (city_id, category, source_type);
create index if not exists idx_retrieval_logs_created_at
    on retrieval_logs (created_at);

create or replace function match_document_chunks(
    query_embedding vector(768),
    match_count integer default 5,
    filter_city_id text default null,
    filter_team_id text default null,
    filter_category text default null,
    filter_source_type text default null,
    query_text text default null
)
returns table (
    chunk_id uuid,
    document_id uuid,
    chunk_text text,
    chunk_index integer,
    title text,
    category text,
    city_id text,
    team_id text,
    source_type text,
    source_path text,
    similarity double precision
)
language plpgsql
as $$
declare
    started_at timestamptz := clock_timestamp();
    effective_match_count integer := least(greatest(coalesce(match_count, 5), 1), 20);
    filter_payload jsonb := jsonb_build_object(
        'city_id', filter_city_id,
        'team_id', filter_team_id,
        'category', filter_category,
        'source_type', filter_source_type
    );
begin
    return query
    with matched as materialized (
        select
            dc.id as chunk_id,
            dc.document_id,
            dc.chunk_text,
            dc.chunk_index,
            d.title,
            d.category,
            d.city_id,
            d.team_id,
            d.source_type,
            d.source_path,
            1 - (dc.embedding <=> query_embedding) as similarity
        from document_chunks dc
        join documents d on d.id = dc.document_id
        where dc.is_active = true
          and (filter_city_id is null or d.city_id = filter_city_id)
          and (filter_team_id is null or d.team_id = filter_team_id)
          and (filter_category is null or d.category = filter_category)
          and (filter_source_type is null or d.source_type = filter_source_type)
        order by dc.embedding <=> query_embedding
        limit effective_match_count
    ),
    logged as (
        insert into retrieval_logs (
            query_text,
            top_k,
            filters,
            latency_ms,
            result_count,
            retrieval_strategy
        )
        select
            match_document_chunks.query_text,
            effective_match_count,
            filter_payload,
            greatest(0, floor(extract(epoch from (clock_timestamp() - started_at)) * 1000)::integer),
            count(*)::integer,
            'vector'
        from matched
        returning id
    )
    select
        matched.chunk_id,
        matched.document_id,
        matched.chunk_text,
        matched.chunk_index,
        matched.title,
        matched.category,
        matched.city_id,
        matched.team_id,
        matched.source_type,
        matched.source_path,
        matched.similarity
    from matched;
end;
$$;
