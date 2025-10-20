from typing import Any, Literal
from pydantic import BaseModel, Field
from enum import Enum


class Credentials(BaseModel):
    deployment: Literal["Weaviate", "Docker", "Local", "Custom"]
    url: str
    key: str


class ConversationItem(BaseModel):
    type: str
    content: str


class ChunksPayload(BaseModel):
    uuid: str
    page: int
    pageSize: int
    credentials: Credentials


class GetChunkPayload(BaseModel):
    uuid: str
    embedder: str
    credentials: Credentials


class GetVectorPayload(BaseModel):
    uuid: str
    showAll: bool
    credentials: Credentials


class ConnectPayload(BaseModel):
    credentials: Credentials
    port: str


class DataBatchPayload(BaseModel):
    chunk: str
    isLastChunk: bool
    total: int
    fileID: str
    order: int
    credentials: Credentials


class LoadPayload(BaseModel):
    reader: str
    chunker: str
    embedder: str
    fileBytes: list[str]
    fileNames: list[str]
    filePath: str
    document_type: str
    chunkUnits: int
    chunkOverlap: int


class ImportPayload(BaseModel):
    data: list
    textValues: list[str]
    config: dict


class GetComponentPayload(BaseModel):
    component: str


class SetComponentPayload(BaseModel):
    component: str
    selected_component: str


# Import


class FileStatus(str, Enum):
    READY = "READY"
    CREATE_NEW = "CREATE_NEW"
    STARTING = "STARTING"
    LOADING = "LOADING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    INGESTING = "INGESTING"
    NER = "NER"
    EXTRACTION = "EXTRACTION"
    SUMMARIZING = "SUMMARIZING"
    DONE = "DONE"
    ERROR = "ERROR"


class ConfigSetting(BaseModel):
    type: str
    value: str | int
    description: str
    values: list[str]


class RAGComponentConfig(BaseModel):
    name: str
    variables: list[str]
    library: list[str]
    description: str
    config: dict[str, ConfigSetting]
    type: str
    available: bool


class RAGComponentClass(BaseModel):
    selected: str
    components: dict[str, RAGComponentConfig]


class RAGConfig(BaseModel):
    Reader: RAGComponentClass
    Chunker: RAGComponentClass
    Embedder: RAGComponentClass
    Retriever: RAGComponentClass
    Generator: RAGComponentClass


class StatusReport(BaseModel):
    fileID: str
    status: str
    message: str
    took: float


class CreateNewDocument(BaseModel):
    new_file_id: str
    filename: str
    original_file_id: str


class FileConfig(BaseModel):
    fileID: str
    filename: str
    isURL: bool
    overwrite: bool
    extension: str
    source: str
    content: str
    labels: list[str]
    rag_config: dict[str, RAGComponentClass]
    file_size: int
    status: FileStatus
    metadata: str
    status_report: dict


class ImportStreamPayload(BaseModel):
    fileMap: dict[str, FileConfig]


class VerbaConfig(BaseModel):
    RAG: dict[str, RAGComponentClass]
    SETTING: dict


class DocumentFilter(BaseModel):
    title: str
    uuid: str


class GetSuggestionsPayload(BaseModel):
    query: str
    limit: int
    credentials: Credentials


class DeleteSuggestionPayload(BaseModel):
    uuid: str
    credentials: Credentials


class GetAllSuggestionsPayload(BaseModel):
    page: int
    pageSize: int
    credentials: Credentials


class QueryPayload(BaseModel):
    query: str
    RAG: dict[str, RAGComponentClass]
    labels: list[str]
    documentFilter: list[DocumentFilter]
    credentials: Credentials


class DatacountPayload(BaseModel):
    embedding_model: str
    documentFilter: list[DocumentFilter]
    credentials: Credentials


class SetRAGConfigPayload(BaseModel):
    rag_config: RAGConfig
    credentials: Credentials


class SetUserConfigPayload(BaseModel):
    user_config: dict
    credentials: Credentials


class SetThemeConfigPayload(BaseModel):
    theme: dict
    themes: dict
    credentials: Credentials


class ChunkScore(BaseModel):
    uuid: str
    score: float
    chunk_id: int
    embedder: str


class GetContentPayload(BaseModel):
    uuid: str
    page: int
    chunkScores: list[ChunkScore]
    credentials: Credentials


class GeneratePayload(BaseModel):
    query: str
    context: str
    conversation: list[ConversationItem]
    rag_config: dict[str, RAGComponentClass]


class ConfigPayload(BaseModel):
    config: VerbaConfig


class RAGConfigPayload(BaseModel):
    config: VerbaConfig


class SearchQueryPayload(BaseModel):
    query: str
    labels: list[str]
    page: int
    pageSize: int
    credentials: Credentials


class GetDocumentPayload(BaseModel):
    uuid: str
    credentials: Credentials


class UpdateDocumentLabelsPayload(BaseModel):
    uuid: str
    labels: list[str]
    credentials: Credentials


class ResetPayload(BaseModel):
    resetMode: str
    credentials: Credentials




class GeneratePartReq(BaseModel):
    series: str = Field(..., pattern=r"^\d{3}$")
    revision: str | None = Field(None, pattern=r"^\d{2}$")
    detail_prefix: str | None = Field(None, pattern=r"^\d{1,4}$")
    note: str | None = None
    created_by: str | None = None
    description: str | None = None
    customer_id: str | None = None
    attrs: dict[str, Any] | None = None
    vendor_id: int | None = None
    drawing: str | None = None
    base_key: str | None = None
    rma_no: str | None = None


class GeneratePartResp(BaseModel):
    part_no: str
    series: str
    serial: int
    detail_code: str
    detail_prefix: str | None = None
    detail_suffix: str
    revision: str
    owner: str | None = None
    series_name: str | None = None
    rule_version: str | None = None
    idempotency_key: str | None = None
    created_by: str
    created_at: str
    note: str | None = None
    base_key: str | None = None
    customer_id: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)


class PartDetailResp(GeneratePartResp):
    pass


class ErrorResp(BaseModel):
    detail: str
