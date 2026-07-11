def test_package_has_expected_version() -> None:
    import trading_bot

    assert trading_bot.__version__ == "0.1.0"
