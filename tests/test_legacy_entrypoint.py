import app as legacy_app_module


def test_legacy_flask_entrypoint_is_explicitly_marked():
    assert legacy_app_module.app.config["LEGACY_COMPATIBILITY_ENTRYPOINT"] is True
    assert legacy_app_module.app.config["PRIMARY_ENTRYPOINT"] == "src.api.app"
    assert "Legacy Flask compatibility entrypoint" in legacy_app_module.LEGACY_ENTRYPOINT_MESSAGE
