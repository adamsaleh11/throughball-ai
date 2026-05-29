create extension if not exists vector;

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    source_path text not null unique,
    category text not null,
    title text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    source_path text not null,
    category text not null,
    title text not null,
    chunk_index integer not null,
    content text not null,
    content_hash text not null,
    embedding_model text not null,
    embedding vector(768) not null,
    is_active boolean not null default true,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (content_hash, embedding_model)
);

create index if not exists idx_documents_category on documents (category);
create index if not exists idx_document_chunks_document_index_model
    on document_chunks (document_id, chunk_index, embedding_model);
create index if not exists idx_document_chunks_source_path on document_chunks (source_path);
create index if not exists idx_document_chunks_content_hash_model
    on document_chunks (content_hash, embedding_model);
create index if not exists idx_document_chunks_active_category
    on document_chunks (is_active, category);
create index if not exists idx_document_chunks_embedding
    on document_chunks using ivfflat (embedding vector_cosine_ops);
