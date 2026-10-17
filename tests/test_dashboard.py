"""Дашборд запускается на всех наборах данных без исключений."""
import os
import pytest
from streamlit.testing.v1 import AppTest

APP = os.path.abspath("dashboard/app.py")


@pytest.mark.parametrize("dataset", ["sample", "sample2", "sample3"])
def test_dashboard_runs(dataset):
    at = AppTest.from_file(APP, default_timeout=90).run()
    at.sidebar.selectbox[0].set_value(dataset).run()
    assert not at.exception, [str(e.value)[:200] for e in at.exception]
