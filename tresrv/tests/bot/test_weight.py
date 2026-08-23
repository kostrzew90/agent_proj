import pytest

from tresrv.bot.weight import parse_waga_command


def test_parse_waga_command_valid():
    assert parse_waga_command(["80.5"]) == 80.5


def test_parse_waga_command_no_args_raises():
    with pytest.raises(ValueError):
        parse_waga_command([])


def test_parse_waga_command_out_of_range_raises():
    with pytest.raises(ValueError):
        parse_waga_command(["500"])
