"""Hardening from the 2026-11 security audit."""
import pytest

from analysis.fundamentals.xbrl_filing import parse_xbrl


@pytest.mark.parametrize("doc", [
    '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
    b'<!doctype x><x/>',
])
def test_parse_xbrl_refuses_dtd(doc):
    with pytest.raises(ValueError, match="DTD"):
        parse_xbrl(doc)
