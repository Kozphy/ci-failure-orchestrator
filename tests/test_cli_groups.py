"""Every CLI command is classified; experimental surface is empty after the cut."""

from __future__ import annotations

import argparse

from ci_failure_orchestrator import module_status as ms
from ci_failure_orchestrator.cli import build_parser


def _subcommand_help() -> dict[str, str]:
    parser = build_parser()
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return {choice.dest: choice.help or "" for choice in action._choices_actions}


def test_every_command_is_classified_exactly_once():
    commands = set(_subcommand_help())
    assert ms.CANONICAL_COMMANDS.isdisjoint(ms.EXPERIMENTAL_COMMANDS)
    assert commands == ms.CANONICAL_COMMANDS | ms.EXPERIMENTAL_COMMANDS


def test_no_experimental_commands_remain():
    assert ms.EXPERIMENTAL_COMMANDS == frozenset()
    for name, text in _subcommand_help().items():
        assert not text.startswith(ms.EXPERIMENTAL_LABEL), name


def test_top_level_help_names_the_control_plane_path():
    text = build_parser().format_help()
    assert "fix-repo" in text
    assert "CONTROL_PLANE" in text or "never merges" in text
    assert "[experimental]" not in text
