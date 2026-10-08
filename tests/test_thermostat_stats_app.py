from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "appdaemon" / "apps" / "thermostat_stats.py"


def _load_thermostat_stats_module(monkeypatch):
    hassapi = types.ModuleType("hassapi")
    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy_ext = types.ModuleType("sqlalchemy.ext")
    sqlalchemy_declarative = types.ModuleType("sqlalchemy.ext.declarative")
    sqlalchemy_orm = types.ModuleType("sqlalchemy.orm")

    class SQLAlchemyError(Exception):
        pass

    class OperationalError(SQLAlchemyError):
        pass

    class PendingRollbackError(SQLAlchemyError):
        pass

    class _Metadata:
        def create_all(self, engine):
            return None

    def declarative_base():
        class Base:
            metadata = _Metadata()

        return Base

    def column(*args, **kwargs):
        return None

    sqlalchemy.Boolean = object
    sqlalchemy.Column = column
    sqlalchemy.DateTime = object
    sqlalchemy.Float = object
    sqlalchemy.Integer = object
    sqlalchemy.String = object
    sqlalchemy.Text = object
    sqlalchemy.create_engine = Mock()
    sqlalchemy.text = lambda statement: statement
    sqlalchemy.exc = types.SimpleNamespace(
        SQLAlchemyError=SQLAlchemyError,
        OperationalError=OperationalError,
        PendingRollbackError=PendingRollbackError,
    )
    sqlalchemy.orm = sqlalchemy_orm
    sqlalchemy_orm.sessionmaker = Mock(return_value=Mock(return_value=Mock()))
    sqlalchemy_declarative.declarative_base = declarative_base

    class Hass:
        pass

    hassapi.Hass = Hass
    monkeypatch.setitem(sys.modules, "hassapi", hassapi)
    monkeypatch.setitem(sys.modules, "sqlalchemy", sqlalchemy)
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext", sqlalchemy_ext)
    monkeypatch.setitem(sys.modules, "sqlalchemy.ext.declarative", sqlalchemy_declarative)
    monkeypatch.setitem(sys.modules, "sqlalchemy.orm", sqlalchemy_orm)

    spec = importlib.util.spec_from_file_location("thermostat_stats_test_module", APP_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_commit_rolls_back_session_after_database_failure(monkeypatch) -> None:
    module = _load_thermostat_stats_module(monkeypatch)
    app = module.ThermostatStats.__new__(module.ThermostatStats)
    app.session = Mock()
    app.session.commit.side_effect = module.sqlalchemy.exc.OperationalError(
        "SSL connection has been closed unexpectedly"
    )
    app.log = Mock()

    app._commit_thermostat_change(object())

    app.session.add.assert_called_once()
    app.session.rollback.assert_called_once()
    app.log.assert_called_once()


def test_commit_can_continue_after_rollback(monkeypatch) -> None:
    module = _load_thermostat_stats_module(monkeypatch)
    app = module.ThermostatStats.__new__(module.ThermostatStats)
    app.session = Mock()
    app.session.commit.side_effect = [
        module.sqlalchemy.exc.PendingRollbackError("rolled back due to previous exception"),
        None,
    ]
    app.log = Mock()

    app._commit_thermostat_change(object())
    app._commit_thermostat_change(object())

    assert app.session.add.call_count == 2
    assert app.session.commit.call_count == 2
    app.session.rollback.assert_called_once()
    app.log.assert_called_once()


def test_initialize_uses_pool_pre_ping_for_database_engine(monkeypatch) -> None:
    module = _load_thermostat_stats_module(monkeypatch)
    app = module.ThermostatStats.__new__(module.ThermostatStats)
    app.args = {
        "house_average_temp": "sensor.average_house_temp",
        "house_average_humidity": "sensor.average_house_humidity",
        "thermostat_db": "postgresql://example/thermostat",
        "thermostat": "climate.my_ecobee",
        "sun": "sun.sun",
        "outside_temp": "sensor.outside_temperature",
        "outside_cloud_cover": "sensor.tomorrow_io_the_brewery_cloud_cover",
        "outside_humidity": "sensor.outside_humidity",
    }
    app.listen_state = Mock()

    create_engine = Mock(return_value=Mock())
    monkeypatch.setattr(module.sqlalchemy, "create_engine", create_engine)
    monkeypatch.setattr(module.Base.metadata, "create_all", Mock())
    monkeypatch.setattr(module.ThermostatStats, "_ensure_optional_columns", Mock())
    monkeypatch.setattr(module.sqlalchemy.orm, "sessionmaker", Mock(return_value=Mock(return_value=Mock())))

    app.initialize()

    create_engine.assert_called_once_with(
        "postgresql://example/thermostat",
        echo=True,
        pool_pre_ping=True,
    )
