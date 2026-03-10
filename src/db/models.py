"""
models.py — tabele SQLite (SQLModel).

Tabele:
    Product     — główna encja produktu (slug jako PK)
    RenderJob   — historia renderów i czas wykonania
"""
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class Product(SQLModel, table=True):
    """Główna tabela produktów — jeden wiersz = jeden produkt."""

    slug:         str            = Field(primary_key=True)
    topic:        str            = Field(index=True)
    product_type: str            = Field(default="cutter", index=True)
    size:         str            = Field(default="M")
    status:       str            = Field(default="draft", index=True)

    # Listing Etsy
    title:        Optional[str]  = Field(default=None)
    price:        Optional[float]= Field(default=None)
    tags_json:    Optional[str]  = Field(default=None)   # JSON array

    # Etsy publishing
    etsy_listing_id: Optional[str]  = Field(default=None)
    etsy_url:        Optional[str]  = Field(default=None)

    # Pipeline progress
    steps_json:   Optional[str]  = Field(default="[]")   # JSON array kroków
    svg_count:    int            = Field(default=0)
    stl_count:    int            = Field(default=0)
    render_count: int            = Field(default=0)
    render_engine: Optional[str] = Field(default=None)   # "blender" | "pillow"

    # Timestamps
    created_at:   datetime       = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at:   datetime       = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    class Config:
        # Pozwala na dodatkowe pola w konstruktorze (np. z JSON)
        extra = "ignore"


class RenderJob(SQLModel, table=True):
    """Historia renderów — każde uruchomienie BlenderRenderAgent."""

    id:           Optional[int]  = Field(default=None, primary_key=True)
    slug:         str            = Field(index=True, foreign_key="product.slug")
    engine:       str            = Field(default="pillow")   # "blender" | "pillow"
    success:      bool           = Field(default=False)
    render_count: int            = Field(default=0)
    duration_s:   Optional[float]= Field(default=None)
    error:        Optional[str]  = Field(default=None)
    created_at:   datetime       = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
