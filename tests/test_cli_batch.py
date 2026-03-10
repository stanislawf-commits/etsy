"""
test_cli_batch.py — testy --batch dla komendy new-product.
"""
import pytest
from unittest.mock import patch
from click.testing import CliRunner

from cli import cli


FAKE_RESULT = {
    "slug":             "test-cutter-m",
    "title":            "Test Cookie Cutter",
    "price_suggestion": 4.99,
    "tags":             ["cutter", "test"],
    "status":           "ready_for_publish",
    "design":           {"success": True, "mode": "svg"},
    "models":           {"success": True, "sizes": ["S", "M", "L"], "stl_count": 3},
    "renders":          {"success": True, "renders": ["hero.jpg"], "render_dir": "/tmp"},
    "stl_files":        ["/tmp/test.stl"],
}


def test_batch_calls_pipeline_n_times():
    runner = CliRunner()
    with patch("src.pipeline.orchestrator.run_pipeline", return_value=FAKE_RESULT) as mock_pipe:
        result = runner.invoke(cli, ["new-product", "--batch", "3"])
    assert mock_pipe.call_count == 3
    assert result.exit_code == 0


def test_batch_shows_summary_table():
    runner = CliRunner()
    with patch("src.pipeline.orchestrator.run_pipeline", return_value=FAKE_RESULT):
        result = runner.invoke(cli, ["new-product", "--batch", "2"])
    assert "Batch" in result.output or "podsumowanie" in result.output.lower()
    assert "Ukończono" in result.output or "2" in result.output


def test_batch_with_name_exits_with_error():
    runner = CliRunner()
    result = runner.invoke(cli, ["new-product", "SomeName", "--batch", "3"])
    assert result.exit_code == 1
    assert "batch" in result.output.lower() or "NAME" in result.output


def test_batch_handles_pipeline_error():
    runner = CliRunner()
    with patch("src.pipeline.orchestrator.run_pipeline", side_effect=Exception("API error")):
        result = runner.invoke(cli, ["new-product", "--batch", "2"])
    # Nie crasha całkowicie — kontynuuje do następnego produktu
    assert "error" in result.output.lower() or result.exit_code == 0


def test_single_product_unchanged():
    """Upewnij się, że tryb bez --batch działa jak wcześniej."""
    runner = CliRunner()
    with patch("src.pipeline.orchestrator.run_pipeline", return_value=FAKE_RESULT):
        result = runner.invoke(cli, ["new-product", "roses"])
    assert result.exit_code == 0
