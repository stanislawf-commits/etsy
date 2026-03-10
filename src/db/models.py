"""
models.py — tabele SQLite (SQLModel).

Tabele:
    Product      — główna encja produktu (slug jako PK)
    RenderJob    — historia renderów i czas wykonania
    ListingStats — append-only time-series views/favorites z Etsy API
    StockEvent   — zdarzenia magazynowe (sprzedaż, alert, redruk)
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

    # Magazyn
    stock_quantity:    int           = Field(default=999)
    restock_threshold: int           = Field(default=3)
    last_sold_at:      Optional[datetime] = Field(default=None)

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


class StockEvent(SQLModel, table=True):
    """Zdarzenia magazynowe — sprzedaż, alert niskiego stanu, redruk."""

    id:         Optional[int]  = Field(default=None, primary_key=True)
    slug:       str            = Field(index=True, foreign_key="product.slug")
    event_type: str            = Field(index=True)   # "sale" | "restock_alert" | "reprint_triggered" | "auto_draft_created"
    quantity:   int            = Field(default=0)
    source:     str            = Field(default="webhook")  # "webhook" | "cron" | "manual"
    payload:    Optional[str]  = Field(default=None)       # raw JSON
    created_at: datetime       = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ListingStats(SQLModel, table=True):
    """Append-only time-series statystyk Etsy (views + favorites) per listing."""

    id:           Optional[int]  = Field(default=None, primary_key=True)
    slug:         str            = Field(index=True, foreign_key="product.slug")
    listing_id:   str            = Field(index=True)
    views:        int            = Field(default=0)
    favorites:    int            = Field(default=0)
    fetched_at:   datetime       = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
