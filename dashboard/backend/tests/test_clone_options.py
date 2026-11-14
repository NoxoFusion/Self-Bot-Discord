from dashboard.backend.app import validate_utility_clone


def test_validate_clone_defaults_to_info_and_structure():
    data, errors = validate_utility_clone(
        {
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
        }
    )

    assert errors == []
    assert data["options"] == {
        "info": True,
        "structure": True,
        "emojis": False,
    }


def test_validate_clone_accepts_explicit_options():
    data, errors = validate_utility_clone(
        {
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
            "options": {
                "info": False,
                "structure": True,
                "emojis": True,
            },
        }
    )

    assert errors == []
    assert data["options"] == {
        "info": False,
        "structure": True,
        "emojis": True,
    }


def test_validate_clone_requires_at_least_one_option():
    _data, errors = validate_utility_clone(
        {
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
            "options": {
                "info": False,
                "structure": False,
                "emojis": False,
            },
        }
    )

    assert errors
    assert any("option" in error.lower() for error in errors)


def test_validate_clone_rejects_non_boolean_options():
    _data, errors = validate_utility_clone(
        {
            "source_id": "111111111111111111",
            "target_id": "222222222222222222",
            "confirm": True,
            "options": {
                "info": "yes",
                "structure": True,
                "emojis": False,
            },
        }
    )

    assert errors
    assert any("info" in error for error in errors)
