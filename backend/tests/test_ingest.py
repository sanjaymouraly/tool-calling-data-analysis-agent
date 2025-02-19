"""Tests for the ingestion pipeline: uploads, schema inference, quality."""

from __future__ import annotations

import zipfile

import pandas as pd
import pytest

from app.core.errors import NotFoundError, ResourceLimitError, ValidationError
from app.ingest import store
from app.ingest.normalize import coerce_frame, profile_frame, quality_report
from app.ingest.readers import detect_encoding, list_sheets, read_source


def _csv_bytes(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


class TestUpload:
    def test_create_dataset_from_csv(self, db, demo_files):
        raw = (store.settings.demo_dir / "retail_orders.csv").read_bytes()
        stored = store.create_dataset(db, raw=raw, filename="retail_orders.csv")
        dataset = stored.dataset
        assert dataset.row_count == 5018
        assert dataset.column_count == 14
        assert len(dataset.file_hash) == 64
        assert dataset.artifact_path.endswith(".parquet")
        assert dataset.schema_json["columns"]

    def test_content_hash_is_stable(self, db, demo_files):
        raw = (store.settings.demo_dir / "retail_orders.csv").read_bytes()
        first = store.create_dataset(db, raw=raw, filename="a.csv")
        second = store.create_dataset(db, raw=raw, filename="b.csv")
        assert first.dataset.source_hash == second.dataset.source_hash
        # ... but they are separate datasets with their own lineage
        assert first.dataset.id != second.dataset.id

    def test_rejects_empty_file(self, db):
        with pytest.raises(ValidationError):
            store.create_dataset(db, raw=b"", filename="empty.csv")

    def test_rejects_unsupported_extension(self, db):
        with pytest.raises(ValidationError):
            store.create_dataset(db, raw=b"MZ\x00\x00", filename="malware.exe")

    def test_rejects_oversized_upload(self, db, monkeypatch):
        from app.core import config

        monkeypatch.setattr(config.settings, "max_upload_size_mb", 0)
        with pytest.raises(ValidationError):
            store.create_dataset(db, raw=b"a,b\n1,2\n", filename="x.csv")

    def test_preserves_original_file(self, db, demo_files):
        raw = (store.settings.demo_dir / "customers.csv").read_bytes()
        stored = store.create_dataset(db, raw=raw, filename="customers.csv")
        from pathlib import Path

        assert Path(stored.dataset.source_path).read_bytes() == raw

    def test_version_lineage(self, db, demo_files):
        raw = (store.settings.demo_dir / "inventory.csv").read_bytes()
        first = store.create_dataset(db, raw=raw, filename="inventory.csv")
        second = store.create_dataset(db, raw=raw, filename="inventory.csv")
        assert second.dataset.lineage_id == first.dataset.lineage_id
        assert second.dataset.version == first.dataset.version + 1
        assert len(second.dataset.versions) >= 1

    def test_delete_removes_file(self, db, demo_files):
        from pathlib import Path

        raw = (store.settings.demo_dir / "inventory.csv").read_bytes()
        stored = store.create_dataset(db, raw=raw, filename="inventory.csv")
        path = Path(stored.dataset.source_path)
        assert path.exists()
        store.delete_dataset(db, stored.dataset.id)
        assert not path.exists()
        with pytest.raises(NotFoundError):
            store.get_dataset(db, stored.dataset.id)


class TestSchemaInference:
    def test_numeric_and_date_detection(self):
        frame = pd.DataFrame(
            {
                "amount": [1.5, 2.5, 3.5],
                "when": ["2024-01-01", "2024-02-01", "2024-03-01"],
                "label": ["a", "b", "c"],
                "flag": ["yes", "no", "yes"],
            }
        )
        coerced, raw_types = coerce_frame(frame)
        profile = profile_frame(coerced, raw_types=raw_types, original=frame)
        types = {c["name"]: c["inferred_type"] for c in profile["columns"]}
        assert types["amount"] == "numeric"
        assert types["when"] == "date"
        assert types["label"] == "string"
        assert types["flag"] == "boolean"

    def test_currency_detection(self):
        frame = pd.DataFrame({"price": ["$1,200.50", "$99.99", "$15.00"]})
        coerced, raw_types = coerce_frame(frame)
        assert raw_types["price"] == "currency"
        profile = profile_frame(coerced, raw_types=raw_types, original=frame)
        column = profile["columns"][0]
        assert column["inferred_type"] == "currency"
        assert column["currency"] == "USD"
        assert column["stats"]["max"] == pytest.approx(1200.50)

    def test_mixed_numeric_is_flagged(self):
        frame = pd.DataFrame({"value": ["1", "2", "n/a", "4"]})
        coerced, raw_types = coerce_frame(frame)
        assert raw_types["value"] == "mixed_numeric"
        assert pd.to_numeric(coerced["value"], errors="coerce").isna().sum() == 1

    def test_role_hints(self, demo_datasets):
        orders = demo_datasets["Retail Orders"]
        roles = {c["name"]: c.get("role_hint") for c in orders.schema_json["columns"]}
        assert roles["Revenue"] == "money"
        assert roles["Order_Date"] == "date"
        assert roles["Order_ID"] == "order_id"
        assert roles["Region"] == "region"

    def test_missing_values_are_counted(self, demo_datasets):
        orders = demo_datasets["Retail Orders"]
        columns = {c["name"]: c for c in orders.schema_json["columns"]}
        assert columns["Discount"]["missing_count"] > 0
        assert columns["Discount"]["missing_pct"] > 0


class TestQuality:
    def test_quality_report_detects_duplicates(self, demo_datasets):
        orders = demo_datasets["Retail Orders"]
        report = orders.quality_json
        assert report["duplicates"]["count"] > 0
        assert 0 <= report["score"] <= 100
        assert report["warnings"]

    def test_quality_report_on_clean_frame(self):
        frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        report = quality_report(frame)
        assert report["duplicates"]["count"] == 0
        assert report["score"] == 100.0

    def test_outliers_are_detected(self):
        frame = pd.DataFrame({"v": [1, 2, 3, 4, 5, 6, 7, 8, 9, 500]})
        report = quality_report(frame)
        assert report["outliers"].get("v", {}).get("count", 0) >= 1


class TestReaders:
    def test_detects_encoding(self, tmp_path):
        path = tmp_path / "latin.csv"
        path.write_bytes("name\ncafé\n".encode("latin-1"))
        assert detect_encoding(path) in {"latin-1", "cp1252"}

    def test_lists_workbook_sheets(self, tmp_path):
        path = tmp_path / "book.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="One", index=False)
            pd.DataFrame({"b": [2]}).to_excel(writer, sheet_name="Two", index=False)
        assert list_sheets(path) == ["One", "Two"]

    def test_rejects_corrupt_workbook(self, tmp_path):
        path = tmp_path / "broken.xlsx"
        path.write_bytes(b"not a zip file at all")
        with pytest.raises(ValidationError):
            list_sheets(path)

    def test_rejects_zip_bomb(self, tmp_path, monkeypatch):
        from app.ingest import readers

        path = tmp_path / "bomb.xlsx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("big.txt", "0" * (5 * 1024 * 1024))
        monkeypatch.setattr(readers, "MAX_COMPRESSION_RATIO", 1)
        with pytest.raises(ResourceLimitError):
            list_sheets(path)

    def test_reads_specific_sheet(self, tmp_path):
        path = tmp_path / "book.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1, 2]}).to_excel(writer, sheet_name="One", index=False)
            pd.DataFrame({"b": [3, 4]}).to_excel(writer, sheet_name="Two", index=False)
        result = read_source(path, max_rows=100, sheet_name="Two")
        assert result.sheet_name == "Two"
        assert list(result.frame.columns) == ["b"]

    def test_unknown_sheet_raises(self, tmp_path):
        path = tmp_path / "book.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame({"a": [1]}).to_excel(writer, sheet_name="One", index=False)
        with pytest.raises(ValidationError):
            read_source(path, max_rows=10, sheet_name="Nope")

    def test_row_limit_is_enforced(self, tmp_path):
        path = tmp_path / "big.csv"
        pd.DataFrame({"a": range(100)}).to_csv(path, index=False)
        result = read_source(path, max_rows=10)
        assert len(result.frame) == 10
        assert result.truncated is True
