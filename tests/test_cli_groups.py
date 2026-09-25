"""Every CLI command is classified; experimental commands are labeled in --help."""

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


def test_experimental_commands_are_labeled_and_canonical_are_not():
    for name, text in _subcommand_help().items():
        labeled = text.startswith(ms.EXPERIMENTAL_LABEL)
        assert labeled == (name in ms.EXPERIMENTAL_COMMANDS), name


def test_top_level_help_names_the_canonical_path():
    text = build_parser().format_help()
    assert "fix-repo" in text
    assert "[experimental]" in text
