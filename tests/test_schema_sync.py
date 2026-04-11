"""Test _add_missing_columns detects and adds columns absent from the DB."""

from unittest.mock import MagicMock, patch

from mcp_hub.main import _add_missing_columns


def _make_column(name, type_str="VARCHAR(255)"):
    col = MagicMock()
    col.name = name
    col.type = MagicMock()
    col.type.compile = MagicMock(return_value=type_str)
    return col


def test_adds_missing_column():
    table = MagicMock()
    table.name = "mr_reviews"
    table.columns = [_make_column("id", "INTEGER"), _make_column("rebase_ticket_id", "INTEGER")]

    inspector = MagicMock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [{"name": "id"}]

    connection = MagicMock()
    dialect = MagicMock()
    connection.engine.dialect = dialect

    with patch("mcp_hub.main.sa_inspect", return_value=inspector):
        with patch("mcp_hub.main.Base") as mock_base:
            mock_base.metadata.sorted_tables = [table]
            _add_missing_columns(connection)

    executed_stmts = [str(c.args[0]) for c in connection.execute.call_args_list]
    assert len(executed_stmts) == 1
    assert "rebase_ticket_id" in executed_stmts[0]
    assert "ALTER TABLE" in executed_stmts[0]


def test_skips_existing_columns():
    table = MagicMock()
    table.name = "mr_reviews"
    table.columns = [_make_column("id", "INTEGER"), _make_column("verdict", "VARCHAR(20)")]

    inspector = MagicMock()
    inspector.has_table.return_value = True
    inspector.get_columns.return_value = [{"name": "id"}, {"name": "verdict"}]

    connection = MagicMock()

    with patch("mcp_hub.main.sa_inspect", return_value=inspector):
        with patch("mcp_hub.main.Base") as mock_base:
            mock_base.metadata.sorted_tables = [table]
            _add_missing_columns(connection)

    connection.execute.assert_not_called()


def test_skips_nonexistent_tables():
    table = MagicMock()
    table.name = "new_table"
    table.columns = [_make_column("id", "INTEGER")]

    inspector = MagicMock()
    inspector.has_table.return_value = False

    connection = MagicMock()

    with patch("mcp_hub.main.sa_inspect", return_value=inspector):
        with patch("mcp_hub.main.Base") as mock_base:
            mock_base.metadata.sorted_tables = [table]
            _add_missing_columns(connection)

    connection.execute.assert_not_called()
    inspector.get_columns.assert_not_called()
